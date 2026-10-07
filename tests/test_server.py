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
from mockeinvoice.server import LARGEST, PORT, arguments, poster, serve

from . import sample
from .test_buyer import INVOICE, WITH_RESPONSE, XRECHNUNG
from .test_peppol_rules import french

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
        swedish = french(INVOICE).replace("<cbc:IdentificationCode>FR<",
                                          "<cbc:IdentificationCode>SE<")
        status, _headers, body = self.call("POST", "/invoices", swedish)
        self.assertEqual((status, body["error"], body["verdict"], body["findings"]),
                         (422, "NOT-JUDGED", "not judged", []))
        self.assertEqual(body["not_run"], ["SE-R-001", "SE-R-002", "SE-R-003", "SE-R-004",
                                           "SE-R-005", "SE-R-006", "SE-R-013"])

    def test_what_is_not_taken_is_400_by_the_refusals_code(self):
        for document, code in (("hello", "NOT-XML"), ("<a/>", "NOT-UBL"),
                               (INVOICE.replace("billing:3.0<", "billing:9.9<"),
                                "SPECIFICATION")):
            status, _headers, body = self.call("POST", "/invoices", document)
            self.assertEqual((status, body["error"]), (400, code))
            self.assertEqual(sorted(body), ["error", "reason"])
        self.assertEqual([away["error"] for away in self.call("GET", "/_mock/turned-away")[2]],
                         ["NOT-XML", "NOT-UBL", "SPECIFICATION"])

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
        self.assertEqual((body["mock"], body["version"], body["side"], body["answers"]),
                         ("mock-einvoice", __version__, "buyer", "required"))
        self.assertIn("POST /_mock/invoices/<id>/responses", body["paths"])
        self.assertEqual(len(body["paths"]), 12)

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
        asked = arguments([])
        self.assertEqual((asked.host, asked.port, asked.answers, asked.seller_url, asked.clock),
                         ("127.0.0.1", PORT, "required", None, None))
        self.assertEqual(PORT, 8100)

    def test_what_can_be_set(self):
        asked = arguments(["--port", "0", "--answers", "never", "--seller-url", "http://s/r",
                           "--clock", "2026-10-07T09:00", "--quiet"])
        self.assertEqual((asked.port, asked.answers, asked.seller_url, asked.clock, asked.quiet),
                         (0, "never", "http://s/r", datetime.datetime(2026, 10, 7, 9, 0), True))

    def test_the_command_starts_a_server_and_says_where(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        running = subprocess.Popen(
            [sys.executable, "-m", "mockeinvoice", "--port", "0", "--quiet"],
            cwd=root, stderr=subprocess.PIPE, universal_newlines=True)
        try:
            said = running.stderr.readline()
            found = re.match(r"mock-einvoice \S+: a buyer on (http://127\.0\.0\.1:\d+)$",
                             said.strip())
            self.assertTrue(found, said)
            with urllib.request.urlopen(found.group(1) + "/", timeout=10) as answer:
                self.assertEqual(json.loads(answer.read().decode("utf-8"))["side"], "buyer")
        finally:
            running.terminate()
            running.wait(timeout=10)
            running.stderr.close()


if __name__ == "__main__":
    unittest.main()
