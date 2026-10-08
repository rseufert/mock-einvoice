"""The mock over HTTP: each path, what it answers, and what it refuses."""
import datetime
import http.client
import json
import os
import re
import subprocess
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from mockeinvoice import __version__, validate_response
from mockeinvoice.buyer import Buyer
from mockeinvoice.model import catalogue
from mockeinvoice.server import LARGEST, PORT, arguments, poster, serve
from mockeinvoice.supplier import Supplier

from . import sample, unbuilt
from .test_buyer import INVOICE, WITH_RESPONSE, XRECHNUNG
from .test_order import ORDER, buyer, lines, order

NOON = datetime.datetime(2026, 10, 7, 12, 0, 30)
REJECTED = {"code": "RE", "reasons": [{"code": "REF", "text": "no purchase order",
                                       "conditions": [["BT-13", "PO-7"]]}], "actions": ["NIN"]}


class Seller(BaseHTTPRequestHandler):
    """Where responses are sent: keeps what it is given and answers as told."""
    got: list
    status = 200

    def do_POST(self):
        self.got.append((self.headers.get("Content-Type"),
                         self.rfile.read(int(self.headers["Content-Length"]))))
        self.send_response(self.status)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *_args):
        pass


class Served(unittest.TestCase):
    answers = "required"

    def setUp(self):
        self.seller = type("Seller", (Seller,), {"got": []})
        self.selling = self.start(ThreadingHTTPServer(("127.0.0.1", 0), self.seller))
        self.buyer = Buyer(answers=self.answers, now=lambda: NOON,
                           deliver=poster("http://127.0.0.1:%d/responses"
                                          % self.selling.server_address[1]))
        self.server = self.start(serve(self.buyer, port=0, quiet=True))
        self.base = "http://127.0.0.1:%d" % self.server.server_address[1]

    def start(self, server):
        threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01},
                         daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server

    def call(self, method, path, body=None, headers=None):
        """(status, headers, body): the body read as JSON where it is JSON."""
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        request = urllib.request.Request(self.base + path, data=body, method=method,
                                         headers=headers or {})
        try:
            with urllib.request.urlopen(request, timeout=10) as answer:
                status, said, raw = answer.status, answer.headers, answer.read()
        except urllib.error.HTTPError as refused:
            with refused:
                status, said, raw = refused.code, refused.headers, refused.read()
        if said.get("Content-Type", "").startswith("application/json"):
            return status, said, json.loads(raw.decode("utf-8"))
        return status, said, raw


class TheNetworksSide(Served):
    def test_a_valid_invoice_is_taken_in(self):
        status, headers, body = self.call("POST", "/invoices", INVOICE)
        self.assertEqual((status, headers["Location"]), (201, "/_mock/invoices/1"))
        self.assertEqual(body, {
            "id": "1", "kind": "Invoice", "number": "GLX-4711", "issued": "2026-10-02",
            "type": "380", "specification": "peppol", "profile": "01",
            "seller": "Globex GmbH", "buyer": "ACME Corporation",
            "received": "2026-10-07T12:00:30", "verdict": "valid", "status": "",
            "findings": [], "responses": [], "document": "/_mock/invoices/1/document"})
        self.assertEqual(self.seller.got, [])

    def test_an_invalid_one_is_422_with_the_findings(self):
        status, _headers, body = self.call(
            "POST", "/invoices", INVOICE.replace("<cbc:ID>GLX-4711</cbc:ID>", "", 1))
        self.assertEqual((status, body["error"], body["verdict"]), (422, "INVALID", "invalid"))
        self.assertIn("BR-02", [found["code"] for found in body["findings"]])
        self.assertEqual(self.call("GET", "/_mock/invoices")[2], [])

    def test_one_that_could_not_be_judged_is_422_with_the_rules_not_run(self):
        # Every rule is built, so this is the server as it would be without
        # two of Germany's.
        with unbuilt("peppol", "DE-R-001", "DE-R-002"):
            status, _headers, body = self.call("POST", "/invoices", INVOICE)
        self.assertEqual((status, body["error"], body["verdict"], body["findings"]),
                         (422, "NOT-JUDGED", "not judged", []))
        self.assertEqual(body["not_run"], ["DE-R-001", "DE-R-002"])

    def test_what_is_not_taken_is_400_by_the_refusals_code(self):
        for document, code in (("hello", "NOT-XML"), ("<a/>", "NOT-UBL"),
                               (INVOICE.replace("billing:3.0<", "billing:9.9<"),
                                "SPECIFICATION")):
            status, _headers, body = self.call("POST", "/invoices", document)
            self.assertEqual((status, body["error"]), (400, code))
            self.assertEqual(sorted(body), ["error", "reason"])
        self.assertEqual([(away["side"], away["error"])
                          for away in self.call("GET", "/_mock/turned-away")[2]],
                         [("buyer", "NOT-XML"), ("buyer", "NOT-UBL"), ("buyer", "SPECIFICATION")])

    def test_under_billing_with_response_it_is_acknowledged_to_the_seller(self):
        _status, _headers, body = self.call("POST", "/invoices", WITH_RESPONSE)
        self.assertEqual((body["profile"], body["status"]), ("02", "AB"))
        said = body["responses"][0]
        self.assertEqual((said["code"], said["delivery"]["status"]), ("AB", 200))
        (kind, xml), = self.seller.got
        self.assertEqual(kind, "application/xml; charset=utf-8")
        read, report = validate_response(xml)
        self.assertEqual((read.code, read.document.id, report.verdict),
                         ("AB", "GLX-4711", "valid"))
        self.assertEqual(self.call("GET", "/_mock/responses/1")[2], xml)

    def test_a_body_too_large_or_of_no_length(self):
        # Only the headers are sent: the answer comes before any body is read.
        for length, status, code in ((str(LARGEST + 1), 413, "TOO-LARGE"),
                                     (None, 411, "NO-LENGTH"), ("many", 411, "NO-LENGTH")):
            connection = http.client.HTTPConnection(*self.server.server_address[:2], timeout=10)
            self.addCleanup(connection.close)
            connection.putrequest("POST", "/invoices")
            if length:
                connection.putheader("Content-Length", length)
            connection.endheaders()
            answer = connection.getresponse()
            self.assertEqual((answer.status, json.loads(answer.read().decode("utf-8"))["error"]),
                             (status, code))
        self.assertEqual(self.call("POST", "/invoices", INVOICE)[0], 201)


class TheMocksSide(Served):
    def setUp(self):
        super().setUp()
        self.call("POST", "/invoices", INVOICE)

    def test_the_index_names_every_path(self):
        _status, _headers, body = self.call("GET", "/")
        self.assertEqual((body["mock"], body["version"], body["sides"], body["answers"]),
                         ("mock-einvoice", __version__, ["buyer", "supplier"], "required"))
        self.assertIn("POST /_mock/invoices/<id>/responses", body["paths"])
        self.assertIn("POST /_mock/orders/<id>/invoices", body["paths"])
        self.assertIn("GET /_mock/terms/<BT-n or BG-n>", body["paths"])
        self.assertEqual(len(body["paths"]), 27)

    def test_the_terms_are_the_packages_own_table(self):
        status, _headers, body = self.call("GET", "/_mock/terms")
        self.assertEqual((status, body), (200, catalogue()))
        self.assertEqual((len(body["terms"]), len(body["groups"])), (164, 32))
        self.assertEqual(self.call("GET", "/_mock/terms/BT-13")[::2], (200, {
            "id": "BT-13", "name": "Purchase order reference", "group": None,
            "kind": "identifier"}))
        self.assertEqual(self.call("GET", "/_mock/terms/BT-129")[2]["attributes"],
                         {"unitCode": "BT-130"})
        status, _headers, body = self.call("GET", "/_mock/terms/BG-25")
        self.assertEqual((status, body["name"], body["repeats"], body["terms"][:2]),
                         (200, "Invoice line", True, ["BT-126", "BT-127"]))

    def test_a_term_that_is_not_one(self):
        for identifier, why in (
                ("BT-4", "BT-4 is no business term or group known here"),
                ("bt-13", "bt-13 is no business term or group known here"),
                ("13", "13 is no business term"),
                ("BG-33", "BG-33 is no business term"),
                ("BT-29-1", "BT-29-1 is the schemeID of BT-29, and is listed there")):
            status, _headers, body = self.call("GET", "/_mock/terms/" + identifier)
            self.assertEqual((status, body["error"]), (404, "NO-SUCH-TERM"), identifier)
            self.assertIn(why, body["reason"])
        self.assertEqual(self.call("POST", "/_mock/terms", b"")[0], 405)
        self.assertEqual(self.call("GET", "/_mock/terms/BT-13/name")[0], 404)

    def test_health_is_what_the_other_mocks_answer_too(self):
        self.call("POST", "/_mock/sent", INVOICE)
        self.assertEqual(self.call("GET", "/_mock/health")[::2],
                         (200, {"status": "ok", "version": __version__, "held": 1, "sent": 1}))

    def test_what_is_held(self):
        self.call("POST", "/invoices", XRECHNUNG)
        _status, _headers, body = self.call("GET", "/_mock/invoices")
        self.assertEqual([(one["id"], one["specification"], one["profile"]) for one in body],
                         [("1", "peppol", "01"), ("2", "xrechnung", "")])
        self.assertNotIn("findings", body[0])
        self.assertEqual(self.call("GET", "/_mock/invoices/2")[2]["findings"], [])
        status, headers, raw = self.call("GET", "/_mock/invoices/1/document")
        self.assertEqual((status, headers["Content-Type"], raw),
                         (200, "application/xml; charset=utf-8", INVOICE.encode("utf-8")))

    def test_the_buyer_says_something_and_the_seller_gets_it(self):
        status, headers, body = self.call("POST", "/_mock/invoices/1/responses", REJECTED)
        self.assertEqual((status, headers["Location"]), (201, "/_mock/responses/1"))
        self.assertEqual(body, {
            "id": "1", "invoice": "1", "code": "RE", "partial": False, "forced": False,
            "delivery": {"to": self.buyer.deliver(b"")["to"], "status": 200},
            "warnings": [], "document": "/_mock/responses/1"})
        read, report = validate_response(self.seller.got[0][1])
        self.assertEqual(report.verdict, "valid")
        self.assertEqual([(s.reason_code, s.list_id, s.reason, s.conditions)
                          for s in read.statuses],
                         [("REF", "OPStatusReason", "no purchase order", [("BT-13", "PO-7")]),
                          ("NIN", "OPStatusAction", "", [])])
        held = self.call("GET", "/_mock/invoices/1")[2]
        self.assertEqual((held["status"], held["responses"]), ("RE", [body]))

    def test_out_of_order_is_409_by_the_guides_rule_unless_forced(self):
        self.call("POST", "/_mock/invoices/1/responses", REJECTED)
        status, _headers, body = self.call("POST", "/_mock/invoices/1/responses", {"code": "AP"})
        self.assertEqual((status, body["error"], sorted(body)),
                         (409, "OP-BR111-R004", ["error", "reason"]))
        status, _headers, body = self.call("POST", "/_mock/invoices/1/responses",
                                           {"code": "AP", "force": True})
        self.assertEqual((status, body["forced"]), (201, True))

    def test_one_that_would_fail_its_rules_is_422_with_the_finding(self):
        status, _headers, body = self.call("POST", "/_mock/invoices/1/responses", {"code": "RE"})
        self.assertEqual((status, body["error"], [f["code"] for f in body["findings"]]),
                         (422, "INVALID", ["PEPPOL-T111-R001"]))
        self.assertEqual(self.seller.got, [])

    def test_xrechnung_has_no_response(self):
        self.call("POST", "/invoices", XRECHNUNG)
        status, _headers, body = self.call("POST", "/_mock/invoices/2/responses", {"code": "AB"})
        self.assertEqual((status, body["error"]), (409, "NO-RESPONSE"))

    def test_a_request_that_is_not_what_is_asked_for(self):
        for body, code in (("{", "NOT-JSON"), ([1], "REQUEST"), ({}, "REQUEST"),
                           ({"code": "AB", "why": "x"}, "REQUEST"), ({"code": 7}, "REQUEST"),
                           ({"code": "AB", "force": "yes"}, "REQUEST"),
                           ({"code": "UQ", "reasons": "REF"}, "REQUEST"),
                           ({"code": "UQ", "reasons": [{"code": "REF", "conditions": ["x"]}]},
                            "REQUEST"),
                           ({"code": "UQ", "reasons": [{"cod": "REF"}]}, "REQUEST")):
            status, _headers, said = self.call("POST", "/_mock/invoices/1/responses", body)
            self.assertEqual((status, said["error"]), (400, code), body)
        self.assertEqual(self.call("GET", "/_mock/invoices/1")[2]["responses"], [])

    def test_what_is_not_there(self):
        for method, path, body, status, code in (
                ("GET", "/_mock/invoices/9", None, 404, "NO-SUCH-INVOICE"),
                ("GET", "/_mock/invoices/9/document", None, 404, "NO-SUCH-INVOICE"),
                ("POST", "/_mock/invoices/9/responses", {"code": "AB"}, 404, "NO-SUCH-INVOICE"),
                ("GET", "/_mock/responses/9", None, 404, "NO-SUCH-RESPONSE"),
                ("GET", "/nowhere", None, 404, "NO-SUCH-PATH"),
                ("GET", "/invoices", None, 405, "METHOD"),
                ("DELETE", "/_mock/invoices/1", None, 405, "METHOD")):
            got, _headers, said = self.call(method, path, body)
            self.assertEqual((got, said["error"]), (status, code), path)

    def test_validate_holds_a_document_to_its_rules_and_keeps_nothing(self):
        _status, _headers, body = self.call("POST", "/_mock/validate", XRECHNUNG)
        self.assertEqual((body["kind"], body["specification"], body["verdict"]),
                         ("Invoice", "xrechnung", "valid"))
        _status, _headers, body = self.call("POST", "/_mock/validate",
                                            sample("peppol-response.xml"))
        self.assertEqual((body["kind"], body["verdict"], body["rules_run"]),
                         ("ApplicationResponse", "valid", 82))
        status, _headers, body = self.call(
            "POST", "/_mock/validate", INVOICE.replace("<cbc:ID>GLX-4711</cbc:ID>", "", 1))
        self.assertEqual((status, body["verdict"]), (200, "invalid"))
        status, _headers, body = self.call("POST", "/_mock/validate", "<a/>")
        self.assertEqual((status, body["error"]), (400, "NOT-UBL"))
        self.assertEqual(len(self.call("GET", "/_mock/invoices")[2]), 1)
        self.assertEqual(self.call("GET", "/_mock/turned-away")[2], [])

    def test_the_buyers_behaviour_is_a_patch_away(self):
        self.assertEqual(self.call("GET", "/_mock/buyer")[2], {"answers": "required"})
        status, _headers, body = self.call("PATCH", "/_mock/buyer", {"answers": "always"})
        self.assertEqual((status, body), (200, {"answers": "always"}))
        self.assertEqual(self.call("POST", "/invoices", INVOICE)[2]["status"], "AB")
        for wrong in ({"answers": "sometimes"}, {"answer": "never"}):
            self.assertEqual(self.call("PATCH", "/_mock/buyer", wrong)[0], 400)
        self.assertEqual(self.call("GET", "/_mock/buyer")[2], {"answers": "always"})

    def test_reset_forgets_everything_but_how_it_behaves(self):
        self.call("PATCH", "/_mock/buyer", {"answers": "never"})
        self.call("POST", "/invoices", "hello")
        self.assertEqual(self.call("POST", "/_mock/reset", b"")[2], {"reset": True})
        self.assertEqual((self.call("GET", "/_mock/invoices")[2],
                          self.call("GET", "/_mock/turned-away")[2],
                          self.call("GET", "/_mock/buyer")[2]), ([], [], {"answers": "never"}))
        self.assertEqual(self.call("POST", "/invoices", INVOICE)[2]["id"], "1")


class TheSupplier(unittest.TestCase):
    """Two of the mock: one sends as a supplier, the other receives as a
    buyer, and each is told where the other is."""

    def setUp(self):
        self.buyer, self.supplier = Buyer(now=lambda: NOON), Supplier(now=lambda: NOON)
        self.buying = self.start(serve(self.buyer, port=0, quiet=True))
        self.selling = self.start(serve(Buyer(), port=0, quiet=True, supplier=self.supplier))
        self.base = "http://127.0.0.1:%d" % self.selling.server_address[1]
        self.buyers = "http://127.0.0.1:%d" % self.buying.server_address[1]
        self.supplier.deliver = poster(self.buyers + "/invoices")
        self.buyer.deliver = poster(self.base + "/responses")

    start, call = Served.start, Served.call

    def at_the_buyer(self, method, path, body=None):
        self.base, kept = self.buyers, self.base
        try:
            return self.call(method, path, body)
        finally:
            self.base = kept

    def test_a_document_is_sent_and_the_buyer_holds_it(self):
        status, headers, body = self.call("POST", "/_mock/sent", INVOICE)
        self.assertEqual((status, headers["Location"]), (201, "/_mock/sent/1"))
        self.assertEqual(body, {
            "id": "1", "kind": "Invoice", "number": "GLX-4711", "issued": "2026-10-02",
            "type": "380", "specification": "peppol", "seller": "Globex GmbH",
            "buyer": "ACME Corporation", "sent": "2026-10-07T12:00:30", "verdict": "valid",
            "forced": False, "delivery": {"to": self.buyers + "/invoices", "status": 201},
            "status": "", "order": None, "findings": [], "responses": [],
            "document": "/_mock/sent/1/document"})
        self.assertEqual(self.at_the_buyer("GET", "/_mock/invoices/1/document")[2],
                         INVOICE.encode("utf-8"))
        self.assertEqual(self.call("GET", "/_mock/sent/1/document")[2], INVOICE.encode("utf-8"))
        self.assertEqual([(one["id"], one["status"])
                          for one in self.call("GET", "/_mock/sent")[2]], [("1", "")])

    def test_the_buyers_responses_come_back_and_move_its_status(self):
        self.call("POST", "/_mock/sent", INVOICE)
        for asked in ({"code": "AB"}, REJECTED):
            _status, _headers, said = self.at_the_buyer("POST", "/_mock/invoices/1/responses",
                                                        asked)
            self.assertEqual(said["delivery"]["status"], 201)
        sent = self.call("GET", "/_mock/sent/1")[2]
        self.assertEqual((sent["status"], sent["responses"]), ("RE", [
            {"id": "1", "sent": "1", "code": "AB", "partial": False, "ignored": "",
             "received": "2026-10-07T12:00:30", "document": "/_mock/answers/1"},
            {"id": "2", "sent": "1", "code": "RE", "partial": False, "ignored": "",
             "received": "2026-10-07T12:00:30", "document": "/_mock/answers/2"}]))
        self.assertEqual(self.call("GET", "/_mock/answers/2")[2],
                         self.at_the_buyer("GET", "/_mock/responses/2")[2])

    def test_one_out_of_order_is_taken_and_ignored(self):
        self.call("POST", "/_mock/sent", INVOICE)
        self.at_the_buyer("POST", "/_mock/invoices/1/responses", REJECTED)
        said = self.at_the_buyer("POST", "/_mock/invoices/1/responses",
                                 {"code": "AP", "force": True})[2]
        self.assertEqual(said["delivery"]["status"], 201)
        sent = self.call("GET", "/_mock/sent/1")[2]
        self.assertEqual((sent["status"], [got["ignored"] for got in sent["responses"]]),
                         ("RE", ["", "OP-BR111-R004"]))

    def test_one_that_is_not_valid_is_not_sent_unless_forced(self):
        broken = INVOICE.replace("<cbc:ID>GLX-4711</cbc:ID>", "", 1)
        status, _headers, body = self.call("POST", "/_mock/sent", broken)
        self.assertEqual((status, body["error"], body["verdict"]), (422, "INVALID", "invalid"))
        self.assertIn("BR-02", [found["code"] for found in body["findings"]])
        self.assertEqual(self.call("GET", "/_mock/sent")[2], [])
        status, _headers, body = self.call("POST", "/_mock/sent?force=true", broken)
        self.assertEqual((status, body["forced"], body["verdict"], body["delivery"]["status"]),
                         (201, True, "invalid", 422))
        self.assertEqual([away["error"]
                          for away in self.at_the_buyer("GET", "/_mock/turned-away")[2]],
                         ["INVALID"])
        self.assertEqual(self.call("POST", "/_mock/sent?force=false", INVOICE)[2]["forced"],
                         False)

    def test_what_is_not_an_invoice_and_what_is_not_asked_right(self):
        for path, body, status, code in (
                ("/_mock/sent", "hello", 400, "NOT-XML"),
                ("/_mock/sent?force=true", "<a/>", 400, "NOT-UBL"),
                ("/_mock/sent?force=yes", INVOICE, 400, "REQUEST"),
                ("/_mock/sent?forced=true", INVOICE, 400, "REQUEST")):
            got, _headers, said = self.call("POST", path, body)
            self.assertEqual((got, said["error"]), (status, code), path)
        self.assertEqual(self.call("GET", "/_mock/sent")[2], [])

    def test_a_response_that_is_not_one_fails_its_rules_or_is_about_nothing_sent(self):
        response = sample("peppol-response.xml").decode("utf-8")
        for body, status, code in (
                ("hello", 400, "NOT-XML"), (INVOICE, 400, "NOT-A-RESPONSE"),
                (response.replace(">UQ<", ">OK<"), 422, "INVALID"),
                (response, 422, "NO-SUCH-INVOICE")):
            got, _headers, said = self.call("POST", "/responses", body)
            self.assertEqual((got, said["error"]), (status, code))
            self.assertEqual("findings" in said, code == "INVALID")
        self.assertEqual([(away["side"], away["error"])
                          for away in self.call("GET", "/_mock/turned-away")[2]],
                         [("supplier", "NOT-XML"), ("supplier", "NOT-A-RESPONSE"),
                          ("supplier", "INVALID"), ("supplier", "NO-SUCH-INVOICE")])

    def test_a_response_from_anywhere_is_taken_if_it_is_about_a_document_sent(self):
        self.call("POST", "/_mock/sent", INVOICE)
        status, headers, body = self.call("POST", "/responses", sample("peppol-response.xml"))
        self.assertEqual((status, headers["Location"], body["code"]),
                         (201, "/_mock/answers/1", "UQ"))
        self.assertEqual(self.call("GET", "/_mock/sent/1")[2]["status"], "UQ")

    def test_what_is_not_there_and_reset(self):
        for path, code in (("/_mock/sent/9", "NO-SUCH-DOCUMENT"),
                           ("/_mock/sent/9/document", "NO-SUCH-DOCUMENT"),
                           ("/_mock/answers/9", "NO-SUCH-RESPONSE")):
            got, _headers, said = self.call("GET", path)
            self.assertEqual((got, said["error"]), (404, code))
        self.call("POST", "/_mock/sent", INVOICE)
        self.call("POST", "/responses", sample("peppol-response.xml"))
        self.call("POST", "/responses", "hello")
        self.call("POST", "/_mock/reset", b"")
        self.assertEqual((self.call("GET", "/_mock/sent")[2],
                          self.call("GET", "/_mock/turned-away")[2],
                          self.call("GET", "/_mock/answers/1")[0]), ([], [], 404))

    def test_an_order_is_taken_billed_and_held_by_the_buyer(self):
        status, headers, body = self.call("POST", "/_mock/orders", ORDER)
        self.assertEqual((status, headers["Location"]), (201, "/_mock/orders/1"))
        self.assertEqual(body, {
            "id": "1", "number": "4500000017", "reference": "", "buyer": ORDER["buyer"],
            "received": "2026-10-07T12:00:30", "status": "open", "currency": "",
            "lines": [
                {"line": "10", "name": "Widget", "seller_item": "W-100", "buyer_item": "",
                 "quantity": "40", "unit": "C62", "price": "20.00", "billed": "0",
                 "open": "40"},
                {"line": "20", "name": "Installation", "seller_item": "", "buyer_item": "",
                 "quantity": "2.5", "unit": "HUR", "price": "33.333", "billed": "0",
                 "open": "2.5"}],
            "invoices": []})
        self.assertEqual((self.call("GET", "/_mock/sent")[2],
                          self.at_the_buyer("GET", "/_mock/invoices")[2]), ([], []))
        status, headers, body = self.call("POST", "/_mock/orders/1/invoices", b"")
        self.assertEqual((status, headers["Location"]), (201, "/_mock/sent/1"))
        self.assertEqual(body, {
            "id": "1", "kind": "Invoice", "number": "GLX-0001", "issued": "2026-10-07",
            "type": "380", "specification": "peppol", "seller": "Globex GmbH",
            "buyer": "ACME Corporation", "sent": "2026-10-07T12:00:30", "verdict": "valid",
            "forced": False, "delivery": {"to": self.buyers + "/invoices", "status": 201},
            "status": "", "order": "/_mock/orders/1", "findings": [], "responses": [],
            "document": "/_mock/sent/1/document"})
        held = self.at_the_buyer("GET", "/_mock/invoices/1")[2]
        self.assertEqual((held["number"], held["verdict"], held["seller"]),
                         ("GLX-0001", "valid", "Globex GmbH"))
        self.assertEqual(self.at_the_buyer("GET", "/_mock/invoices/1/document")[2],
                         self.call("GET", "/_mock/sent/1/document")[2])
        self.assertIn(b"<cbc:ID>4500000017</cbc:ID>",
                      self.call("GET", "/_mock/sent/1/document")[2])
        taken = self.call("GET", "/_mock/orders/1")[2]
        self.assertEqual((taken["status"], taken["invoices"],
                          [line["open"] for line in taken["lines"]]),
                         ("billed", ["/_mock/sent/1"], ["0", "0.0"]))
        self.assertEqual(self.call("GET", "/_mock/orders")[2], [
            {"id": "1", "number": "4500000017", "reference": "", "buyer": "ACME Corporation",
             "received": "2026-10-07T12:00:30", "status": "billed"}])

    def test_what_the_buyer_says_of_an_invoice_written_here_comes_back(self):
        self.call("POST", "/_mock/orders", ORDER)
        self.call("POST", "/_mock/orders/1/invoices", {})
        self.at_the_buyer("POST", "/_mock/invoices/1/responses", {"code": "AP"})
        self.assertEqual(self.call("GET", "/_mock/sent/1")[2]["status"], "AP")

    def test_an_order_billed_in_parts(self):
        self.call("POST", "/_mock/orders", ORDER)
        asked = {"lines": [{"line": "10", "quantity": 15}, {"line": "20", "quantity": 0.5}]}
        status, _headers, body = self.call("POST", "/_mock/orders/1/invoices", asked)
        self.assertEqual((status, body["number"]), (201, "GLX-0001"))
        taken = self.call("GET", "/_mock/orders/1")[2]
        self.assertEqual((taken["status"], [(line["billed"], line["open"])
                                            for line in taken["lines"]]),
                         ("billed in part", [("15", "25"), ("0.5", "2.0")]))
        status, _headers, body = self.call("POST", "/_mock/orders/1/invoices", asked["lines"])
        self.assertEqual((status, body["error"]), (400, "REQUEST"))
        for lines_asked, got, code in (
                ([{"line": "10", "quantity": 26}], 409, "OVER-BILLED"),
                ([{"line": "30", "quantity": 1}], 404, "NO-SUCH-LINE"),
                ([{"line": "10", "quantity": "0"}], 400, "REQUEST"),
                ([{"line": "10", "quantity": 1}, {"line": "10", "quantity": 1}], 400, "REQUEST"),
                ([{"line": "10"}], 400, "REQUEST"),
                ([{"line": 10, "quantity": 1}], 400, "REQUEST"),
                ([], 400, "REQUEST"),
                ("10", 400, "REQUEST")):
            status, _headers, body = self.call("POST", "/_mock/orders/1/invoices",
                                               {"lines": lines_asked})
            self.assertEqual((status, body["error"]), (got, code), lines_asked)
        self.assertEqual(self.call("POST", "/_mock/orders/1/invoices", {"force": True})[0], 400)
        self.assertEqual(self.call("POST", "/_mock/orders/1/invoices", {})[2]["number"],
                         "GLX-0002")
        status, _headers, body = self.call("POST", "/_mock/orders/1/invoices", {})
        self.assertEqual((status, body["error"], body["reason"]),
                         (409, "BILLED", "order 4500000017 is billed in full, by GLX-0001 "
                                         "and GLX-0002"))
        self.assertEqual(len(self.call("GET", "/_mock/sent")[2]), 2)

    def test_an_order_that_is_not_taken(self):
        for said, got, code in ((order(delivery="tomorrow"), 400, "REQUEST"),
                                (lines({"price": "dear"}), 400, "REQUEST"),
                                ([ORDER], 400, "REQUEST"),
                                ("{", 400, "NOT-JSON"),
                                (buyer(postal_code=None), 422, "UNBILLABLE")):
            status, _headers, body = self.call("POST", "/_mock/orders", said)
            self.assertEqual((status, body["error"]), (got, code), said)
        self.assertEqual((body["verdict"], [found["code"] for found in body["findings"]]),
                         ("invalid", ["DE-R-009"]))
        self.assertEqual(self.call("GET", "/_mock/orders")[2], [])
        for method, path in (("GET", "/_mock/orders/1"), ("POST", "/_mock/orders/1/invoices")):
            status, _headers, body = self.call(method, path, b"" if method == "POST" else None)
            self.assertEqual((status, body["error"]), (404, "NO-SUCH-ORDER"))

    def test_a_price_with_a_fraction_written_as_a_number_is_the_price_as_written(self):
        # 0.1 and 0.7 are not what a float holds; 3 at 0.1 would be 0.30000000000000004.
        self.call("POST", "/_mock/orders", json.dumps(
            lines({"quantity": 3, "price": 0.1}, {"line": "20", "quantity": 0.7, "price": 1})))
        taken = self.call("GET", "/_mock/orders/1")[2]
        self.assertEqual([(line["quantity"], line["price"]) for line in taken["lines"]],
                         [("3", "0.1"), ("0.7", "1")])
        self.call("POST", "/_mock/orders/1/invoices", b"")
        document = self.call("GET", "/_mock/sent/1/document")[2]
        self.assertIn(b'<cbc:PriceAmount currencyID="EUR">0.1</cbc:PriceAmount>', document)
        self.assertIn(b'<cbc:PayableAmount currencyID="EUR">1.19</cbc:PayableAmount>', document)

    def test_who_the_supplier_is_and_changing_it(self):
        status, _headers, body = self.call("GET", "/_mock/supplier")
        self.assertEqual((status, body["name"], body["vat_rate"], body["payment_days"]),
                         (200, "Globex GmbH", "19", 30))
        self.assertEqual(sorted(body), sorted(
            ["name", "endpoint", "vat", "legal_id", "street", "city", "postal_code", "country",
             "contact", "telephone", "email", "iban", "bic", "currency", "vat_rate",
             "payment_days", "number_prefix"]))
        status, _headers, body = self.call("PATCH", "/_mock/supplier", {
            "name": "Initech AG", "vat_rate": 7.5, "payment_days": 10, "number_prefix": "INI-"})
        self.assertEqual((status, body["name"], body["vat_rate"], body["city"]),
                         (200, "Initech AG", "7.5", "Hamburg"))
        self.assertEqual(self.call("GET", "/_mock/supplier")[2], body)
        self.call("POST", "/_mock/orders", ORDER)
        sent = self.call("POST", "/_mock/orders/1/invoices", b"")[2]
        self.assertEqual((sent["number"], sent["seller"]), ("INI-0001", "Initech AG"))
        document = self.call("GET", "/_mock/sent/1/document")[2]
        self.assertIn(b"<cbc:DueDate>2026-10-17</cbc:DueDate>", document)
        self.assertIn(b"<cbc:Percent>7.5</cbc:Percent>", document)
        for changes in ({"fax": "1"}, {"vat_rate": 0}, {"payment_days": 1.5}, ["Initech"]):
            status, _headers, body = self.call("PATCH", "/_mock/supplier", changes)
            self.assertEqual((status, body["error"]), (400, "REQUEST"), changes)
        self.call("POST", "/_mock/reset", b"")
        self.assertEqual((self.call("GET", "/_mock/supplier")[2]["name"],
                          self.call("GET", "/_mock/orders")[2]), ("Initech AG", []))

    def test_a_supplier_changed_so_that_its_invoice_is_not_valid_does_not_send_it(self):
        self.call("POST", "/_mock/orders", ORDER)
        self.call("PATCH", "/_mock/supplier", {"vat": ""})
        status, _headers, body = self.call("POST", "/_mock/orders/1/invoices", b"")
        self.assertEqual((status, body["error"], body["verdict"]), (422, "NOT-VALID", "invalid"))
        self.assertTrue(body["findings"])
        self.assertEqual((self.call("GET", "/_mock/sent")[2],
                          self.call("GET", "/_mock/orders/1")[2]["status"]), ([], "open"))
        status, _headers, body = self.call("POST", "/_mock/orders", order(number="2"))
        self.assertEqual((status, body["error"]), (422, "UNBILLABLE"))

    def test_with_no_buyer_there_the_document_is_recorded_all_the_same(self):
        self.buying.shutdown()
        self.buying.server_close()
        _status, _headers, body = self.call("POST", "/_mock/sent", INVOICE)
        self.assertIn("error", body["delivery"])
        self.supplier.deliver = None
        self.assertIsNone(self.call("POST", "/_mock/sent", INVOICE)[2]["delivery"])


class Delivery(Served):
    def test_a_seller_who_refuses_is_recorded_and_the_response_stands(self):
        self.seller.status = 503
        self.call("POST", "/invoices", INVOICE)
        status, _headers, body = self.call("POST", "/_mock/invoices/1/responses", {"code": "AB"})
        self.assertEqual((status, body["delivery"]["status"]), (201, 503))

    def test_a_seller_who_is_not_there(self):
        self.selling.shutdown()
        self.selling.server_close()
        self.call("POST", "/invoices", INVOICE)
        _status, _headers, body = self.call("POST", "/_mock/invoices/1/responses",
                                            {"code": "AB"})
        self.assertIn("error", body["delivery"])
        self.assertEqual(self.call("GET", "/_mock/invoices/1")[2]["status"], "AB")


class TheCommandLine(unittest.TestCase):
    def test_the_defaults(self):
        self.assertTrue(arguments(["-q"]).quiet)
        asked = arguments([])
        self.assertEqual((asked.host, asked.port, asked.answers, asked.seller_url,
                          asked.buyer_url, asked.clock),
                         ("127.0.0.1", PORT, "required", None, None, None))
        self.assertEqual(PORT, 8100)

    def test_what_can_be_set(self):
        asked = arguments(["--port", "0", "--answers", "never", "--seller-url", "http://s/r",
                           "--buyer-url", "http://b/i", "--clock", "2026-10-07T09:00",
                           "--quiet"])
        self.assertEqual((asked.port, asked.answers, asked.seller_url, asked.buyer_url,
                          asked.clock, asked.quiet),
                         (0, "never", "http://s/r", "http://b/i",
                          datetime.datetime(2026, 10, 7, 9, 0), True))

    def test_the_command_starts_a_server_and_says_where(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        running = subprocess.Popen(
            [sys.executable, "-m", "mockeinvoice", "--port", "0", "--quiet"],
            cwd=root, stdout=subprocess.PIPE, universal_newlines=True)
        try:
            said = running.stdout.readline()
            found = re.match(r"mock-einvoice \S+: a buyer and a supplier on (http://127\.0\.0\.1:\d+)$",
                             said.strip())
            self.assertTrue(found, said)
            with urllib.request.urlopen(found.group(1) + "/", timeout=10) as answer:
                self.assertEqual(json.loads(answer.read().decode("utf-8"))["sides"],
                                 ["buyer", "supplier"])
        finally:
            running.terminate()
            running.wait(timeout=10)
            running.stdout.close()


if __name__ == "__main__":
    unittest.main()
