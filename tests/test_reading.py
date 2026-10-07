"""Reading UBL: where each term lands, and what is said of what is not held."""
import unittest
from decimal import Decimal

from mockeinvoice import read, write
from mockeinvoice.ubl import parse

from . import sample

HEAD = ('<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2" '
        'xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2" '
        'xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">')


def invoice(inside: str) -> str:
    return HEAD + inside + "</Invoice>"


def codes(findings):
    return [(f.level, f.code, f.path) for f in findings]


class AnInvoice(unittest.TestCase):
    def setUp(self):
        self.document, self.specification, self.findings = read(sample("peppol-invoice.xml"))

    def test_it_is_read_with_nothing_to_say_about_it(self):
        self.assertEqual(self.document.kind, "Invoice")
        self.assertEqual(self.specification, "peppol")
        self.assertEqual(self.findings, [])

    def test_the_terms_of_the_document_are_under_their_numbers(self):
        expected = {"BT-1": "GLX-4711", "BT-2": "2026-10-02", "BT-9": "2026-11-01",
                    "BT-3": "380", "BT-5": "EUR", "BT-10": "ACME-PO-4500000017",
                    "BT-13": "4500000017", "BT-27": "Globex GmbH", "BT-28": "Globex",
                    "BT-30": "HRB 12345", "BT-31": "DE123456789", "BT-34": "4012345000009",
                    "BT-35": "Industriestrasse 1", "BT-37": "Hamburg", "BT-38": "20095",
                    "BT-40": "DE", "BT-41": "Accounts receivable", "BT-43": "ar@globex.example",
                    "BT-44": "ACME Corporation", "BT-48": "DE987654321", "BT-52": "Berlin",
                    "BT-55": "DE", "BT-72": "2026-09-30", "BT-20": "30 days net",
                    "BT-106": "1000.00", "BT-109": "1000.00", "BT-110": "190.00",
                    "BT-112": "1190.00", "BT-107": "10.00", "BT-108": "10.00",
                    "BT-115": "1190.00"}
        self.assertEqual({term: self.document.text(term) for term in expected}, expected)
        for absent in ("BT-6", "BT-7", "BT-11", "BT-45", "BT-59", "BT-111", "BT-113"):
            self.assertIsNone(self.document.term(absent), absent)

    def test_an_amount_is_a_decimal_with_its_currency_beside_it(self):
        total = self.document.term("BT-112")
        self.assertEqual(total.number, Decimal("1190.00"))
        self.assertIsInstance(total.number, Decimal)
        self.assertEqual(total.attributes, {"currencyID": "EUR"})

    def test_the_seller_has_one_identifier_and_the_sepa_one_is_the_creditor_identifier(self):
        self.assertEqual([(v.text, v.attributes) for v in self.document.values("BT-29")],
                         [("4012345000009", {"schemeID": "0088"})])
        self.assertEqual(self.document.text("BT-90"), "DE98ZZZ09999999999")
        self.assertEqual(self.document.text("BT-29-1"), "0088")
        self.assertEqual(self.document.text("BT-30-1"), "0204")

    def test_a_tax_registration_that_is_not_vat_keeps_the_scheme_it_was_under(self):
        self.assertEqual(self.document.term("BT-31").attributes, {})
        other = self.document.term("BT-32")
        self.assertEqual((other.text, other.attributes),
                         ("22/333/44444", {"TaxScheme/ID": "FC"}))

    def test_a_note_with_a_subject_code_is_split_and_one_without_is_not(self):
        notes = self.document.all("BG-1")
        self.assertEqual([(n.text("BT-21"), n.text("BT-22")) for n in notes],
                         [("AAI", "Goods remain ours until paid for."),
                          ("", "Thank you for the order.")])

    def test_allowances_and_charges_are_told_apart_by_the_indicator(self):
        allowance, = self.document.all("BG-20")
        charge, = self.document.all("BG-21")
        self.assertEqual({t: allowance.text(t) for t in ("BT-92", "BT-93", "BT-94", "BT-95",
                                                         "BT-96", "BT-97", "BT-98")},
                         {"BT-92": "10.00", "BT-93": "1000.00", "BT-94": "1", "BT-95": "S",
                          "BT-96": "19", "BT-97": "Discount", "BT-98": "95"})
        self.assertEqual({t: charge.text(t) for t in ("BT-99", "BT-102", "BT-103", "BT-104")},
                         {"BT-99": "10.00", "BT-102": "S", "BT-103": "19", "BT-104": "Freight"})
        self.assertIsNone(charge.term("BT-92"))

    def test_the_payment_instruction_and_the_vat_breakdown_are_groups(self):
        payment, = self.document.all("BG-16")
        self.assertEqual({t: payment.text(t) for t in ("BT-81", "BT-82", "BT-83", "BT-84",
                                                       "BT-85", "BT-86")},
                         {"BT-81": "30", "BT-82": "Credit transfer", "BT-83": "GLX-4711",
                          "BT-84": "DE02120300000000202051", "BT-85": "Globex GmbH",
                          "BT-86": "BYLADEM1001"})
        breakdown, = self.document.all("BG-23")
        self.assertEqual({t: breakdown.text(t) for t in ("BT-116", "BT-117", "BT-118", "BT-119")},
                         {"BT-116": "1000.00", "BT-117": "190.00", "BT-118": "S", "BT-119": "19"})

    def test_each_line_is_a_group_with_its_own_terms(self):
        first, second = self.document.all("BG-25")
        self.assertEqual({t: first.text(t) for t in ("BT-126", "BT-129", "BT-130", "BT-131",
                                                     "BT-132", "BT-153", "BT-155", "BT-151",
                                                     "BT-152", "BT-146", "BT-149", "BT-150")},
                         {"BT-126": "1", "BT-129": "40", "BT-130": "C62", "BT-131": "800.00",
                          "BT-132": "10", "BT-153": "Widget", "BT-155": "W-100", "BT-151": "S",
                          "BT-152": "19", "BT-146": "20.00", "BT-149": "1", "BT-150": "C62"})
        self.assertEqual([(v.text, v.attributes) for v in first.values("BT-158")],
                         [("31161500", {"listID": "STI"}),
                          ("44531000", {"listID": "CPV", "listVersionID": "2008"})])
        attribute, = first.all("BG-32")
        self.assertEqual((attribute.text("BT-160"), attribute.text("BT-161")), ("Colour", "Grey"))
        self.assertEqual(second.term("BT-129").number, Decimal("2.5"))
        self.assertEqual(second.text("BT-154"), "Fitting on site & hand-over")
        allowance, = second.all("BG-27")
        self.assertEqual((allowance.text("BT-136"), allowance.text("BT-139")),
                         ("50.00", "Introductory"))
        self.assertEqual(second.all("BG-28"), [])
        # A line's terms are the line's, not the document's.
        self.assertIsNone(self.document.term("BT-126"))


class ACreditNote(unittest.TestCase):
    def setUp(self):
        self.document, self.specification, self.findings = read(sample("peppol-creditnote.xml"))

    def test_it_is_the_same_model_with_another_kind(self):
        self.assertEqual((self.document.kind, self.specification, self.findings),
                         ("CreditNote", "peppol", []))
        self.assertEqual(self.document.text("BT-3"), "381")

    def test_its_due_date_is_the_documents_though_ubl_puts_it_in_the_payment_means(self):
        self.assertEqual(self.document.text("BT-9"), "2026-11-01")
        payment, = self.document.all("BG-16")
        self.assertIsNone(payment.term("BT-9"))

    def test_its_project_reference_is_a_document_reference_of_type_50(self):
        self.assertEqual(self.document.text("BT-11"), "PRJ-7")
        self.assertEqual(self.document.all("BG-24"), [])

    def test_its_lines_and_quantities_have_the_same_numbers_as_an_invoices(self):
        first, second = self.document.all("BG-25")
        self.assertEqual((first.text("BT-129"), first.text("BT-130")), ("40", "C62"))
        self.assertEqual(second.text("BT-126"), "2")

    def test_the_invoice_it_corrects_is_a_preceding_invoice(self):
        preceding, = self.document.all("BG-3")
        self.assertEqual((preceding.text("BT-25"), preceding.text("BT-26")),
                         ("GLX-4711", "2026-10-02"))

    def test_an_invoices_elements_in_a_credit_note_are_not_held(self):
        text = sample("peppol-creditnote.xml").decode().replace(
            "<cbc:CreditNoteTypeCode>381</cbc:CreditNoteTypeCode>",
            "<cbc:CreditNoteTypeCode>381</cbc:CreditNoteTypeCode><cbc:DueDate>2026-11-01</cbc:DueDate>")
        _document, findings = parse(text)
        self.assertEqual(codes(findings), [("warning", "UNHELD", "/CreditNote/cbc:DueDate")])


class WhatIsNotHeld(unittest.TestCase):
    """Nothing is dropped in silence: each of these is a finding with a path."""

    def test_an_element_with_no_business_term_is_named(self):
        document, findings = parse(invoice(
            "<cbc:UBLVersionID>2.1</cbc:UBLVersionID><cbc:ID>1</cbc:ID>"
            "<cac:InvoiceLine><cbc:ID>1</cbc:ID><cbc:UUID>x</cbc:UUID></cac:InvoiceLine>"
            "<cac:InvoiceLine><cbc:ID>2</cbc:ID><cac:Item><cbc:BrandName>B</cbc:BrandName>"
            "</cac:Item></cac:InvoiceLine>"))
        self.assertEqual(codes(findings), [
            ("warning", "UNHELD", "/Invoice/cbc:UBLVersionID"),
            ("warning", "UNHELD", "/Invoice/cac:InvoiceLine[1]/cbc:UUID"),
            ("warning", "UNHELD", "/Invoice/cac:InvoiceLine[2]/cac:Item/cbc:BrandName")])
        self.assertIn("cbc:UBLVersionID has no business term", findings[0].text)
        self.assertEqual(document.text("BT-1"), "1")
        self.assertEqual([line.text("BT-126") for line in document.all("BG-25")], ["1", "2"])

    def test_an_element_from_another_vocabulary_is_named_with_its_namespace_gone(self):
        _document, findings = parse(invoice(
            '<ext:UBLExtensions xmlns:ext="urn:oasis:names:specification:ubl:schema:xsd:'
            'CommonExtensionComponents-2"><ext:UBLExtension/></ext:UBLExtensions>'
            '<x:Thing xmlns:x="urn:example">1</x:Thing>'))
        self.assertEqual([f.path for f in findings],
                         ["/Invoice/ext:UBLExtensions", "/Invoice/Thing"])

    def test_an_element_that_repeats_where_the_standard_has_one_is_an_error(self):
        document, findings = parse(invoice(
            "<cbc:ID>1</cbc:ID><cbc:ID>2</cbc:ID><cbc:ID>3</cbc:ID>"
            "<cac:PaymentTerms><cbc:Note>a</cbc:Note></cac:PaymentTerms>"
            "<cac:PaymentTerms><cbc:Note>b</cbc:Note></cac:PaymentTerms>"))
        self.assertEqual(codes(findings), [
            ("error", "REPEATED", "/Invoice/cbc:ID[2]"),
            ("error", "REPEATED", "/Invoice/cac:PaymentTerms[2]")])
        # Every value is held all the same, in order, for a rule to count.
        self.assertEqual([v.text for v in document.values("BT-1")], ["1", "2", "3"])
        self.assertEqual([v.text for v in document.values("BT-20")], ["a", "b"])

    def test_what_may_repeat_does_so_without_a_finding(self):
        document, findings = parse(invoice(
            "<cbc:Note>a</cbc:Note><cbc:Note>b</cbc:Note>"
            "<cac:AccountingSupplierParty><cac:Party>"
            '<cac:PartyIdentification><cbc:ID schemeID="0088">1</cbc:ID></cac:PartyIdentification>'
            "<cac:PartyIdentification><cbc:ID>2</cbc:ID></cac:PartyIdentification>"
            "</cac:Party></cac:AccountingSupplierParty>"
            "<cac:PaymentMeans><cbc:PaymentMeansCode>30</cbc:PaymentMeansCode></cac:PaymentMeans>"
            "<cac:PaymentMeans><cbc:PaymentMeansCode>58</cbc:PaymentMeansCode></cac:PaymentMeans>"))
        self.assertEqual(findings, [])
        self.assertEqual([v.text for v in document.values("BT-29")], ["1", "2"])
        self.assertEqual([g.text("BT-81") for g in document.all("BG-16")], ["30", "58"])

    def test_an_attribute_the_standard_has_no_place_for_is_kept_and_named(self):
        document, findings = parse(invoice(
            '<cbc:ID schemeID="X">1</cbc:ID>'
            '<cbc:DocumentCurrencyCode listID="ISO4217">EUR</cbc:DocumentCurrencyCode>'
            '<cbc:IssueDate xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
            'xsi:nil="false">2026-10-02</cbc:IssueDate>'))
        self.assertEqual(codes(findings), [
            ("warning", "UNHELD", "/Invoice/cbc:ID/@schemeID"),
            ("warning", "UNHELD", "/Invoice/cbc:DocumentCurrencyCode/@listID"),
            ("warning", "UNHELD",
             "/Invoice/cbc:IssueDate/@{http://www.w3.org/2001/XMLSchema-instance}nil")])
        self.assertEqual(document.term("BT-1").attributes, {"schemeID": "X"})
        self.assertEqual(document.term("BT-5").attributes, {"listID": "ISO4217"})
        self.assertIn("kept with the value", findings[0].text)
        self.assertEqual(document.term("BT-2").attributes, {})
        self.assertIn("not held", findings[2].text)

    def test_a_number_that_is_not_a_decimal_is_an_error_and_its_text_is_kept(self):
        document, findings = parse(invoice(
            '<cac:LegalMonetaryTotal><cbc:PayableAmount currencyID="EUR">1,190.00'
            '</cbc:PayableAmount><cbc:PrepaidAmount currencyID="EUR">1e2</cbc:PrepaidAmount>'
            "</cac:LegalMonetaryTotal>"))
        self.assertEqual(codes(findings), [
            ("error", "NOT-DECIMAL", "/Invoice/cac:LegalMonetaryTotal/cbc:PayableAmount"),
            ("error", "NOT-DECIMAL", "/Invoice/cac:LegalMonetaryTotal/cbc:PrepaidAmount")])
        self.assertIn("'1,190.00' is not a decimal number", findings[0].text)
        self.assertEqual(document.text("BT-115"), "1,190.00")
        self.assertIsNone(document.term("BT-115").number)

    def test_text_that_is_not_a_number_is_no_finding_where_no_number_is_meant(self):
        _document, findings = parse(invoice("<cbc:ID>1,190.00</cbc:ID>"))
        self.assertEqual(findings, [])

    def test_text_among_elements_and_elements_in_text_are_said(self):
        _document, findings = parse(invoice(
            "stray<cbc:ID>1<cbc:Note>x</cbc:Note></cbc:ID>"
            "<cac:PaymentTerms><cbc:Note>a</cbc:Note>tail</cac:PaymentTerms>"))
        self.assertEqual(codes(findings), [
            ("warning", "TEXT", "/Invoice"),
            ("error", "STRUCTURE", "/Invoice/cbc:ID"),
            ("warning", "TEXT", "/Invoice/cac:PaymentTerms")])

    def test_white_space_among_elements_is_nothing(self):
        _document, findings = parse(invoice("\n  <cbc:ID>1</cbc:ID>\n  "))
        self.assertEqual(findings, [])

    def test_a_group_with_nothing_in_it_is_still_there(self):
        """That it is there is something a rule can ask, and the published
        rules do: an empty VAT breakdown is a VAT breakdown to BR-CO-18."""
        document, findings = parse(invoice(
            "<cac:PaymentMeans></cac:PaymentMeans><cac:AllowanceCharge><cbc:ChargeIndicator>"
            "false</cbc:ChargeIndicator></cac:AllowanceCharge><cac:TaxTotal><cac:TaxSubtotal/>"
            "<cac:TaxSubtotal/></cac:TaxTotal><cac:InvoiceLine/>"))
        self.assertEqual(findings, [])
        self.assertEqual([len(document.all(g)) for g in ("BG-16", "BG-20", "BG-21", "BG-23",
                                                         "BG-25")], [1, 1, 0, 2, 1])
        self.assertTrue(document.all("BG-25")[0].empty())
        self.assertEqual(parse(write(document))[0], document)

    def test_a_group_that_occurs_once_is_there_by_its_terms_or_by_being_written_empty(self):
        document, _findings = parse(invoice(
            "<cac:InvoicePeriod/><cac:AccountingSupplierParty><cac:Party><cac:PostalAddress>"
            "<cbc:CityName>Hamburg</cbc:CityName></cac:PostalAddress></cac:Party>"
            "</cac:AccountingSupplierParty><cac:InvoiceLine><cac:InvoicePeriod>"
            "<cbc:StartDate>2026-10-01</cbc:StartDate></cac:InvoicePeriod><cac:Price/>"
            "</cac:InvoiceLine>"))
        line, = document.all("BG-25")
        self.assertEqual({g: document.has(g) for g in ("BG-4", "BG-5", "BG-6", "BG-7", "BG-14",
                                                       "BG-22", "BG-25", "BG-23")},
                         {"BG-4": True, "BG-5": True, "BG-6": False, "BG-7": False, "BG-14": True,
                          "BG-22": False, "BG-25": True, "BG-23": False})
        self.assertEqual({g: line.has(g) for g in ("BG-26", "BG-29", "BG-31", "BG-30")},
                         {"BG-26": True, "BG-29": True, "BG-31": False, "BG-30": False})
        # Only what held nothing is noted; the rest is there because its terms are.
        self.assertEqual((document.present, line.present), ({"BG-14"}, {"BG-29"}))
        self.assertEqual(parse(write(document))[0], document)
        self.assertIn(b"<cac:InvoicePeriod></cac:InvoicePeriod>", write(document))


class WhatTheBindingFixes(unittest.TestCase):
    def test_a_charge_indicator_written_as_a_number_is_read_and_said(self):
        document, findings = parse(invoice(
            "<cac:AllowanceCharge><cbc:ChargeIndicator>1</cbc:ChargeIndicator>"
            '<cbc:Amount currencyID="EUR">5.00</cbc:Amount></cac:AllowanceCharge>'
            "<cac:AllowanceCharge><cbc:ChargeIndicator>0</cbc:ChargeIndicator>"
            '<cbc:Amount currencyID="EUR">7.00</cbc:Amount></cac:AllowanceCharge>'))
        self.assertEqual(document.all("BG-21")[0].text("BT-99"), "5.00")
        self.assertEqual(document.all("BG-20")[0].text("BT-92"), "7.00")
        self.assertEqual(codes(findings), [
            ("warning", "FIXED", "/Invoice/cac:AllowanceCharge[1]/cbc:ChargeIndicator"),
            ("warning", "FIXED", "/Invoice/cac:AllowanceCharge[2]/cbc:ChargeIndicator")])
        self.assertIn("is '1' here; it is read as 'true'", findings[0].text)

    def test_an_allowance_or_charge_that_says_neither_is_not_held(self):
        document, findings = parse(invoice(
            '<cac:AllowanceCharge><cbc:Amount currencyID="EUR">5.00</cbc:Amount>'
            "</cac:AllowanceCharge><cac:AllowanceCharge><cbc:ChargeIndicator>yes"
            "</cbc:ChargeIndicator></cac:AllowanceCharge>"))
        self.assertEqual(codes(findings), [("warning", "UNHELD", "/Invoice/cac:AllowanceCharge[1]"),
                                           ("warning", "UNHELD", "/Invoice/cac:AllowanceCharge[2]")])
        self.assertEqual(document.all("BG-20") + document.all("BG-21"), [])

    def test_a_tax_scheme_other_than_vat_on_a_category_is_said(self):
        _document, findings = parse(invoice(
            "<cac:TaxTotal><cac:TaxSubtotal><cac:TaxCategory><cbc:ID>S</cbc:ID>"
            "<cac:TaxScheme><cbc:ID>GST</cbc:ID></cac:TaxScheme></cac:TaxCategory>"
            "</cac:TaxSubtotal></cac:TaxTotal>"))
        self.assertEqual(codes(findings), [(
            "warning", "FIXED",
            "/Invoice/cac:TaxTotal/cac:TaxSubtotal/cac:TaxCategory/cac:TaxScheme/cbc:ID")])

    def test_vat_is_vat_in_any_case_and_keeps_how_it_was_written(self):
        document, findings = parse(invoice(
            "<cac:AccountingSupplierParty><cac:Party>"
            "<cac:PartyTaxScheme><cbc:CompanyID>DE1</cbc:CompanyID><cac:TaxScheme>"
            "<cbc:ID> vat </cbc:ID></cac:TaxScheme></cac:PartyTaxScheme>"
            "</cac:Party></cac:AccountingSupplierParty>"))
        self.assertEqual(findings, [])
        self.assertEqual(document.term("BT-31").attributes, {"TaxScheme/ID": " vat "})
        self.assertIsNone(document.term("BT-32"))

    def test_a_buyers_registration_that_is_not_vat_is_held_as_its_vat_identifier_and_said(self):
        document, findings = parse(invoice(
            "<cac:AccountingCustomerParty><cac:Party>"
            "<cac:PartyTaxScheme><cbc:CompanyID>123</cbc:CompanyID><cac:TaxScheme>"
            "<cbc:ID>FC</cbc:ID></cac:TaxScheme></cac:PartyTaxScheme>"
            "</cac:Party></cac:AccountingCustomerParty>"))
        self.assertEqual(codes(findings), [(
            "warning", "UNHELD", "/Invoice/cac:AccountingCustomerParty/cac:Party/cac:PartyTaxScheme")])
        self.assertEqual(document.term("BT-48").attributes, {"TaxScheme/ID": "FC"})

    def test_a_document_reference_is_the_invoiced_object_only_with_type_130(self):
        document, findings = parse(invoice(
            '<cac:AdditionalDocumentReference><cbc:ID schemeID="ABZ">OBJ</cbc:ID>'
            "<cbc:DocumentTypeCode>130</cbc:DocumentTypeCode></cac:AdditionalDocumentReference>"
            "<cac:AdditionalDocumentReference><cbc:ID>ATT</cbc:ID>"
            "<cbc:DocumentDescription>Timesheet</cbc:DocumentDescription><cac:Attachment>"
            '<cbc:EmbeddedDocumentBinaryObject mimeCode="text/csv" filename="t.csv">YQ=='
            "</cbc:EmbeddedDocumentBinaryObject><cac:ExternalReference><cbc:URI>https://x.example/t"
            "</cbc:URI></cac:ExternalReference></cac:Attachment></cac:AdditionalDocumentReference>"
            "<cac:AdditionalDocumentReference><cbc:ID>PRJ</cbc:ID>"
            "<cbc:DocumentTypeCode>50</cbc:DocumentTypeCode></cac:AdditionalDocumentReference>"))
        self.assertEqual((document.text("BT-18"), document.text("BT-18-1")), ("OBJ", "ABZ"))
        first, second = document.all("BG-24")
        self.assertEqual({t: first.text(t) for t in ("BT-122", "BT-123", "BT-124", "BT-125",
                                                     "BT-125-1", "BT-125-2")},
                         {"BT-122": "ATT", "BT-123": "Timesheet", "BT-124": "https://x.example/t",
                          "BT-125": "YQ==", "BT-125-1": "text/csv", "BT-125-2": "t.csv"})
        # In an invoice, type 50 is not the project: it is a supporting
        # document whose type the standard has no term for.
        self.assertEqual(second.text("BT-122"), "PRJ")
        self.assertIsNone(document.term("BT-11"))
        self.assertEqual(codes(findings), [(
            "warning", "UNHELD", "/Invoice/cac:AdditionalDocumentReference[3]/cbc:DocumentTypeCode")])


class TheVatTotalInTwoCurrencies(unittest.TestCase):
    TOTALS = ("<cbc:DocumentCurrencyCode>EUR</cbc:DocumentCurrencyCode>"
              "<cbc:TaxCurrencyCode>%s</cbc:TaxCurrencyCode>"
              '<cac:TaxTotal><cbc:TaxAmount currencyID="EUR">190.00</cbc:TaxAmount>'
              '<cac:TaxSubtotal><cbc:TaxAmount currencyID="EUR">190.00</cbc:TaxAmount>'
              "</cac:TaxSubtotal></cac:TaxTotal>"
              '<cac:TaxTotal><cbc:TaxAmount currencyID="%s">1650.00</cbc:TaxAmount></cac:TaxTotal>')

    def test_the_second_total_in_the_accounting_currency_is_its_own_term(self):
        document, findings = parse(invoice(self.TOTALS % ("SEK", "SEK")))
        self.assertEqual(findings, [])
        self.assertEqual((document.text("BT-110"), document.text("BT-111")), ("190.00", "1650.00"))
        self.assertEqual(document.term("BT-111").attributes, {"currencyID": "SEK"})
        self.assertEqual(len(document.all("BG-23")), 1)

    def test_a_second_total_with_a_breakdown_of_its_own_is_a_repeat_whatever_its_currency(self):
        document, findings = parse(invoice((self.TOTALS % ("SEK", "SEK")).replace(
            "1650.00</cbc:TaxAmount>", "1650.00</cbc:TaxAmount><cac:TaxSubtotal>"
            '<cbc:TaxAmount currencyID="SEK">1650.00</cbc:TaxAmount></cac:TaxSubtotal>')))
        self.assertEqual(codes(findings), [("error", "REPEATED", "/Invoice/cac:TaxTotal[2]")])
        self.assertIsNone(document.term("BT-111"))
        self.assertEqual(len(document.all("BG-23")), 2)

    def test_without_an_accounting_currency_there_is_no_second_total(self):
        document, _findings = parse(invoice(
            (self.TOTALS % ("SEK", "SEK")).replace("<cbc:TaxCurrencyCode>SEK</cbc:TaxCurrencyCode>", "")))
        self.assertIsNone(document.term("BT-111"))
        document, _findings = parse(invoice(self.TOTALS % ("EUR", "EUR")))
        self.assertIsNone(document.term("BT-111"))
        # Nor is a total that names no currency one, where none is the accounting currency.
        document, _findings = parse(invoice(
            "<cbc:DocumentCurrencyCode>EUR</cbc:DocumentCurrencyCode>"
            "<cac:TaxTotal><cbc:TaxAmount>190.00</cbc:TaxAmount></cac:TaxTotal>"))
        self.assertEqual((document.text("BT-110"), document.term("BT-111")), ("190.00", None))

    def test_a_second_total_in_any_other_currency_is_a_repeat_of_the_first(self):
        document, findings = parse(invoice(self.TOTALS % ("SEK", "NOK")))
        self.assertEqual(codes(findings), [("error", "REPEATED", "/Invoice/cac:TaxTotal[2]")])
        self.assertEqual([v.text for v in document.values("BT-110")], ["190.00", "1650.00"])
        self.assertIsNone(document.term("BT-111"))


class TheCreditorIdentifier(unittest.TestCase):
    def test_it_is_read_from_the_payee_as_from_the_seller_whatever_the_case_of_sepa(self):
        document, findings = parse(invoice(
            "<cac:PayeeParty>"
            '<cac:PartyIdentification><cbc:ID schemeID="sepa">CRED</cbc:ID></cac:PartyIdentification>'
            '<cac:PartyIdentification><cbc:ID schemeID="0088">PAYEE</cbc:ID></cac:PartyIdentification>'
            "<cac:PartyName><cbc:Name>Factor</cbc:Name></cac:PartyName></cac:PayeeParty>"))
        self.assertEqual(findings, [])
        self.assertEqual((document.text("BT-90"), document.text("BT-60"), document.text("BT-59")),
                         ("CRED", "PAYEE", "Factor"))


if __name__ == "__main__":
    unittest.main()
