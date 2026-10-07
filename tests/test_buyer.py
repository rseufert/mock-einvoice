"""The buyer: what it takes in, what it turns away, and what it will say."""
import datetime
import unittest

from mockeinvoice import response, validate_response
from mockeinvoice.buyer import (ORDER, PROCESS, Buyer, NotSaid, Sent, TurnedAway,
                                out_of_order)

from . import sample
from .test_peppol_rules import french

INVOICE = sample("peppol-invoice.xml").decode("utf-8")
CREDIT_NOTE = sample("peppol-creditnote.xml").decode("utf-8")
XRECHNUNG = sample("xrechnung-invoice.xml").decode("utf-8")
WITH_RESPONSE = INVOICE.replace("urn:fdc:peppol.eu:2017:poacc:billing:01:1.0",
                                "urn:peppol:bis:billing_with_response")
NOON = datetime.datetime(2026, 10, 7, 12, 0, 30)
REF = [{"code": "REF", "text": "no purchase order"}]


def buyer(**how) -> Buyer:
    return Buyer(now=lambda: NOON, **how)


def holding(document: str = INVOICE, **how):
    made = buyer(**how)
    return made, made.receive(document)


class TakingIn(unittest.TestCase):
    def test_a_valid_document_is_held(self):
        made, held = holding()
        self.assertEqual((held.id, held.number, held.profile, held.received),
                         ("1", "GLX-4711", "01", "2026-10-07T12:00:30"))
        self.assertEqual(held.xml, INVOICE.encode("utf-8"))
        self.assertIs(made.invoices["1"], held)

    def test_documents_are_numbered_as_they_come(self):
        made, _first = holding()
        self.assertEqual(made.receive(CREDIT_NOTE).id, "2")
        self.assertEqual(made.receive(XRECHNUNG.encode("utf-8")).id, "3")

    def test_an_invalid_one_is_turned_away_with_its_report(self):
        broken = INVOICE.replace("<cbc:ID>GLX-4711</cbc:ID>", "", 1)
        made = buyer()
        with self.assertRaises(TurnedAway) as raised:
            made.receive(broken)
        away = raised.exception
        self.assertEqual(away.code, "INVALID")
        self.assertIn("BR-02", [f.code for f in away.report.failures])
        self.assertEqual(made.invoices, {})
        self.assertEqual([(when, code) for when, code, _why in made.turned_away],
                         [("2026-10-07T12:00:30", "INVALID")])

    def test_one_that_could_not_be_judged_is_turned_away_naming_the_rules(self):
        swedish = french(INVOICE).replace("<cbc:IdentificationCode>FR<",
                                          "<cbc:IdentificationCode>SE<")
        with self.assertRaises(TurnedAway) as raised:
            buyer().receive(swedish)
        away = raised.exception
        self.assertEqual((away.code, away.report.verdict), ("NOT-JUDGED", "not judged"))
        self.assertIn("SE-R-001", away.reason)
        self.assertIn("7 fatal rules", away.reason)

    def test_what_is_not_taken_is_turned_away_by_the_refusals_own_code(self):
        for document, code in (("hello", "NOT-XML"), (sample("peppol-response.xml"),
                                                      "NOT-AN-INVOICE"),
                               (INVOICE.replace("billing:3.0<", "billing:9.9<"),
                                "SPECIFICATION")):
            with self.assertRaises(TurnedAway) as raised:
                buyer().receive(document)
            self.assertEqual((raised.exception.code, raised.exception.report), (code, None))

    def test_a_duplicate_is_taken_like_the_first(self):
        # Not built: a real buyer's system would likely reject it.
        made, _first = holding()
        self.assertEqual(made.receive(INVOICE).id, "2")


class Acknowledging(unittest.TestCase):
    def codes(self, document, **how):
        _made, held = holding(document, **how)
        return [said.code for said in held.responses]

    def test_by_default_only_where_the_profile_requires_a_response(self):
        self.assertEqual(self.codes(INVOICE), [])
        self.assertEqual(self.codes(WITH_RESPONSE), ["AB"])

    def test_always(self):
        self.assertEqual(self.codes(INVOICE, answers="always"), ["AB"])

    def test_never_is_the_buyer_who_owes_one_and_sends_none(self):
        self.assertEqual(self.codes(WITH_RESPONSE, answers="never"), [])

    def test_xrechnung_is_never_acknowledged(self):
        self.assertEqual(self.codes(XRECHNUNG, answers="always"), [])

    def test_answers_is_one_of_three(self):
        with self.assertRaises(ValueError):
            Buyer(answers="sometimes")


class WhatAResponseSays(unittest.TestCase):
    def test_it_is_from_the_buyer_to_the_seller_about_the_document(self):
        made, held = holding()
        said = made.answer("1", "UQ", reasons=[{"code": "REF", "text": "no purchase order",
                                                "conditions": [("BT-13", "PO-7")]}],
                           actions=["PIN"], note="Please send the order number.")
        read, report = validate_response(said.xml)
        self.assertEqual((report.verdict, report.findings), ("valid", []))
        self.assertEqual((read.id, read.issue_date, read.issue_time, read.effective_date),
                         ("IR-000001", "2026-10-07", "12:00:30", "2026-10-07"))
        self.assertEqual((read.specification, read.profile),
                         (response.SPECIFICATION, response.PROFILE))
        self.assertEqual((read.sender.endpoint.text, read.sender.endpoint.attributes,
                          read.sender.name),
                         ("4098765000003", {"schemeID": "0088"}, "ACME Corporation"))
        self.assertEqual((read.receiver.endpoint.text, read.receiver.name),
                         ("4012345000009", "Globex GmbH"))
        self.assertEqual((read.document.id, read.document.issue_date, read.document.type_code),
                         ("GLX-4711", "2026-10-02", "380"))
        self.assertEqual(read.note, "Please send the order number.")
        self.assertEqual([(s.reason_code, s.list_id, s.reason, s.conditions)
                          for s in read.statuses],
                         [("REF", "OPStatusReason", "no purchase order", [("BT-13", "PO-7")]),
                          ("PIN", "OPStatusAction", "", [])])
        self.assertEqual((held.status, held.responses, made.responses), ("UQ", [said],
                                                                         {"1": said}))

    def test_a_credit_notes_type_code_is_its_own(self):
        # OP-BR111-R014
        made, _held = holding(CREDIT_NOTE)
        read, _report = validate_response(made.answer("1", "AP").xml)
        self.assertEqual((read.document.type_code, read.document.id), ("381", "GLX-4711-C"))

    def test_under_billing_with_response_the_profile_is_that(self):
        _made, held = holding(WITH_RESPONSE)
        read, report = validate_response(held.responses[0].xml)
        self.assertEqual((read.profile, report.verdict),
                         (response.BILLING_WITH_RESPONSE, "valid"))

    def test_every_status_can_be_said_and_is_valid(self):
        for code in ORDER:
            made, _held = holding()
            said = made.answer("1", code, reasons=REF if code in ("UQ", "CA", "RE") else ())
            self.assertEqual(validate_response(said.xml)[1].verdict, "valid", code)

    def test_one_that_would_fail_its_own_rules_is_not_said_forced_or_not(self):
        for force in (False, True):
            made, held = holding()
            with self.assertRaises(NotSaid) as raised:
                made.answer("1", "RE", force=force)
            self.assertEqual(raised.exception.code, "INVALID")
            self.assertEqual([f.code for f in raised.exception.findings], ["PEPPOL-T111-R001"])
            self.assertEqual((held.responses, made.responses), ([], {}))

    def test_a_code_that_is_not_one_of_the_seven_is_named_by_the_rule(self):
        made, _held = holding()
        with self.assertRaises(NotSaid) as raised:
            made.answer("1", "OK")
        self.assertEqual([f.code for f in raised.exception.findings], ["PEPPOL-T111-B03001"])

    def test_a_warning_does_not_stop_it_and_is_kept(self):
        made, _held = holding()
        said = made.answer("1", "UQ", reasons=["OTH"])
        self.assertEqual([(f.level, f.code) for f in said.warnings],
                         [("warning", "PEPPOL-T111-R002")])

    def test_xrechnung_has_no_response(self):
        made, _held = holding(XRECHNUNG)
        with self.assertRaises(NotSaid) as raised:
            made.answer("1", "AB")
        self.assertEqual(raised.exception.code, "NO-RESPONSE")
        self.assertIn("XRechnung 3.0", raised.exception.reason)

    def test_a_document_not_held_and_a_clarification_misspelt(self):
        made, _held = holding()
        for arguments, code in ((("7", "AB"), "NO-SUCH-INVOICE"),
                                (("1", "UQ", [{"cod": "REF"}]), "REQUEST")):
            with self.assertRaises(NotSaid) as raised:
                made.answer(*arguments)
            self.assertEqual(raised.exception.code, code)

    def test_it_is_delivered_where_there_is_somewhere_to_deliver_it(self):
        posted = []

        def deliver(xml):
            posted.append(xml)
            return {"to": "seller", "status": 200}
        made, _held = holding(deliver=deliver)
        said = made.answer("1", "AB")
        self.assertEqual((posted, said.delivery), ([said.xml], {"to": "seller", "status": 200}))
        self.assertIsNone(holding()[0].answer("1", "AB").delivery)


PARTLY = [{"code": "PPD", "text": "half now"}]


class TheOrder(unittest.TestCase):
    """The guide's process rules, which are in no Schematron file."""

    def said(self, *steps, **how):
        """Give responses in turn; the rule that stopped the last, or None."""
        made, _held = holding()
        for step in steps[:-1]:
            self.give(made, step)
        try:
            self.give(made, steps[-1], **how)
        except NotSaid as no:
            return no.code
        return None

    @staticmethod
    def give(made, step, **how):
        code, _, part = step.partition("/")
        reasons = PARTLY if part else REF if code in ("UQ", "CA", "RE") else ()
        return made.answer("1", code, reasons=reasons, **how)

    def test_any_status_may_be_first(self):
        for code in ORDER:
            self.assertIsNone(self.said(code), code)

    def test_forwards_with_any_left_out(self):
        self.assertIsNone(self.said("AB", "IP", "UQ", "CA", "AP", "PD"))
        self.assertIsNone(self.said("AB", "PD"))
        self.assertIsNone(self.said("IP", "RE"))

    def test_never_backwards(self):
        for steps in (("IP", "AB"), ("UQ", "IP"), ("CA", "UQ"), ("AB", "UQ", "AB")):
            self.assertEqual(self.said(*steps), "OP-BR111-R012", steps)

    def test_only_under_query_and_a_part_payment_come_twice(self):
        self.assertIsNone(self.said("UQ", "UQ", "UQ"))
        self.assertIsNone(self.said("PD/part", "PD/part", "PD"))
        for code in ("AB", "IP", "CA"):
            self.assertEqual(self.said(code, code), "OP-BR111-R012", code)

    def test_nothing_follows_a_rejection_or_a_payment_in_full(self):
        for final in ("RE", "PD"):
            for code in ORDER:
                self.assertEqual(self.said(final, code), "OP-BR111-R004", (final, code))
        self.assertEqual(self.said("PD/part", "PD", "PD/part"), "OP-BR111-R004")

    def test_only_paid_follows_accepted(self):
        for code in ORDER[:-1]:
            self.assertEqual(self.said("AP", code), "OP-BR111-R005", code)
        self.assertIsNone(self.said("AP", "PD/part"))
        self.assertIsNone(self.said("AP", "PD"))

    def test_the_refusal_names_the_rule_and_what_went_before(self):
        made, _held = holding()
        made.answer("1", "AP")
        with self.assertRaises(NotSaid) as raised:
            made.answer("1", "UQ", reasons=REF)
        self.assertIn("UQ cannot follow AP", raised.exception.reason)
        self.assertIn("OP-BR111-R005", raised.exception.reason)

    def test_force_gives_it_anyway_and_says_it_was_forced(self):
        made, held = holding()
        made.answer("1", "AP")
        said = made.answer("1", "UQ", reasons=REF, force=True)
        self.assertEqual((said.forced, held.status), (True, "UQ"))
        self.assertEqual(validate_response(said.xml)[1].verdict, "valid")
        self.assertFalse(made.answer("1", "PD", force=True).forced)

    def test_every_rule_named_is_one_that_can_be_broken(self):
        broken = {out_of_order([_sent(a)], b, False) for a in ORDER for b in ORDER}
        self.assertEqual(broken - {None}, set(PROCESS))


def _sent(code):
    return Sent("1", "1", code, False, False, b"")


if __name__ == "__main__":
    unittest.main()
