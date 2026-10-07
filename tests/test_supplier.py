"""The supplier: what it sends, what it will not, and what it hears back."""
import datetime
import unittest

from mockeinvoice.buyer import ORDER, Buyer, TurnedAway
from mockeinvoice.supplier import NotSent, Supplier

from . import sample
from .test_buyer import CREDIT_NOTE, INVOICE, REF, XRECHNUNG
from .test_peppol_rules import french

NOON = datetime.datetime(2026, 10, 7, 12, 0, 30)
BROKEN = INVOICE.replace("<cbc:ID>GLX-4711</cbc:ID>", "", 1)
RESPONSE = sample("peppol-response.xml").decode("utf-8")      # UQ, about GLX-4711, a 380
PARTLY = [{"code": "PPD", "text": "half now"}]


def pair(**how):
    """A supplier and a buyer who deliver to each other, with no HTTP between."""
    buyer = Buyer(now=lambda: NOON, **how)
    supplier = Supplier(now=lambda: NOON,
                        deliver=lambda xml: {"to": "buyer", "held": buyer.receive(xml).id})
    buyer.deliver = lambda xml: {"to": "seller", "ignored": supplier.hear(xml).ignored}
    return supplier, buyer


class Sending(unittest.TestCase):
    def test_a_valid_document_is_sent_and_recorded(self):
        delivered = []
        supplier = Supplier(now=lambda: NOON,
                            deliver=lambda xml: delivered.append(xml) or {"status": 201})
        issued = supplier.send(INVOICE)
        self.assertEqual((issued.id, issued.number, issued.sent, issued.forced, issued.status),
                         ("1", "GLX-4711", "2026-10-07T12:00:30", False, ""))
        self.assertEqual((delivered, issued.delivery, issued.xml),
                         ([INVOICE.encode("utf-8")], {"status": 201}, INVOICE.encode("utf-8")))
        self.assertEqual(supplier.send(XRECHNUNG.encode("utf-8")).id, "2")
        self.assertEqual(list(supplier.sent), ["1", "2"])

    def test_with_nowhere_to_send_it_is_recorded_and_goes_nowhere(self):
        self.assertIsNone(Supplier().send(INVOICE).delivery)

    def test_one_that_is_not_valid_is_not_sent(self):
        swedish = french(INVOICE).replace("<cbc:IdentificationCode>FR<",
                                          "<cbc:IdentificationCode>SE<")
        for document, code, verdict in ((BROKEN, "INVALID", "invalid"),
                                        (swedish, "NOT-JUDGED", "not judged")):
            delivered = []
            supplier = Supplier(deliver=delivered.append)
            with self.assertRaises(NotSent) as raised:
                supplier.send(document)
            self.assertEqual((raised.exception.code, raised.exception.report.verdict),
                             (code, verdict))
            self.assertEqual((delivered, supplier.sent), ([], {}))

    def test_unless_it_is_forced(self):
        delivered = []
        supplier = Supplier(deliver=lambda xml: delivered.append(xml) or {})
        issued = supplier.send(BROKEN, force=True)
        self.assertEqual((issued.forced, issued.report.verdict, delivered),
                         (True, "invalid", [BROKEN.encode("utf-8")]))
        self.assertFalse(supplier.send(INVOICE, force=True).forced)

    def test_what_is_not_an_invoice_is_never_sent(self):
        for force in (False, True):
            for document, code in (("hello", "NOT-XML"), (RESPONSE, "NOT-AN-INVOICE"),
                                   (INVOICE.replace("billing:3.0<", "billing:9.9<"),
                                    "SPECIFICATION")):
                delivered = []
                with self.assertRaises(NotSent) as raised:
                    Supplier(deliver=delivered.append).send(document, force=force)
                self.assertEqual((raised.exception.code, raised.exception.report, delivered),
                                 (code, None, []))


class HearingBack(unittest.TestCase):
    def test_a_response_moves_the_documents_status(self):
        supplier = Supplier(now=lambda: NOON)
        issued = supplier.send(INVOICE)
        got = supplier.hear(RESPONSE)
        self.assertEqual((got.id, got.invoice, got.code, got.partial, got.ignored,
                          got.received),
                         ("1", "1", "UQ", False, "", "2026-10-07T12:00:30"))
        self.assertEqual((got.xml, got.response.statuses[0].reason_code),
                         (RESPONSE.encode("utf-8"), "REF"))
        self.assertEqual((issued.status, issued.responses, supplier.answers),
                         ("UQ", [got], {"1": got}))

    def test_one_that_is_not_a_response_or_fails_its_rules_is_turned_away(self):
        supplier = Supplier(now=lambda: NOON)
        supplier.send(INVOICE)
        for document, code in (
                ("hello", "NOT-XML"), (INVOICE, "NOT-A-RESPONSE"),
                (RESPONSE.replace('<cbc:StatusReasonCode listID="OPStatusReason">REF', '<cbc:'
                                  'StatusReasonCode listID="OPStatusReason">NO'), "INVALID")):
            with self.assertRaises(TurnedAway) as raised:
                supplier.hear(document)
            self.assertEqual(raised.exception.code, code)
            self.assertEqual(raised.exception.report is not None, code == "INVALID")
        self.assertEqual([code for _when, code, _why in supplier.turned_away],
                         ["NOT-XML", "NOT-A-RESPONSE", "INVALID"])
        self.assertEqual(supplier.answers, {})

    def test_one_about_a_document_never_sent_is_turned_away(self):
        supplier = Supplier()
        for sent, wanted in ((None, "none was sent with that number"),
                             (CREDIT_NOTE.replace("GLX-4711-C", "GLX-4711"),
                              "is of type 381 (OP-BR111-R014)")):
            if sent:
                supplier.send(sent)
            with self.assertRaises(TurnedAway) as raised:
                supplier.hear(RESPONSE)
            self.assertEqual(raised.exception.code, "NO-SUCH-INVOICE")
            self.assertIn(wanted, raised.exception.reason)

    def test_of_two_sent_with_one_number_it_is_about_the_later(self):
        supplier = Supplier()
        first, second = supplier.send(INVOICE), supplier.send(INVOICE)
        supplier.hear(RESPONSE)
        self.assertEqual((first.status, second.status), ("", "UQ"))


class TheTwoTogether(unittest.TestCase):
    def test_an_invoice_goes_over_and_its_responses_come_back(self):
        supplier, buyer = pair(answers="always")
        issued = supplier.send(INVOICE)
        self.assertEqual((issued.delivery, issued.status), ({"to": "buyer", "held": "1"}, "AB"))
        buyer.answer("1", "UQ", reasons=REF, actions=["PIN"])
        buyer.answer("1", "AP")
        buyer.answer("1", "PD", reasons=PARTLY)
        self.assertEqual((issued.status, issued.responses[-1].partial), ("PD", True))
        buyer.answer("1", "PD")
        self.assertEqual([(got.code, got.ignored) for got in issued.responses],
                         [("AB", ""), ("UQ", ""), ("AP", ""), ("PD", ""), ("PD", "")])
        self.assertEqual(issued.responses[0].xml, buyer.responses["1"].xml)

    def test_a_response_out_of_order_is_kept_and_ignored(self):
        for first, then, rule in (("RE", "AP", "OP-BR111-R004"), ("PD", "PD", "OP-BR111-R004"),
                                  ("AP", "UQ", "OP-BR111-R005"), ("CA", "IP", "OP-BR111-R012")):
            supplier, buyer = pair()
            issued = supplier.send(INVOICE)
            for code, force in ((first, False), (then, True)):
                said = buyer.answer("1", code, force=force,
                                    reasons=REF if code in ("UQ", "CA", "RE") else ())
            self.assertEqual((said.delivery["ignored"], issued.status), (rule, first))
            self.assertEqual([got.ignored for got in issued.responses], ["", rule])

    def test_what_was_ignored_does_not_count_against_what_follows(self):
        supplier, buyer = pair()
        issued = supplier.send(INVOICE)
        buyer.answer("1", "AP")
        buyer.answer("1", "RE", reasons=REF, force=True)
        # To the buyer a rejection is final, so its payment is forced too. To
        # the supplier, who ignored the rejection, paid follows accepted.
        buyer.answer("1", "PD", force=True)
        self.assertEqual([(got.code, got.ignored) for got in issued.responses],
                         [("AP", ""), ("RE", "OP-BR111-R005"), ("PD", "")])
        self.assertEqual(issued.status, "PD")

    def test_any_status_may_come_first(self):
        for code in ORDER:
            supplier, buyer = pair()
            issued = supplier.send(INVOICE)
            buyer.answer("1", code, reasons=REF if code in ("UQ", "CA", "RE") else ())
            self.assertEqual((issued.status, issued.responses[0].ignored), (code, ""))

    def test_a_credit_note_is_answered_as_a_credit_note(self):
        supplier, buyer = pair()
        issued = supplier.send(CREDIT_NOTE)
        buyer.answer("1", "AP")
        self.assertEqual(issued.status, "AP")


if __name__ == "__main__":
    unittest.main()
