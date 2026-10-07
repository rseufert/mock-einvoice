"""Peppol BIS Billing 3.0's rules for a seller in one of seven countries.

For each country: a document from there that none of its rules has anything
to say of, and then each rule shown to fail when what it asks for is broken.
"""
import unittest

from mockeinvoice import validate
from mockeinvoice.rules import REGISTRY, published, run
from mockeinvoice.rules.peppol_national import tin
from mockeinvoice.ubl import parse_tree

from .test_business_rules import cut
from .test_rules import CREDIT_NOTE, INVOICE, changed

NATIONAL = sorted(i for i in published.PEPPOL if not i.startswith(("PEPPOL-", "DE-R-")))
SETS = {"DK": 14, "GR": 19, "IS": 10, "IT": 4, "NL": 9, "NO": 2, "SE": 13}
MEANS = '<cbc:PaymentMeansCode name="Credit transfer">%s</cbc:PaymentMeansCode>'
PAYMENT_ID = "<cbc:PaymentID>%s</cbc:PaymentID>"
ACCOUNT = "<cbc:ID>%s</cbc:ID>\n      <cbc:Name>Globex GmbH</cbc:Name>"
BRANCH = "<cbc:ID>%s</cbc:ID>\n      </cac:FinancialInstitutionBranch>"
OTHER_TAX = ("<cbc:CompanyID>%s</cbc:CompanyID>\n        <cac:TaxScheme>\n          "
             "<cbc:ID>%s</cbc:ID>")
SELLERS_LEGAL = '<cbc:CompanyID schemeID="%s">%s</cbc:CompanyID>'
BUYERS_LEGAL = "<cbc:RegistrationName>ACME Corporation</cbc:RegistrationName>"
SELLERS_VAT, BUYERS_VAT = "<cbc:CompanyID>DE123456789<", "<cbc:CompanyID>DE987654321<"
RATE = "<cbc:Percent>19</cbc:Percent>"
REFERENCE = ("<cac:AdditionalDocumentReference><cbc:ID>%s</cbc:ID><cbc:DocumentDescription>%s"
             "</cbc:DocumentDescription>%s</cac:AdditionalDocumentReference>"
             "<cac:AccountingSupplierParty>")
URI = ("<cac:Attachment><cac:ExternalReference><cbc:URI>https://example.gr/i/1</cbc:URI>"
       "</cac:ExternalReference></cac:Attachment>")
REPRESENTATIVE = ("<cac:TaxRepresentativeParty><cac:PartyName><cbc:Name>Rep</cbc:Name>"
                  "</cac:PartyName><cac:PostalAddress>%s<cac:Country><cbc:IdentificationCode>"
                  "%s</cbc:IdentificationCode></cac:Country></cac:PostalAddress>"
                  "<cac:PartyTaxScheme><cbc:CompanyID>%s</cbc:CompanyID><cac:TaxScheme>"
                  "<cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:PartyTaxScheme>"
                  "</cac:TaxRepresentativeParty><cac:Delivery>")
TIN, OTHER_TIN = "090000045", "094014201"


def found(text: str) -> list:
    """The national rules a document fails as sent, each once, in order."""
    document, _findings, sent = parse_tree(text)
    return sorted({f.code for f in run(document, "peppol", sent) if f.code in NATIONAL})


def placed(text: str, seller: str, buyer: str = "FR", sellers_vat: str = None,
           buyers_vat: str = "FR98765432101") -> str:
    """The sample with its seller and buyer somewhere else, and one note."""
    text = changed(text, "<cbc:IdentificationCode>DE<", "<cbc:IdentificationCode>%s<" % seller,
                   "<cbc:IdentificationCode>DE<", "<cbc:IdentificationCode>%s<" % buyer,
                   SELLERS_VAT, "<cbc:CompanyID>%s<" % (sellers_vat or seller + "123456789"),
                   BUYERS_VAT, "<cbc:CompanyID>%s<" % buyers_vat)
    return text.replace("  <cbc:Note>Thank you for the order.</cbc:Note>\n", "")


def sellers(text: str, name: str) -> str:
    """Without an element of the seller's address."""
    return cut(text, "<cbc:%s>" % name, "</cbc:%s>\n" % name)


def buyers(text: str, name: str) -> str:
    """Without an element of the buyer's address."""
    at = text.index("<cac:AccountingCustomerParty>")
    return text[:at] + cut(text[at:], "<cbc:%s>" % name, "</cbc:%s>\n" % name)


def paid(text: str, code: str, identifier: str = None, account: str = None,
         branch: str = None) -> str:
    text = changed(text, text[text.index(MEANS[:26]):text.index("</cbc:PaymentMeansCode>")],
                   (MEANS % code)[:-len("</cbc:PaymentMeansCode>")])
    if identifier is not None:
        text = changed(text, PAYMENT_ID % "GLX-4711", PAYMENT_ID % identifier)
    if account is not None:
        text = changed(text, ACCOUNT % "DE02120300000000202051", ACCOUNT % account)
    if branch is not None:
        text = changed(text, BRANCH % "BYLADEM1001", BRANCH % branch)
    return text


class Cases(unittest.TestCase):
    """A country's document, and what breaking it fails."""
    maxDiff = None

    def fails(self, text: str, *expected: str) -> None:
        self.assertEqual(found(text), sorted(expected))


class WhatIsBuilt(unittest.TestCase):
    def test_all_71_of_them_61_fatal(self):
        self.assertEqual(len(NATIONAL), 71)
        self.assertLessEqual(set(NATIONAL), set(REGISTRY["peppol"]))
        flags = [published.PEPPOL[i] for i in NATIONAL]
        self.assertEqual((flags.count("fatal"), flags.count("warning")), (61, 10))
        self.assertEqual({country: sum(1 for i in NATIONAL if i.startswith(country + "-"))
                          for country in SETS}, SETS)
        # With Peppol's own 63 and Germany's 31, that is every rule it publishes.
        self.assertEqual(set(REGISTRY["peppol"]), set(published.PEPPOL))
        self.assertEqual(len(REGISTRY["peppol"]), 63 + 31 + 71)

    def test_a_document_from_none_of_the_seven_is_asked_none(self):
        self.assertEqual(found(INVOICE), [])
        self.assertEqual(found(placed(INVOICE, "FR", sellers_vat="FR12345678901")), [])

    def test_the_buyers_country_alone_asks_nothing(self):
        for country in SETS:
            self.assertEqual(found(placed(INVOICE, "FR", country,
                                          sellers_vat="FR12345678901")), [], country)


class Norway(Cases):
    BASE = changed(placed(INVOICE, "NO", sellers_vat="NO923609016MVA"),
                   OTHER_TAX % ("22/333/44444", "FC"), OTHER_TAX % ("Foretaksregisteret", "TAX"))

    def test_a_norwegian_document(self):
        self.fails(self.BASE)

    def test_the_vat_identifier(self):
        for wrong in ("NO923609017MVA", "NO923609016", "NO92360901MVA", "NO923609016MVAX",
                      "NO 923609016MVA"):
            self.fails(changed(self.BASE, "NO923609016MVA", wrong), "NO-R-001")

    def test_one_that_does_not_start_no_is_not_asked_about(self):
        # Norwegian by its tax representative, with no VAT identifier of its own.
        text = changed(cut(self.BASE, "<cac:PartyTaxScheme>", "</cac:PartyTaxScheme>\n"),
                       "<cac:Delivery>", REPRESENTATIVE % ("", "NO", "NO923609016MVA"))
        self.fails(text)

    def test_no_is_in_capitals(self):
        """Norwegian by `no`, and then not asked, because it does not start `NO`."""
        text = changed(self.BASE, "NO923609016MVA", "no1", "Foretaksregisteret", "x")
        self.fails(text, "NO-R-002")

    def test_foretaksregisteret(self):
        self.fails(changed(self.BASE, "Foretaksregisteret", "Registered"), "NO-R-002")
        self.fails(changed(self.BASE, OTHER_TAX % ("Foretaksregisteret", "TAX"),
                           OTHER_TAX % ("Foretaksregisteret", "FC")), "NO-R-002")
        self.assertEqual(published.PEPPOL["NO-R-002"], "warning")

    def test_norwegian_is_by_the_vat_identifier_before_the_address(self):
        swedish_vat = changed(self.BASE, "NO923609016MVA", "FR12345678901")
        self.assertEqual(found(swedish_vat), [])
        # And by the address where there is no VAT identifier anywhere.
        nowhere = cut(self.BASE, "<cac:PartyTaxScheme>", "</cac:PartyTaxScheme>\n")
        self.fails(changed(nowhere, "Foretaksregisteret", "x"), "NO-R-002")
        self.fails(changed(nowhere, "<cbc:IdentificationCode>NO<",
                           "<cbc:IdentificationCode> no <", "Foretaksregisteret", "x"),
                   "NO-R-002")


class Denmark(Cases):
    BASE = paid(changed(placed(INVOICE, "DK", "DK"), SELLERS_LEGAL % ("0204", "HRB 12345"),
                        SELLERS_LEGAL % ("0184", "13585628"),
                        'listVersionID="2008"', 'listVersionID="19.05.01"'), "58")
    NOTE = changed(placed(CREDIT_NOTE, "DK", "DK"), SELLERS_LEGAL % ("0204", "HRB 12345"),
                   SELLERS_LEGAL % ("0184", "13585628"),
                   'listVersionID="2008"', 'listVersionID="26.08.01"')

    def abroad(self, text: str) -> str:
        """The same document with its buyer in Sweden."""
        at = text.index("<cac:AccountingCustomerParty>")
        return text[:at] + changed(text[at:], "<cbc:IdentificationCode>DK<",
                                   "<cbc:IdentificationCode>SE<")

    def test_a_danish_document(self):
        self.fails(self.BASE)
        self.fails(self.abroad(self.BASE))

    def test_the_sellers_cvr_number(self):
        self.fails(cut(self.BASE, '<cbc:CompanyID schemeID="0184">', "</cbc:CompanyID>"),
                   "DK-R-002")
        self.fails(changed(self.BASE, ">13585628<", "> <"), "DK-R-002")
        self.fails(changed(self.BASE, 'schemeID="0184"', 'schemeID="0204"'), "DK-R-014")
        self.fails(changed(self.BASE, ' schemeID="0184"', ""), "DK-R-014")
        # Both are asked whoever the buyer is.
        self.fails(self.abroad(changed(self.BASE, 'schemeID="0184"', 'schemeID="0204"')),
                   "DK-R-014")

    def test_a_credit_note_with_a_negative_amount_due(self):
        note = paid(self.NOTE, "58")
        self.fails(note)
        negative = changed(note, ">1190.00</cbc:PayableAmount>", ">-1190.00</cbc:PayableAmount>")
        self.fails(negative, "DK-R-016")
        self.fails(self.abroad(negative))
        # An invoice may have one.
        self.fails(changed(self.BASE, ">1190.00</cbc:PayableAmount>",
                           ">-1190.00</cbc:PayableAmount>"))

    def test_an_identifier_names_its_scheme(self):
        text = changed(self.BASE, '<cbc:ID schemeID="SEPA">', "<cbc:ID>")
        self.fails(text, "DK-R-013")
        self.fails(self.abroad(text))
        # One with no identifier in it has nothing to name a scheme for.
        self.fails(cut(self.BASE, '<cbc:ID schemeID="SEPA">', "</cbc:ID>"))

    def test_how_an_invoice_is_paid(self):
        self.fails(paid(self.BASE, "30"), "DK-R-005")
        self.fails(paid(self.BASE, " 58"), "DK-R-005")
        for code in ("31", "42"):
            self.fails(paid(self.BASE, code))
            self.fails(paid(self.BASE, code, branch=" "), "DK-R-006")
            self.fails(paid(self.BASE, code, account=""), "DK-R-006")
        self.fails(paid(self.BASE, "49"), "DK-R-007")
        mandate = ("</cac:PayeeFinancialAccount>\n    <cac:PaymentMandate><cbc:ID>M-1</cbc:ID>%s"
                   "</cac:PaymentMandate>")
        debited = "<cac:PayerFinancialAccount><cbc:ID>DK50</cbc:ID></cac:PayerFinancialAccount>"
        self.fails(changed(paid(self.BASE, "49"), "</cac:PayeeFinancialAccount>",
                           mandate % debited))
        self.fails(changed(paid(self.BASE, "49"), "</cac:PayeeFinancialAccount>", mandate % ""),
                   "DK-R-007")

    def test_a_giro_payment(self):
        self.fails(paid(self.BASE, "50", "01#", "1234567"))
        self.fails(paid(self.BASE, "50", "04#1234567890123456", "12345678"))
        self.fails(paid(self.BASE, "50", "02#", "1234567"), "DK-R-008")
        self.fails(paid(self.BASE, "50", "01#", "123456"), "DK-R-008")
        self.fails(paid(self.BASE, "50", "01#", "123456789"), "DK-R-008")
        self.fails(paid(self.BASE, "50", "15#123456789012345", "1234567"), "DK-R-009")
        self.fails(paid(self.BASE, "50", "04#12345678901234567", "1234567"), "DK-R-009")

    def test_a_fik_payment(self):
        self.fails(paid(self.BASE, "93", "73#", "12345678"))
        self.fails(paid(self.BASE, "93", "71#123456789012345", "12345678"))
        self.fails(paid(self.BASE, "93", "75#1234567890123456", "12345678"))
        self.fails(paid(self.BASE, "93", "74#", "12345678"), "DK-R-010")
        self.fails(paid(self.BASE, "93", "73#", "1234567"), "DK-R-010")
        self.fails(paid(self.BASE, "93", "71#12345678901234", "12345678"), "DK-R-011")
        self.fails(paid(self.BASE, "93", "75#12345678901234567", "12345678"), "DK-R-011")

    def test_a_credit_note_is_not_asked_how_it_is_paid(self):
        self.fails(self.NOTE)           # means of payment 30, which an invoice may not have
        self.fails(self.abroad(paid(self.BASE, "30")))

    def test_the_buyers_cvr_number(self):
        text = changed(self.BASE, BUYERS_LEGAL, BUYERS_LEGAL + SELLERS_LEGAL % ("0204", "1"))
        self.fails(text, "DK-R-017")
        self.fails(changed(text, SELLERS_LEGAL % ("0204", "1"), SELLERS_LEGAL % ("0184", "1")))
        self.fails(self.abroad(text))

    def test_the_unspsc_version(self):
        for version in ("19.0501", "26.08.01", "26.0801"):
            self.fails(changed(self.BASE, '"19.05.01"', '"%s"' % version))
        text = changed(self.BASE, '"19.05.01"', '"2008"')
        self.fails(text, "DK-R-003")
        self.fails(changed(self.BASE, ' listVersionID="19.05.01"', ""), "DK-R-003")
        self.fails(changed(text, 'listID="TST"', 'listID="STI"'))
        self.fails(self.abroad(text))

    def test_a_tax_that_is_not_vat(self):
        coded = "<cbc:AllowanceChargeReasonCode>ZZZ</cbc:AllowanceChargeReasonCode>"
        text = changed(self.BASE, "<cbc:AllowanceChargeReason>Freight", coded
                       + "<cbc:AllowanceChargeReason>Freight")
        self.fails(text, "DK-R-004")
        for reason in ("1234", "0000", " 9999 ", "Pant#1", "a#b#c"):
            self.fails(changed(text, "Reason>Freight", "Reason>%s" % reason))
        for reason in ("123", "12345", "-123", "abcd", "#Pant", "Pant#", "#"):
            self.fails(changed(text, "Reason>Freight", "Reason>%s" % reason), "DK-R-004")
        self.fails(cut(text, "<cbc:AllowanceChargeReason>", "</cbc:AllowanceChargeReason>"),
                   "DK-R-004")
        self.fails(self.abroad(text))

    def test_denmark_is_dk_as_written(self):
        text = changed(self.BASE, 'schemeID="0184"', 'schemeID="0204"')
        for other in ("dk", " DK "):
            self.fails(changed(text, "<cbc:IdentificationCode>DK<",
                               "<cbc:IdentificationCode>%s<" % other))
        # And by the address, whatever the VAT identifier says.
        self.fails(changed(text, "DK123456789", "SE556012579001"), "DK-R-014")


class Italy(Cases):
    BASE = changed(placed(INVOICE, "IT", sellers_vat="IT12345678901"),
                   OTHER_TAX % ("22/333/44444", "FC"), OTHER_TAX % ("RSSMRA85T10A562S", "FC"))

    def test_an_italian_document(self):
        self.fails(self.BASE)

    def test_the_tax_registration(self):
        for wrong in ("22/333/44444", "1234567890", "RSSMRA85T10A562SX", "rssmra85t10a562s", ""):
            self.fails(changed(self.BASE, "RSSMRA85T10A562S", wrong), "IT-R-001")
        self.fails(changed(self.BASE, "RSSMRA85T10A562S", " 12345678901 "))

    def test_the_address(self):
        for name, rule in (("StreetName", "IT-R-002"), ("CityName", "IT-R-003"),
                           ("PostalZone", "IT-R-004")):
            self.fails(sellers(self.BASE, name), rule)
        # There, and empty, is there.
        self.fails(changed(self.BASE, "Industriestrasse 1", ""))

    def test_italian_is_by_the_vat_identifier_before_the_address(self):
        self.fails(sellers(changed(self.BASE, "IT12345678901", "FR12345678901"), "CityName"))
        self.fails(sellers(placed(INVOICE, "FR", sellers_vat="IT12345678901"), "CityName"),
                   "IT-R-001", "IT-R-003")


class Sweden(Cases):
    BASE = changed(placed(INVOICE, "SE", sellers_vat="SE556012579001"),
                   SELLERS_LEGAL % ("0204", "HRB 12345"), SELLERS_LEGAL % ("0007", "5560125790"),
                   OTHER_TAX % ("22/333/44444", "FC"),
                   OTHER_TAX % ("Godkänd för F-skatt", "TAX")).replace(
                       RATE, "<cbc:Percent>25</cbc:Percent>")

    def test_a_swedish_document(self):
        self.fails(self.BASE)

    def test_the_vat_identifier(self):
        self.fails(changed(self.BASE, "SE556012579001", "SE5560125790"), "SE-R-001")
        self.fails(changed(self.BASE, "SE556012579001", "SE55601257900A"), "SE-R-002")
        self.fails(changed(self.BASE, "SE556012579001", "SE55601257900"), "SE-R-001")
        # One that does not start SE is not asked about.
        self.fails(changed(self.BASE, "SE556012579001", "FR123"))

    def test_the_organisation_number(self):
        self.fails(changed(self.BASE, ">5560125790<", ">55601257AB<"), "SE-R-003", "SE-R-013")
        self.fails(changed(self.BASE, ">5560125790<", ">556012579<"), "SE-R-004", "SE-R-013")
        self.fails(changed(self.BASE, ">5560125790<", ">5560125791<"), "SE-R-013")
        self.fails(changed(self.BASE, ">5560125790<", "> 5560125790 <"))
        # Asked by the address alone, whatever the VAT identifier.
        self.fails(changed(self.BASE, "SE556012579001", "FR123", ">5560125790<",
                           ">5560125791<"), "SE-R-013")

    def test_f_skatt(self):
        self.fails(changed(self.BASE, "Godkänd för F-skatt", "F-skatt"), "SE-R-005")
        self.fails(changed(self.BASE, "Godkänd för F-skatt", " godkänd för f-skatt "))
        # Only of a seller that gives an organisation number.
        self.fails(cut(changed(self.BASE, "Godkänd för F-skatt", "F-skatt"),
                       '<cbc:CompanyID schemeID="0007">', "</cbc:CompanyID>"))

    def test_the_standard_rate(self):
        for rate in ("12", "6", "25.0"):
            self.fails(self.BASE.replace("<cbc:Percent>25<", "<cbc:Percent>%s<" % rate))
        self.fails(changed(self.BASE, "<cbc:Percent>25<", "<cbc:Percent>19<"), "SE-R-006")
        self.fails(cut(self.BASE, "<cbc:Percent>", "</cbc:Percent>"), "SE-R-006")
        # Not asked of a seller whose VAT identifier is not Swedish.
        self.fails(changed(self.BASE, "SE556012579001", "FR123", "<cbc:Percent>25<",
                           "<cbc:Percent>19<"))

    def test_giro_accounts(self):
        self.fails(paid(self.BASE, "30", account="1234567", branch="SE:PLUSGIRO"))
        self.fails(paid(self.BASE, "30", account="12A", branch="SE:PLUSGIRO"), "SE-R-007")
        self.fails(paid(self.BASE, "30", account="123456789", branch="SE:PLUSGIRO"), "SE-R-010")
        self.fails(paid(self.BASE, "30", account="1", branch="SE:PLUSGIRO"), "SE-R-010")
        self.fails(paid(self.BASE, "30", account="12345678", branch="SE:BANKGIRO"))
        self.fails(paid(self.BASE, "30", account="1234AB7", branch="SE:BANKGIRO"), "SE-R-008")
        self.fails(paid(self.BASE, "30", account="123456", branch="SE:BANKGIRO"), "SE-R-009")
        # Not asked of another means of payment.
        self.fails(paid(self.BASE, "58", account="12A", branch="SE:PLUSGIRO"))
        for rule in ("SE-R-007", "SE-R-008", "SE-R-009", "SE-R-010", "SE-R-011", "SE-R-012"):
            self.assertEqual(published.PEPPOL[rule], "warning")

    def test_means_of_payment_that_should_be_30(self):
        self.fails(paid(self.BASE, "50"), "SE-R-011")
        self.fails(paid(self.BASE, "56"), "SE-R-011")
        self.fails(paid(self.BASE, "31"))
        both = changed(self.BASE, "<cbc:IdentificationCode>FR<", "<cbc:IdentificationCode>SE<")
        self.fails(paid(both, "31"), "SE-R-012")

    def test_sweden_is_se_as_written(self):
        text = changed(self.BASE, ">5560125790<", ">5560125791<")
        self.fails(changed(text, "<cbc:IdentificationCode>SE<", "<cbc:IdentificationCode>se<"))

    def test_peppols_swedish_example_is_valid(self):
        """It was `not judged` while these rules were not built."""
        from . import upstream
        import os
        path = os.path.join(upstream.FETCHED, "peppol", "rules", "examples", "vat-category-O.xml")
        if not os.path.exists(path):
            self.skipTest("Peppol's files are not in this repository: python tools/fetch_peppol.py")
        with open(path, "rb") as handle:
            _document, report = validate(handle.read())
        self.assertEqual((report.findings, report.verdict), ([], "valid"))


class Greece(Cases):
    NUMBER = "%s|02/10/2026|0|1.1|A|4711" % TIN
    BASE = changed(
        placed(INVOICE, "GR", "GR", sellers_vat="EL" + TIN, buyers_vat="EL" + OTHER_TIN),
        "<cbc:ID>GLX-4711</cbc:ID>", "<cbc:ID>%s</cbc:ID>" % NUMBER,
        '<cbc:EndpointID schemeID="0088">4012345000009<',
        '<cbc:EndpointID schemeID="9933">%s<' % TIN,
        '<cbc:EndpointID schemeID="0088">4098765000003</cbc:EndpointID>',
        '<cbc:EndpointID schemeID="9933">%s</cbc:EndpointID><cac:PartyName><cbc:Name>ACME'
        "</cbc:Name></cac:PartyName>" % OTHER_TIN,
        "<cac:AccountingSupplierParty>", REFERENCE % ("400001234567890", "##M.AR.K##", ""),
        "<cac:AccountingSupplierParty>", REFERENCE % ("u", "##INVOICE|URL##", URI))

    def numbered(self, number: str) -> str:
        return changed(self.BASE, self.NUMBER, number)

    def test_a_greek_document(self):
        self.fails(self.BASE)
        self.assertTrue(all(tin(value) for value in (TIN, OTHER_TIN)))

    def test_the_invoice_number_is_six_parts(self):
        self.fails(self.numbered(self.NUMBER + "|x"), "GR-R-001-1")
        self.fails(self.numbered("%s|02/10/2026|0|1.1|A" % TIN), "GR-R-001-1", "GR-R-001-7")
        self.fails(self.numbered("%s|02/10/2026|0|1.1||" % TIN), "GR-R-001-6", "GR-R-001-7")
        self.fails(self.numbered("GLX-4711"), "GR-R-001-1", "GR-R-001-2", "GR-R-001-3",
                   "GR-R-001-4", "GR-R-001-5", "GR-R-001-6", "GR-R-001-7")

    def test_its_first_part_is_the_sellers_tax_number(self):
        self.fails(self.numbered(self.NUMBER.replace(TIN, OTHER_TIN)), "GR-R-001-2")
        self.fails(self.numbered(self.NUMBER.replace(TIN, "090000046")), "GR-R-001-2")
        self.fails(self.numbered(self.NUMBER.replace(TIN, TIN + "0")), "GR-R-001-2")
        # The seller's own, and not a tax number that checks.
        self.fails(changed(self.numbered(self.NUMBER.replace(TIN, "090000046")),
                           ">EL%s<" % TIN, ">EL090000046<"),
                   "GR-R-001-2", "GR-R-003", "GR-S-011")
        # Or its tax representative's.
        represented = changed(self.numbered(self.NUMBER.replace(TIN, OTHER_TIN)),
                              "<cac:Delivery>", REPRESENTATIVE % ("", "GR", "EL" + OTHER_TIN))
        self.fails(represented)

    def test_its_second_part_is_the_issue_date(self):
        for wrong in ("03/10/2026", "2/10/2026", "02-10-2026", "2026/10/02", "", "02/10/26"):
            self.fails(self.numbered(self.NUMBER.replace("02/10/2026", wrong)), "GR-R-001-3")

    def test_its_third_part_is_a_whole_number(self):
        for wrong in ("-1", "x", " "):
            self.fails(self.numbered(self.NUMBER.replace("|0|", "|%s|" % wrong)), "GR-R-001-4")
        self.fails(self.numbered(self.NUMBER.replace("|0|", "|17|")))
        # A number that is not a whole one is where the published test stops.
        document, _findings, sent = parse_tree(self.numbered(self.NUMBER.replace("|0|", "|1.5|")))
        [finding] = [f for f in run(document, "peppol", sent) if f.code == "GR-R-001-4"]
        self.assertIn("not a whole one", finding.text)

    def test_its_fourth_part_is_a_greek_document_type(self):
        for right in ("1.6", "2.1", "2.4", "5.1", "5.2"):
            self.fails(self.numbered(self.NUMBER.replace("|1.1|", "|%s|" % right)))
        for wrong in ("1.2", "11", " 1.1", ""):
            self.fails(self.numbered(self.NUMBER.replace("|1.1|", "|%s|" % wrong)), "GR-R-001-5")

    def test_the_names(self):
        self.fails(cut(self.BASE, "<cac:PartyName>", "</cac:PartyName>"), "GR-R-002")
        self.fails(changed(self.BASE, "<cbc:Name>ACME</cbc:Name>", "<cbc:Name></cbc:Name>"),
                   "GR-R-005")

    def test_the_sellers_vat_identifier(self):
        self.fails(changed(self.BASE, ">EL%s<" % TIN, ">GR%s<" % TIN),
                   "GR-R-003", "GR-S-011")
        self.fails(changed(self.BASE, ">EL%s<" % TIN, ">EL090000046<"),
                   "GR-R-001-2", "GR-R-003", "GR-S-011")
        self.assertEqual(published.PEPPOL["GR-S-011"], "warning")
        # The check is of the first nine characters, whatever follows.
        self.fails(changed(self.BASE, ">EL%s<" % TIN, ">EL%s77<" % TIN))
        # A seller with none of its own, Greek by its tax representative.
        represented = changed(cut(self.BASE, "<cac:PartyTaxScheme>", "</cac:PartyTaxScheme>\n"),
                              "<cac:Delivery>", REPRESENTATIVE % ("", "GR", "EL" + TIN))
        self.fails(represented, "GR-S-011")

    def test_the_mark_number(self):
        text = cut(self.BASE, "<cac:AdditionalDocumentReference><cbc:ID>4",
                   "</cac:AdditionalDocumentReference>")
        self.fails(text, "GR-R-004-1")
        self.fails(changed(self.BASE, "<cac:AccountingSupplierParty>",
                           REFERENCE % ("5", "##M.AR.K##", "")), "GR-R-004-1")
        self.fails(changed(self.BASE, ">400001234567890<", ">0400001234567890<"), "GR-R-004-2")
        self.fails(changed(self.BASE, ">400001234567890<", ">x<"), "GR-R-004-2")
        # Only what it starts with is looked at.
        self.fails(changed(self.BASE, ">400001234567890<", ">4x<"))

    def test_the_invoice_url(self):
        one = "<cac:AdditionalDocumentReference><cbc:ID>u"
        self.fails(cut(self.BASE, one, "</cac:AdditionalDocumentReference>"), "GR-S-008-1")
        self.assertEqual(published.PEPPOL["GR-S-008-1"], "warning")
        self.fails(changed(self.BASE, "<cac:AccountingSupplierParty>",
                           REFERENCE % ("v", "##INVOICE|URL##", URI)), "GR-R-008-2", "GR-S-008-1")
        self.fails(changed(self.BASE, URI, ""), "GR-R-008-3")

    def test_the_mark_and_the_url_are_for_a_seller_whose_address_is_in_greece(self):
        text = cut(cut(self.BASE, "<cac:AdditionalDocumentReference><cbc:ID>4",
                       "</cac:AdditionalDocumentReference>"),
                   "<cac:AdditionalDocumentReference><cbc:ID>u",
                   "</cac:AdditionalDocumentReference>")
        self.fails(text, "GR-R-004-1", "GR-S-008-1")
        self.fails(changed(text, "<cbc:IdentificationCode>GR<", "<cbc:IdentificationCode>CY<"))

    def test_the_electronic_addresses(self):
        seller = '<cbc:EndpointID schemeID="9933">%s<' % TIN
        self.fails(changed(self.BASE, seller, '<cbc:EndpointID schemeID="0088">%s<' % TIN),
                   "GR-R-009")
        self.fails(changed(self.BASE, seller, '<cbc:EndpointID schemeID="9933">090000046<'),
                   "GR-R-009")
        buyer = '<cbc:EndpointID schemeID="9933">%s<' % OTHER_TIN
        self.fails(changed(self.BASE, buyer, '<cbc:EndpointID schemeID="0088">%s<' % OTHER_TIN),
                   "GR-R-010")

    def test_the_buyers_vat_identifier_where_the_buyer_is_greek(self):
        self.fails(changed(self.BASE, ">EL%s<" % OTHER_TIN, ">EL094014202<"), "GR-R-006")
        at = self.BASE.index("<cac:AccountingCustomerParty>")
        none = self.BASE[:at] + cut(self.BASE[at:], "<cac:PartyTaxScheme>",
                                    "</cac:PartyTaxScheme>\n")
        self.fails(none, "GR-R-006")
        # A buyer elsewhere is asked neither that nor for a tax number as its address.
        abroad = changed(none, '<cbc:EndpointID schemeID="9933">%s<' % OTHER_TIN,
                         '<cbc:EndpointID schemeID="0088">4098765000003<')
        at = abroad.index("<cac:AccountingCustomerParty>")
        self.fails(abroad[:at] + changed(abroad[at:], "<cbc:IdentificationCode>GR<",
                                         "<cbc:IdentificationCode>FR<"))

    def test_greek_is_gr_or_el_by_the_vat_identifier_first(self):
        text = self.numbered("GLX-4711")
        self.assertIn("GR-R-001-1", found(text))
        self.assertEqual(found(changed(text, ">EL%s<" % TIN, ">FR12345678901<")), [])
        # A tax representative makes the seller Greek, but not its address one
        # that must be a tax number.
        represented = changed(
            cut(placed(INVOICE, "FR", sellers_vat="x"), "<cac:PartyTaxScheme>",
                "</cac:PartyTaxScheme>\n"),
            "<cac:Delivery>", REPRESENTATIVE % ("", "GR", "EL" + TIN))
        self.assertEqual([i for i in found(represented) if i in ("GR-R-001-1", "GR-R-009")],
                         ["GR-R-001-1"])


class Iceland(Cases):
    """Peppol publishes no unit tests for these ten: these are all there is."""
    BASE = changed(placed(INVOICE, "IS", "IS"), SELLERS_LEGAL % ("0204", "HRB 12345"),
                   SELLERS_LEGAL % ("0196", "5501694729"),
                   BUYERS_LEGAL, BUYERS_LEGAL + SELLERS_LEGAL % ("0196", "6502697649"))

    def eindagi(self, date: str, text: str = None) -> str:
        return changed(text or self.BASE, "<cac:AccountingSupplierParty>",
                       REFERENCE % (date, "EINDAGI", ""))

    def abroad(self, text: str) -> str:
        at = text.index("<cac:AccountingCustomerParty>")
        return text[:at] + changed(text[at:], "<cbc:IdentificationCode>IS<",
                                   "<cbc:IdentificationCode>DK<")

    def test_there_are_no_published_tests_for_them(self):
        from . import upstream
        self.assertNotIn("unit-UBL-IS", upstream.PEPPOL_DIRECTORIES)

    def test_an_icelandic_document(self):
        self.fails(self.BASE)
        self.fails(self.eindagi("2026-11-15"))

    def test_the_type(self):
        self.fails(changed(self.BASE, ">380</cbc:InvoiceTypeCode>", ">383</cbc:InvoiceTypeCode>"),
                   "IS-R-001")
        self.fails(changed(self.BASE, ">380</cbc:InvoiceTypeCode>", ">381</cbc:InvoiceTypeCode>"))
        self.assertEqual(published.PEPPOL["IS-R-001"], "warning")

    def test_the_sellers_kennitala_and_address(self):
        self.fails(changed(self.BASE, 'schemeID="0196">5501694729', 'schemeID="0204">5501694729'),
                   "IS-R-002")
        self.fails(cut(self.BASE, '<cbc:CompanyID schemeID="0196">', "</cbc:CompanyID>"),
                   "IS-R-002")
        self.fails(sellers(self.BASE, "StreetName"), "IS-R-003")
        self.fails(sellers(self.BASE, "PostalZone"), "IS-R-003")
        self.fails(sellers(self.BASE, "CityName"))

    def test_an_account_of_twelve_characters(self):
        for code, rule in (("9", "IS-R-006"), ("42", "IS-R-007")):
            self.fails(paid(self.BASE, code, account="051526001234"))
            self.fails(paid(self.BASE, code), rule)
            self.fails(cut(paid(self.BASE, code), "<cac:PayeeFinancialAccount>",
                           "</cac:PayeeFinancialAccount>\n"), rule)
        self.fails(paid(self.BASE, "30"))

    def test_the_final_due_date(self):
        for wrong in ("2026-11-1", "15.11.2026", "2026-13-01", "2026-11-15Z"):
            self.assertIn("IS-R-008", found(self.eindagi(wrong)), wrong)
        self.fails(cut(self.eindagi("2026-11-15"), "<cbc:DueDate>", "</cbc:DueDate>\n"),
                   "IS-R-009", "IS-R-010")
        self.fails(self.eindagi("2026-10-31"), "IS-R-010")
        self.fails(self.eindagi("2026-11-01"))

    def test_a_credit_note_with_a_final_due_date_always_fails(self):
        """The rule looks for the due date where an invoice has it."""
        note = changed(placed(CREDIT_NOTE, "IS", "IS"), SELLERS_LEGAL % ("0204", "HRB 12345"),
                       SELLERS_LEGAL % ("0196", "5501694729"),
                       BUYERS_LEGAL, BUYERS_LEGAL + SELLERS_LEGAL % ("0196", "6502697649"))
        self.fails(note)
        self.fails(self.eindagi("2026-11-15", note), "IS-R-009", "IS-R-010")

    def test_the_buyers_kennitala_and_address(self):
        text = changed(self.BASE, 'schemeID="0196">6502697649', 'schemeID="0204">6502697649')
        self.fails(text, "IS-R-004")
        self.fails(self.abroad(text))
        self.fails(buyers(self.BASE, "StreetName"), "IS-R-005")
        self.fails(buyers(self.BASE, "PostalZone"), "IS-R-005")
        self.fails(self.abroad(buyers(self.BASE, "PostalZone")))

    def test_iceland_is_is_as_written(self):
        text = sellers(self.BASE, "StreetName")
        self.fails(changed(text, "<cbc:IdentificationCode>IS<", "<cbc:IdentificationCode>is<"))
        self.fails(changed(text, "IS123456789", "FR12345678901"), "IS-R-003")


class TheNetherlands(Cases):
    BASE = changed(placed(INVOICE, "NL", "NL", sellers_vat="NL123456789B01"),
                   SELLERS_LEGAL % ("0204", "HRB 12345"), SELLERS_LEGAL % ("0106", "12345678"),
                   BUYERS_LEGAL, BUYERS_LEGAL + SELLERS_LEGAL % ("0190", "00000001123456780000"))
    NOTE = changed(placed(CREDIT_NOTE, "NL", "NL", sellers_vat="NL123456789B01"),
                   SELLERS_LEGAL % ("0204", "HRB 12345"), SELLERS_LEGAL % ("0106", "12345678"))

    def abroad(self, text: str) -> str:
        at = text.index("<cac:AccountingCustomerParty>")
        return text[:at] + changed(text[at:], "<cbc:IdentificationCode>NL<",
                                   "<cbc:IdentificationCode>BE<")

    def test_a_dutch_document(self):
        self.fails(self.BASE)
        self.fails(self.NOTE)

    def test_a_credit_note_names_its_invoice(self):
        self.fails(cut(self.NOTE, "<cac:BillingReference>", "</cac:BillingReference>\n"),
                   "NL-R-001")

    def test_the_addresses(self):
        for name in ("StreetName", "CityName", "PostalZone"):
            self.fails(sellers(self.BASE, name), "NL-R-002")
            self.fails(buyers(self.BASE, name), "NL-R-004")
            self.fails(self.abroad(buyers(self.BASE, name)))

    def test_the_legal_registrations(self):
        self.fails(changed(self.BASE, 'schemeID="0106"', 'schemeID="0204"'), "NL-R-003")
        self.fails(changed(self.BASE, 'schemeID="0106"', 'schemeID="0190"'))
        self.fails(changed(self.BASE, ">12345678<", "> <"), "NL-R-003")
        text = changed(self.BASE, 'schemeID="0190"', 'schemeID="0204"')
        self.fails(text, "NL-R-005")
        self.fails(self.abroad(text))

    def test_the_tax_representatives_address(self):
        whole = ("<cbc:StreetName>Kade 1</cbc:StreetName><cbc:CityName>Rotterdam</cbc:CityName>"
                 "<cbc:PostalZone>3011</cbc:PostalZone>")
        self.fails(changed(self.BASE, "<cac:Delivery>", REPRESENTATIVE % (whole, "NL", "NL1")))
        partial = changed(self.BASE, "<cac:Delivery>", REPRESENTATIVE % (
            "<cbc:CityName>Rotterdam</cbc:CityName>", "NL", "NL1"))
        self.fails(partial, "NL-R-006")
        self.fails(changed(partial, "%s</cbc:IdentificationCode></cac:Country></cac:PostalAddress>"
                           % "NL", "BE</cbc:IdentificationCode></cac:Country></cac:PostalAddress>"))

    def test_a_means_of_payment_where_money_is_owed(self):
        unpaid = cut(self.BASE, "<cac:PaymentMeans>", "</cac:PaymentMeans>\n")
        self.fails(unpaid, "NL-R-007")
        for due in ("0.00", "-5.00"):
            self.fails(changed(unpaid, ">1190.00</cbc:PayableAmount>",
                               ">%s</cbc:PayableAmount>" % due))
        # A credit note the other way round.
        note = cut(self.NOTE, "<cac:PaymentMeans>", "</cac:PaymentMeans>\n")
        self.fails(note)
        self.fails(changed(note, ">1190.00</cbc:PayableAmount>", ">-1.00</cbc:PayableAmount>"),
                   "NL-R-007")

    def test_the_means_of_payment_between_two_in_the_netherlands(self):
        for code in ("48", "49", "57", "58", "59", " 30 "):
            self.fails(paid(self.BASE, code))
        self.fails(paid(self.BASE, "31"), "NL-R-008")
        self.fails(self.abroad(paid(self.BASE, "31")))

    def test_an_order_line_needs_an_order(self):
        text = cut(self.BASE, "<cac:OrderReference>", "</cac:OrderReference>\n")
        self.fails(text, "NL-R-009")
        self.fails(cut(text, "<cac:OrderLineReference>", "</cac:OrderLineReference>\n"))

    def test_the_netherlands_is_by_the_address_however_it_is_written(self):
        text = sellers(self.BASE, "CityName")
        self.fails(changed(text, "<cbc:IdentificationCode>NL<", "<cbc:IdentificationCode> nl <"),
                   "NL-R-002")
        self.fails(changed(text, "NL123456789B01", "FR12345678901"), "NL-R-002")
        self.fails(sellers(placed(INVOICE, "FR", sellers_vat="NL123456789B01"), "CityName"))


class TheNationalExamples(unittest.TestCase):
    """Peppol's three, which its national authorities keep. Not all are clean."""

    def test_what_is_said_of_them(self):
        import os
        from . import upstream
        folder = os.path.join(upstream.FETCHED, "peppol", "rules", "national-examples")
        if not os.path.isdir(folder):
            self.skipTest("Peppol's files are not in this repository: python tools/fetch_peppol.py")
        said = {}
        for country, name in (("GR", "GR-base-example-correct.xml"),
                              ("GR", "GR-base-example-TaxRepresentative.xml"),
                              ("NO", "Norwegian-example-1.xml")):
            with open(os.path.join(folder, country, name), "rb") as handle:
                _document, report = validate(handle.read())
            said[name] = (report.verdict, sorted({f.code for f in report.findings}))
        self.assertEqual(said, {
            # No invoice URL, which a Greek seller should have.
            "GR-base-example-correct.xml": ("valid", ["GR-S-008-1"]),
            # Its seller has no legal name, which the core asks for (BR-06),
            # and no VAT identifier of its own.
            "GR-base-example-TaxRepresentative.xml": ("invalid", ["BR-06", "GR-S-011"]),
            # A scheme named on a VAT category, which the core warns of.
            "Norwegian-example-1.xml": ("valid", ["UBL-CR-679"]),
        })
