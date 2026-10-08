"""The supplier: what sends an invoice out, and what it hears back.

    from mockeinvoice.supplier import Supplier

    supplier = Supplier(deliver=...)
    issued = supplier.send(xml)             # or NotSent, saying why
    got = supplier.hear(response_xml)       # or TurnedAway
    issued.status                           # "AP": the last thing the buyer said

A document is held to its rules before it is sent, as a real sender's access
point does, and one that is not `valid` is not sent unless it is forced:
a buyer's system has to be tried against invoices that are wrong.

An Invoice Response is held to its own rules and matched to a document sent,
by its number and type code. Peppol's guide says of a response that comes out
of order that the seller may ignore it; such a one is kept, marked with the
rule it broke (`buyer.PROCESS`), and does not move the document's status.

It can also be told of an order, and writes the invoice for one itself:

    order = supplier.take({"number": "4500000017", "buyer": {...}, "lines": [...]})
    issued = supplier.bill(order.id)        # or NotBilled; all of it, or some lines' worth

What an order is, and where the rest of the invoice comes from, is in
`mockeinvoice.order`. Nothing is billed until it is asked for.
"""
from __future__ import annotations

import datetime
import threading
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple, Union

from . import order as _order
from . import response as _response
from . import specification as _specification
from .buyer import TurnedAway, out_of_order
from .model import Document, Refused
from .order import NotTaken, Order
from .response import Response
from .rules import Report, check, check_response
from .ubl import parse_tree, write


class NotSent(Exception):
    """A document the supplier did not send, and why: the refusal's own code
    where it is not a document that is taken, and `INVALID` or `NOT-JUDGED`
    with its `report` where it is."""

    def __init__(self, code: str, reason: str, report: Optional[Report] = None):
        super().__init__(reason)
        self.code, self.reason, self.report = code, reason, report


class NotBilled(Exception):
    """An invoice the supplier did not write for an order, and why. Where it
    wrote one that is not valid, `report` is what was found."""

    def __init__(self, code: str, reason: str, report: Optional[Report] = None):
        super().__init__(reason)
        self.code, self.reason, self.report = code, reason, report


@dataclass
class Got:
    """One Invoice Response the supplier was given."""
    id: str
    invoice: str                            # the id of the document it answers
    code: str
    partial: bool                           # a payment in part: PD with the reason PPD
    # The guide's rule it broke by coming when it did, or "": a response that
    # broke one is kept and does not move the document's status.
    ignored: str
    xml: bytes
    response: Response
    received: str


@dataclass
class Issued:
    """A document the supplier sent."""
    id: str
    xml: bytes
    document: Document
    report: Report
    sent: str                               # when, as an ISO 8601 date and time
    forced: bool                            # sent though it was not valid
    # What became of sending it to the buyer: {"to": url, "status": 201},
    # {"to": url, "error": "..."}, or None where there was nowhere to send it.
    delivery: Optional[dict] = None
    responses: List[Got] = field(default_factory=list)
    order: str = ""                         # the id of the order it was written for, or ""

    @property
    def number(self) -> str:
        return self.document.text("BT-1")

    @property
    def status(self) -> str:
        """The last thing the buyer said that was not ignored, or ""."""
        heeded = [got.code for got in self.responses if not got.ignored]
        return heeded[-1] if heeded else ""


class Supplier:
    """A supplier's system: the documents it has sent and what came back.

    `deliver` is called with each document's XML and returns what became of
    sending it (see `Issued.delivery`); without one, documents are recorded
    and go nowhere. `now` is the clock. `who` is what it puts in an invoice it
    writes itself (`order.WHO`, with any changes); `reset` leaves it alone.
    """

    def __init__(self, deliver: Optional[Callable[[bytes], dict]] = None,
                 now: Optional[Callable[[], datetime.datetime]] = None,
                 who: Optional[dict] = None):
        self.deliver = deliver
        self.who = _order.described(_order.WHO, who or {})
        self.now = now or (lambda: datetime.datetime.now(datetime.timezone.utc))
        self.lock = threading.RLock()
        self.reset()

    def reset(self) -> None:
        with self.lock:
            self.sent: Dict[str, Issued] = {}
            self.answers: Dict[str, Got] = {}
            # Responses that were turned away: (when, code, reason), oldest first.
            self.turned_away: List[Tuple[str, str, str]] = []
            self.orders: Dict[str, Order] = {}
            self.written = 0                # the invoices it has written and numbered

    def stamp(self) -> str:
        return self.now().replace(microsecond=0, tzinfo=None).isoformat()

    # -- sending ------------------------------------------------------------------------

    def send(self, data: Union[bytes, str], force: bool = False) -> Issued:
        """Send a document to the buyer, or raise `NotSent`. `force` sends
        one that is not valid; it does not send what is not an invoice."""
        raw = data.encode("utf-8") if isinstance(data, str) else data
        return self.delivered(self.judged(raw, force))

    def judged(self, raw: bytes, force: bool = False) -> Issued:
        """Hold a document to its rules and record it as sent, or raise `NotSent`."""
        try:
            document, findings, elements = parse_tree(raw)
            specification = _specification.identify(document)
        except Refused as refused:
            raise NotSent(refused.code, refused.reason)
        report = check(document, specification, findings, elements)
        if report.verdict != "valid" and not force:
            raise NotSent(report.verdict.upper().replace(" ", "-"),
                          "the document is %s and was not sent: \"force\" sends it anyway"
                          % report.verdict, report)
        with self.lock:
            issued = Issued(str(len(self.sent) + 1), raw, document, report, self.stamp(),
                            report.verdict != "valid")
            self.sent[issued.id] = issued
        return issued

    def delivered(self, issued: Issued) -> Issued:
        # Not under the lock: a buyer may answer before it has finished
        # taking the document, and its answer has to be heard.
        if self.deliver is not None:
            issued.delivery = self.deliver(issued.xml)
        return issued

    # -- billing an order ---------------------------------------------------------------

    def describe(self, changes: dict) -> dict:
        """Change who the supplier is, or raise `NotTaken`."""
        with self.lock:
            self.who = _order.described(self.who, changes)
            return self.who

    def take(self, said: object) -> Order:
        """Take an order, or raise `NotTaken`. Nothing is billed for it yet.

        The invoice it would be billed with is written and held to its rules
        first, and thrown away: an order that could not be billed (a buyer in
        Germany with no post code, an endpoint that is no GLN) is not taken.
        """
        order = _order.read_order(said)
        with self.lock:
            document = _order.invoice(order, self.who, self.numbered(), self.now().date())
            report = check(document, "peppol")
            if report.verdict != "valid":
                raise NotTaken("the invoice for this order would be %s, and an order that "
                               "cannot be billed is not taken" % report.verdict, report)
            order.id, order.received = str(len(self.orders) + 1), self.stamp()
            self.orders[order.id] = order
        return order

    def bill(self, identifier: str, quantities: Optional[Dict[str, object]] = None) -> Issued:
        """Write the invoice for an order and send it, or raise `NotBilled`:
        for these quantities of its lines, by the order's line numbers, or
        for all that is not yet billed. An invoice that is not valid is not
        sent, and nothing is counted as billed."""
        with self.lock:
            order = self.orders.get(identifier)
            if order is None:
                raise NotBilled("NO-SUCH-ORDER", "no order %s was taken" % identifier)
            if order.status == "billed":
                raise NotBilled("BILLED", "order %s is billed in full, by %s"
                                % (order.number, " and ".join(
                                    self.sent[one].number for one in order.invoices)))
            billing = self.asked_for(order, quantities)
            document = _order.invoice(order, self.who, self.numbered(), self.now().date(),
                                      billing)
            try:
                issued = self.judged(write(document))
            except NotSent as no:
                raise NotBilled("NOT-VALID", "the invoice written for order %s is %s and "
                                "was not sent" % (order.number, no.report.verdict), no.report)
            issued.order = order.id
            self.written += 1
            order.invoices.append(issued.id)
            for line in order.lines:
                line.billed += billing.get(line.line, 0)
        return self.delivered(issued)

    def numbered(self) -> str:
        """The number of the next invoice it writes."""
        return "%s%04d" % (self.who["number_prefix"], self.written + 1)

    def asked_for(self, order: Order, quantities: Optional[Dict[str, object]]) -> dict:
        """What to bill of each line, by line number: what was asked for, or
        what is open."""
        if quantities is None:
            return {line.line: line.open for line in order.lines if line.open}
        billing = {}
        for number, asked in quantities.items():
            line = order.line(number)
            if line is None:
                raise NotBilled("NO-SUCH-LINE", "order %s has no line %s: its lines are %s"
                                % (order.number, number,
                                   ", ".join(one.line for one in order.lines)))
            try:
                quantity = _order.number(asked, "line %s's quantity" % number)
            except NotTaken as no:
                raise NotBilled("REQUEST", str(no))
            if quantity <= 0:
                raise NotBilled("REQUEST", "line %s is to be billed for %s, and an invoice "
                                "line is for more than nothing" % (number, quantity))
            if quantity > line.open:
                raise NotBilled("OVER-BILLED", "line %s is to be billed for %s, and %s of the "
                                "%s ordered is not yet billed"
                                % (number, quantity, line.open, line.quantity))
            billing[number] = quantity
        if not billing:
            raise NotBilled("REQUEST", "no line was named to be billed")
        return billing

    # -- hearing back -------------------------------------------------------------------

    def hear(self, data: Union[bytes, str]) -> Got:
        """Take an Invoice Response, or raise `TurnedAway`."""
        raw = data.encode("utf-8") if isinstance(data, str) else data
        with self.lock:
            try:
                return self.heard(raw)
            except TurnedAway as away:
                self.turned_away.append((self.stamp(), away.code, away.reason))
                raise

    def heard(self, raw: bytes) -> Got:
        try:
            read, findings, elements = _response.parse_tree(raw)
        except Refused as refused:
            raise TurnedAway(refused.code, refused.reason)
        report = check_response(elements, findings)
        if report.failures:
            raise TurnedAway("INVALID", "the response is invalid: %d finding%s, the first %s "
                             "at %s" % (len(report.failures),
                                        "" if len(report.failures) == 1 else "s",
                                        report.failures[0].code, report.failures[0].path),
                             report)
        issued = self.answered(read)
        partial = read.code == "PD" and any(
            status.reason_code == "PPD" and status.list_id == _response.REASON_LIST
            for status in read.statuses)
        heeded = [got for got in issued.responses if not got.ignored]
        got = Got(str(len(self.answers) + 1), issued.id, read.code, partial,
                  out_of_order(heeded, read.code, partial) or "", raw, read, self.stamp())
        self.answers[got.id] = got
        issued.responses.append(got)
        return got

    def answered(self, read: Response) -> Issued:
        """The document a response is about: the last one sent with its number
        and its type code."""
        number, type_code = read.document.id.strip(), read.document.type_code.strip()
        numbered = [issued for issued in self.sent.values()
                    if issued.number.strip() == number]
        if not numbered:
            raise TurnedAway("NO-SUCH-INVOICE", "the response is about a document numbered "
                             "%r, and none was sent with that number" % number)
        typed = [issued for issued in numbered
                 if issued.document.text("BT-3").strip() == type_code]
        if not typed:
            raise TurnedAway("NO-SUCH-INVOICE", "the response is about a document numbered "
                             "%r of type %r, and the one sent with that number is of type "
                             "%s (OP-BR111-R014)"
                             % (number, type_code,
                                " and ".join(sorted({issued.document.text("BT-3")
                                                     for issued in numbered}))))
        return typed[-1]
