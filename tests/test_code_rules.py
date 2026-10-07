"""The code list rules of EN 16931, BR-CL-01 to BR-CL-26."""
import os
import unittest

import mockeinvoice
from mockeinvoice.rules import REGISTRY, published, run
from mockeinvoice.rules.codelists import LISTS
from mockeinvoice.rules.en16931_codes import AMOUNTS, listed
from mockeinvoice.ubl import parse

from .test_reading import invoice
from .test_rules import CREDIT_NOTE, INVOICE, changed

CODE_RULES = sorted(i for i in published.EN16931 if i.startswith("BR-CL-"))


def codes(text: str) -> list:
    """The code list rules a document fails, with where."""
    document, _findings = parse(text)
    return [(f.code, f.path) for f in run(document, "en16931") if f.code in CODE_RULES]


def failing(text: str) -> list:
    return sorted({code for code, _path in codes(text)})


class TheLists(unittest.TestCase):
    def test_there_are_23_rules_all_fatal_all_built_each_with_its_list(self):
        self.assertEqual(len(CODE_RULES), 23)
        self.assertNotIn("BR-CL-02", CODE_RULES)
        self.assertLessEqual(set(CODE_RULES), set(REGISTRY["en16931"]))
        self.assertEqual(sorted(LISTS), CODE_RULES)
        self.assertTrue(all(published.EN16931[i] == "fatal" for i in CODE_RULES))

    def test_the_lists_are_the_sizes_the_published_tests_have(self):
        sizes = {rule: [len(codes.split()) for codes in lists] for rule, lists in LISTS.items()
                 if rule != "BR-CL-24"}
        self.assertEqual(sizes["BR-CL-01"], [50, 13])       # invoices, credit notes
        self.assertEqual(sizes["BR-CL-10"], [243, 1])       # ICD, and SEPA
        self.assertEqual(sizes["BR-CL-17"], [10])
        self.assertEqual(sizes["BR-CL-06"], [3])
        self.assertEqual(sizes["BR-CL-23"], [2162])
        self.assertEqual(LISTS["BR-CL-04"], LISTS["BR-CL-03"])
        self.assertEqual(LISTS["BR-CL-14"], LISTS["BR-CL-15"])
        self.assertEqual(len(LISTS["BR-CL-24"]), 6)

    def test_a_list_is_kept_as_the_test_has_it_with_a_space_at_each_end_and_one_between(self):
        for rule, lists in LISTS.items():
            if rule == "BR-CL-24":
                continue
            for codes in lists:
                self.assertTrue(codes.startswith(" ") and codes.endswith(" "), rule)
                # Two spaces together would let an empty code through.
                self.assertNotIn("  ", codes, rule)

    def test_the_lists_say_whose_they_are_and_their_licence_is_beside_them(self):
        from mockeinvoice.rules import codelists
        self.assertIn("European Union Public\nLicence 1.2", codelists.__doc__)
        self.assertIn("Do not edit by hand", codelists.__doc__)
        beside = os.path.join(os.path.dirname(codelists.__file__), "LICENSE-EUPL-1.2.txt")
        with open(beside, encoding="utf-8") as handle:
            self.assertIn("EUROPEAN UNION PUBLIC LICENCE v. 1.2", handle.read())
        self.assertTrue(mockeinvoice.__file__)

    def test_how_a_code_is_compared(self):
        self.assertTrue(listed("EUR", " EUR USD "))
        self.assertTrue(listed("  EUR\n", " EUR USD "))
        for text in ("eur", "EU", "EUR USD", "", " ", "EUR "):
            self.assertFalse(listed(text, " EUR USD "), repr(text))


class EachRuleFails(unittest.TestCase):
    """The invoice all of them pass, with one code made one that is not listed."""
    CASES = {
        "BR-CL-01": ("<cbc:InvoiceTypeCode>380", "<cbc:InvoiceTypeCode>381"),
        "BR-CL-03": ('<cbc:PayableAmount currencyID="EUR">', '<cbc:PayableAmount currencyID="EUX">'),
        "BR-CL-04": ("<cbc:DocumentCurrencyCode>EUR", "<cbc:DocumentCurrencyCode>EUX"),
        "BR-CL-05": ("<cbc:BuyerReference>", "<cbc:TaxCurrencyCode>EUX</cbc:TaxCurrencyCode>"
                     "<cbc:BuyerReference>"),
        "BR-CL-06": ("<cac:OrderReference>", "<cac:InvoicePeriod><cbc:DescriptionCode>5"
                     "</cbc:DescriptionCode></cac:InvoicePeriod><cac:OrderReference>"),
        "BR-CL-07": ("<cac:AccountingSupplierParty>", '<cac:AdditionalDocumentReference><cbc:ID '
                     'schemeID="XX9">M-1</cbc:ID><cbc:DocumentTypeCode>130</cbc:DocumentTypeCode>'
                     "</cac:AdditionalDocumentReference><cac:AccountingSupplierParty>"),
        "BR-CL-08": ("<cbc:Note>#AAI#", "<cbc:Note>#QQQ#"),
        "BR-CL-10": ('<cbc:ID schemeID="0088">4012345000009</cbc:ID>',
                     '<cbc:ID schemeID="0001">4012345000009</cbc:ID>'),
        "BR-CL-11": ('<cbc:CompanyID schemeID="0204">', '<cbc:CompanyID schemeID="9999">'),
        "BR-CL-13": (' listID="STI"', ' listID="CPV"'),
        "BR-CL-14": ("<cbc:PostalZone>10115</cbc:PostalZone>\n        <cac:Country>\n          "
                     "<cbc:IdentificationCode>DE", "<cbc:PostalZone>10115</cbc:PostalZone>\n        "
                     "<cac:Country>\n          <cbc:IdentificationCode>DEU"),
        "BR-CL-15": ("</cac:SellersItemIdentification>", "</cac:SellersItemIdentification>"
                     "<cac:OriginCountry><cbc:IdentificationCode>EU</cbc:IdentificationCode>"
                     "</cac:OriginCountry>"),
        "BR-CL-16": ('<cbc:PaymentMeansCode name="Credit transfer">30',
                     '<cbc:PaymentMeansCode name="Credit transfer">99'),
        "BR-CL-17": ("<cbc:ID>S</cbc:ID>\n        <cbc:Percent>19</cbc:Percent>\n        "
                     "<cac:TaxScheme>\n          <cbc:ID>VAT</cbc:ID>\n        </cac:TaxScheme>\n"
                     "      </cac:TaxCategory>\n    </cac:TaxSubtotal>",
                     "<cbc:ID>s</cbc:ID>\n        <cbc:Percent>19</cbc:Percent>\n        "
                     "<cac:TaxScheme>\n          <cbc:ID>VAT</cbc:ID>\n        </cac:TaxScheme>\n"
                     "      </cac:TaxCategory>\n    </cac:TaxSubtotal>"),
        "BR-CL-18": ("<cac:ClassifiedTaxCategory>\n        <cbc:ID>S</cbc:ID>",
                     "<cac:ClassifiedTaxCategory>\n        <cbc:ID>s</cbc:ID>"),
        "BR-CL-19": ("<cbc:AllowanceChargeReasonCode>95", "<cbc:AllowanceChargeReasonCode>96"),
        "BR-CL-20": ("<cbc:AllowanceChargeReason>Freight</cbc:AllowanceChargeReason>",
                     "<cbc:AllowanceChargeReasonCode>95</cbc:AllowanceChargeReasonCode>"
                     "<cbc:AllowanceChargeReason>Freight</cbc:AllowanceChargeReason>"),
        "BR-CL-21": ("</cac:SellersItemIdentification>", "</cac:SellersItemIdentification>"
                     '<cac:StandardItemIdentification><cbc:ID schemeID="GTIN">4012345000016'
                     "</cbc:ID></cac:StandardItemIdentification>"),
        "BR-CL-22": ("<cbc:Percent>19</cbc:Percent>\n        <cac:TaxScheme>\n          <cbc:ID>VAT"
                     "</cbc:ID>\n        </cac:TaxScheme>\n      </cac:TaxCategory>\n    "
                     "</cac:TaxSubtotal>",
                     "<cbc:Percent>19</cbc:Percent><cbc:TaxExemptionReasonCode>VATEX-EU-0"
                     "</cbc:TaxExemptionReasonCode>\n        <cac:TaxScheme>\n          <cbc:ID>VAT"
                     "</cbc:ID>\n        </cac:TaxScheme>\n      </cac:TaxCategory>\n    "
                     "</cac:TaxSubtotal>"),
        "BR-CL-23": ('unitCode="HUR"', 'unitCode="hour"'),
        "BR-CL-24": ("<cac:AccountingSupplierParty>", "<cac:AdditionalDocumentReference><cbc:ID>T-1"
                     '</cbc:ID><cac:Attachment><cbc:EmbeddedDocumentBinaryObject mimeCode="text/plain"'
                     ' filename="t.txt">eA==</cbc:EmbeddedDocumentBinaryObject></cac:Attachment>'
                     "</cac:AdditionalDocumentReference><cac:AccountingSupplierParty>"),
        "BR-CL-25": ('<cbc:EndpointID schemeID="0088">4098765000003',
                     '<cbc:EndpointID schemeID="GLN">4098765000003'),
        "BR-CL-26": ("</cbc:ActualDeliveryDate>", "</cbc:ActualDeliveryDate><cac:DeliveryLocation>"
                     '<cbc:ID schemeID="GLN">4098765000011</cbc:ID></cac:DeliveryLocation>'),
    }
    # What else must fail with a change: a currency that is no longer the VAT
    # total's, a VAT accounting currency with no total in it, the standard
    # rated category's own rules where a code is no longer its code, and its
    # rule that it has no reason for exemption.
    BESIDE = {"BR-CL-04": ["BR-CO-15"], "BR-CL-05": ["BR-53"], "BR-CL-17": ["BR-S-01"],
              "BR-CL-18": ["BR-S-08"], "BR-CL-22": ["BR-S-10"]}

    def test_every_rule_has_a_case(self):
        self.assertEqual(sorted(self.CASES), CODE_RULES)

    def test_the_documents_they_are_changed_from_fail_none(self):
        self.assertEqual(codes(INVOICE), [])
        self.assertEqual(codes(CREDIT_NOTE), [])

    def test_each_change_fails_its_rule_and_no_other_code_list_rule(self):
        for identifier, pairs in self.CASES.items():
            with self.subTest(rule=identifier):
                self.assertEqual(failing(changed(INVOICE, *pairs)), [identifier])

    def test_and_a_listed_code_in_its_place_fails_nothing(self):
        good = {"BR-CL-01": "<cbc:InvoiceTypeCode>384", "BR-CL-03": 'currencyID="EUR">',
                "BR-CL-04": "<cbc:DocumentCurrencyCode>EUR", "BR-CL-05": "<cbc:TaxCurrencyCode>USD",
                "BR-CL-06": "<cbc:DescriptionCode>35", "BR-CL-07": 'schemeID="ABZ"',
                "BR-CL-08": "<cbc:Note>#ZZZ#", "BR-CL-10": 'schemeID="0060"',
                "BR-CL-11": 'schemeID="0002"', "BR-CL-13": 'listID="ZZZ"',
                "BR-CL-14": "<cbc:IdentificationCode>FR", "BR-CL-15": "<cbc:IdentificationCode>CN",
                "BR-CL-16": '">58', "BR-CL-19": "<cbc:AllowanceChargeReasonCode>100",
                "BR-CL-20": "<cbc:AllowanceChargeReasonCode>FC", "BR-CL-21": 'schemeID="0160"',
                "BR-CL-22": "<cbc:TaxExemptionReasonCode>vatex-eu-132",
                "BR-CL-23": 'unitCode="XPP"', "BR-CL-24": 'mimeCode="text/csv"',
                "BR-CL-25": 'schemeID="EM"', "BR-CL-26": 'schemeID="0088"'}
        bad = {"BR-CL-01": "<cbc:InvoiceTypeCode>381", "BR-CL-03": 'currencyID="EUX">',
               "BR-CL-04": "<cbc:DocumentCurrencyCode>EUX", "BR-CL-05": "<cbc:TaxCurrencyCode>EUX",
               "BR-CL-06": "<cbc:DescriptionCode>5", "BR-CL-07": 'schemeID="XX9"',
               "BR-CL-08": "<cbc:Note>#QQQ#", "BR-CL-10": 'schemeID="0001"',
               "BR-CL-11": 'schemeID="9999"', "BR-CL-13": 'listID="CPV"',
               "BR-CL-14": "<cbc:IdentificationCode>DEU", "BR-CL-15": "<cbc:IdentificationCode>EU",
               "BR-CL-16": '">99', "BR-CL-19": "<cbc:AllowanceChargeReasonCode>96",
               "BR-CL-20": "<cbc:AllowanceChargeReasonCode>95", "BR-CL-21": 'schemeID="GTIN"',
               "BR-CL-22": "<cbc:TaxExemptionReasonCode>VATEX-EU-0",
               "BR-CL-23": 'unitCode="hour"', "BR-CL-24": 'mimeCode="text/plain"',
               "BR-CL-25": 'schemeID="GLN"', "BR-CL-26": 'schemeID="GLN"'}
        self.assertEqual(sorted(set(good) | {"BR-CL-17", "BR-CL-18"}), CODE_RULES)
        for identifier, pairs in self.CASES.items():
            if identifier not in good:
                continue
            with self.subTest(rule=identifier):
                text = changed(INVOICE, *pairs)
                self.assertEqual(failing(changed(text, bad[identifier], good[identifier])), [])

    def test_what_fails_beside_them_among_all_the_rules(self):
        for identifier, pairs in self.CASES.items():
            with self.subTest(rule=identifier):
                document, _findings = parse(changed(INVOICE, *pairs))
                fired = sorted({f.code for f in run(document, "en16931")})
                self.assertEqual(fired, sorted([identifier] + self.BESIDE.get(identifier, [])))

    def test_where_the_code_is_says_which_of_several(self):
        self.assertEqual(codes(changed(INVOICE, *self.CASES["BR-CL-23"])),
                         [("BR-CL-23", "BG-25[2]/BT-129")])
        self.assertEqual(codes(changed(INVOICE, *self.CASES["BR-CL-03"])),
                         [("BR-CL-03", "BT-115")])
        self.assertEqual(codes(changed(INVOICE, *self.CASES["BR-CL-08"])),
                         [("BR-CL-08", "BG-1[1]")])
        self.assertEqual(codes(changed(INVOICE, *self.CASES["BR-CL-17"])),
                         [("BR-CL-17", "BG-23/BT-118")])


class WhatTheTestsSayExactly(unittest.TestCase):
    def test_a_credit_note_has_its_own_type_codes(self):
        self.assertEqual(failing(changed(CREDIT_NOTE, "<cbc:CreditNoteTypeCode>381",
                                         "<cbc:CreditNoteTypeCode>380")), ["BR-CL-01"])
        # 81 is in both lists.
        self.assertEqual(failing(changed(CREDIT_NOTE, "<cbc:CreditNoteTypeCode>381",
                                         "<cbc:CreditNoteTypeCode>81")), [])
        self.assertEqual(failing(changed(INVOICE, "<cbc:InvoiceTypeCode>380",
                                         "<cbc:InvoiceTypeCode>81")), [])

    def test_every_amount_is_asked_its_currency_and_one_without_fails(self):
        self.assertEqual(len(AMOUNTS), 24)
        document, _findings = parse(INVOICE.replace('currencyID="EUR"', 'currencyID="EUX"'))
        asked = {f.path.split("/")[-1] for f in run(document, "en16931") if f.code == "BR-CL-03"}
        # Every amount the invoice has: the allowance's and charge's amounts
        # and base, the totals, the VAT amounts, and each line's.
        self.assertEqual(asked, {"BT-92", "BT-93", "BT-99", "BT-106", "BT-107", "BT-108", "BT-109",
                                 "BT-110", "BT-112", "BT-115", "BT-116", "BT-117", "BT-131",
                                 "BT-136", "BT-146"})
        self.assertEqual(failing(changed(INVOICE, '<cbc:PayableAmount currencyID="EUR">',
                                         "<cbc:PayableAmount>")), ["BR-CL-03"])
        self.assertEqual(failing(changed(INVOICE, '<cbc:PayableAmount currencyID="EUR">',
                                         '<cbc:PayableAmount currencyID=" EUR ">')), [])

    def test_a_qualifier_that_is_not_there_is_not_asked(self):
        for old in (' schemeID="0088"', ' schemeID="0204"', ' listID="STI"', ' unitCode="HUR"'):
            self.assertEqual(failing(INVOICE.replace(old, "")), [], old)
        # A price's base quantity has a unit too.
        self.assertEqual(codes(changed(INVOICE, '<cbc:BaseQuantity unitCode="C62">',
                                       '<cbc:BaseQuantity unitCode="each">')),
                         [("BR-CL-23", "BG-25[1]/BT-149")])
        # There and empty, it is asked and nothing is not a code.
        self.assertEqual(failing(changed(INVOICE, ' unitCode="HUR"', ' unitCode=""')), ["BR-CL-23"])

    def test_a_code_is_trimmed_and_its_case_matters_but_for_one_list(self):
        self.assertEqual(failing(changed(INVOICE, "<cbc:DocumentCurrencyCode>EUR",
                                         "<cbc:DocumentCurrencyCode> EUR\n")), [])
        self.assertEqual(failing(changed(INVOICE, "<cbc:DocumentCurrencyCode>EUR",
                                         "<cbc:DocumentCurrencyCode>eur")), ["BR-CL-04"])
        # Two codes are not a code, though each is in the list.
        self.assertEqual(failing(changed(INVOICE, "<cbc:DocumentCurrencyCode>EUR",
                                         "<cbc:DocumentCurrencyCode>EUR USD")), ["BR-CL-04"])

    def test_sepa_is_a_scheme_for_the_seller_and_the_payee_and_not_the_buyer(self):
        identifier = ('<cac:PartyIdentification><cbc:ID schemeID="%s">DE98ZZZ09999999999</cbc:ID>'
                      "</cac:PartyIdentification>")
        self.assertEqual(codes(INVOICE), [])       # the seller's is in the sample
        payee = changed(INVOICE, "<cac:Delivery>", "<cac:PayeeParty>%s<cac:PartyName><cbc:Name>"
                        "Factor AG</cbc:Name></cac:PartyName></cac:PayeeParty><cac:Delivery>"
                        % (identifier % "SEPA").replace("DE98ZZZ0", "DE98ZZZ1"))
        self.assertEqual(codes(payee), [])
        buyer = changed(INVOICE, '4098765000003</cbc:EndpointID>',
                        "4098765000003</cbc:EndpointID>" + identifier % "SEPA")
        self.assertEqual(codes(buyer), [("BR-CL-10", "BT-46")])
        # In small letters it is the creditor identifier to the reader and no
        # scheme to the rule.
        self.assertEqual(codes(changed(INVOICE, 'schemeID="SEPA"', 'schemeID="sepa"')),
                         [("BR-CL-10", "BT-90")])

    def test_a_notes_subject_is_whatever_is_between_its_first_two_hashes(self):
        def note(text):
            return failing(invoice("<cbc:Note>%s</cbc:Note>" % text))
        self.assertEqual(note("#AAI#text"), [])
        self.assertEqual(note("#QQQ#text"), ["BR-CL-08"])
        self.assertEqual(note("no subject"), [])
        # Not at the front, where the reader does not take it for a subject.
        self.assertEqual(note("see #QQQ# below"), ["BR-CL-08"])
        self.assertEqual(note("see #AAI# below"), [])
        # Only three characters are asked.
        self.assertEqual(note("#QQ#text"), [])
        self.assertEqual(note("#QQQQ#text"), [])
        self.assertEqual(note("a # b"), [])
        # Looked for in the list's text, so part of two codes will do.
        self.assertEqual(note("# AA#text"), [])
        self.assertEqual(note("#A A#text"), [])
        self.assertEqual(note("#Q Q#text"), ["BR-CL-08"])
        self.assertEqual(note("#aai#text"), ["BR-CL-08"])

    def test_each_note_is_asked(self):
        self.assertEqual(codes(invoice("<cbc:Note>#AAI#a</cbc:Note><cbc:Note>#QQQ#b</cbc:Note>")),
                         [("BR-CL-08", "BG-1[2]")])

    def test_a_mime_type_is_compared_as_written(self):
        def attachment(mime):
            return failing(invoice(
                "<cac:AdditionalDocumentReference><cbc:ID>T-1</cbc:ID><cac:Attachment>"
                "<cbc:EmbeddedDocumentBinaryObject%s>eA==</cbc:EmbeddedDocumentBinaryObject>"
                "</cac:Attachment></cac:AdditionalDocumentReference>" % mime))
        for mime in LISTS["BR-CL-24"]:
            self.assertEqual(attachment(' mimeCode="%s"' % mime), [], mime)
        self.assertEqual(attachment(' mimeCode=" application/pdf"'), ["BR-CL-24"])
        self.assertEqual(attachment(' mimeCode="Application/PDF"'), ["BR-CL-24"])
        self.assertEqual(attachment(""), [])

    def test_a_vat_exemption_reason_code_may_be_in_either_case(self):
        def reason(code):
            return failing(invoice(
                "<cac:TaxTotal><cac:TaxSubtotal><cac:TaxCategory><cbc:ID>E</cbc:ID>"
                "<cbc:TaxExemptionReasonCode>%s</cbc:TaxExemptionReasonCode></cac:TaxCategory>"
                "</cac:TaxSubtotal></cac:TaxTotal>" % code))
        self.assertEqual(reason("VATEX-EU-132"), [])
        self.assertEqual(reason("vatex-eu-132"), [])
        self.assertEqual(reason(" Vatex-EU-O "), [])
        self.assertEqual(reason("VATEX-EU-133"), ["BR-CL-22"])

    def test_the_category_codes_of_a_line_and_of_the_rest_are_two_rules(self):
        line = "<cac:InvoiceLine><cac:Item><cac:ClassifiedTaxCategory><cbc:ID>X</cbc:ID>" \
               "</cac:ClassifiedTaxCategory></cac:Item></cac:InvoiceLine>"
        self.assertEqual(failing(invoice(line)), ["BR-CL-18"])
        for indicator, term in (("false", "BT-95"), ("true", "BT-102")):
            text = invoice("<cac:AllowanceCharge><cbc:ChargeIndicator>%s</cbc:ChargeIndicator>"
                           "<cac:TaxCategory><cbc:ID>X</cbc:ID></cac:TaxCategory>"
                           "</cac:AllowanceCharge>" % indicator)
            self.assertEqual(codes(text), [("BR-CL-17", "%s/%s" % (
                "BG-20" if term == "BT-95" else "BG-21", term))])
        for code in LISTS["BR-CL-17"][0].split():
            self.assertEqual(failing(invoice(line.replace("X", code))), [], code)

    def test_reason_codes_of_allowances_and_charges_are_two_lists_on_the_document_and_a_line(self):
        def reasons(indicator, code, on_line):
            inside = ("<cac:AllowanceCharge><cbc:ChargeIndicator>%s</cbc:ChargeIndicator>"
                      "<cbc:AllowanceChargeReasonCode>%s</cbc:AllowanceChargeReasonCode>"
                      "</cac:AllowanceCharge>" % (indicator, code))
            return failing(invoice("<cac:InvoiceLine>%s</cac:InvoiceLine>" % inside if on_line
                                   else inside))
        for on_line in (False, True):
            self.assertEqual(reasons("false", "95", on_line), [])
            self.assertEqual(reasons("false", "FC", on_line), ["BR-CL-19"])
            self.assertEqual(reasons("true", "FC", on_line), [])
            self.assertEqual(reasons("true", "95", on_line), ["BR-CL-20"])

    def test_the_scheme_of_an_invoiced_object_on_the_document_and_on_a_line(self):
        reference = ('<cac:%s><cbc:ID schemeID="%s">M-1</cbc:ID><cbc:DocumentTypeCode>130'
                     "</cbc:DocumentTypeCode></cac:%s>")
        document = reference % ("AdditionalDocumentReference", "XX9", "AdditionalDocumentReference")
        on_line = "<cac:InvoiceLine>%s</cac:InvoiceLine>" % (
            reference % ("DocumentReference", "XX9", "DocumentReference"))
        self.assertEqual(codes(invoice(document)), [("BR-CL-07", "BT-18")])
        self.assertEqual(codes(invoice(on_line)), [("BR-CL-07", "BG-25/BT-128")])
        self.assertEqual(codes(invoice(on_line.replace("XX9", "ABZ"))), [])

    def test_every_country_and_each_partys_scheme_is_asked(self):
        country = "<cac:Country><cbc:IdentificationCode>XX</cbc:IdentificationCode></cac:Country>"
        legal = '<cac:PartyLegalEntity><cbc:CompanyID schemeID="XX">1</cbc:CompanyID></cac:PartyLegalEntity>'
        endpoint = '<cbc:EndpointID schemeID="XX">1</cbc:EndpointID>'
        text = invoice(
            "<cac:AccountingSupplierParty><cac:Party>%s<cac:PostalAddress>%s</cac:PostalAddress>%s"
            "</cac:Party></cac:AccountingSupplierParty>" % (endpoint, country, legal)
            + "<cac:AccountingCustomerParty><cac:Party>%s<cac:PostalAddress>%s</cac:PostalAddress>%s"
            "</cac:Party></cac:AccountingCustomerParty>" % (endpoint, country, legal)
            + "<cac:PayeeParty>%s</cac:PayeeParty>" % legal
            + "<cac:TaxRepresentativeParty><cac:PostalAddress>%s</cac:PostalAddress>"
            "</cac:TaxRepresentativeParty>" % country
            + "<cac:Delivery><cac:DeliveryLocation><cac:Address>%s</cac:Address>"
            "</cac:DeliveryLocation></cac:Delivery>" % country)
        self.assertEqual(codes(text), [
            ("BR-CL-11", "BT-30"), ("BR-CL-11", "BT-47"), ("BR-CL-11", "BT-61"),
            ("BR-CL-14", "BT-40"), ("BR-CL-14", "BT-55"), ("BR-CL-14", "BT-69"),
            ("BR-CL-14", "BT-80"), ("BR-CL-25", "BT-34"), ("BR-CL-25", "BT-49")])
