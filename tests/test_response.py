"""The Peppol Invoice Response: reading, writing, and its rules."""
import os
import re
import unittest
import xml.etree.ElementTree as ET

from mockeinvoice import (Refused, Response, read_response, response, validate_response,
                          write_response)
from mockeinvoice.model import Value
from mockeinvoice.rules import REGISTRY, check_response, published, run
from mockeinvoice.rules import peppol_response as rules
from mockeinvoice.rules import untdid
from mockeinvoice.ubl import tree

from . import sample, upstream
from .test_rules import changed

SAMPLE = sample("peppol-response.xml").decode("utf-8")
ALL = sorted(published.PEPPOL_RESPONSE)
FETCHED = os.path.join(upstream.FETCHED, "peppol-response")
HAVE = os.path.isdir(FETCHED)
WITHOUT = "Peppol's files are not in this repository: python tools/fetch_peppol.py"
HEAD = ('<ApplicationResponse xmlns="urn:oasis:names:specification:ubl:schema:xsd:'
        'ApplicationResponse-2" xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:'
        'CommonAggregateComponents-2" xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:'
        'CommonBasicComponents-2"%s>')
REASON = '<cbc:StatusReasonCode listID="OPStatusReason">REF</cbc:StatusReasonCode>'
ACTION = '<cbc:StatusReasonCode listID="OPStatusAction">PIN</cbc:StatusReasonCode>'
SELLERS = '<cbc:ID schemeID="0088">4012345000009</cbc:ID>'


def fragment(inside: str, attributes: str = "") -> str:
    return HEAD % attributes + inside + "</ApplicationResponse>"


def found(text: str) -> list:
    """The rules a response fails as sent, with where. Not through the
    reader, so that a fragment can be asked."""
    return [(f.code, f.path) for f in run(None, "peppol-response", tree(text))]


def failing(text: str) -> list:
    return sorted({code for code, _path in found(text)})


def says(text: str) -> list:
    """What a fragment fails, leaving aside that it lacks what a whole
    response must have."""
    return [code for code in failing(text)
            if not (code.startswith("PEPPOL-T111-B") and code[-2:] in ("01", "02", "03", "04",
                                                                      "05", "06", "07")
                    and code not in ("PEPPOL-T111-B03301", "PEPPOL-T111-B03303"))]


def answering(code: str, statuses: str = "") -> str:
    return fragment("<cac:DocumentResponse><cac:Response><cbc:ResponseCode>%s</cbc:ResponseCode>%s"
                    "</cac:Response></cac:DocumentResponse>" % (code, statuses))


def status(inside: str) -> str:
    return "<cac:Status>%s</cac:Status>" % inside


class Reading(unittest.TestCase):
    def setUp(self):
        self.response, self.findings = read_response(SAMPLE)

    def test_what_it_says_of_which_invoice(self):
        r = self.response
        self.assertEqual(self.findings, [])
        self.assertEqual((r.specification, r.profile), (response.SPECIFICATION, response.PROFILE))
        self.assertEqual((r.id, r.issue_date, r.issue_time), ("ACME-IMR-0001", "2026-10-05", "09:30:00"))
        self.assertEqual((r.code, r.effective_date), ("UQ", "2026-10-05"))
        self.assertEqual(response.CODES[r.code], "under query")
        self.assertEqual((r.document.id, r.document.issue_date, r.document.type_code),
                         ("GLX-4711", "2026-10-02", "380"))

    def test_the_buyer_sends_it_and_the_seller_receives_it(self):
        r = self.response
        self.assertEqual((r.sender.name, r.sender.endpoint.text, r.sender.endpoint.attributes),
                         ("ACME Corporation", "4098765000003", {"schemeID": "0088"}))
        self.assertEqual((r.sender.contact_name, r.sender.telephone, r.sender.email),
                         ("Accounts payable", "+49 30 000000", "ap@acme.example"))
        self.assertEqual((r.receiver.name, r.receiver.identifier.text),
                         ("Globex GmbH", "4012345000009"))
        self.assertEqual((r.issuer.name, r.issuer.identifier.text), ("Globex GmbH", "4012345000009"))
        self.assertEqual((r.recipient.name, r.recipient.identifier), ("ACME Corporation", None))

    def test_its_reasons_each_with_its_list_and_what_it_is_about(self):
        first, second = self.response.statuses
        self.assertEqual((first.reason_code, first.list_id, first.conditions),
                         ("REF", "OPStatusReason", [("BT-132", "20")]))
        self.assertEqual(first.reason, "No purchase order line is named on line 2.")
        self.assertEqual((second.reason_code, second.list_id, second.reason, second.conditions),
                         ("PIN", "OPStatusAction", "", []))
        self.assertEqual((response.REASONS["REF"], response.ACTIONS["PIN"]),
                         ("references incorrect", "provide information"))

    def test_what_has_no_place_in_a_response_is_said_and_not_held(self):
        text = changed(SAMPLE, "<cbc:IssueTime>", "<cbc:UUID>1</cbc:UUID><cbc:IssueTime>",
                       '<cbc:ResponseCode>', '<cbc:ResponseCode name="x">',
                       "<cbc:Telephone>", "<cbc:Telefax>1</cbc:Telefax><cbc:Telephone>")
        held, findings = read_response(text)
        self.assertEqual([(f.level, f.code, f.path) for f in findings], [
            ("warning", "UNHELD", "/ApplicationResponse/cbc:UUID"),
            ("warning", "UNHELD", "/ApplicationResponse/cac:SenderParty/cac:Contact/cbc:Telefax"),
            ("warning", "UNHELD", "/ApplicationResponse/cac:DocumentResponse/cac:Response/"
                                  "cbc:ResponseCode/@name")])
        self.assertEqual(held, self.response)

    def test_an_element_twice_where_a_response_has_one_is_said_and_the_first_is_held(self):
        text = changed(SAMPLE, "<cbc:Note>", "<cbc:Note>first</cbc:Note><cbc:Note>")
        held, findings = read_response(text)
        self.assertEqual([(f.level, f.code, f.path) for f in findings],
                         [("error", "REPEATED", "/ApplicationResponse/cbc:Note[2]")])
        self.assertEqual(held.note, "first")
        # Reasons and what they are about repeat, and that is nothing to say.
        self.assertEqual(len(self.response.statuses), 2)


class Refusals(unittest.TestCase):
    def refused(self, data) -> str:
        with self.assertRaises(Refused) as caught:
            read_response(data)
        return caught.exception.code

    def test_what_is_not_a_response_is_refused_by_name(self):
        self.assertEqual(self.refused("not xml"), "NOT-XML")
        self.assertEqual(self.refused('<!DOCTYPE a [<!ENTITY b "c">]>' + SAMPLE.split("?>", 1)[1]),
                         "DTD")
        self.assertEqual(self.refused(sample("peppol-invoice.xml")), "NOT-A-RESPONSE")
        with self.assertRaises(Refused) as caught:
            read_response(sample("peppol-invoice.xml"))
        self.assertIn("is a Invoice", caught.exception.reason.replace("an Invoice", "a Invoice"))

    def test_another_kind_of_application_response_is_refused(self):
        other = changed(SAMPLE, "urn:fdc:peppol.eu:poacc:trns:invoice_response:3",
                        "urn:fdc:peppol.eu:poacc:trns:mlr:3")
        self.assertEqual(self.refused(other), "NOT-AN-INVOICE-RESPONSE")
        self.assertEqual(self.refused(fragment("<cbc:ID>1</cbc:ID>")), "NOT-AN-INVOICE-RESPONSE")
        # A later version of the same is taken, as Peppol's own rule takes it.
        later = changed(SAMPLE, "invoice_response:3<", "invoice_response:3.1<")
        self.assertEqual(read_response(later)[0].specification,
                         "urn:fdc:peppol.eu:poacc:trns:invoice_response:3.1")

    def test_an_invoice_reader_refuses_a_response(self):
        from mockeinvoice import read
        with self.assertRaises(Refused) as caught:
            read(SAMPLE)
        self.assertEqual(caught.exception.code, "NOT-AN-INVOICE")


class Writing(unittest.TestCase):
    def test_the_sample_is_written_back_byte_for_byte(self):
        held, _findings = read_response(SAMPLE)
        self.assertEqual(write_response(held), SAMPLE.encode("utf-8"))

    def test_one_made_by_hand(self):
        made = Response(id="R-1", issue_date="2026-10-07", code="AP")
        made.sender = response.Party(Value("4098765000003", {"schemeID": "0088"}), None, "ACME")
        made.receiver = response.Party(Value("4012345000009", {"schemeID": "0088"}), None, "Globex")
        made.document = response.Answered("GLX-4711", "", "380")
        written = write_response(made)
        self.assertEqual(read_response(written), (made, []))
        _held, report = validate_response(written)
        self.assertEqual(report.findings, [])
        # Nothing empty is written: an empty element is a fault in a response.
        self.assertNotIn(b"IssueTime", written)
        self.assertNotIn(b"Contact", written)
        self.assertNotIn(b"IssuerParty", written)
        self.assertNotIn(b"/>", written)

    def test_a_receiver_has_no_contact_to_write(self):
        held, _findings = read_response(SAMPLE)
        held.receiver.contact_name = "Nobody"
        written = write_response(held)
        self.assertEqual(written.count(b"<cac:Contact>"), 1)
        self.assertNotIn(b"Nobody", written)

    def test_text_is_escaped(self):
        held, _findings = read_response(SAMPLE)
        held.note = 'a < b & "c"'
        self.assertEqual(read_response(write_response(held))[0].note, 'a < b & "c"')


class WhatIsBuilt(unittest.TestCase):
    def test_all_82_published_rules(self):
        self.assertEqual(len(ALL), 82)
        self.assertEqual(sorted(REGISTRY["peppol-response"]), ALL)
        kinds = {kind: sum(1 for i in ALL if i.startswith(kind))
                 for kind in ("PEPPOL-T111-B", "PEPPOL-T111-R", "PEPPOL-COMMON-")}
        self.assertEqual(kinds, {"PEPPOL-T111-B": 54, "PEPPOL-T111-R": 8, "PEPPOL-COMMON-": 20})
        flags = [published.PEPPOL_RESPONSE[i] for i in ALL]
        self.assertEqual((flags.count("fatal"), flags.count("warning")), (71, 11))

    def test_the_sample_fails_none_and_is_valid(self):
        _held, report = validate_response(SAMPLE)
        self.assertEqual((report.findings, report.verdict), ([], "valid"))
        self.assertEqual(report.not_built, {"peppol-response": {}})
        self.assertEqual(len(report.ran), 82)
        self.assertEqual(report.specification, "peppol-response")

    def test_a_finding_is_where_in_the_response_and_links_to_peppols_rules(self):
        _held, report = validate_response(changed(SAMPLE, REASON, "").replace(
            "<cbc:StatusReason>No purchase order line is named on line 2.</cbc:StatusReason>", "")
            .replace(ACTION, ""))
        finding = next(f for f in report.findings if f.code == "PEPPOL-T111-R001")
        self.assertEqual((finding.level, finding.path),
                         ("fatal", "/ApplicationResponse/cac:DocumentResponse/cac:Response"))
        self.assertIn("ad6828c94f8090bdfd620df4e48b213977afa2cb", finding.link)
        self.assertEqual(report.verdict, "invalid")


class WhatAResponseSays(unittest.TestCase):
    def test_a_query_a_condition_and_a_rejection_owe_a_reason_code(self):
        for code in ("UQ", "CA", "RE", " RE ", "CA UQ"):
            self.assertIn("PEPPOL-T111-R001", says(answering(code)), code)
            self.assertIn("PEPPOL-T111-R001", says(answering(code, status(
                "<cbc:StatusReason>why</cbc:StatusReason>"))), code)
            self.assertNotIn("PEPPOL-T111-R001", says(answering(code, status(REASON))), code)
        for code in ("AB", "IP", "AP", "PD", "re", ""):
            self.assertNotIn("PEPPOL-T111-R001", says(answering(code)), code)

    def test_other_wants_a_text_and_that_is_a_warning(self):
        other = '<cbc:StatusReasonCode listID="OPStatusReason">OTH</cbc:StatusReasonCode>'
        self.assertIn("PEPPOL-T111-R002", says(answering("RE", status(other))))
        self.assertNotIn("PEPPOL-T111-R002", says(answering("RE", status(
            other + "<cbc:StatusReason>because</cbc:StatusReason>"))))
        self.assertNotIn("PEPPOL-T111-R002", says(answering("RE", status(REASON))))
        # Picked by the code as written: with space around it, it is not asked.
        self.assertNotIn("PEPPOL-T111-R002", says(answering("RE", status(other.replace(
            ">OTH<", "> OTH <")))))
        self.assertEqual(published.PEPPOL_RESPONSE["PEPPOL-T111-R002"], "warning")

    def test_partially_paid_wants_a_text_and_its_other_rule_cannot_fail(self):
        partly = '<cbc:StatusReasonCode listID="OPStatusReason">PPD</cbc:StatusReasonCode>'
        self.assertEqual(says(answering("PD", status(partly))), ["PEPPOL-T111-R004"])
        self.assertEqual(says(answering("PD", status(
            partly + "<cbc:StatusReason>half</cbc:StatusReason>"))), [])
        # Meant to hold PPD to PD; as published it holds it to nothing.
        self.assertNotIn("PEPPOL-T111-R005", says(answering("AP", status(
            partly + "<cbc:StatusReason>half</cbc:StatusReason>"))))
        self.assertIn("cannot fail", REGISTRY["peppol-response"]["PEPPOL-T111-R005"].about)

    def test_a_status_that_is_two_things_is_asked_the_first_rule_that_fits(self):
        both = ('<cbc:StatusReasonCode listID="OPStatusReason">OTH</cbc:StatusReasonCode>'
                '<cbc:StatusReasonCode listID="OPStatusReason">PPD</cbc:StatusReasonCode>')
        self.assertEqual([c for c in says(answering("PD", status(both)))
                          if c in ("PEPPOL-T111-R002", "PEPPOL-T111-R004")], ["PEPPOL-T111-R002"])

    def test_a_status_under_both_lists_is_asked_the_actions_rule_only(self):
        both = answering("RE", status(
            '<cbc:StatusReasonCode listID="OPStatusAction">XXX</cbc:StatusReasonCode>'
            '<cbc:StatusReasonCode listID="OPStatusReason">YYY</cbc:StatusReasonCode>'))
        got = [c for c in says(both) if c in ("PEPPOL-T111-R006", "PEPPOL-T111-R007")]
        self.assertEqual(got, ["PEPPOL-T111-R006"])

    def test_a_reason_code_is_one_of_the_list_it_names(self):
        def coded(list_id, code):
            return says(answering("RE", status(
                '<cbc:StatusReasonCode listID="%s">%s</cbc:StatusReasonCode>' % (list_id, code))))
        self.assertEqual(coded("OPStatusReason", "REF"), [])
        self.assertEqual(coded("OPStatusAction", "NIN"), [])
        self.assertEqual(coded("OPStatusAction", " NIN "), [])
        # A reason under the actions' name, and the other way round.
        self.assertEqual(coded("OPStatusAction", "REF"), ["PEPPOL-T111-R006"])
        self.assertEqual(coded("OPStatusReason", "NIN"), ["PEPPOL-T111-R007"])
        self.assertEqual(coded("OPStatusReason", "XXX"), ["PEPPOL-T111-B03301", "PEPPOL-T111-R007"])
        # OTH is in both.
        self.assertEqual(coded("OPStatusAction", "OTH"), ["PEPPOL-T111-R002"])
        self.assertEqual(coded("OPStatusReason", "OTH"), ["PEPPOL-T111-R002"])
        self.assertEqual(coded("Mine", "REF"), ["PEPPOL-T111-B03303"])

    def test_the_identifiers_of_the_specification_and_the_profile(self):
        self.assertEqual(says(fragment("<cbc:CustomizationID>urn:other</cbc:CustomizationID>")),
                         ["PEPPOL-T111-R003"])
        self.assertEqual(says(fragment("<cbc:CustomizationID> %s.1 </cbc:CustomizationID>"
                                          % response.SPECIFICATION)), [])
        for profile, right in ((response.PROFILE, True), (" %s " % response.PROFILE, True),
                               (response.BILLING_WITH_RESPONSE, True), ("urn:other", False),
                               (response.PROFILE + ".1", False)):
            got = says(fragment("<cbc:ProfileID>%s</cbc:ProfileID>" % profile))
            self.assertEqual(got, [] if right else ["PEPPOL-T111-R008"], profile)


class TheStructure(unittest.TestCase):
    """The 53 built rules about what a response holds."""

    def test_each_thing_that_must_be_there(self):
        seen = set()
        for number, path, what in rules.BASIC:
            if what == "*" or isinstance(what, tuple):
                continue
            identifier = "PEPPOL-T111-B" + number
            self.assertEqual(failing(SAMPLE), [])
            names = path.split("/") if path else []
            # An empty holder, so that everything it must have is missing.
            inside = "<x/>"
            for name in reversed(names):
                inside = "<%s>%s</%s>" % (name, inside, name)
            bare = fragment(inside.replace("<x/>", "<cbc:Other>1</cbc:Other>"))
            self.assertIn(identifier, failing(bare), identifier)
            seen.add(identifier)
        self.assertEqual(len(seen), 30)

    def test_what_must_be_there_is_not_missed_when_it_is(self):
        self.assertEqual([c for c in failing(SAMPLE) if "-B0" in c], [])
        for old, rule in (("<cbc:ID>ACME-IMR-0001</cbc:ID>", "00103"),
                          ("<cbc:RegistrationName>ACME Corporation</cbc:RegistrationName>", "01401"),
                          ("<cbc:AttributeID>BT-132</cbc:AttributeID>", "03601"),
                          ("<cbc:DocumentTypeCode>380</cbc:DocumentTypeCode>", "03902"),
                          ("<cbc:Name>Globex GmbH</cbc:Name>", "04701"),
                          ("<cbc:Name>ACME Corporation</cbc:Name>", "05301"),
                          (' listID="OPStatusAction"', "03302")):
            got = [c for c in failing(changed(SAMPLE, old, "")) if c.startswith("PEPPOL-T111-B")]
            self.assertIn("PEPPOL-T111-B" + rule, got, old)

    def test_nothing_that_has_no_place(self):
        seen = set()
        for number, path, what in rules.BASIC:
            if what != "*":
                continue
            identifier = "PEPPOL-T111-B" + number
            inside = "<cbc:Other>1</cbc:Other>"
            for name in reversed(path.split("/") if path else []):
                inside = "<%s>%s</%s>" % (name, inside, name)
            got = [(c, p) for c, p in found(fragment(inside)) if c == identifier]
            self.assertEqual(len(got), 1, identifier)
            self.assertTrue(got[0][1].endswith("/cbc:Other"), got)
            seen.add(identifier)
        self.assertEqual(len(seen), 13)
        # It is fatal, and in the sample it is the rule's finding and not the reader's.
        _held, report = validate_response(changed(SAMPLE, "<cbc:IssueTime>",
                                                  "<cbc:UUID>1</cbc:UUID><cbc:IssueTime>"))
        self.assertEqual([(f.level, f.code, f.path) for f in report.findings],
                         [("fatal", "PEPPOL-T111-B00109", "/ApplicationResponse/cbc:UUID")])

    def test_a_contact_is_the_senders_and_a_receiver_has_none(self):
        contact = "<cac:Contact><cbc:Name>n</cbc:Name></cac:Contact>"
        self.assertNotIn("PEPPOL-T111-B00803", failing(fragment(
            "<cac:SenderParty>%s</cac:SenderParty>" % contact)))
        self.assertIn("PEPPOL-T111-B02003", failing(fragment(
            "<cac:ReceiverParty>%s</cac:ReceiverParty>" % contact)))

    def test_how_often_is_not_asked(self):
        text = changed(SAMPLE, "<cbc:Note>", "<cbc:Note>first</cbc:Note><cbc:Note>")
        self.assertEqual(failing(text), [])

    def test_the_codes(self):
        def one(old, new):
            return [c for c in failing(changed(SAMPLE, old, new))]
        self.assertEqual(one("<cbc:ResponseCode>UQ", "<cbc:ResponseCode>XX"), ["PEPPOL-T111-B03001"])
        self.assertEqual(one("<cbc:ResponseCode>UQ", "<cbc:ResponseCode> RE\n"), [])
        for code in response.CODES:
            self.assertNotIn("PEPPOL-T111-B03001", one("<cbc:ResponseCode>UQ",
                                                       "<cbc:ResponseCode>" + code), code)
        endpoint = '<cbc:EndpointID schemeID="%s">4098765000003'
        self.assertEqual(one(endpoint % "0088", endpoint % "0037"), ["PEPPOL-T111-B00902"])
        self.assertEqual(one(endpoint % "0088", "<cbc:EndpointID>4098765000003"),
                         ["PEPPOL-T111-B00901"])
        # Named as nothing, it is named, and nothing is not a scheme.
        self.assertEqual(one(endpoint % "0088", endpoint % ""), ["PEPPOL-T111-B00902"])
        receivers = '<cbc:EndpointID schemeID="%s">4012345000009'
        self.assertEqual(one(receivers % "0088", receivers % "0037"), ["PEPPOL-T111-B02102"])
        self.assertEqual(one(receivers % "0088", "<cbc:EndpointID>4012345000009"),
                         ["PEPPOL-T111-B02101"])
        # A party identifier's scheme is asked only where it has one.
        was = '<cbc:ID schemeID="0088">4098765000003</cbc:ID>'
        self.assertEqual(one(was, '<cbc:ID schemeID="XX">1</cbc:ID>'), ["PEPPOL-T111-B01201"])
        self.assertEqual(one(was, "<cbc:ID>1</cbc:ID>"), [])
        for place, rule in ((0, "02401"), (1, "04501")):
            parts = SAMPLE.split(SELLERS)
            self.assertEqual(len(parts), 3)
            parts[place] += '<cbc:ID schemeID="XX">1</cbc:ID>'
            parts[1 - place] += SELLERS
            self.assertEqual(failing("".join(parts)), ["PEPPOL-T111-B" + rule], rule)
        recipient = changed(SAMPLE, "<cac:RecipientParty>", "<cac:RecipientParty>"
                            '<cac:PartyIdentification><cbc:ID schemeID="XX">1</cbc:ID>'
                            "</cac:PartyIdentification>")
        self.assertEqual(failing(recipient), ["PEPPOL-T111-B05101"])
        self.assertEqual(failing(recipient.replace('<cbc:ID schemeID="XX">1</cbc:ID>', "<cbc:Other>1"
                                                   "</cbc:Other>")), ["PEPPOL-T111-B05001"])


class TheDocumentAnswered(unittest.TestCase):
    """Its type code, held to UNTDID 1001 as Peppol has it."""

    def typed(self, code: str) -> list:
        return failing(changed(SAMPLE, "<cbc:DocumentTypeCode>380", "<cbc:DocumentTypeCode>" + code))

    def test_the_list_is_727_numbers_in_38_runs(self):
        self.assertEqual(len(untdid.DOCUMENT_NAME_CODES), 727)
        self.assertEqual(len(untdid.RUNS_1001_D17A), 38)
        runs = untdid.RUNS_1001_D17A
        self.assertTrue(all(first <= last for first, last in runs))
        self.assertTrue(all(runs[i][1] + 1 < runs[i + 1][0] for i in range(len(runs) - 1)))
        self.assertEqual((runs[0], runs[-1]), ((1, 470), (998, 998)))

    def test_a_code_of_the_list_passes_and_another_number_does_not(self):
        for code in ("380", "381", "1", "470", " 380\n", "998", "751", "326", "384", "389"):
            self.assertEqual(self.typed(code), [], code)
        for code in ("0", "471", "480", "492", "999", "1000", "0380", "380.0", "invoice", "38 0"):
            self.assertEqual(self.typed(code), ["PEPPOL-T111-B04201"], code)

    def test_four_invoice_types_peppols_billing_allows_are_not_in_it(self):
        from mockeinvoice.rules.peppol import CREDIT_NOTE_TYPES, INVOICE_TYPES
        missing = sorted(code for code in INVOICE_TYPES | CREDIT_NOTE_TYPES
                         if code not in untdid.DOCUMENT_NAME_CODES)
        self.assertEqual(missing, ["817", "875", "876", "877"])
        for code in missing:
            self.assertEqual(self.typed(code), ["PEPPOL-T111-B04201"], code)

    def test_a_year_that_is_in_peppols_list_passes(self):
        self.assertNotIn("1999", untdid.DOCUMENT_NAME_CODES)
        self.assertEqual(self.typed("1999"), [])
        self.assertEqual(self.typed("2017"), ["PEPPOL-T111-B04201"])

    def test_where_it_is_and_that_it_is_fatal(self):
        _held, report = validate_response(changed(SAMPLE, "<cbc:DocumentTypeCode>380",
                                                  "<cbc:DocumentTypeCode>875"))
        self.assertEqual([(f.level, f.code, f.path) for f in report.findings], [
            ("fatal", "PEPPOL-T111-B04201", "/ApplicationResponse/cac:DocumentResponse/"
                                            "cac:DocumentReference/cbc:DocumentTypeCode")])
        self.assertEqual(report.verdict, "invalid")


class WhatPeppolAsksOfEveryDocument(unittest.TestCase):
    def test_no_empty_element(self):
        self.assertEqual(found(changed(SAMPLE, "<cbc:IssueTime>09:30:00</cbc:IssueTime>",
                                       "<cbc:IssueTime/>")),
                         [("PEPPOL-COMMON-R001", "/ApplicationResponse/cbc:IssueTime")])

    def test_an_element_with_only_an_attribute_is_empty(self):
        self.assertIn("PEPPOL-COMMON-R001", failing(changed(
            SAMPLE, "<cbc:IssueTime>09:30:00</cbc:IssueTime>", '<cbc:IssueTime x="1"> </cbc:IssueTime>')))

    def test_where_its_schema_is_is_asked_twice(self):
        located = SAMPLE.replace("<ApplicationResponse ", '<ApplicationResponse xmlns:xsi="http://'
                                 'www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="a b" ', 1)
        _held, report = validate_response(located)
        self.assertEqual(sorted((f.level, f.code) for f in report.findings
                                if f.code.startswith("PEPPOL-")),
                         [("fatal", "PEPPOL-T111-B00108"), ("warning", "PEPPOL-COMMON-R003")])

    def test_dates(self):
        for old in ("<cbc:IssueDate>2026-10-05", "<cbc:IssueDate>2026-10-02"):
            for bad in ("5.10.2026", "2026-10-05Z", "2026-02-30"):
                self.assertEqual(failing(changed(SAMPLE, old, "<cbc:IssueDate>" + bad)),
                                 ["PEPPOL-COMMON-R030"], bad)
        # The day a response takes effect is not one of the dates asked.
        self.assertEqual(failing(changed(SAMPLE, "<cbc:EffectiveDate>2026-10-05",
                                         "<cbc:EffectiveDate>soon")), [])

    def test_identifiers_by_their_scheme_as_in_an_invoice(self):
        self.assertEqual(found(changed(SAMPLE, ">4098765000003</cbc:EndpointID>",
                                       ">4098765000004</cbc:EndpointID>")),
                         [("PEPPOL-COMMON-R040", "/ApplicationResponse/cac:SenderParty/cbc:EndpointID")])
        was = '<cbc:ID schemeID="0088">4098765000003</cbc:ID>'
        for scheme, value, rule in (("0192", "923609017", "R041"), ("0208", "0202239952", "R043"),
                                    ("0007", "5560125791", "R049"), ("0151", "51824753557", "R050"),
                                    ("0106", "1234567", "R054"), ("0184", "DK1", "R042")):
            self.assertEqual(failing(changed(SAMPLE, was, '<cbc:ID schemeID="%s">%s</cbc:ID>'
                                             % (scheme, value))), ["PEPPOL-COMMON-" + rule], scheme)
        for scheme, value, rule in (("0201", "UFY9M", "R044"), ("0210", "0123456789", "R045"),
                                    ("0211", "IT00743110158", "R047"), ("0096", "123", "R052"),
                                    ("0198", "12345678", "R053"), ("0190", "1", "R055"),
                                    ("9944", "NL1", "R056-1"), ("0217", "1", "R057")):
            # 9944 is an address scheme and no ISO 6523 code, so on a party
            # identifier it fails the rule about that as well.
            beside = ["PEPPOL-T111-B01201"] if scheme == "9944" else []
            self.assertEqual(failing(changed(SAMPLE, was, '<cbc:ID schemeID="%s">%s</cbc:ID>'
                                             % (scheme, value))),
                             ["PEPPOL-COMMON-" + rule] + beside, scheme)
        # 9907 has a rule and is not a scheme an electronic address may have.
        self.assertEqual(failing(changed(SAMPLE, 'schemeID="0088">4098765000003</cbc:EndpointID>',
                                         'schemeID="9907">RSSMRA85T10</cbc:EndpointID>')),
                         ["PEPPOL-COMMON-R046", "PEPPOL-T111-B00902"])
        # A tax registration has no place in a response, and is asked all the same.
        registered = changed(SAMPLE, "<cac:Contact>", "<cac:PartyTaxScheme><cbc:CompanyID>NL1"
                             "</cbc:CompanyID><cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme>"
                             "</cac:PartyTaxScheme><cac:Contact>")
        self.assertEqual(failing(registered), ["PEPPOL-COMMON-R056-2", "PEPPOL-T111-B00803"])
        common = [i for i in ALL if i.startswith("PEPPOL-COMMON-")]
        self.assertLessEqual({i for i in common if i not in ("PEPPOL-COMMON-R001",
                                                             "PEPPOL-COMMON-R003",
                                                             "PEPPOL-COMMON-R030")},
                             set(REGISTRY["peppol"]))
        for identifier in common:
            if identifier in REGISTRY["peppol"]:
                self.assertEqual(REGISTRY["peppol"][identifier].about,
                                 REGISTRY["peppol-response"][identifier].about)


@unittest.skipUnless(HAVE, WITHOUT)
class PeppolsOwnFiles(unittest.TestCase):
    def examples(self):
        folder = os.path.join(FETCHED, "rules", "examples")
        for directory, _folders, names in sorted(os.walk(folder)):
            for name in sorted(names):
                with open(os.path.join(directory, name), "rb") as handle:
                    yield name, handle.read()

    def test_its_fourteen_examples_are_taken_whole(self):
        codes = []
        for name, data in self.examples():
            held, findings = read_response(data)
            self.assertEqual(findings, [], name)
            self.assertEqual(read_response(write_response(held)), (held, []), name)
            # Element for element: nothing in the example is lost on the way.
            def leaves(xml):
                return sorted((e.tag, (e.text or "").strip(), tuple(sorted(e.attrib.items())))
                              for e in ET.fromstring(xml).iter() if not len(e))
            self.assertEqual(leaves(write_response(held)), leaves(data), name)
            _held, report = validate_response(data)
            self.assertEqual(report.findings, [], name)
            self.assertEqual((report.not_built, report.verdict),
                             ({"peppol-response": {}}, "valid"), name)
            codes.append(held.code)
        self.assertEqual(len(codes), 14)
        self.assertEqual(sorted(set(codes)), ["AP", "CA", "IP", "PD", "RE", "UQ"])

    def test_its_unit_tests(self):
        counts, disagreements, not_built = upstream.tally("response")
        self.assertEqual(disagreements, [])
        self.assertEqual(dict(counts), {"files": 3, "cases": 13, "expectations": 13, "agree": 13})
        self.assertEqual(not_built, {})

    def test_its_document_type_codes_are_the_united_nations_of_2017_and_a_year(self):
        root = ET.parse(os.path.join(FETCHED, "structure", "codelist", "UNCL1001.xml")).getroot()
        theirs = {e.text.strip() for e in root.iter() if e.tag.endswith("}Id")}
        self.assertEqual(len(theirs), 728)
        self.assertEqual(theirs - untdid.DOCUMENT_NAME_CODES, {"1999"})
        self.assertEqual(untdid.DOCUMENT_NAME_CODES - theirs, set())
        self.assertIn("D.17A", [e.text for e in root if e.tag.endswith("}Version")])

    def test_the_lists_here_are_its_lists(self):
        def listed(name):
            root = ET.parse(os.path.join(FETCHED, "structure", "codelist", name + ".xml")).getroot()
            return {e.text.strip() for e in root.iter() if e.tag.endswith("}Id")}
        self.assertEqual(listed("UNCL4343-T111"), set(response.CODES))
        self.assertEqual(listed("OPStatusReason"), set(response.REASONS))
        self.assertEqual(listed("OPStatusAction"), set(response.ACTIONS))
        self.assertEqual(listed("eas"), set(rules.ADDRESS_SCHEMES))
        self.assertEqual(listed("ICD"), set(rules.ICD))

    def test_the_structure_here_is_the_structure_it_describes(self):
        root = ET.parse(os.path.join(FETCHED, "structure", "syntax",
                                     "ubl-invoiceresponse.xml")).getroot()

        def described(element):
            out = {}
            for child in element:
                if child.tag.endswith("}Element"):
                    term = next(c.text for c in child if c.tag.endswith("}Term"))
                    inside = described(child)
                    out[term] = inside or None
            return out
        document = next(e for e in root if e.tag.endswith("}Document"))
        self.assertEqual(described(document), response.STRUCTURE)

    def test_the_rules_written_by_hand_there_are_the_rules_built_here(self):
        schematron = "{http://purl.oclc.org/dsdl/schematron}"
        theirs = set()
        for directory, _folders, names in os.walk(os.path.join(FETCHED, "rules", "sch")):
            for name in names:
                for element in ET.parse(os.path.join(directory, name)).getroot().iter(
                        schematron + "assert"):
                    theirs.add(element.get("id"))
        ours = {i for i in ALL if not re.match(r"PEPPOL-T111-B", i)}
        self.assertEqual(theirs, ours)
        self.assertLessEqual(ours, set(REGISTRY["peppol-response"]))


class TheEngine(unittest.TestCase):
    def test_a_response_is_held_to_its_own_layer_and_no_invoices(self):
        _held, report = validate_response(SAMPLE)
        self.assertFalse(any(i.startswith(("BR-", "UBL-", "DE-R-")) for i in report.ran))
        self.assertEqual(report.not_applicable, {"peppol-response": {}})
        sent = tree(SAMPLE)
        self.assertEqual(check_response(sent).findings, [])
