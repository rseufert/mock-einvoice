"""The plain business rules of EN 16931, BR-01 to BR-65: what must be there."""
import unittest
from decimal import Decimal

from mockeinvoice import write
from mockeinvoice.model import INVOICED_OBJECT_REFERENCE, PROJECT_REFERENCE, Group, Value
from mockeinvoice.rules import REGISTRY, published, run
from mockeinvoice.rules.calculation import Incomputable, doubles, normalize_space, said, xs_date
from mockeinvoice.ubl import parse

from .test_reading import invoice
from .test_rules import CREDIT_NOTE, INVOICE, LINE_CHARGE, changed, failing, found

PLAIN = sorted(i for i in published.EN16931 if i[3:].isdigit())
TAX_CATEGORY = ("<cac:TaxCategory>\n      <cbc:ID>S</cbc:ID>\n      <cbc:Percent>19</cbc:Percent>\n"
                "      <cac:TaxScheme>\n        <cbc:ID>VAT</cbc:ID>\n      </cac:TaxScheme>\n"
                "    </cac:TaxCategory>\n")
BREAKDOWN_CATEGORY = ("<cbc:ID>S</cbc:ID>\n        <cbc:Percent>19</cbc:Percent>\n"
                      "        <cac:TaxScheme>\n          <cbc:ID>VAT</cbc:ID>\n"
                      "        </cac:TaxScheme>\n      </cac:TaxCategory>\n    </cac:TaxSubtotal>")
REPRESENTATIVE = (
    "<cac:TaxRepresentativeParty><cac:PartyName><cbc:Name>Fiscal SARL</cbc:Name></cac:PartyName>"
    "<cac:PostalAddress><cbc:CityName>Lyon</cbc:CityName><cac:Country><cbc:IdentificationCode>FR"
    "</cbc:IdentificationCode></cac:Country></cac:PostalAddress><cac:PartyTaxScheme>"
    "<cbc:CompanyID>FR12345678901</cbc:CompanyID><cac:TaxScheme><cbc:ID>VAT</cbc:ID>"
    "</cac:TaxScheme></cac:PartyTaxScheme></cac:TaxRepresentativeParty><cac:Delivery>")
PAYEE = ("<cac:PayeeParty>%s</cac:PayeeParty><cac:Delivery>")
PERIOD = ("<cac:InvoicePeriod><cbc:StartDate>%s</cbc:StartDate><cbc:EndDate>%s</cbc:EndDate>"
          "</cac:InvoicePeriod>")


def cut(text: str, start: str, end: str, leave: str = "") -> str:
    """The document without what runs from `start` to the next `end`."""
    assert text.count(start) >= 1, start
    at = text.index(start)
    return text[:at] + leave + text[text.index(end, at) + len(end):]


def swap(*pairs: str):
    return lambda text: changed(text, *pairs)


def without(start: str, end: str, leave: str = ""):
    return lambda text: cut(text, start, end, leave)


def representative(*pairs: str):
    return swap("<cac:Delivery>", changed(REPRESENTATIVE, *pairs))


def detail(text: str, identifier: str) -> str:
    document, _findings = parse(text)
    return next(f.text for f in run(document, "en16931") if f.code == identifier)


class EachRuleFails(unittest.TestCase):
    """The invoice all of them pass, changed in one place.

    Each change fails its rule. Where it must fail others too, they are
    beside it: a line with no price has no price that is not negative, and a
    total that is not there does not add up.
    """
    CASES = {
        "BR-01": (without("<cbc:CustomizationID>", "</cbc:CustomizationID>"), ()),
        "BR-02": (swap("<cbc:ID>GLX-4711</cbc:ID>", "<cbc:ID> \n</cbc:ID>"), ()),
        "BR-03": (without("<cbc:IssueDate>", "</cbc:IssueDate>"), ()),
        "BR-04": (without("<cbc:InvoiceTypeCode>", "</cbc:InvoiceTypeCode>"), ()),
        "BR-05": (swap("<cbc:DocumentCurrencyCode>EUR", "<cbc:DocumentCurrencyCode>"),
                  ("BR-CL-04", "BR-CO-15")),     # and nothing is not a currency
        "BR-06": (swap("Globex GmbH</cbc:RegistrationName>", "</cbc:RegistrationName>"), ()),
        "BR-07": (without("<cbc:RegistrationName>ACME", "</cbc:RegistrationName>"), ()),
        "BR-08": (without("<cac:PostalAddress>\n        <cbc:StreetName>Industrie",
                          "</cac:PostalAddress>"), ()),
        "BR-09": (swap("20095</cbc:PostalZone>\n        <cac:Country>\n          "
                       "<cbc:IdentificationCode>DE", "20095</cbc:PostalZone>\n        "
                       "<cac:Country>\n          <cbc:IdentificationCode>"), ("BR-CL-14",)),
        "BR-10": (without("<cac:PostalAddress>\n        <cbc:StreetName>Hauptstrasse",
                          "</cac:PostalAddress>"), ()),
        "BR-11": (without("10115</cbc:PostalZone>\n        <cac:Country>", "</cac:Country>",
                          "10115</cbc:PostalZone>"), ()),
        "BR-12": (without('<cbc:LineExtensionAmount currencyID="EUR">1000.00',
                          "</cbc:LineExtensionAmount>"), ("BR-CO-10", "BR-CO-13")),
        "BR-13": (without("<cbc:TaxExclusiveAmount", "</cbc:TaxExclusiveAmount>"),
                  ("BR-CO-13", "BR-CO-15")),
        "BR-14": (without("<cbc:TaxInclusiveAmount", "</cbc:TaxInclusiveAmount>"),
                  ("BR-CO-15", "BR-CO-16")),
        "BR-15": (without("<cbc:PayableAmount", "</cbc:PayableAmount>"), ("BR-CO-16",)),
        "BR-16": (lambda text: text[:text.index("  <cac:InvoiceLine>")] + "</Invoice>",
                  ("BR-CO-10",)),
        "BR-17": (swap("<cac:Delivery>", PAYEE % "<cac:PartyIdentification><cbc:ID>77</cbc:ID>"
                       "</cac:PartyIdentification>"), ()),
        "BR-18": (representative("<cac:PartyName><cbc:Name>Fiscal SARL</cbc:Name>"
                                 "</cac:PartyName>", ""), ()),
        "BR-19": (lambda text: cut(representative()(text), "<cac:PostalAddress><cbc:CityName>Lyon",
                                   "</cac:PostalAddress>"), ()),
        "BR-20": (representative("<cac:Country><cbc:IdentificationCode>FR"
                                 "</cbc:IdentificationCode></cac:Country>", ""), ()),
        "BR-21": (swap("<cac:InvoiceLine>\n    <cbc:ID>1</cbc:ID>", "<cac:InvoiceLine>"), ()),
        "BR-22": (without('<cbc:InvoicedQuantity unitCode="C62">', "</cbc:InvoicedQuantity>"),
                  ("BR-23",)),
        "BR-23": (swap('<cbc:InvoicedQuantity unitCode="C62">', "<cbc:InvoicedQuantity>"), ()),
        "BR-24": (without('<cbc:LineExtensionAmount currencyID="EUR">800.00',
                          "</cbc:LineExtensionAmount>"), ("BR-CO-10",)),
        "BR-25": (swap("<cbc:Name>Widget</cbc:Name>", "<cbc:Name/>"), ()),
        "BR-26": (without('<cbc:PriceAmount currencyID="EUR">20.00', "</cbc:PriceAmount>"),
                  ("BR-27",)),
        "BR-27": (swap(">20.00</cbc:PriceAmount>", ">-20.00</cbc:PriceAmount>"), ()),
        "BR-28": (swap('<cbc:BaseQuantity unitCode="C62">1</cbc:BaseQuantity>',
                       '<cbc:BaseQuantity unitCode="C62">1</cbc:BaseQuantity><cac:AllowanceCharge>'
                       "<cbc:ChargeIndicator>false</cbc:ChargeIndicator>"
                       '<cbc:Amount currencyID="EUR">0.00</cbc:Amount>'
                       '<cbc:BaseAmount currencyID="EUR">-20.00</cbc:BaseAmount>'
                       "</cac:AllowanceCharge>"), ()),
        "BR-29": (swap("<cac:OrderReference>", PERIOD % ("2026-10-02", "2026-10-01")
                       + "<cac:OrderReference>"), ()),
        "BR-30": (swap("<cac:OrderLineReference>", PERIOD % ("2026-10-02", "2026-10-01")
                       + "<cac:OrderLineReference>"), ()),
        "BR-31": (swap('<cbc:Amount currencyID="EUR">10.00</cbc:Amount>\n    <cbc:BaseAmount',
                       "<cbc:BaseAmount"), ("BR-CO-11",)),
        "BR-32": (swap("1000.00</cbc:BaseAmount>\n    " + TAX_CATEGORY,
                       "1000.00</cbc:BaseAmount>\n"), ()),
        "BR-33": (swap("<cbc:AllowanceChargeReasonCode>95</cbc:AllowanceChargeReasonCode>\n"
                       "    <cbc:AllowanceChargeReason>Discount</cbc:AllowanceChargeReason>", ""),
                  ("BR-CO-21",)),
        "BR-36": (swap('Freight</cbc:AllowanceChargeReason>\n    <cbc:Amount currencyID="EUR">'
                       "10.00</cbc:Amount>", "Freight</cbc:AllowanceChargeReason>"),
                  ("BR-CO-12",)),
        "BR-37": (swap('10.00</cbc:Amount>\n    ' + TAX_CATEGORY, "10.00</cbc:Amount>\n"), ()),
        "BR-38": (swap("<cbc:AllowanceChargeReason>Freight</cbc:AllowanceChargeReason>", ""),
                  ("BR-CO-22",)),
        "BR-41": (swap('<cbc:Amount currencyID="EUR">50.00</cbc:Amount>', ""), ()),
        "BR-42": (swap("<cbc:AllowanceChargeReason>Introductory</cbc:AllowanceChargeReason>", ""),
                  ("BR-CO-23",)),
        "BR-43": (swap("<cac:Item>\n      <cbc:Description>", LINE_CHARGE % (
            "<cbc:AllowanceChargeReason>Rush</cbc:AllowanceChargeReason>")), ()),
        "BR-44": (swap("<cac:Item>\n      <cbc:Description>", LINE_CHARGE % (
            '<cbc:Amount currencyID="EUR">0.00</cbc:Amount>')), ("BR-CO-24",)),
        "BR-45": (without("<cbc:TaxableAmount", "</cbc:TaxableAmount>"), ("BR-CO-17",)),
        "BR-46": (swap('<cbc:TaxAmount currencyID="EUR">190.00</cbc:TaxAmount>\n'
                       "      <cac:TaxCategory>", "<cac:TaxCategory>"),
                  ("BR-CO-14", "BR-CO-17")),
        "BR-47": (swap(BREAKDOWN_CATEGORY, BREAKDOWN_CATEGORY.replace("<cbc:ID>S</cbc:ID>", "")),
                  ()),
        "BR-48": (swap(BREAKDOWN_CATEGORY, BREAKDOWN_CATEGORY.replace(
            "<cbc:Percent>19</cbc:Percent>", "")), ("BR-CO-17",)),
        "BR-49": (without("<cbc:PaymentMeansCode", "</cbc:PaymentMeansCode>"), ()),
        "BR-50": (swap("<cbc:ID>DE02120300000000202051</cbc:ID>", "<cbc:ID></cbc:ID>"), ()),
        "BR-51": (swap("<cbc:PaymentID>GLX-4711</cbc:PaymentID>",
                       "<cbc:PaymentID>GLX-4711</cbc:PaymentID><cac:CardAccount>"
                       "<cbc:PrimaryAccountNumberID>12345678901</cbc:PrimaryAccountNumberID>"
                       "<cbc:NetworkID>VISA</cbc:NetworkID></cac:CardAccount>"), ()),
        "BR-52": (swap("<cac:AccountingSupplierParty>", "<cac:AdditionalDocumentReference>"
                       "<cbc:DocumentDescription>Timesheet</cbc:DocumentDescription>"
                       "</cac:AdditionalDocumentReference><cac:AccountingSupplierParty>"), ()),
        "BR-53": (swap("<cbc:BuyerReference>", "<cbc:TaxCurrencyCode>USD</cbc:TaxCurrencyCode>"
                       "<cbc:BuyerReference>"), ()),
        "BR-54": (swap("<cbc:Value>Grey</cbc:Value>", ""), ()),
        "BR-55": (swap("<cac:AccountingSupplierParty>", "<cac:BillingReference/>"
                       "<cac:AccountingSupplierParty>"), ()),
        "BR-56": (representative("<cbc:ID>VAT</cbc:ID>", "<cbc:ID>TAX</cbc:ID>"), ()),
        "BR-57": (swap("</cbc:ActualDeliveryDate>", "</cbc:ActualDeliveryDate>"
                       "<cac:DeliveryLocation><cac:Address><cbc:CityName>Berlin</cbc:CityName>"
                       "</cac:Address></cac:DeliveryLocation>"), ()),
        "BR-61": (without("<cac:PayeeFinancialAccount>", "</cac:PayeeFinancialAccount>"), ()),
        "BR-62": (swap('<cbc:EndpointID schemeID="0088">4012345000009',
                       "<cbc:EndpointID>4012345000009"), ()),
        "BR-63": (swap('<cbc:EndpointID schemeID="0088">4098765000004',
                       "<cbc:EndpointID>4098765000004"), ()),
        "BR-64": (swap("</cac:SellersItemIdentification>", "</cac:SellersItemIdentification>"
                       "<cac:StandardItemIdentification><cbc:ID>4012345000016</cbc:ID>"
                       "</cac:StandardItemIdentification>"), ()),
        "BR-65": (swap(' listID="STI"', ""), ()),
    }

    # What the standard rated category's own rules make of the same changes:
    # a breakdown whose amounts no longer come to what the lines, allowances
    # and charges say (BR-S-08, BR-S-09), or that is no longer there (BR-S-01).
    VAT = {'BR-16': ['BR-S-08'], 'BR-24': ['BR-S-08'], 'BR-31': ['BR-S-08'], 'BR-32': ['BR-S-08'], 'BR-36': ['BR-S-08'], 'BR-37': ['BR-S-08'], 'BR-45': ['BR-S-08', 'BR-S-09'], 'BR-46': ['BR-S-09'], 'BR-47': ['BR-S-01'], 'BR-48': ['BR-S-09']}

    def test_every_plain_rule_is_built_and_has_a_case(self):
        self.assertEqual(len(PLAIN), 58)
        self.assertLessEqual(set(PLAIN), set(REGISTRY["en16931"]))
        self.assertEqual(sorted(self.CASES), PLAIN)

    def test_each_change_fails_its_rule_and_only_what_is_beside_it(self):
        for identifier, (change, beside) in self.CASES.items():
            with self.subTest(rule=identifier):
                self.assertEqual(failing(change(INVOICE)), sorted(
                    (identifier,) + beside + tuple(self.VAT.get(identifier, ()))))

    def test_all_but_one_are_fatal_and_too_much_of_a_card_number_is_a_warning(self):
        self.assertEqual([i for i in PLAIN if published.EN16931[i] != "fatal"], ["BR-51"])
        document, _findings = parse(self.CASES["BR-51"][0](INVOICE))
        finding, = run(document, "en16931")
        self.assertEqual((finding.level, finding.code, finding.path),
                         ("warning", "BR-51", "BG-16"))

    def test_the_same_changes_fail_the_same_rules_in_a_credit_note(self):
        # The changes are written for an invoice, so the credit note is given
        # the invoice's names for things, changed, and given its own back.
        names = (("InvoiceLine", "CreditNoteLine"), ("InvoicedQuantity", "CreditedQuantity"),
                 ("InvoiceTypeCode", "CreditNoteTypeCode"), ("</Invoice>", "</CreditNote>"),
                 ("<cbc:ID>GLX-4711</cbc:ID>\n  <cbc:IssueDate>",
                  "<cbc:ID>GLX-4711-C</cbc:ID>\n  <cbc:IssueDate>"))
        for identifier in ("BR-02", "BR-04", "BR-16", "BR-21", "BR-22", "BR-23", "BR-26",
                           "BR-30", "BR-42", "BR-54", "BR-65"):
            with self.subTest(rule=identifier):
                change, beside = self.CASES[identifier]
                text = CREDIT_NOTE
                for invoices, credit_notes in names:
                    text = text.replace(credit_notes, invoices)
                text = change(text)
                for invoices, credit_notes in names:
                    text = text.replace(invoices, credit_notes)
                self.assertEqual(parse(text)[0].kind, "CreditNote")
                self.assertEqual(failing(text), sorted(
                    (identifier,) + beside + tuple(self.VAT.get(identifier, ()))))

    def test_where_a_failure_is_says_which_of_several(self):
        self.assertEqual(found(self.CASES["BR-21"][0](INVOICE)), [("BR-21", "BG-25[1]")])
        self.assertEqual(found(self.CASES["BR-41"][0](INVOICE)), [("BR-41", "BG-25[2]/BG-27")])
        self.assertEqual(found(self.CASES["BR-65"][0](INVOICE)), [("BR-65", "BG-25[1]/BT-158")])
        self.assertEqual(found(self.CASES["BR-02"][0](INVOICE)), [("BR-02", "BT-1")])
        self.assertIn("it is there with nothing in it", detail(self.CASES["BR-02"][0](INVOICE), "BR-02"))
        self.assertIn("it is not there", detail(self.CASES["BR-03"][0](INVOICE), "BR-03"))

    def test_a_whole_tax_representative_and_a_whole_payee_fail_nothing(self):
        self.assertEqual(found(representative()(INVOICE)), [])
        self.assertEqual(found(changed(INVOICE, "<cac:Delivery>", PAYEE % (
            "<cac:PartyIdentification><cbc:ID>77</cbc:ID></cac:PartyIdentification>"
            "<cac:PartyName><cbc:Name>Factor AG</cbc:Name></cac:PartyName>"))), [])


class ThereOrSomethingInIt(unittest.TestCase):
    """The two things the published tests ask, which are not the same."""

    def test_a_rule_that_asks_for_something_in_it_fails_on_white_space(self):
        for inside in ("", " ", "\t\r\n "):
            self.assertIn("BR-02", failing(invoice("<cbc:ID>%s</cbc:ID>" % inside)), repr(inside))
        self.assertNotIn("BR-02", failing(invoice("<cbc:ID>1</cbc:ID>")))
        # A no-break space is not white space to XPath.
        self.assertNotIn("BR-02", failing(invoice("<cbc:ID> </cbc:ID>")))

    def test_a_rule_that_asks_only_that_it_is_there_passes_an_empty_element(self):
        line = "<cac:InvoiceLine>%s</cac:InvoiceLine>"
        self.assertNotIn("BR-24", failing(invoice(line % "<cbc:LineExtensionAmount/>")))
        self.assertIn("BR-24", failing(invoice(line % "")))
        self.assertNotIn("BR-22", failing(invoice(line % "<cbc:InvoicedQuantity/>")))
        self.assertIn("BR-23", failing(invoice(line % "<cbc:InvoicedQuantity/>")))
        self.assertNotIn("BR-23", failing(invoice(line % '<cbc:InvoicedQuantity unitCode=""/>')))

    def test_an_element_twice_where_the_test_takes_one_cannot_be_computed(self):
        text = invoice("<cbc:IssueDate>2026-10-02</cbc:IssueDate><cbc:IssueDate>2026-10-02"
                       "</cbc:IssueDate>")
        self.assertIn("could not be computed: BT-2 occurs 2 times", detail(text, "BR-03"))

    def test_a_rule_about_a_group_is_not_asked_where_the_group_is_not(self):
        asked = failing(invoice("<cac:InvoiceLine/>"))
        for identifier in ("BR-09", "BR-11", "BR-12", "BR-17", "BR-18", "BR-20", "BR-29", "BR-31",
                           "BR-36", "BR-41", "BR-45", "BR-49", "BR-52", "BR-55", "BR-57"):
            self.assertNotIn(identifier, asked)
        for identifier in ("BR-01", "BR-08", "BR-10", "BR-21", "BR-26", "BR-27"):
            self.assertIn(identifier, asked)
        self.assertNotIn("BR-16", asked)
        self.assertIn("BR-16", failing(invoice("")))

    def test_an_empty_group_is_asked(self):
        asked = failing(invoice(
            "<cac:AccountingSupplierParty><cac:Party><cac:PostalAddress/></cac:Party>"
            "</cac:AccountingSupplierParty><cac:LegalMonetaryTotal/><cac:PaymentMeans/>"
            "<cac:TaxTotal><cac:TaxSubtotal/></cac:TaxTotal>"))
        self.assertNotIn("BR-08", asked)
        for identifier in ("BR-09", "BR-12", "BR-13", "BR-14", "BR-15", "BR-45", "BR-46", "BR-47",
                           "BR-48", "BR-49"):
            self.assertIn(identifier, asked)


class ThePrice(unittest.TestCase):
    def price(self, *amounts: str, gross: str = "") -> list:
        inside = "".join('<cbc:PriceAmount currencyID="EUR">%s</cbc:PriceAmount>' % amount
                         for amount in amounts)
        if gross:
            inside += ("<cac:AllowanceCharge><cbc:ChargeIndicator>false</cbc:ChargeIndicator>"
                       '<cbc:BaseAmount currencyID="EUR">%s</cbc:BaseAmount></cac:AllowanceCharge>'
                       % gross)
        return failing(invoice("<cac:InvoiceLine><cac:Price>%s</cac:Price></cac:InvoiceLine>"
                               % inside))

    def test_nought_is_not_negative_and_a_number_is_read_as_a_double(self):
        for amount in ("0", "-0", "0.00", " 5 ", "1e3", "INF", "-1e-400"):
            self.assertNotIn("BR-27", self.price(amount), amount)
        for amount in ("-0.01", "-1e3", "-INF", "NaN"):
            self.assertIn("BR-27", self.price(amount), amount)

    def test_no_price_is_not_a_price_that_is_not_negative(self):
        self.assertIn("BR-27", self.price())
        self.assertIn("BR-26", self.price())

    def test_text_that_is_no_number_cannot_be_computed(self):
        text = invoice('<cac:InvoiceLine><cac:Price><cbc:PriceAmount currencyID="EUR">free'
                       "</cbc:PriceAmount></cac:Price></cac:InvoiceLine>")
        self.assertIn("could not be computed: BT-146 is 'free'", detail(text, "BR-27"))
        self.assertIn("BR-27", self.price(""))

    def test_of_two_prices_one_that_is_not_negative_is_enough(self):
        self.assertNotIn("BR-27", self.price("-1", "1"))
        self.assertIn("BR-27", self.price("-1", "-2"))

    def test_a_gross_price_need_not_be_there_but_may_not_be_negative(self):
        self.assertNotIn("BR-28", self.price("1"))
        self.assertNotIn("BR-28", self.price("1", gross="0"))
        self.assertIn("BR-28", self.price("1", gross="-0.01"))
        self.assertIn("BR-28", self.price("1", gross="NaN"))


class ThePeriod(unittest.TestCase):
    def period(self, start: str, end: str, line: bool = False) -> list:
        inside = "<cac:InvoicePeriod>%s%s</cac:InvoicePeriod>" % (
            "<cbc:StartDate>%s</cbc:StartDate>" % start if start is not None else "",
            "<cbc:EndDate>%s</cbc:EndDate>" % end if end is not None else "")
        return failing(invoice("<cac:InvoiceLine>%s</cac:InvoiceLine>" % inside if line
                               else inside))

    def test_it_may_end_the_day_it_starts_and_one_date_alone_is_no_period_to_compare(self):
        self.assertNotIn("BR-29", self.period("2026-10-02", "2026-10-02"))
        self.assertNotIn("BR-29", self.period("2026-10-02", "2027-01-01"))
        self.assertIn("BR-29", self.period("2027-01-01", "2026-12-31"))
        self.assertNotIn("BR-29", self.period("2026-10-02", None))
        self.assertNotIn("BR-29", self.period(None, "2026-10-02"))
        self.assertNotIn("BR-29", self.period(None, None))
        # Alone, a date is not even read.
        self.assertNotIn("BR-29", self.period("soon", None))

    def test_the_documents_period_and_a_lines_are_two_rules(self):
        self.assertEqual([i for i in self.period("2026-10-02", "2026-10-01")
                          if i in ("BR-29", "BR-30")], ["BR-29"])
        self.assertEqual([i for i in self.period("2026-10-02", "2026-10-01", line=True)
                          if i in ("BR-29", "BR-30")], ["BR-30"])

    def test_a_date_that_is_no_date_cannot_be_computed(self):
        for start in ("02.10.2026", "2026-02-30", "2026-10-2", "", "2026-10-02+15:00"):
            document, _findings = parse(invoice(PERIOD % (start, "2026-10-03")))
            finding = next(f for f in run(document, "en16931") if f.code == "BR-29")
            self.assertIn("could not be computed: BT-73 is %r, which is not a date" % start,
                          finding.text)

    def test_a_date_with_a_time_zone_is_compared_as_the_moment_its_day_starts(self):
        # The 2nd at +14:00 starts before the 1st at -12:00 does.
        self.assertNotIn("BR-29", self.period("2026-10-02+14:00", "2026-10-01-12:00"))
        self.assertIn("BR-29", self.period("2026-10-02-12:00", "2026-10-02+14:00"))
        self.assertNotIn("BR-29", self.period("2026-10-02Z", "2026-10-02"))
        self.assertNotIn("BR-29", self.period(" 2026-10-02\n", "2026-10-02"))


class ThePayee(unittest.TestCase):
    def payee(self, inside: str) -> list:
        return [code for code, _path in found(changed(INVOICE, "<cac:Delivery>", PAYEE % inside))]

    def identified(self, identifier: str, scheme: str = "") -> str:
        return ("<cac:PartyIdentification><cbc:ID%s>%s</cbc:ID></cac:PartyIdentification>"
                % (' schemeID="%s"' % scheme if scheme else "", identifier))

    def named(self, name: str) -> str:
        return "<cac:PartyName><cbc:Name>%s</cbc:Name></cac:PartyName>" % name

    def test_its_name_is_not_the_sellers_trading_name(self):
        self.assertEqual(self.payee(self.named("Globex")), ["BR-17"])
        # The seller's legal name is not what the test compares with.
        self.assertEqual(self.payee(self.named("Globex GmbH")), [])
        self.assertEqual(self.payee(self.named("globex")), [])
        self.assertEqual(self.payee(self.named("Globex ")), [])

    def test_no_identifier_of_its_is_one_of_the_sellers(self):
        name = self.named("Factor AG")
        self.assertEqual(self.payee(self.identified("4012345000009") + name), ["BR-17"])
        self.assertEqual(self.payee(self.identified("4012345000009", "0088") + name), ["BR-17"])
        self.assertEqual(self.payee(self.identified("4012345000010") + name), [])
        # The creditor identifier is an identifier like any other to this test.
        self.assertEqual(self.payee(self.identified("DE98ZZZ09999999999", "SEPA") + name),
                         ["BR-17"])
        self.assertEqual(self.payee(self.identified("DE98ZZZ09999999999") + name), ["BR-17"])
        self.assertEqual(self.payee(self.identified("DE98ZZZ0000", "SEPA") + name), [])


class ThePayment(unittest.TestCase):
    def means(self, code: str, account: str = None) -> list:
        inside = "<cbc:PaymentMeansCode>%s</cbc:PaymentMeansCode>" % code
        if account is not None:
            inside += "<cac:PayeeFinancialAccount>%s</cac:PayeeFinancialAccount>" % account
        return [i for i in failing(invoice("<cac:PaymentMeans>%s</cac:PaymentMeans>" % inside))
                if i in ("BR-49", "BR-50", "BR-61")]

    def test_a_credit_transfer_names_its_account(self):
        for code in ("30", "58"):
            self.assertEqual(self.means(code, "<cbc:ID>DE02</cbc:ID>"), [])
            self.assertEqual(self.means(code), ["BR-61"])
            self.assertEqual(self.means(code, ""), ["BR-50", "BR-61"])
            self.assertEqual(self.means(code, "<cbc:ID> </cbc:ID>"), ["BR-50"])
        self.assertEqual(self.means("31"), [])
        self.assertEqual(self.means("49", ""), [])
        self.assertEqual(self.means("300"), [])

    def test_the_two_rules_do_not_read_the_code_alike(self):
        # With a space around it the code is a transfer to one and not the other.
        self.assertEqual(self.means(" 30 ", ""), ["BR-61"])
        self.assertEqual(self.means(" 30 ", "<cbc:ID/>"), [])

    def test_each_payment_instruction_is_asked(self):
        text = changed(INVOICE, "  <cac:PaymentTerms>", "<cac:PaymentMeans><cbc:PaymentMeansCode>"
                       "58</cbc:PaymentMeansCode></cac:PaymentMeans><cac:PaymentTerms>")
        self.assertEqual(found(text), [("BR-61", "BG-16[2]")])

    def test_ten_characters_of_a_card_number_are_not_too_many(self):
        def card(number):
            return "BR-51" in failing(invoice(
                "<cac:PaymentMeans><cac:CardAccount><cbc:PrimaryAccountNumberID>%s"
                "</cbc:PrimaryAccountNumberID></cac:CardAccount></cac:PaymentMeans>" % number))
        self.assertFalse(card("1234567890"))
        self.assertFalse(card("  1234567890  "))
        self.assertTrue(card("12345678901"))
        self.assertTrue(card("1234 567890"))


class TheRest(unittest.TestCase):
    def test_a_breakdown_not_subject_to_vat_needs_no_rate(self):
        def breakdown(category):
            return "BR-48" in failing(invoice(
                "<cac:TaxTotal><cac:TaxSubtotal><cac:TaxCategory><cbc:ID>%s</cbc:ID><cac:TaxScheme>"
                "<cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:TaxCategory></cac:TaxSubtotal>"
                "</cac:TaxTotal>" % category))
        self.assertFalse(breakdown("O"))
        self.assertFalse(breakdown(" O "))
        self.assertTrue(breakdown("o"))
        self.assertTrue(breakdown("E"))

    def test_a_vat_accounting_currency_wants_a_vat_total_in_exactly_it(self):
        def text(code, *currencies):
            return "BR-53" in failing(invoice(
                "<cbc:DocumentCurrencyCode>EUR</cbc:DocumentCurrencyCode><cbc:TaxCurrencyCode>%s"
                "</cbc:TaxCurrencyCode>%s" % (code, "".join(
                    '<cac:TaxTotal><cbc:TaxAmount currencyID="%s">1.00</cbc:TaxAmount>'
                    "</cac:TaxTotal>" % currency for currency in currencies))))
        self.assertTrue(text("USD"))
        self.assertTrue(text("USD", "EUR"))
        self.assertFalse(text("USD", "EUR", "USD"))
        self.assertFalse(text("EUR", "EUR"))
        self.assertTrue(text(" USD", "EUR", "USD"))
        self.assertTrue(text("usd", "EUR", "USD"))
        self.assertNotIn("BR-53", failing(invoice(
            "<cbc:DocumentCurrencyCode>EUR</cbc:DocumentCurrencyCode>")))

    def test_a_tax_representatives_vat_identifier_is_one_whose_scheme_is_vat(self):
        for scheme, fails in (("VAT", False), (" vat ", False), ("TAX", True), ("", True)):
            text = representative("<cbc:ID>VAT</cbc:ID>", "<cbc:ID>%s</cbc:ID>" % scheme)(INVOICE)
            self.assertEqual("BR-56" in failing(text), fails, scheme)
        self.assertIn("BR-56", failing(invoice("<cac:TaxRepresentativeParty/>")))

    def test_a_scheme_named_as_nothing_is_still_named(self):
        text = changed(INVOICE, '<cbc:EndpointID schemeID="0088">4012345000009',
                       '<cbc:EndpointID schemeID="">4012345000009')
        # To the rule that wants one named. Nothing is not in the code list.
        self.assertEqual(found(text), [("BR-CL-25", "BT-34")])

    def test_an_item_attribute_wants_both_and_says_which_is_missing(self):
        text = changed(INVOICE, "<cbc:Name>Colour</cbc:Name>", "")
        self.assertEqual(found(text), [("BR-54", "BG-25[1]/BG-32")])
        self.assertIn("it has no BT-160", detail(text, "BR-54"))
        self.assertNotIn("BR-54", failing(changed(INVOICE, "<cbc:Value>Grey</cbc:Value>",
                                                  "<cbc:Value/>")))


class AReferenceToldByItsTypeCode(unittest.TestCase):
    """The invoiced object and, on a credit note, the project: an additional
    document reference like the supporting documents, and asked the same."""
    OBJECT = ("<cac:AdditionalDocumentReference>%s<cbc:DocumentTypeCode>130"
              "</cbc:DocumentTypeCode></cac:AdditionalDocumentReference>")

    def test_an_invoiced_object_reference_with_no_identifier_fails(self):
        self.assertIn(("BR-52", "BT-18"), found(invoice(self.OBJECT % "")))
        self.assertIn("BR-52", failing(invoice(self.OBJECT % "<cbc:ID> </cbc:ID>")))
        self.assertNotIn("BR-52", failing(invoice(self.OBJECT % "<cbc:ID>M-1</cbc:ID>")))

    def test_a_credit_notes_project_reference_with_no_identifier_fails(self):
        text = changed(CREDIT_NOTE, "<cbc:ID>PRJ-7</cbc:ID>", "")
        self.assertEqual(found(text), [("BR-52", "BT-11")])
        self.assertEqual(found(CREDIT_NOTE), [])
        # On an invoice the project has an element of its own, which is no
        # additional document reference and is not asked.
        self.assertNotIn("BR-52", failing(invoice("<cac:ProjectReference/>")))
        self.assertNotIn("BR-52", failing(invoice(
            "<cac:ProjectReference><cbc:ID/></cac:ProjectReference>")))

    def test_a_supporting_documents_identifier_has_something_in_it(self):
        reference = "<cac:AdditionalDocumentReference>%s</cac:AdditionalDocumentReference>"
        self.assertEqual(found(invoice(reference % "<cbc:ID> </cbc:ID>"))[0], ("BR-52", "BG-24"))
        self.assertNotIn("BR-52", failing(invoice(reference % "<cbc:ID>T-1</cbc:ID>")))

    def test_that_it_was_there_is_held_only_when_nothing_else_says_so(self):
        document, findings = parse(invoice(self.OBJECT % ""))
        self.assertEqual((document.present, findings), ({INVOICED_OBJECT_REFERENCE}, []))
        self.assertTrue(document.has(INVOICED_OBJECT_REFERENCE))
        document, _findings = parse(invoice(self.OBJECT % "<cbc:ID>M-1</cbc:ID>"))
        self.assertEqual(document.present, set())
        self.assertTrue(document.has(INVOICED_OBJECT_REFERENCE))
        document, _findings = parse(invoice(""))
        self.assertFalse(document.has(INVOICED_OBJECT_REFERENCE))
        self.assertFalse(document.has(PROJECT_REFERENCE))

    def test_it_is_written_back_as_what_it_was(self):
        for text in (invoice(self.OBJECT % ""), changed(CREDIT_NOTE, "<cbc:ID>PRJ-7</cbc:ID>", "")):
            document, _findings = parse(text)
            again, findings = parse(write(document))
            self.assertEqual((again, findings), (document, []))
            self.assertEqual(again.all("BG-24"), [])
        self.assertIn(b"<cbc:DocumentTypeCode>130</cbc:DocumentTypeCode>",
                      write(parse(invoice(self.OBJECT % ""))[0]))


class XPathsOwn(unittest.TestCase):
    def group(self, *texts: str) -> Group:
        group = Group()
        for text in texts:
            group.add("BT-1", Value(text))
        return group

    def test_white_space_is_four_characters(self):
        self.assertEqual(normalize_space(" a \t\r\n b "), "a b")
        self.assertEqual(normalize_space(" a "), " a ")
        self.assertEqual(normalize_space(""), "")

    def test_what_a_term_says(self):
        self.assertEqual(said(self.group(), "BT-1"), "")
        self.assertEqual(said(self.group("  x  y "), "BT-1"), "x y")
        with self.assertRaises(Incomputable):
            said(self.group("x", "y"), "BT-1")

    def test_doubles(self):
        self.assertEqual(doubles(self.group("1.50", " -2 ", ".5", "5.", "1E2", "-INF"), "BT-1"),
                         [Decimal("1.5"), Decimal(-2), Decimal("0.5"), Decimal(5), Decimal(100),
                          Decimal("-Infinity")])
        self.assertEqual(doubles(self.group("NaN", "-1e-400"), "BT-1"), [None, Decimal(0)])
        self.assertEqual(doubles(self.group(), "BT-1"), [])
        for text in ("", "1,5", "+INF", "nan", "1e", "0x10", "1 000"):
            with self.assertRaises(Incomputable, msg=text):
                doubles(self.group(text), "BT-1")

    def test_dates(self):
        self.assertIsNone(xs_date(self.group(), "BT-1"))
        day = xs_date(self.group("2026-10-02"), "BT-1")
        self.assertEqual(xs_date(self.group("2026-10-02Z"), "BT-1"), day)
        self.assertEqual(xs_date(self.group("2026-10-03"), "BT-1") - day, 1440)
        self.assertEqual(xs_date(self.group("2026-10-02+01:30"), "BT-1") - day, -90)
        self.assertEqual(xs_date(self.group("2026-10-02-14:00"), "BT-1") - day, 840)
        for text in ("2026-10-02T00:00:00", "26-10-02", "2026-13-01", "2026-10-02+14:01",
                     "2026-10-02+01:60", "2026-10-02 Z", "0000-01-01", "12026-01-01"):
            with self.assertRaises(Incomputable, msg=text):
                xs_date(self.group(text), "BT-1")
        with self.assertRaises(Incomputable):
            xs_date(self.group("2026-10-02", "2026-10-02"), "BT-1")
