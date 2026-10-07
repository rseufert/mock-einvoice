"""Peppol BIS Billing 3.0's rules for a seller and a buyer both in Germany."""
import unittest

from mockeinvoice.rules import REGISTRY, published, run
from mockeinvoice.rules.german import iban
from mockeinvoice.ubl import parse_tree

from .test_business_rules import cut
from .test_rules import CREDIT_NOTE, INVOICE, changed

GERMAN = sorted(i for i in published.PEPPOL if i.startswith("DE-R-"))
MEANS = '<cbc:PaymentMeansCode name="Credit transfer">%s</cbc:PaymentMeansCode>'
ACCOUNT = "<cbc:ID>DE02120300000000202051</cbc:ID>"
TERMS = "<cbc:Note>30 days net</cbc:Note>"
MANDATE = ("</cac:PayeeFinancialAccount><cac:PaymentMandate><cbc:ID>M-1</cbc:ID>%s"
           "</cac:PaymentMandate>")
PAYER = "<cac:PayerFinancialAccount><cbc:ID>%s</cbc:ID></cac:PayerFinancialAccount>"
CARD = ("<cac:CardAccount><cbc:PrimaryAccountNumberID>1234</cbc:PrimaryAccountNumberID>"
        "<cbc:NetworkID>VISA</cbc:NetworkID></cac:CardAccount>")
ATTACHED = ("<cac:AdditionalDocumentReference><cbc:ID>%s</cbc:ID><cac:Attachment>%s"
            "</cac:Attachment></cac:AdditionalDocumentReference>")
EMBEDDED = ('<cbc:EmbeddedDocumentBinaryObject mimeCode="text/csv" filename="%s">eA=='
            "</cbc:EmbeddedDocumentBinaryObject>")
SELLERS_PLACE = ("<cbc:CityName>Hamburg</cbc:CityName>\n        <cbc:PostalZone>20095"
                 "</cbc:PostalZone>")
BUYERS_PLACE = ("<cbc:CityName>Berlin</cbc:CityName>\n        <cbc:PostalZone>10115"
                "</cbc:PostalZone>")


def found(text: str) -> list:
    """Germany's rules that a document fails as sent, with where."""
    document, _findings, sent = parse_tree(text)
    return [(f.code, f.path) for f in run(document, "peppol", sent) if f.code.startswith("DE-R-")]


def failing(text: str) -> list:
    return sorted({code for code, _path in found(text)})


def abroad(text: str) -> str:
    """The same document with its buyer in Austria."""
    at = text.index("<cac:AccountingCustomerParty>")
    return text[:at] + changed(text[at:], "<cbc:IdentificationCode>DE",
                               "<cbc:IdentificationCode>AT")


def paid(code: str, inside: str = None) -> str:
    """The sample paid another way: its payment instruction's code, and what
    is in it besides."""
    text = changed(INVOICE, MEANS % "30", MEANS % code)
    if inside is None:
        return text
    return cut(text, "<cac:PayeeFinancialAccount>", "</cac:PayeeFinancialAccount>", inside)


class WhatIsBuilt(unittest.TestCase):
    def test_all_31_of_them_24_fatal(self):
        self.assertEqual(len(GERMAN), 31)
        self.assertLessEqual(set(GERMAN), set(REGISTRY["peppol"]))
        flags = [published.PEPPOL[i] for i in GERMAN]
        self.assertEqual((flags.count("fatal"), flags.count("warning")), (24, 7))

    def test_the_documents_this_project_wrote_fail_none(self):
        self.assertEqual(found(INVOICE), [])
        self.assertEqual(found(CREDIT_NOTE), [])


class EachRule(unittest.TestCase):
    """The German invoice all of them pass, changed in one place; and the
    same change with the buyer abroad, where none of them is asked."""
    seen = set()

    def case(self, rule: str, text: str, beside=()) -> None:
        wanted = sorted("DE-R-" + name for name in (rule,) + tuple(beside))
        self.assertEqual(failing(text), wanted, rule)
        self.assertEqual(failing(abroad(text)), [], rule)
        self.seen.add("DE-R-" + rule)

    def test_the_document(self):
        self.case("001", cut(INVOICE, "<cac:PaymentMeans>", "</cac:PaymentMeans>"))
        self.case("015", cut(INVOICE, "<cbc:BuyerReference>", "</cbc:BuyerReference>"))
        self.case("015", changed(INVOICE, ">ACME-PO-4500000017</cbc:BuyerReference>",
                                 "> </cbc:BuyerReference>"))
        self.case("017", changed(INVOICE, "<cbc:InvoiceTypeCode>380", "<cbc:InvoiceTypeCode>383"))
        self.case("026", changed(INVOICE, "<cbc:InvoiceTypeCode>380", "<cbc:InvoiceTypeCode>384"))
        self.assertEqual(failing(changed(
            INVOICE, "<cbc:InvoiceTypeCode>380", "<cbc:InvoiceTypeCode>384",
            "<cac:AccountingSupplierParty>", "<cac:BillingReference><cac:InvoiceDocumentReference>"
            "<cbc:ID>GLX-1</cbc:ID></cac:InvoiceDocumentReference></cac:BillingReference>"
            "<cac:AccountingSupplierParty>")), [])
        self.assertEqual(failing(changed(CREDIT_NOTE, "<cbc:CreditNoteTypeCode>381",
                                         "<cbc:CreditNoteTypeCode>396")), ["DE-R-017"])

    def test_a_seller_with_no_tax_registration(self):
        registrations = INVOICE[INVOICE.index("      <cac:PartyTaxScheme>\n        <cbc:CompanyID>DE1"):
                                INVOICE.index("      <cac:PartyLegalEntity>\n        "
                                              "<cbc:RegistrationName>Globex")]
        self.assertEqual(registrations.count("<cac:PartyTaxScheme>"), 2)
        without = INVOICE.replace(registrations, "")
        self.case("016", without)
        # Either registration will do, and so will a tax representative.
        self.assertEqual(failing(INVOICE.replace(registrations, registrations.replace(
            "DE123456789", ""))), [])
        self.assertEqual(failing(changed(without, "<cac:Delivery>",
                                         "<cac:TaxRepresentativeParty><cac:PartyName><cbc:Name>R"
                                         "</cbc:Name></cac:PartyName></cac:TaxRepresentativeParty>"
                                         "<cac:Delivery>")), [])
        # Not asked where every category is O, not subject to VAT.
        self.assertEqual(failing(without.replace("<cbc:ID>S</cbc:ID>", "<cbc:ID>O</cbc:ID>")), [])
        self.assertEqual(failing(without.replace("<cbc:ID>S</cbc:ID>", "<cbc:ID> S </cbc:ID>")), [])
        # One line, one allowance or one charge in another category is enough.
        exempt = without.replace("<cbc:ID>S</cbc:ID>", "<cbc:ID>O</cbc:ID>")
        for place in ("<cac:ClassifiedTaxCategory>\n        <cbc:ID>O",
                      "Freight</cbc:AllowanceChargeReason>\n    <cbc:Amount currencyID=\"EUR\">10.00"
                      "</cbc:Amount>\n    <cac:TaxCategory>\n      <cbc:ID>O",
                      "1000.00</cbc:BaseAmount>\n    <cac:TaxCategory>\n      <cbc:ID>O"):
            self.assertEqual(failing(changed(exempt, place, place[:-1] + "E")), ["DE-R-016"], place)
        # The breakdown's category is not asked.
        breakdown = "190.00</cbc:TaxAmount>\n      <cac:TaxCategory>\n        <cbc:ID>O"
        self.assertEqual(failing(changed(exempt, breakdown, breakdown[:-1] + "E")), [])

    def test_the_parties(self):
        self.case("002", cut(INVOICE, "<cac:Contact>", "</cac:Contact>"))
        self.case("003", changed(INVOICE, "<cbc:CityName>Hamburg</cbc:CityName>", ""))
        self.case("004", changed(INVOICE, SELLERS_PLACE, "<cbc:CityName>Hamburg</cbc:CityName>"))
        self.case("005", changed(INVOICE, "<cbc:Name>Accounts receivable</cbc:Name>", ""))
        self.case("006", changed(INVOICE, "<cbc:Telephone>+49 40 000000</cbc:Telephone>", ""),
                  ["027"])
        self.case("007", changed(INVOICE, "<cbc:ElectronicMail>ar@globex.example"
                                          "</cbc:ElectronicMail>", ""), ["028"])
        self.case("008", changed(INVOICE, "<cbc:CityName>Berlin</cbc:CityName>",
                                 "<cbc:CityName> </cbc:CityName>"))
        self.case("009", changed(INVOICE, BUYERS_PLACE, "<cbc:CityName>Berlin</cbc:CityName>"))
        address = ("</cbc:ActualDeliveryDate><cac:DeliveryLocation><cac:Address>%s<cac:Country>"
                   "<cbc:IdentificationCode>DE</cbc:IdentificationCode></cac:Country></cac:Address>"
                   "</cac:DeliveryLocation>")
        city, code = "<cbc:CityName>Kiel</cbc:CityName>", "<cbc:PostalZone>24103</cbc:PostalZone>"
        self.assertEqual(failing(changed(INVOICE, "</cbc:ActualDeliveryDate>", address % (city + code))),
                         [])
        self.case("010", changed(INVOICE, "</cbc:ActualDeliveryDate>", address % code))
        self.case("011", changed(INVOICE, "</cbc:ActualDeliveryDate>", address % city))
        rate = "<cbc:Percent>19</cbc:Percent>\n        <cac:TaxScheme>\n          <cbc:ID>VAT</cbc:ID>" \
               "\n        </cac:TaxScheme>\n      </cac:TaxCategory>\n    </cac:TaxSubtotal>"
        self.case("014", changed(INVOICE, rate, rate.replace("<cbc:Percent>19</cbc:Percent>", "")))

    def test_a_telephone_number_and_an_email_address(self):
        telephone = "<cbc:Telephone>%s</cbc:Telephone>"
        for number, right in (("+49 40 000000", True), ("112", True), ("a1b2c3", True),
                              ("12", False), ("call me", False)):
            text = changed(INVOICE, telephone % "+49 40 000000", telephone % number)
            self.assertEqual(failing(text), [] if right else ["DE-R-027"], number)
        self.seen.add("DE-R-027")
        email = "<cbc:ElectronicMail>%s</cbc:ElectronicMail>"
        for address, right in (("ar@globex.example", True), (" a@b.c ", True), ("a@b", False),
                               ("a b@c.d", False), ("a@b@c.d", False), ("a@b..c", False),
                               ("@b.c", False), ("a@b.c.", False)):
            text = changed(INVOICE, email % "ar@globex.example", email % address)
            self.assertEqual(failing(text), [] if right else ["DE-R-028"], address)
        self.seen.add("DE-R-028")
        self.assertEqual({published.PEPPOL["DE-R-027"], published.PEPPOL["DE-R-028"]}, {"warning"})

    def test_cash_discount_in_the_payment_terms(self):
        def terms(note):
            return changed(INVOICE, TERMS, "<cbc:Note>%s</cbc:Note>" % note)
        for note in ("#SKONTO#TAGE=14#PROZENT=2.00#\n",
                     "#SKONTO#TAGE=14#PROZENT=2.00#BASISBETRAG=1000.00#\n",
                     "#SKONTO#TAGE=7#PROZENT=3.00#\n#SKONTO#TAGE=14#PROZENT=2.00#\n30 days net",
                     "30 days net\n  #SKONTO#TAGE=14#PROZENT=2.00#  \n",
                     "30 days net, no # here",
                     "#SKONTO#TAGE=14#PROZENT=2.00#BASISBETRAG=-10.00#\r\n"):
            self.assertEqual(failing(terms(note)), [], note)
        for note in ("#SKONTO#TAGE=14#PROZENT=2#\n",                # two decimals
                     "#SKONTO#TAGE=14#PROZENT=2.00\n",              # no closing #
                     "#skonto#TAGE=14#PROZENT=2.00#\n",
                     "#SKONTO#PROZENT=2.00#TAGE=14#\n",
                     "#RABATT#TAGE=14#PROZENT=2.00#\n",
                     "#SKONTO#TAGE=14#PROZENT=2.00#",               # no line break after it
                     "#SKONTO#TAGE=14#PROZENT=2.00# 30 days net\n",
                     "  #RABATT#TAGE=14#PROZENT=2.00#\n",           # with space before it
                     "#SKONTO#TAGE=14#PROZENT=2.00#x\n#SKONTO#TAGE=7#PROZENT=3.00#\n"):
            self.assertEqual(failing(terms(note)), ["DE-R-018"], note)
            self.assertEqual(failing(abroad(terms(note))), [], note)
        self.seen.add("DE-R-018")

    def test_attached_documents(self):
        def attached(*names):
            return changed(INVOICE, "<cac:AccountingSupplierParty>", "".join(
                ATTACHED % ("T-%d" % n, EMBEDDED % name) for n, name in enumerate(names))
                + "<cac:AccountingSupplierParty>")
        self.assertEqual(failing(attached("a.csv", "b.csv")), [])
        self.case("022", attached("a.csv", "b.csv", "a.csv"))
        self.assertEqual(found(attached("a.csv", "b.csv", "a.csv")),
                         [("DE-R-022", "/Invoice/cac:AdditionalDocumentReference[3]")])
        self.assertEqual(failing(attached("a.csv", "A.csv")), [])

        def located(uri):
            return changed(INVOICE, "<cac:AccountingSupplierParty>", ATTACHED % (
                "T-1", "<cac:ExternalReference>%s</cac:ExternalReference>" % uri)
                + "<cac:AccountingSupplierParty>")
        for uri in ("https://example.org/a.pdf", "ftp://x", "urn:x", "ab:"):
            self.assertEqual(failing(located("<cbc:URI>%s</cbc:URI>" % uri)), [], uri)
        for uri in ("example.org/a.pdf", "//example.org", "1a:x", "a:x", " https://x"):
            self.assertEqual(failing(located("<cbc:URI>%s</cbc:URI>" % uri)), ["DE-R-T02"], uri)
        self.case("T02", located("<cbc:Note>none</cbc:Note>"))

    def test_payment_by_credit_transfer(self):
        self.assertEqual(failing(paid("58")), [])
        self.case("023-1", paid("30", ""))
        self.case("023-1", paid("58", ""), ["019"])
        self.case("023-2", changed(INVOICE, "</cac:PayeeFinancialAccount>",
                                   "</cac:PayeeFinancialAccount>" + CARD.join(["", ""])), )
        with_mandate = changed(INVOICE, "</cac:PayeeFinancialAccount>", MANDATE % (PAYER % "DE1"))
        self.assertEqual(failing(with_mandate), ["DE-R-023-2"])
        # A transfer that is not a SEPA one is not asked for an IBAN.
        self.assertEqual(failing(changed(INVOICE, ACCOUNT, "<cbc:ID>12345</cbc:ID>")), [])
        self.case("019", changed(paid("58"), ACCOUNT, "<cbc:ID>DE02120300000000202052</cbc:ID>"))
        self.case("019", changed(paid("58"), ACCOUNT, "<cbc:ID>12345</cbc:ID>"))
        self.assertEqual(failing(changed(paid("58"), ACCOUNT,
                                         "<cbc:ID>DE02 1203 0000 0000 2020 51</cbc:ID>")), [])
        self.assertEqual(published.PEPPOL["DE-R-019"], "warning")

    def test_payment_by_card(self):
        for code in ("48", "54", "55"):
            self.assertEqual(failing(paid(code, CARD)), [], code)
            self.case("024-1", paid(code, ""))
            self.case("024-2", changed(paid(code), "<cac:PayeeFinancialAccount>",
                                       CARD + "<cac:PayeeFinancialAccount>"))

    def test_payment_by_direct_debit(self):
        debit = (MANDATE % (PAYER % "DE02120300000000202051"))[len("</cac:PayeeFinancialAccount>"):]
        self.assertEqual(failing(paid("59", debit)), [])
        self.case("025-1", paid("59", ""), ["020"])
        self.case("025-2", paid("59", CARD + debit))
        self.case("020", paid("59", debit.replace("202051", "202052")))
        self.case("031", paid("59", debit.replace(PAYER % "DE02120300000000202051", "")), ["020"])
        # The mandate wants the creditor's identifier, on the seller or a payee.
        sepa = ('<cac:PartyIdentification>\n        <cbc:ID schemeID="SEPA">DE98ZZZ09999999999</cbc:ID>'
                "\n      </cac:PartyIdentification>")
        self.case("030", changed(paid("59", debit), sepa, ""))
        self.case("030", changed(paid("59", debit), 'schemeID="SEPA"', 'schemeID="sepa"'))
        self.assertEqual(failing(changed(INVOICE, sepa, "")), [])       # no mandate, none wanted
        self.assertEqual(failing(changed(
            paid("59", debit), sepa, "", "<cac:Delivery>", "<cac:PayeeParty>%s<cac:PartyName>"
            "<cbc:Name>Factor AG</cbc:Name></cac:PartyName></cac:PayeeParty><cac:Delivery>" % sepa)), [])

    def test_zz_every_rule_failed_somewhere_above(self):
        for name in sorted(n for n in dir(self) if n.startswith("test_") and "zz" not in n):
            getattr(self, name)()
        self.assertEqual(sorted(self.seen), GERMAN)


class WhatCannotBeComputed(unittest.TestCase):
    def test_a_payment_instruction_with_two_codes(self):
        text = changed(INVOICE, MEANS % "30", MEANS % "30" + "<cbc:PaymentMeansCode>58"
                       "</cbc:PaymentMeansCode>")
        document, _findings, sent = parse_tree(text)
        said = {f.code: f.text for f in run(document, "peppol", sent) if f.code.startswith("DE-R-")}
        self.assertIn("DE-R-023-1", said)
        self.assertTrue(all("could not be computed" in text for text in said.values()))


class BothInGermany(unittest.TestCase):
    def test_a_german_seller_and_a_buyer_abroad_are_asked_none_of_them(self):
        bare = cut(cut(INVOICE, "<cac:PaymentMeans>", "</cac:PaymentMeans>"),
                   "<cac:Contact>", "</cac:Contact>")
        self.assertEqual(failing(bare), ["DE-R-001", "DE-R-002"])
        self.assertEqual(failing(abroad(bare)), [])
        seller_abroad = bare.replace("20095</cbc:PostalZone>\n        <cac:Country>\n          "
                                     "<cbc:IdentificationCode>DE", "20095</cbc:PostalZone>\n        "
                                     "<cac:Country>\n          <cbc:IdentificationCode>AT")
        self.assertNotEqual(seller_abroad, bare)
        self.assertEqual(failing(seller_abroad), [])

    def test_however_germany_is_written(self):
        bare = cut(INVOICE, "<cac:PaymentMeans>", "</cac:PaymentMeans>")
        self.assertEqual(failing(bare.replace("<cbc:IdentificationCode>DE<",
                                              "<cbc:IdentificationCode> de\n<")), ["DE-R-001"])


class AnIban(unittest.TestCase):
    def test_check_digits(self):
        for account in ("DE02120300000000202051", "GB82WEST12345698765432", "NL91ABNA0417164300",
                        "DE02 1203 0000 0000 2020 51", "\tDE02120300000000202051\n"):
            self.assertTrue(iban(account), account)
        for account in ("DE02120300000000202052", "DE03120300000000202051", "DE0212030000000020205", "de02120300000000202051",
                        "", "DE", "DE0A120300000000202051", "DE02-1203-0000-0000-2020-51"):
            self.assertFalse(iban(account), account)

    def test_a_small_letter_in_the_body_is_not_its_capital(self):
        # The published test reads a character by its code point, so `w` is
        # 64 where `W` is 32, and the right check digits are others.
        self.assertTrue(iban("GB82WEST12345698765432"))
        self.assertFalse(iban("GB82west12345698765432"))
