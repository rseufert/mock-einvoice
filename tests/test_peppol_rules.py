"""Peppol BIS Billing 3.0's own rules: PEPPOL-EN16931 and PEPPOL-COMMON."""
import os
import re
import unittest
import xml.etree.ElementTree as ET

from mockeinvoice import validate
from mockeinvoice.rules import REGISTRY, SCOPES, could_apply, peppol, published, run
from mockeinvoice.rules.tree import top
from mockeinvoice.ubl import parse_tree, tree

from . import unbuilt, upstream
from .test_business_rules import cut
from .test_rules import CREDIT_NOTE, INVOICE, changed

OWN = sorted(i for i in published.PEPPOL if i.startswith("PEPPOL-"))
RULE_FILE = os.path.join(upstream.FETCHED, "peppol", "rules", "sch", "PEPPOL-EN16931-UBL.sch")
BUYERS_COUNTRY = ("<cbc:PostalZone>10115</cbc:PostalZone>\n        <cac:Country>\n          "
                  "<cbc:IdentificationCode>%s")
SELLERS_IDENTIFIER = '<cbc:ID schemeID="0088">4012345000009</cbc:ID>'
PRICE_ALLOWANCE = ('<cbc:BaseQuantity unitCode="C62">1</cbc:BaseQuantity><cac:AllowanceCharge>'
                   "<cbc:ChargeIndicator>%s</cbc:ChargeIndicator>"
                   '<cbc:Amount currencyID="EUR">%s</cbc:Amount>%s</cac:AllowanceCharge>')
PERIOD = ("<cac:InvoicePeriod><cbc:StartDate>%s</cbc:StartDate><cbc:EndDate>%s</cbc:EndDate>"
          "</cac:InvoicePeriod>")
BREAKDOWN_RATE = ("<cbc:Percent>19</cbc:Percent>\n        <cac:TaxScheme>\n          <cbc:ID>VAT"
                  "</cbc:ID>\n        </cac:TaxScheme>\n      </cac:TaxCategory>\n    "
                  "</cac:TaxSubtotal>")
USD_TOTAL = '<cac:TaxTotal><cbc:TaxAmount currencyID="USD">%s</cbc:TaxAmount></cac:TaxTotal>'


def found(text: str) -> list:
    """Peppol's own rules that a document fails as sent, with where. Not
    Germany's, which are in `test_peppol_de_rules.py`."""
    document, _findings, sent = parse_tree(text)
    return [(f.code, f.path) for f in run(document, "peppol", sent)
            if f.code.startswith("PEPPOL-")]


def failing(text: str) -> list:
    return sorted({code for code, _path in found(text)})


def french(text: str) -> str:
    """The sample with seller and buyer in France, and one note."""
    text = text.replace("<cbc:IdentificationCode>DE<", "<cbc:IdentificationCode>FR<")
    text = text.replace(">DE123456789<", ">FR12345678901<").replace(">DE987654321<",
                                                                    ">FR98765432101<")
    return changed(text, "  <cbc:Note>Thank you for the order.</cbc:Note>\n", "")


class WhatIsBuilt(unittest.TestCase):
    def test_peppols_own_63_rules_and_none_of_a_countrys(self):
        self.assertEqual(len(OWN), 63)
        self.assertEqual(sorted(i for i in REGISTRY["peppol"] if i.startswith("PEPPOL-")), OWN)
        flags = [published.PEPPOL[i] for i in OWN]
        self.assertEqual((flags.count("fatal"), flags.count("warning")), (54, 9))

    def test_the_documents_this_project_wrote_fail_none(self):
        self.assertEqual(found(INVOICE), [])
        self.assertEqual(found(CREDIT_NOTE), [])
        self.assertEqual(found(french(INVOICE)), [])

    def test_a_finding_is_where_in_the_document_and_links_to_peppols_rules(self):
        document, _findings, sent = parse_tree(changed(
            INVOICE, "<cbc:DueDate>2026-11-01", "<cbc:DueDate>1.11.2026"))
        finding, = [f for f in run(document, "peppol", sent)]
        self.assertEqual((finding.level, finding.code, finding.path),
                         ("fatal", "PEPPOL-EN16931-F001", "/Invoice/cbc:DueDate"))
        self.assertEqual(finding.text, "a date is ten characters, `YYYY-MM-DD`: it is '1.11.2026'")
        self.assertIn("806866bd2bd91d7e9623b68f08164e8fbe9e67a0", finding.link)


class EachRule(unittest.TestCase):
    """The invoice all of them pass, changed in one place: the rules of
    Peppol's that then fail, which is the one named and whatever must fail
    beside it."""

    def case(self, rule: str, text: str, beside=()) -> None:
        wanted = sorted(["PEPPOL-" + rule] + ["PEPPOL-" + other for other in beside])
        self.assertEqual(failing(text), wanted, rule)
        self.seen.add("PEPPOL-" + rule)

    seen = set()

    def test_the_head_of_the_document(self):
        self.case("EN16931-R001", cut(INVOICE, "<cbc:ProfileID>", "</cbc:ProfileID>"),
                  ["EN16931-R007"])
        self.case("EN16931-R007", changed(INVOICE, "billing:01:1.0<", "billing:01:2.0<"))
        self.case("EN16931-R002", changed(INVOICE, BUYERS_COUNTRY % "DE", BUYERS_COUNTRY % "FR"))
        # Two notes need both of them in Germany, however the country is written.
        self.case("EN16931-R002", changed(INVOICE, "Hamburg</cbc:CityName>\n        "
                                          "<cbc:PostalZone>20095</cbc:PostalZone>\n        "
                                          "<cac:Country>\n          <cbc:IdentificationCode>DE",
                                          "Hamburg</cbc:CityName>\n        <cbc:PostalZone>20095"
                                          "</cbc:PostalZone>\n        <cac:Country>\n          "
                                          "<cbc:IdentificationCode>AT"))
        self.assertEqual(failing(INVOICE.replace("<cbc:IdentificationCode>DE<",
                                                 "<cbc:IdentificationCode> de <")), [])
        text = cut(INVOICE, "<cbc:BuyerReference>", "</cbc:BuyerReference>")
        self.assertEqual(failing(text), [])         # the order reference will do
        self.case("EN16931-R003", cut(text, "<cac:OrderReference>", "</cac:OrderReference>"))
        self.case("EN16931-R004", changed(INVOICE, "billing:3.0<", "billing:3.0::ext<"))
        self.case("EN16931-R004", changed(INVOICE, "urn:cen.eu:en16931:2017#compliant#", ""))
        self.assertEqual(failing(changed(INVOICE, "billing:3.0<", "billing:3.0#conformant#x<")), [])
        self.case("EN16931-R008", changed(INVOICE, "<cbc:BuyerReference>",
                                          "<cbc:AccountingCost/><cbc:BuyerReference>"))
        self.case("EN16931-R010", cut(INVOICE, '<cbc:EndpointID schemeID="0088">4098',
                                      "</cbc:EndpointID>"))
        self.case("EN16931-R020", cut(INVOICE, '<cbc:EndpointID schemeID="0088">4012',
                                      "</cbc:EndpointID>"))

    def test_the_profiles_peppol_has(self):
        for name in ("urn:peppol:france:billing:regulated", "urn:peppol:bis:billing_with_response",
                     " urn:fdc:peppol.eu:2017:poacc:billing:01:1.0 "):
            self.assertEqual(failing(changed(INVOICE, ">urn:fdc:peppol.eu:2017:poacc:billing:01:1.0<",
                                             ">%s<" % name)), [], name)

    def test_an_empty_element_is_one_with_nothing_but_attributes_too(self):
        self.assertEqual(found(changed(INVOICE, "<cbc:BuyerReference>", '<cbc:AccountingCost x="1">'
                                       " \n</cbc:AccountingCost><cbc:BuyerReference>")),
                         [("PEPPOL-EN16931-R008", "/Invoice/cbc:AccountingCost")])
        self.assertEqual(failing(changed(INVOICE, "<cac:PaymentTerms>", "<cac:PaymentTerms/>"
                                         "<cac:PaymentTerms>")), ["PEPPOL-EN16931-R008"])

    def test_vat_totals(self):
        accounting = "<cbc:TaxCurrencyCode>%s</cbc:TaxCurrencyCode><cbc:BuyerReference>"
        self.case("EN16931-R005", changed(INVOICE, "<cbc:BuyerReference>", accounting % " EUR "),
                  ["EN16931-R054"])
        start, end = INVOICE.index("    <cac:TaxSubtotal>"), INVOICE.index("  </cac:TaxTotal>")
        self.case("EN16931-R053", INVOICE[:start] + INVOICE[end:], ["EN16931-R054"])
        usd = changed(INVOICE, "<cbc:BuyerReference>", accounting % "USD")
        self.case("EN16931-R054", usd, ["EN16931-R055"])
        both = changed(usd, "  <cac:LegalMonetaryTotal>", USD_TOTAL % "200.00"
                       + "<cac:LegalMonetaryTotal>")
        self.assertEqual(failing(both), [])
        self.case("EN16931-R055", both.replace('"USD">200.00<', '"USD">-200.00<'))
        self.assertEqual(failing(both.replace('"USD">200.00<', '"USD">0<')), [])

    def test_the_two_vat_totals_have_one_sign_and_nought_has_either(self):
        def totals(invoice, accounting):
            return "PEPPOL-EN16931-R055" in failing(
                '<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2" '
                'xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2" '
                'xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">'
                "<cbc:DocumentCurrencyCode>EUR</cbc:DocumentCurrencyCode><cbc:TaxCurrencyCode>USD"
                '</cbc:TaxCurrencyCode><cac:TaxTotal><cbc:TaxAmount currencyID="EUR">%s'
                '</cbc:TaxAmount></cac:TaxTotal><cac:TaxTotal><cbc:TaxAmount currencyID="USD">%s'
                "</cbc:TaxAmount></cac:TaxTotal></Invoice>" % (invoice, accounting))
        for invoice, accounting, fails in (("1", "1", False), ("-1", "-1", False), ("-1", "0", False),
                                           ("0", "-1", False), ("1", "0", False), ("-1", "1", True),
                                           ("1", "-1", True)):
            self.assertEqual(totals(invoice, accounting), fails, (invoice, accounting))
        # A VAT total with no breakdown and no accounting currency is one too many.
        self.assertEqual(failing(changed(INVOICE, "  <cac:LegalMonetaryTotal>", USD_TOTAL % "1.00"
                                         + "<cac:LegalMonetaryTotal>")), ["PEPPOL-EN16931-R054"])

    def test_allowances_and_charges(self):
        amount = '<cbc:Amount currencyID="EUR">%s</cbc:Amount>\n    <cbc:BaseAmount'
        self.case("EN16931-R040", changed(INVOICE, amount % "10.00", amount % "10.03"))
        self.assertEqual(failing(changed(INVOICE, amount % "10.00", amount % "10.01")), [])
        self.assertEqual(failing(changed(INVOICE, amount % "10.00", amount % "9.99")), [])
        # Exactly two cents out is within two cents.
        self.assertEqual(failing(changed(INVOICE, amount % "10.00", amount % "10.02")), [])
        self.assertEqual(failing(changed(INVOICE, amount % "10.00", amount % "9.98")), [])
        self.case("EN16931-R040", changed(INVOICE, amount % "10.00", "<cbc:BaseAmount"))
        base = '<cbc:BaseAmount currencyID="EUR">1000.00</cbc:BaseAmount>\n'
        self.case("EN16931-R041", changed(INVOICE, base, ""))
        freight = ('Freight</cbc:AllowanceChargeReason>\n    <cbc:Amount currencyID="EUR">10.00'
                   "</cbc:Amount>")
        self.case("EN16931-R042", changed(INVOICE, freight, freight
                                          + '<cbc:BaseAmount currencyID="EUR">1.00</cbc:BaseAmount>'))
        true = "<cbc:ChargeIndicator>true</cbc:ChargeIndicator>"
        for other in ("1", "TRUE", "yes", ""):
            text = changed(INVOICE, true, "<cbc:ChargeIndicator>%s</cbc:ChargeIndicator>" % other)
            self.assertIn("PEPPOL-EN16931-R043", failing(text), other)
        self.case("EN16931-R043", changed(INVOICE, true, "<cbc:ChargeIndicator>1</cbc:ChargeIndicator>"))
        self.assertEqual(failing(changed(INVOICE, true, "<cbc:ChargeIndicator> true\n"
                                         "</cbc:ChargeIndicator>")), [])

    def test_an_allowance_one_rule_took_is_asked_no_other(self):
        # A percentage and no base amount, and an indicator of `0`: the first
        # fails its rule, and the rule about the indicator is not asked.
        text = changed(INVOICE, '<cbc:BaseAmount currencyID="EUR">1000.00</cbc:BaseAmount>\n', "",
                       "<cbc:ChargeIndicator>false</cbc:ChargeIndicator>\n    "
                       "<cbc:AllowanceChargeReasonCode>",
                       "<cbc:ChargeIndicator>0</cbc:ChargeIndicator>\n    "
                       "<cbc:AllowanceChargeReasonCode>")
        self.assertEqual(failing(text), ["PEPPOL-EN16931-R041"])
        # On a line too.
        text = changed(INVOICE, "<cbc:AllowanceChargeReason>Introductory",
                       "<cbc:MultiplierFactorNumeric>20</cbc:MultiplierFactorNumeric>"
                       "<cbc:AllowanceChargeReason>Introductory")
        self.assertEqual(found(text), [
            ("PEPPOL-EN16931-R041", "/Invoice/cac:InvoiceLine[2]/cac:AllowanceCharge")])

    def test_the_allowance_on_a_price(self):
        base = '<cbc:BaseAmount currencyID="EUR">%s</cbc:BaseAmount>'
        was = '<cbc:BaseQuantity unitCode="C62">1</cbc:BaseQuantity>'
        self.assertEqual(failing(changed(INVOICE, was, PRICE_ALLOWANCE % ("false", "2.00",
                                                                         base % "22.00"))), [])
        self.case("EN16931-R044", changed(INVOICE, was, PRICE_ALLOWANCE % ("true", "0.00", "")))
        self.case("EN16931-R046", changed(INVOICE, was, PRICE_ALLOWANCE % ("false", "1.00",
                                                                          base % "22.00")))
        self.assertEqual(failing(changed(INVOICE, was, PRICE_ALLOWANCE % ("false", "1.00", ""))), [])
        # With a gross price and no discount, nothing is equal to anything.
        self.case("EN16931-R046", changed(INVOICE, was, (PRICE_ALLOWANCE % (
            "false", "0", base % "20.00")).replace('<cbc:Amount currencyID="EUR">0</cbc:Amount>', "")))

    def test_payment_currency_and_periods(self):
        for code in ("49", "59"):
            self.case("EN16931-R061", changed(INVOICE, '">30</cbc:PaymentMeansCode>',
                                              '">%s</cbc:PaymentMeansCode>' % code))
        mandate = "</cac:PayeeFinancialAccount><cac:PaymentMandate><cbc:ID>M-1</cbc:ID></cac:PaymentMandate>"
        self.assertEqual(failing(changed(INVOICE, '">30</cbc:PaymentMeansCode>',
                                         '"> 49 </cbc:PaymentMeansCode>',
                                         "</cac:PayeeFinancialAccount>", mandate)), [])
        self.case("EN16931-R051", changed(INVOICE, '<cbc:PayableAmount currencyID="EUR">',
                                          '<cbc:PayableAmount currencyID="USD">'))
        self.case("EN16931-R051", changed(INVOICE, '<cbc:PayableAmount currencyID="EUR">',
                                          "<cbc:PayableAmount>"), ["EN16931-CL007"])

        def periods(line_start, line_end):
            return changed(INVOICE, "<cac:OrderReference>", PERIOD % ("2026-09-10", "2026-09-30")
                           + "<cac:OrderReference>", "<cac:OrderLineReference>",
                           PERIOD % (line_start, line_end) + "<cac:OrderLineReference>")
        self.assertEqual(failing(periods("2026-09-10", "2026-09-30")), [])
        self.case("EN16931-R110", periods("2026-09-09", "2026-09-30"))
        self.case("EN16931-R111", periods("2026-09-10", "2026-10-01"))
        # Not asked where the document has no period.
        self.assertEqual(failing(changed(INVOICE, "<cac:OrderLineReference>", PERIOD % (
            "2020-01-01", "2030-01-01") + "<cac:OrderLineReference>")), [])
        reference = ("  <cac:AdditionalDocumentReference>\n    <cbc:ID>PRJ-7</cbc:ID>\n    "
                     "<cbc:DocumentTypeCode>50</cbc:DocumentTypeCode>\n  "
                     "</cac:AdditionalDocumentReference>\n")
        self.assertIn(reference, CREDIT_NOTE)
        self.case("EN16931-R080", changed(CREDIT_NOTE, reference, reference * 2))
        self.assertEqual(failing(changed(INVOICE, "<cac:AccountingSupplierParty>",
                                         reference * 2 + "<cac:AccountingSupplierParty>")), [])
        # Two references that are not the project are not two projects.
        supporting = ("<cac:AdditionalDocumentReference><cbc:ID>T-1</cbc:ID>"
                      "</cac:AdditionalDocumentReference>")
        self.assertEqual(failing(changed(CREDIT_NOTE, reference, reference + supporting * 2)), [])

    def test_lines(self):
        net = '<cbc:LineExtensionAmount currencyID="EUR">%s</cbc:LineExtensionAmount>'
        self.case("EN16931-R120", changed(INVOICE, net % "800.00", net % "800.03"))
        self.assertEqual(failing(changed(INVOICE, net % "800.00", net % "800.02")), [])
        self.assertEqual(failing(changed(INVOICE, net % "800.00", net % "799.98")), [])
        self.case("EN16931-R120", changed(INVOICE, net % "200.00", net % "250.00"))
        # A line's charge is added: 2.5 at 100.00, less 50.00, plus 5.00.
        charged = changed(INVOICE, "<cac:Item>\n      <cbc:Description>",
                          "<cac:AllowanceCharge><cbc:ChargeIndicator>true</cbc:ChargeIndicator>"
                          '<cbc:Amount currencyID="EUR">5.00</cbc:Amount></cac:AllowanceCharge>'
                          "<cac:Item>\n      <cbc:Description>")
        self.case("EN16931-R120", charged)
        self.assertEqual(failing(changed(charged, net % "200.00", net % "205.00")), [])
        base = '<cbc:BaseQuantity unitCode="C62">%s</cbc:BaseQuantity>'
        self.case("EN16931-R121", changed(INVOICE, base % "1", base % "0"))
        self.case("EN16931-R121", changed(INVOICE, base % "1", base % "-1"), ["EN16931-R120"])
        # The price is for the base quantity: 40 at 200.00 a ten is 800.00.
        self.assertEqual(failing(changed(INVOICE, base % "1", base % "10",
                                         ">20.00</cbc:PriceAmount>", ">200.00</cbc:PriceAmount>")), [])
        self.case("EN16931-R130", changed(INVOICE, base % "1", base.replace("C62", "HUR") % "1"))
        reference = ("<cac:DocumentReference><cbc:ID>M-1</cbc:ID><cbc:DocumentTypeCode>%s"
                     "</cbc:DocumentTypeCode></cac:DocumentReference>")
        at = "<cac:OrderLineReference>\n      <cbc:LineID>10</cbc:LineID>\n    </cac:OrderLineReference>"
        self.assertEqual(failing(changed(INVOICE, at, at + reference % "130")), [])
        self.case("EN16931-R100", changed(INVOICE, at, at + reference % "130" * 2))
        self.case("EN16931-R101", changed(INVOICE, at, at + reference % "916"))

    def test_an_allowance_marked_0_is_not_counted_in_its_lines_net_amount(self):
        marked = changed(INVOICE, "<cbc:ChargeIndicator>false</cbc:ChargeIndicator>\n      "
                         "<cbc:AllowanceChargeReason>Introductory",
                         "<cbc:ChargeIndicator>0</cbc:ChargeIndicator>\n      "
                         "<cbc:AllowanceChargeReason>Introductory")
        self.assertEqual(failing(marked), ["PEPPOL-EN16931-R043", "PEPPOL-EN16931-R120"])

    def test_code_lists_and_type_codes(self):
        attachment = ("<cac:AdditionalDocumentReference><cbc:ID>T-1</cbc:ID><cac:Attachment>"
                      '<cbc:EmbeddedDocumentBinaryObject mimeCode="%s" filename="t">eA=='
                      "</cbc:EmbeddedDocumentBinaryObject></cac:Attachment>"
                      "</cac:AdditionalDocumentReference><cac:AccountingSupplierParty>")
        self.case("EN16931-CL001", changed(INVOICE, "<cac:AccountingSupplierParty>",
                                           attachment % "text/plain"))
        self.assertEqual(failing(changed(INVOICE, "<cac:AccountingSupplierParty>",
                                         attachment % "text/csv")), [])
        self.case("EN16931-CL002", changed(INVOICE, "<cbc:AllowanceChargeReasonCode>95",
                                           "<cbc:AllowanceChargeReasonCode>96"))
        freight = "<cbc:AllowanceChargeReason>Freight"
        self.case("EN16931-CL003", changed(
            INVOICE, freight, "<cbc:AllowanceChargeReasonCode>95</cbc:AllowanceChargeReasonCode>"
            + freight))
        self.assertEqual(failing(changed(
            INVOICE, freight, "<cbc:AllowanceChargeReasonCode> FC </cbc:AllowanceChargeReasonCode>"
            + freight)), [])
        period = ("<cac:InvoicePeriod><cbc:DescriptionCode>%s</cbc:DescriptionCode>"
                  "</cac:InvoicePeriod><cac:OrderReference>")
        self.case("EN16931-CL006", changed(INVOICE, "<cac:OrderReference>", period % "5"))
        self.assertEqual(failing(changed(INVOICE, "<cac:OrderReference>", period % "35")), [])
        payable = '<cbc:PayableAmount currencyID="%s">'
        self.case("EN16931-CL007", changed(INVOICE, payable % "EUR", payable % "EUX"),
                  ["EN16931-R051"])
        endpoint = '<cbc:EndpointID schemeID="%s">4098765000003'
        self.case("EN16931-CL008", changed(INVOICE, endpoint % "0088", endpoint % "0037"))
        self.case("EN16931-P0100", changed(INVOICE, "<cbc:InvoiceTypeCode>380",
                                           "<cbc:InvoiceTypeCode>381"))
        self.case("EN16931-P0101", changed(CREDIT_NOTE, "<cbc:CreditNoteTypeCode>381",
                                           "<cbc:CreditNoteTypeCode>380"))
        self.assertEqual(failing(changed(INVOICE, "<cbc:InvoiceTypeCode>380",
                                         "<cbc:InvoiceTypeCode>384")), [])
        for code in ("326", "384"):
            self.case("EN16931-P0112", changed(INVOICE, "<cbc:InvoiceTypeCode>380",
                                               "<cbc:InvoiceTypeCode>%s" % code,
                                               BUYERS_COUNTRY % "DE", BUYERS_COUNTRY % "AT"),
                      ["EN16931-R002"])

    def test_peppols_lists_are_narrower_than_the_cores_in_three_places(self):
        payable = '<cbc:PayableAmount currencyID="%s">'
        # The dobra's old code is the core's and its new one is Peppol's.
        self.assertIn("PEPPOL-EN16931-CL007", failing(changed(INVOICE, payable % "EUR",
                                                              payable % "STD")))
        self.assertNotIn("PEPPOL-EN16931-CL007", failing(changed(INVOICE, payable % "EUR",
                                                                 payable % "STN")))
        # 81 is an invoice type to the core, and a credit note type to Peppol.
        self.assertEqual(failing(changed(INVOICE, "<cbc:InvoiceTypeCode>380",
                                         "<cbc:InvoiceTypeCode>81")), ["PEPPOL-EN16931-P0100"])
        self.assertEqual(failing(changed(CREDIT_NOTE, "<cbc:CreditNoteTypeCode>381",
                                         "<cbc:CreditNoteTypeCode>81")), [])
        # A type code is not asked of a document whose profile is not Peppol's.
        self.assertEqual(failing(changed(INVOICE, "<cbc:InvoiceTypeCode>380",
                                         "<cbc:InvoiceTypeCode>381", "billing:01:1.0<",
                                         "billing:01:2.0<")), ["PEPPOL-EN16931-R007"])
        self.assertEqual((len(peppol.CURRENCIES), len(peppol.ADDRESS_SCHEMES),
                          len(peppol.INVOICE_TYPES), len(peppol.CREDIT_NOTE_TYPES)),
                         (178, 83, 26, 5))

    def test_an_exemption_reason_code_goes_with_its_category(self):
        for number, reason, category in (("04", "G", "G"), ("05", "O", "O"), ("06", "IC", "K"),
                                         ("07", "AE", "AE"), ("08", "D", "E"), ("09", "F", "E"),
                                         ("10", "I", "E"), ("11", "J", "E")):
            coded = ("<cbc:Percent>19</cbc:Percent><cbc:TaxExemptionReasonCode>vatex-eu-%s"
                     "</cbc:TaxExemptionReasonCode>" % reason.lower())
            text = changed(INVOICE, BREAKDOWN_RATE, BREAKDOWN_RATE.replace(
                "<cbc:Percent>19</cbc:Percent>", coded))
            self.case("EN16931-P01" + number, text)
            right = text.replace("<cbc:ID>S</cbc:ID>\n        <cbc:Percent>19</cbc:Percent><cbc:Tax",
                                 "<cbc:ID> %s </cbc:ID>\n        <cbc:Percent>19</cbc:Percent><cbc:Tax"
                                 % category)
            self.assertNotEqual(right, text)
            self.assertEqual(failing(right), [], reason)

    def test_dates(self):
        for name, good in (("IssueDate", "2026-10-02"), ("DueDate", "2026-11-01"),
                           ("ActualDeliveryDate", "2026-09-30")):
            for bad in ("2026-10-2", "02.10.2026", "2026-10-02Z", " 2026-10-02", "2026-02-30"):
                text = changed(INVOICE, "<cbc:%s>%s" % (name, good), "<cbc:%s>%s" % (name, bad))
                self.assertEqual(failing(text), ["PEPPOL-EN16931-F001"], (name, bad))
        self.seen.add("PEPPOL-EN16931-F001")
        text = changed(INVOICE, "<cac:OrderReference>", PERIOD % ("1.9.2026", "2026-09-30")
                       + "<cac:OrderReference>")
        self.assertEqual(found(text), [("PEPPOL-EN16931-F001",
                                        "/Invoice/cac:InvoicePeriod/cbc:StartDate")])

    def test_identifiers_by_scheme(self):
        """Each scheme with a number that is right, most of them a real
        organisation's, and one that is not."""
        cases = (
            ("R040", "0088", ["7300010000001", "5790000435975", "17"], ["4012345000008", "401234A"]),
            ("R041", "0192", ["923609016", "974760673"], ["923609017", "92360901", "000000000"]),
            ("R042", "0184", ["DK12345678", "12345678"], ["DK1234567", "1234567", "SE12345678"]),
            ("R052", "0096", ["1234567890"], ["123456789", "123456789X"]),
            ("R053", "0198", ["DK12345678"], ["12345678", "dk12345678"]),
            ("R043", "0208", ["0202239951", "0403170701"], ["0202239952", "202239951"]),
            ("R044", "0201", ["UFY9MH", "abc123"], ["UFY9M", "UFY9M-"]),
            ("R045", "0210", ["RSSMRA85T10A562S", "01234567890"], ["RSSMRA85T10A5621", "0123456789",
                                                                   "123MRA85T10A562S"]),
            ("R047", "0211", ["IT00743110157", "FR123"], ["IT00743110158", "IT0074311015",
                                                         "IT007431101570"]),
            ("R049", "0007", ["5560125790", "2021005489"], ["5560125791", "556012579", "556012579X"]),
            ("R050", "0151", ["51824753556", "53004085616"], ["51824753557", "5182475355",
                                                           "52824753556"]),
            ("R054", "0106", ["12345678"], ["1234567", "1234567A"]),
            ("R055", "0190", ["00000001234567890123"], ["0000000123456789012"]),
            ("R056-1", "9944", ["NL123456789B01"], ["NL123456789B1", "nl123456789B01"]),
            ("R057", "0217", ["123456789012"], ["12345678901"]),
        )
        self.assertEqual(len(cases), len(peppol.SCHEMES))
        for rule, scheme, right, wrong in cases:
            def with_(value):
                return failing(changed(INVOICE, SELLERS_IDENTIFIER,
                                       '<cbc:ID schemeID="%s">%s</cbc:ID>' % (scheme, value)))
            for value in right:
                self.assertEqual(with_(value), [], (scheme, value))
            for value in wrong:
                self.assertEqual(with_(value), ["PEPPOL-COMMON-" + rule], (scheme, value))
            self.seen.add("PEPPOL-COMMON-" + rule)

    def test_a_scheme_is_asked_wherever_the_identifier_is(self):
        wrong = "4012345000008"
        for old, new, where in (
                ('<cbc:EndpointID schemeID="0088">4012345000009', '<cbc:EndpointID schemeID="0088">'
                 + wrong, "cbc:EndpointID"),
                ('<cbc:CompanyID schemeID="0204">HRB 12345', '<cbc:CompanyID schemeID="0088">' + wrong,
                 "cac:PartyLegalEntity/cbc:CompanyID"),
                ("<cbc:CompanyID>DE123456789", '<cbc:CompanyID schemeID="0088">' + wrong,
                 "cac:PartyTaxScheme[1]/cbc:CompanyID")):
            self.assertEqual(found(changed(INVOICE, old, new)), [
                ("PEPPOL-COMMON-R040", "/Invoice/cac:AccountingSupplierParty/cac:Party/" + where)])
        # Not an identifier that is nobody's: an order's, say.
        self.assertEqual(failing(changed(INVOICE, "<cbc:ID>4500000017</cbc:ID>",
                                         '<cbc:ID schemeID="0088">%s</cbc:ID>' % wrong)), [])

    def test_two_more_about_italian_and_dutch_identifiers(self):
        endpoint = '<cbc:EndpointID schemeID="%s">%s</cbc:EndpointID>'
        was = endpoint % ("0088", "4012345000009")
        # 9907 has a rule of its own and is not a scheme Peppol's list has.
        self.assertEqual(failing(changed(INVOICE, was, endpoint % ("9907", "RSSMRA85T10A562S"))),
                         ["PEPPOL-EN16931-CL008"])
        self.case("COMMON-R046", changed(INVOICE, was, endpoint % ("9907", "RSSMRA85T10")),
                  ["EN16931-CL008"])
        vat = "<cbc:CompanyID>%s</cbc:CompanyID>"
        self.case("COMMON-R056-2", changed(INVOICE, vat % "DE123456789", vat % "NL123456789"))
        self.assertEqual(failing(changed(INVOICE, vat % "DE123456789", vat % " NL123456789B01 ")), [])
        # Not of a registration under another scheme than VAT.
        self.assertEqual(failing(changed(INVOICE, vat % "22/333/44444", vat % "NL1")), [])
        # One that names a scheme with a rule of its own is asked that rule only.
        self.assertEqual(failing(changed(INVOICE, vat % "DE123456789",
                                         '<cbc:CompanyID schemeID="0106">NL1</cbc:CompanyID>')),
                         ["PEPPOL-COMMON-R054"])
        self.assertEqual(published.PEPPOL["PEPPOL-COMMON-R056-2"], "warning")

    def test_zz_every_rule_failed_somewhere_above(self):
        for name in sorted(n for n in dir(self) if n.startswith("test_") and "zz" not in n):
            getattr(self, name)()
        self.assertEqual(sorted(self.seen), OWN)


class TheRulesForASellersCountry(unittest.TestCase):
    """They are in `test_peppol_national_rules.py`. Here: that nothing of
    Peppol's is left to wait on."""

    def root(self, text: str):
        return top(tree(text))

    def test_they_are_built_and_no_set_of_peppols_is_scoped(self):
        national = [i for i in published.PEPPOL if not i.startswith(("PEPPOL-", "DE-R-"))]
        self.assertEqual(len(national), 71)
        self.assertLessEqual(set(national), set(REGISTRY["peppol"]))
        self.assertEqual((SCOPES["peppol"], SCOPES["en16931"]), ({}, {}))

    def test_a_rule_of_no_set_always_could_apply(self):
        self.assertTrue(could_apply("peppol", "PEPPOL-EN16931-R001", self.root(french(INVOICE))))
        self.assertTrue(could_apply("peppol", "SE-R-001", self.root(INVOICE)))
        self.assertTrue(could_apply("xrechnung", "BR-DE-1", self.root(INVOICE)))

    def test_every_published_context_of_a_national_rule_asks_for_the_sellers_country(self):
        """Read from Peppol's own file: none of them is asked of every document."""
        if not os.path.exists(RULE_FILE):
            self.skipTest("Peppol's files are not in this repository: python tools/fetch_peppol.py")
        schematron = "{http://purl.oclc.org/dsdl/schematron}"
        asks = ("supplierCountry", "SupplierCountry", "isGreekSender", "IdentificationCode = 'SE'")
        seen = 0
        for element in ET.parse(RULE_FILE).getroot().iter(schematron + "rule"):
            identifiers = [a.get("id") for a in element.findall(schematron + "assert")]
            if any(not i.startswith("PEPPOL-") for i in identifiers):
                self.assertTrue(any(word in element.get("context") for word in asks), identifiers)
                seen += len(identifiers)
        self.assertEqual(seen, 102)         # the 71, and Germany's 31


class TheVerdict(unittest.TestCase):
    def test_a_document_from_a_country_with_no_rules_of_its_own_is_valid(self):
        _document, report = validate(french(INVOICE))
        self.assertEqual((report.findings, report.verdict), ([], "valid"))
        self.assertEqual(report.not_built, {"en16931": {}, "peppol": {}})
        self.assertEqual(report.not_applicable["peppol"], {})
        self.assertEqual(len(report.ran), 979 + 63 + 31 + 71)

    def test_one_from_germany_is_valid_too_now_that_germanys_rules_are_built(self):
        _document, report = validate(INVOICE)
        self.assertEqual((report.findings, report.verdict), ([], "valid"))
        self.assertEqual(report.unasked, 0)

    def test_one_from_any_of_the_seven_countries_is_judged(self):
        """The sample moved to Sweden was `not judged` while Sweden's
        rules were not built. It is invalid: a German register number is not
        a Swedish organisation number."""
        swedish = french(INVOICE).replace("<cbc:IdentificationCode>FR<",
                                          "<cbc:IdentificationCode>SE<")
        _document, report = validate(swedish)
        self.assertEqual(([f.code for f in report.findings], report.verdict, report.unasked),
                         (["SE-R-003", "SE-R-004", "SE-R-013", "SE-R-005"], "invalid", 0))

    def test_a_document_waits_on_a_rule_that_is_published_and_not_built(self):
        """No rule is, today. This is the package as it would be without
        Sweden's, which is how it was."""
        swedish = french(INVOICE).replace("<cbc:IdentificationCode>FR<",
                                          "<cbc:IdentificationCode>SE<")
        with unbuilt("peppol", "SE-R-"):
            _document, report = validate(swedish)
        self.assertEqual((report.failures, report.verdict), ([], "not judged"))
        self.assertEqual(len(report.not_built["peppol"]), 13)
        self.assertEqual(report.unasked, 7)
        # And with no way to say a set is another country's, every document does.
        with unbuilt("peppol", "SE-R-"):
            self.assertEqual(validate(INVOICE)[1].verdict, "not judged")

    def test_and_a_failure_is_invalid_wherever_it_is_from(self):
        _document, report = validate(changed(french(INVOICE), "<cbc:DueDate>2026-11-01",
                                             "<cbc:DueDate>1.11.2026"))
        self.assertEqual(report.verdict, "invalid")
        self.assertEqual([f.code for f in report.failures], ["PEPPOL-EN16931-F001"])


class PeppolsOwnLists(unittest.TestCase):
    """Nothing is copied from Peppol's rule file. Where it has been fetched,
    the lists here are compared with the lists there."""

    def test_they_are_the_same_lists(self):
        if not os.path.exists(RULE_FILE):
            self.skipTest("Peppol's files are not in this repository: python tools/fetch_peppol.py")
        schematron = "{http://purl.oclc.org/dsdl/schematron}"
        theirs = {}
        for element in ET.parse(RULE_FILE).getroot().iter(schematron + "let"):
            match = re.match(r"\s*tokenize\('([^']*)'", element.get("value"))
            if match:
                theirs[element.get("name")] = frozenset(match.group(1).split())
        self.assertEqual(theirs["ISO4217"], peppol.CURRENCIES)
        self.assertEqual(theirs["eaid"], peppol.ADDRESS_SCHEMES)
        self.assertEqual(theirs["MIMECODE"], peppol.MIME_TYPES)
        self.assertEqual(theirs["UNCL5189"], peppol.ALLOWANCE_REASONS)
        self.assertEqual(theirs["UNCL7161"], peppol.CHARGE_REASONS)
        self.assertEqual(theirs["UNCL2005"], peppol.VAT_POINT_CODES)
        text = open(RULE_FILE, encoding="utf-8").read()
        for ours in (peppol.INVOICE_TYPES, peppol.CREDIT_NOTE_TYPES):
            self.assertTrue(any(frozenset(found.split()) == ours
                                for found in re.findall(r"tokenize\('([^']*)'", text)))
        for name in peppol.PROFILES:
            self.assertIn("'%s'" % name, text)
        self.assertIn("'%s'" % peppol.BILLING, text)
