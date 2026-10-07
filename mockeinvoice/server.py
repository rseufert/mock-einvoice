"""The mock over HTTP: a buyer that invoices are sent to, and a supplier
that sends them.

    mock-einvoice --port 8100

Two sets of paths. What the other party's system uses, as it would use the
network:

    POST /invoices                      to the buyer: a UBL Invoice or CreditNote
    POST /responses                     to the supplier: a Peppol Invoice Response

And what a test uses to look at the mock and to drive it, under `/_mock`.
The buyer:

    GET   /_mock/invoices               what is held
    GET   /_mock/invoices/<id>          one, with its findings and its responses
    GET   /_mock/invoices/<id>/document     as it was sent
    POST  /_mock/invoices/<id>/responses    the buyer says something of it
    GET   /_mock/responses/<id>         an Invoice Response it gave, as XML
    GET   /_mock/buyer, PATCH /_mock/buyer      how the buyer behaves

The supplier:

    POST  /_mock/sent                   send this document to the buyer
    GET   /_mock/sent                   what was sent
    GET   /_mock/sent/<id>              one, with its delivery and what came back
    GET   /_mock/sent/<id>/document     as it was sent
    GET   /_mock/answers/<id>           an Invoice Response it was given, as XML
    POST  /_mock/orders                 tell it of an order, as JSON
    GET   /_mock/orders                 the orders it was told of
    GET   /_mock/orders/<id>            one, with what is billed of each line
    POST  /_mock/orders/<id>/invoices   write the invoice for it, and send it
    GET   /_mock/supplier, PATCH /_mock/supplier    who the supplier is

And both:

    GET   /_mock/health                 that it is up, and its version
    GET   /_mock/turned-away            what was not taken in, and why
    POST  /_mock/validate               a document held to its rules, and not kept
    POST  /_mock/reset                  forget everything

None of this is Peppol's transport. A real invoice travels by AS4 between
access points that find each other by SMP lookup; here it is a `POST`, and
the other party is a URL (`--buyer-url`, `--seller-url`). The paths and the
status codes are this mock's own: nothing published defines them.
"""
from __future__ import annotations

import argparse
import datetime
import decimal
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, List, Optional, Sequence, Tuple

from . import __version__
from . import response as _response
from . import specification as _specification
from .buyer import ANSWERS, Buyer, Held, NotSaid, Sent, TurnedAway, not_run
from .model import Finding, Refused
from .rules import Report, check, check_response
from .order import NotTaken, Order
from .supplier import Got, Issued, NotBilled, NotSent, Supplier
from .ubl import parse_tree, tree

PORT = 8100
LARGEST = 10 * 1024 * 1024         # of a request's body, in bytes
XML = "application/xml; charset=utf-8"
# The HTTP status for each reason a response is not given.
NOT_SAID = {"NO-SUCH-INVOICE": 404, "REQUEST": 400, "INVALID": 422}
# And for each reason an order is not billed.
NOT_BILLED = {"NO-SUCH-ORDER": 404, "NO-SUCH-LINE": 404, "REQUEST": 400, "NOT-VALID": 422}


def finding(found: Finding) -> dict:
    said = {"level": found.level, "code": found.code, "path": found.path, "text": found.text}
    if found.link:
        said["link"] = found.link
    return said


def reported(report: Report) -> dict:
    """A report as JSON: the verdict, what was found, and the fatal rules that
    could apply and were not run, which are why a verdict is `not judged`."""
    return {"specification": report.specification, "verdict": report.verdict,
            "findings": [finding(found) for found in report.findings],
            "rules_run": len(report.ran), "not_run": not_run(report)}


def sent(said: Sent) -> dict:
    return {"id": said.id, "invoice": said.invoice, "code": said.code,
            "partial": said.partial, "forced": said.forced, "delivery": said.delivery,
            "warnings": [finding(found) for found in said.warnings],
            "document": "/_mock/responses/%s" % said.id}


def held(invoice: Held, full: bool = True) -> dict:
    document = invoice.document
    said = {
        "id": invoice.id, "kind": document.kind, "number": invoice.number,
        "issued": document.text("BT-2"), "type": document.text("BT-3"),
        "specification": invoice.report.specification, "profile": invoice.profile,
        "seller": document.text("BT-27"), "buyer": document.text("BT-44"),
        "received": invoice.received, "verdict": invoice.report.verdict,
        "status": invoice.status,
    }
    if full:
        said["findings"] = [finding(found) for found in invoice.report.findings]
        said["responses"] = [sent(one) for one in invoice.responses]
        said["document"] = "/_mock/invoices/%s/document" % invoice.id
    return said


def got(heard: Got) -> dict:
    return {"id": heard.id, "sent": heard.invoice, "code": heard.code,
            "partial": heard.partial, "ignored": heard.ignored, "received": heard.received,
            "document": "/_mock/answers/%s" % heard.id}


def issued(one: Issued, full: bool = True) -> dict:
    document = one.document
    said = {
        "id": one.id, "kind": document.kind, "number": one.number,
        "issued": document.text("BT-2"), "type": document.text("BT-3"),
        "specification": one.report.specification,
        "seller": document.text("BT-27"), "buyer": document.text("BT-44"),
        "sent": one.sent, "verdict": one.report.verdict, "forced": one.forced,
        "delivery": one.delivery, "status": one.status,
        "order": "/_mock/orders/%s" % one.order if one.order else None,
    }
    if full:
        said["findings"] = [finding(found) for found in one.report.findings]
        said["responses"] = [got(heard) for heard in one.responses]
        said["document"] = "/_mock/sent/%s/document" % one.id
    return said


def ordered(order: Order, full: bool = True) -> dict:
    said = {"id": order.id, "number": order.number, "reference": order.reference,
            "buyer": order.buyer["name"], "received": order.received, "status": order.status}
    if full:
        said["buyer"] = order.buyer
        said["currency"] = order.currency
        said["lines"] = [
            {"line": line.line, "name": line.name, "seller_item": line.seller_item,
             "buyer_item": line.buyer_item, "quantity": format(line.quantity, "f"),
             "unit": line.unit, "price": format(line.price, "f"),
             "billed": format(line.billed, "f"), "open": format(line.open, "f")}
            for line in order.lines]
        said["invoices"] = ["/_mock/sent/%s" % one for one in order.invoices]
    return said


def validated(raw: bytes) -> dict:
    """Hold a document to its rules: an invoice or credit note to those of
    its specification, an Invoice Response to its own."""
    root = tree(raw)
    if root.tag == _response.ROOT:
        _read, findings, elements = _response.parse_tree(raw)
        return dict(reported(check_response(elements, findings)), kind="ApplicationResponse")
    document, findings, elements = parse_tree(raw)
    report = check(document, _specification.identify(document), findings, elements)
    return dict(reported(report), kind=document.kind)


def poster(url: str, timeout: float = 10.0) -> Callable[[bytes], dict]:
    """What sends a document to the other party: a `POST` of the XML to one
    URL."""
    def deliver(xml: bytes) -> dict:
        request = urllib.request.Request(url, data=xml, method="POST",
                                         headers={"Content-Type": XML})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as answer:
                return {"to": url, "status": answer.status}
        except urllib.error.HTTPError as refused:
            with refused:
                return {"to": url, "status": refused.code}
        except (OSError, ValueError) as failed:
            return {"to": url, "error": str(failed)}
    return deliver


class Problem(Exception):
    def __init__(self, status: int, code: str, reason: str, **more: object):
        super().__init__(reason)
        self.status, self.body = status, dict({"error": code, "reason": reason}, **more)


ROUTES: List[Tuple[str, "re.Pattern[str]", str]] = [
    (method, re.compile("^%s$" % pattern), name) for method, pattern, name in (
        ("GET", "/", "index"),
        ("POST", "/invoices", "receive"),
        ("POST", "/responses", "hear"),
        ("GET", "/_mock/invoices", "invoices"),
        ("GET", r"/_mock/invoices/(\d+)", "invoice"),
        ("GET", r"/_mock/invoices/(\d+)/document", "invoice_document"),
        ("POST", r"/_mock/invoices/(\d+)/responses", "answer"),
        ("GET", r"/_mock/responses/(\d+)", "response_document"),
        ("GET", "/_mock/buyer", "behaviour"),
        ("PATCH", "/_mock/buyer", "behave"),
        ("POST", "/_mock/sent", "send_out"),
        ("GET", "/_mock/sent", "all_sent"),
        ("GET", r"/_mock/sent/(\d+)", "one_sent"),
        ("GET", r"/_mock/sent/(\d+)/document", "sent_document"),
        ("GET", r"/_mock/answers/(\d+)", "answer_document"),
        ("POST", "/_mock/orders", "take_order"),
        ("GET", "/_mock/orders", "orders"),
        ("GET", r"/_mock/orders/(\d+)", "order"),
        ("POST", r"/_mock/orders/(\d+)/invoices", "bill"),
        ("GET", "/_mock/supplier", "who"),
        ("PATCH", "/_mock/supplier", "describe"),
        ("GET", "/_mock/health", "health"),
        ("GET", "/_mock/turned-away", "turned_away"),
        ("POST", "/_mock/validate", "validate"),
        ("POST", "/_mock/reset", "reset"),
    )]


class Handler(BaseHTTPRequestHandler):
    server_version = "mock-einvoice/%s" % __version__
    protocol_version = "HTTP/1.1"
    buyer: Buyer                    # both set on the class `serve` makes
    supplier: Supplier
    quiet = False

    # -- plumbing -----------------------------------------------------------------------

    def log_message(self, format: str, *args: object) -> None:
        if not self.quiet:
            super().log_message(format, *args)

    def dispatch(self) -> None:
        path, _, self.query = self.path.partition("?")
        allowed = []
        try:
            for method, pattern, name in ROUTES:
                match = pattern.match(path)
                if not match:
                    continue
                if method == self.command:
                    return getattr(self, name)(*match.groups())
                allowed.append(method)
            if allowed:
                raise Problem(405, "METHOD", "%s takes %s, not %s"
                              % (path, " and ".join(allowed), self.command))
            raise Problem(404, "NO-SUCH-PATH", "there is nothing at %s: GET / lists what "
                                               "there is" % path)
        except Problem as problem:
            if self.command != "GET":
                self.close_connection = True    # its body may not have been read
            self.json(problem.status, problem.body)

    do_GET = do_POST = do_PATCH = do_PUT = do_DELETE = dispatch

    def json(self, status: int, body: object, **headers: str) -> None:
        self.send(status, "application/json; charset=utf-8",
                  (json.dumps(body, indent=2, ensure_ascii=False) + "\n").encode("utf-8"),
                  **headers)

    def send(self, status: int, kind: str, body: bytes, **headers: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        for name, value in headers.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def body(self) -> bytes:
        length = self.headers.get("Content-Length")
        if length is None or not length.isdigit():
            raise Problem(411, "NO-LENGTH", "the request has no Content-Length")
        if int(length) > LARGEST:
            raise Problem(413, "TOO-LARGE", "the request is %s bytes, and the most taken is %d"
                          % (length, LARGEST))
        return self.rfile.read(int(length))

    def said(self) -> object:
        """The request's body as JSON, with a number that has a fraction read
        as the decimal it was written as: no amount goes through a float."""
        try:
            return json.loads(self.body().decode("utf-8") or "{}",
                              parse_float=decimal.Decimal)
        except (UnicodeDecodeError, ValueError) as wrong:
            raise Problem(400, "NOT-JSON", "the request is not JSON: %s" % wrong)

    def asked(self, allowed: Sequence[str]) -> dict:
        """The request's body as a JSON object with only these keys."""
        said = self.said()
        if not isinstance(said, dict):
            raise Problem(400, "REQUEST", "the request is a JSON object, not %s"
                          % type(said).__name__)
        unknown = sorted(set(said) - set(allowed))
        if unknown:
            raise Problem(400, "REQUEST", "the request has %s, and what is taken is %s"
                          % (", ".join(unknown), ", ".join(allowed)))
        return said

    def one(self, identifier: str) -> Held:
        invoice = self.buyer.invoices.get(identifier)
        if invoice is None:
            raise Problem(404, "NO-SUCH-INVOICE", "no document %s is held" % identifier)
        return invoice

    # -- the network's side -------------------------------------------------------------

    def receive(self) -> None:
        try:
            invoice = self.buyer.receive(self.body())
        except TurnedAway as away:
            more = reported(away.report) if away.report else {}
            raise Problem(422 if away.report else 400, away.code, away.reason, **more)
        self.json(201, held(invoice), Location="/_mock/invoices/%s" % invoice.id)

    def hear(self) -> None:
        try:
            heard = self.supplier.hear(self.body())
        except TurnedAway as away:
            more = reported(away.report) if away.report else {}
            raise Problem(400 if away.code.startswith("NOT-") else 422, away.code,
                          away.reason, **more)
        self.json(201, got(heard), Location="/_mock/answers/%s" % heard.id)

    # -- the mock's side ----------------------------------------------------------------

    def index(self) -> None:
        self.json(200, {
            "mock": "mock-einvoice", "version": __version__, "sides": ["buyer", "supplier"],
            "answers": self.buyer.answers,
            "paths": ["%s %s" % (method, pattern.pattern.strip("^$").replace(r"(\d+)", "<id>"))
                      for method, pattern, _name in ROUTES]})

    def invoices(self) -> None:
        with self.buyer.lock:
            self.json(200, [held(invoice, full=False)
                            for invoice in self.buyer.invoices.values()])

    def invoice(self, identifier: str) -> None:
        with self.buyer.lock:
            self.json(200, held(self.one(identifier)))

    def invoice_document(self, identifier: str) -> None:
        self.send(200, XML, self.one(identifier).xml)

    def response_document(self, identifier: str) -> None:
        said = self.buyer.responses.get(identifier)
        if said is None:
            raise Problem(404, "NO-SUCH-RESPONSE", "no response %s has been given" % identifier)
        self.send(200, XML, said.xml)

    def answer(self, identifier: str) -> None:
        asked = self.asked(("code", "reasons", "actions", "note", "force"))
        code, note, force = asked.get("code"), asked.get("note", ""), asked.get("force", False)
        reasons, actions = asked.get("reasons", []), asked.get("actions", [])
        if not isinstance(code, str) or not code:
            raise Problem(400, "REQUEST", "the request names the response's code: one of %s"
                          % ", ".join(_response.CODES))
        if not isinstance(note, str) or not isinstance(force, bool):
            raise Problem(400, "REQUEST", "note is text, and force is true or false")
        for name, given in (("reasons", reasons), ("actions", actions)):
            if not isinstance(given, list) or not all(clarification(one) for one in given):
                raise Problem(400, "REQUEST", "%s is a list, each a code or an object with "
                              "code, text and conditions (pairs of a business term and "
                              "a value)" % name)
        try:
            said = self.buyer.answer(identifier, code, reasons, actions, note, force)
        except NotSaid as no:
            more = {"findings": [finding(found) for found in no.findings]} if no.findings else {}
            raise Problem(NOT_SAID.get(no.code, 409), no.code, no.reason, **more)
        self.json(201, sent(said), Location="/_mock/responses/%s" % said.id)

    def send_out(self) -> None:
        force = urllib.parse.parse_qs(self.query, keep_blank_values=True)
        if set(force) - {"force"} or force.get("force", ["true"]) not in (["true"], ["false"]):
            raise Problem(400, "REQUEST", "the one thing to ask for is ?force=true")
        try:
            one = self.supplier.send(self.body(), force.get("force") == ["true"])
        except NotSent as no:
            more = reported(no.report) if no.report else {}
            raise Problem(422 if no.report else 400, no.code, no.reason, **more)
        self.json(201, issued(one), Location="/_mock/sent/%s" % one.id)

    def all_sent(self) -> None:
        with self.supplier.lock:
            self.json(200, [issued(one, full=False) for one in self.supplier.sent.values()])

    def one_issued(self, identifier: str) -> Issued:
        one = self.supplier.sent.get(identifier)
        if one is None:
            raise Problem(404, "NO-SUCH-DOCUMENT", "no document %s was sent" % identifier)
        return one

    def one_sent(self, identifier: str) -> None:
        with self.supplier.lock:
            self.json(200, issued(self.one_issued(identifier)))

    def sent_document(self, identifier: str) -> None:
        self.send(200, XML, self.one_issued(identifier).xml)

    def answer_document(self, identifier: str) -> None:
        heard = self.supplier.answers.get(identifier)
        if heard is None:
            raise Problem(404, "NO-SUCH-RESPONSE", "no response %s was received" % identifier)
        self.send(200, XML, heard.xml)

    def take_order(self) -> None:
        try:
            order = self.supplier.take(self.said())
        except NotTaken as no:
            if no.report:
                raise Problem(422, "UNBILLABLE", no.reason, **reported(no.report))
            raise Problem(400, "REQUEST", no.reason)
        self.json(201, ordered(order), Location="/_mock/orders/%s" % order.id)

    def orders(self) -> None:
        with self.supplier.lock:
            self.json(200, [ordered(order, full=False)
                            for order in self.supplier.orders.values()])

    def order(self, identifier: str) -> None:
        with self.supplier.lock:
            order = self.supplier.orders.get(identifier)
            if order is None:
                raise Problem(404, "NO-SUCH-ORDER", "no order %s was taken" % identifier)
            self.json(200, ordered(order))

    def bill(self, identifier: str) -> None:
        lines = self.asked(("lines",)).get("lines")
        if lines is not None and not (
                isinstance(lines, list)
                and all(isinstance(one, dict) and set(one) == {"line", "quantity"}
                        and isinstance(one["line"], str) for one in lines)):
            raise Problem(400, "REQUEST", "lines is a list, each {\"line\", \"quantity\"}: "
                                          "a line of the order by its number, and how much "
                                          "of it to bill")
        if lines is not None and len({one["line"] for one in lines}) < len(lines):
            raise Problem(400, "REQUEST", "a line is named twice")
        try:
            one = self.supplier.bill(identifier, None if lines is None else {
                one["line"]: one["quantity"] for one in lines})
        except NotBilled as no:
            more = reported(no.report) if no.report else {}
            raise Problem(NOT_BILLED.get(no.code, 409), no.code, no.reason, **more)
        self.json(201, issued(one), Location="/_mock/sent/%s" % one.id)

    def who(self) -> None:
        self.json(200, self.supplier.who)

    def describe(self) -> None:
        try:
            self.json(200, self.supplier.describe(self.said()))
        except NotTaken as no:
            raise Problem(400, "REQUEST", no.reason)

    def health(self) -> None:
        self.json(200, {"status": "ok", "version": __version__,
                        "held": len(self.buyer.invoices), "sent": len(self.supplier.sent)})

    def turned_away(self) -> None:
        with self.buyer.lock, self.supplier.lock:
            both = [(when, side, code, reason)
                    for side, party in (("buyer", self.buyer), ("supplier", self.supplier))
                    for when, code, reason in party.turned_away]
        self.json(200, [{"received": when, "side": side, "error": code, "reason": reason}
                        for when, side, code, reason in sorted(both, key=lambda one: one[0])])

    def validate(self) -> None:
        try:
            self.json(200, validated(self.body()))
        except Refused as refused:
            raise Problem(400, refused.code, refused.reason)

    def behaviour(self) -> None:
        self.json(200, {"answers": self.buyer.answers})

    def behave(self) -> None:
        asked = self.asked(("answers",))
        if asked.get("answers", self.buyer.answers) not in ANSWERS:
            raise Problem(400, "REQUEST", "answers is one of %s, not %r"
                          % (", ".join(ANSWERS), asked["answers"]))
        self.buyer.answers = asked.get("answers", self.buyer.answers)
        self.behaviour()

    def reset(self) -> None:
        if self.headers.get("Content-Length"):
            self.body()
        self.buyer.reset()
        self.supplier.reset()
        self.json(200, {"reset": True})


def clarification(one: object) -> bool:
    """Whether a reason or an action is in a shape `Buyer.answer` reads."""
    if isinstance(one, str):
        return True
    if not isinstance(one, dict):
        return False
    conditions = one.get("conditions", [])
    return (isinstance(one.get("code", ""), str) and isinstance(one.get("text", ""), str)
            and isinstance(conditions, list)
            and all(isinstance(pair, list) and len(pair) == 2
                    and all(isinstance(part, str) for part in pair) for pair in conditions))


def serve(buyer: Buyer, host: str = "127.0.0.1", port: int = PORT, quiet: bool = False,
          supplier: Optional[Supplier] = None) -> ThreadingHTTPServer:
    """A server for one buyer and one supplier, bound and not yet serving:
    call `serve_forever()` on it. Port 0 is a port the operating system
    chooses, which `server_address` then names."""
    handler = type("Handler", (Handler,), {"buyer": buyer, "quiet": quiet,
                                           "supplier": supplier or Supplier(now=buyer.now)})
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    return server


def arguments(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="mock-einvoice",
        description="A mock buyer and supplier. As a buyer it takes UBL invoices and credit "
                    "notes in over HTTP, holds them to EN 16931, Peppol BIS Billing 3.0 "
                    "and XRechnung 3.0, and answers the Peppol ones with Invoice "
                    "Responses. As a supplier it sends them, writes the invoice for "
                    "an order it is told of, and takes the responses.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=PORT, help="default %d" % PORT)
    parser.add_argument("--seller-url", metavar="URL",
                        help="as a buyer: where each Invoice Response is POSTed; without "
                             "it they are kept and read at /_mock/responses/<id>")
    parser.add_argument("--buyer-url", metavar="URL",
                        help="as a supplier: where each document is POSTed; without it "
                             "they are recorded and go nowhere")
    parser.add_argument("--answers", choices=ANSWERS, default="required",
                        help="when a document is acknowledged (AB) on receipt: where its "
                             "profile requires a response (the default), always, or never")
    parser.add_argument("--clock", metavar="YYYY-MM-DDTHH:MM",
                        type=datetime.datetime.fromisoformat,
                        help="the date and time on every response, for output that does "
                             "not change from run to run; the default is now, in UTC")
    parser.add_argument("-q", "--quiet", action="store_true", help="log nothing per request")
    parser.add_argument("--version", action="version", version=__version__)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    asked = arguments(argv)
    now = (lambda: asked.clock) if asked.clock else None
    buyer = Buyer(answers=asked.answers, now=now,
                  deliver=poster(asked.seller_url) if asked.seller_url else None)
    supplier = Supplier(now=now, deliver=poster(asked.buyer_url) if asked.buyer_url else None)
    server = serve(buyer, asked.host, asked.port, asked.quiet, supplier)
    print("mock-einvoice %s: a buyer and a supplier on http://%s:%d"
          % ((__version__,) + server.server_address[:2]), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0

