"""The rule engine, and the calculation and decimal rules of EN 16931.

The plain business rules, BR-01 to BR-65, are in `test_business_rules.py`."""
import unittest
from decimal import Decimal

from mockeinvoice import check, read, rules, validate
from mockeinvoice.model import Finding
from mockeinvoice.rules import REGISTRY, Report, published, rule
from mockeinvoice.rules.calculation import cents, decimals_after_point, xpath_round
from mockeinvoice.ubl import parse

from . import sample
from .test_reading import invoice

INVOICE = sample("peppol-invoice.xml").decode("utf-8")
CREDIT_NOTE = sample("peppol-creditnote.xml").decode("utf-8")
VAT_CATEGORY = ("<cac:ClassifiedTaxCategory>\n        <cbc:ID>S</cbc:ID>\n"
                "        <cbc:Percent>19</cbc:Percent>\n        <cac:TaxScheme>\n"
                "          <cbc:ID>VAT</cbc:ID>\n        </cac:TaxScheme>\n"
                "      </cac:ClassifiedTaxCategory>")
LINE_ALLOWANCE = ("<cbc:AllowanceChargeReason>Introductory</cbc:AllowanceChargeReason>\n"
                  '      <cbc:Amount currencyID="EUR">50.00</cbc:Amount>')
LINE_CHARGE = ("<cac:AllowanceCharge><cbc:ChargeIndicator>true</cbc:ChargeIndicator>"
               "%s</cac:AllowanceCharge>\n    <cac:Item>\n      <cbc:Description>")


def changed(text: str, *pairs: str) -> str:
    """The document with each `old` made `new`, once; it must be there once."""
    for old, new in zip(pairs[::2], pairs[1::2]):
        assert text.count(old) >= 1, old
        text = text.replace(old, new, 1)
    return text


def found(text: str):
    """The rules that fail on a document, as (identifier, where)."""
    document, _findings = parse(text)
    return [(f.code, f.path) for f in rules.run(document, "en16931")]


def failing(text: str):
    return sorted({code for code, _path in found(text)})


class TheEngine(unittest.TestCase):
    def test_every_rule_built_is_one_its_layer_publishes(self):
        for layer, built in REGISTRY.items():
            self.assertLessEqual(set(built), set(published.LAYERS[layer]), layer)

    def test_all_of_the_core_but_the_rules_about_ubl_itself_is_built(self):
        expected = {i for i in published.EN16931 if not i.startswith("UBL-")}
        self.assertEqual(set(REGISTRY["en16931"]), expected)
        self.assertEqual(len(expected), 44 + 58 + 98 + 23)
        self.assertEqual((REGISTRY["peppol"], REGISTRY["xrechnung"]), ({}, {}))

    def test_the_published_lists_are_the_sizes_the_sources_have(self):
        self.assertEqual({layer: len(found) for layer, found in published.LAYERS.items()},
                         {"en16931": 979, "peppol": 166, "xrechnung": 55})
        self.assertEqual(published.EN16931["BR-CO-10"], "fatal")
        self.assertEqual(published.EN16931["UBL-CR-001"], "warning")
        for layer, (name, link) in published.SOURCES.items():
            self.assertTrue(link.startswith("https://github.com/"), layer)
            self.assertTrue(name)

    def test_a_rule_nobody_publishes_cannot_be_written_nor_one_written_twice(self):
        with self.assertRaises(ValueError):
            rule("en16931", "BR-CO-99", "made up")(lambda document: [])
        with self.assertRaises(ValueError):
            rule("en16931", "BR-CO-10", "again")(lambda document: [])
        self.assertNotIn("BR-CO-99", REGISTRY["en16931"])

    def test_a_finding_has_the_rules_id_its_flag_our_words_and_where_it_is_published(self):
        document, _findings = parse(changed(INVOICE, ">800.00</cbc:LineExtensionAmount>",
                                            ">800.01</cbc:LineExtensionAmount>"))
        finding, = rules.run(document, "en16931")
        self.assertEqual((finding.level, finding.code, finding.path),
                         ("fatal", "BR-CO-10", "BT-106"))
        self.assertEqual(finding.text, "the sum of line net amounts (BT-106) is the lines' net "
                         "amounts (BT-131) added up: it is 1000.00 and the lines come to 1000.01")
        self.assertEqual(finding.link, published.SOURCES["en16931"][1])
        self.assertIn("validation-1.3.16", finding.link)

    def test_failures_come_in_the_order_the_rules_are_published(self):
        text = changed(INVOICE, ">1190.00</cbc:PayableAmount>", ">1.000</cbc:PayableAmount>",
                       "<cbc:CompanyID>DE123456789", "<cbc:CompanyID>XX123456789")
        order = list(published.EN16931)
        codes = [code for code, _path in found(text)]
        self.assertEqual(sorted(codes), ["BR-CO-09", "BR-CO-16", "BR-DEC-18"])
        self.assertEqual(codes, sorted(codes, key=order.index))


class TheReport(unittest.TestCase):
    def test_a_document_nothing_is_wrong_with_is_not_judged_while_rules_are_unbuilt(self):
        document, report = validate(INVOICE)
        self.assertEqual(document.text("BT-1"), "GLX-4711")
        self.assertEqual((report.specification, report.findings, report.verdict),
                         ("peppol", [], "not judged"))
        self.assertEqual(len(report.ran), 223)
        self.assertEqual(sorted(report.not_built), ["en16931", "peppol"])
        self.assertEqual(len(report.not_built["en16931"]), 979 - 223)
        self.assertEqual(len(report.not_built["peppol"]), 166)
        self.assertNotIn("BR-CO-10", report.not_built["en16931"])
        self.assertEqual(report.not_built["en16931"]["UBL-SR-01"], "fatal")
        fatal = sum(1 for flag in published.EN16931.values() if flag == "fatal") \
            + sum(1 for flag in published.PEPPOL.values() if flag == "fatal")
        built_fatal = sum(1 for i in REGISTRY["en16931"] if published.EN16931[i] == "fatal")
        self.assertEqual(report.unasked, fatal - built_fatal)

    def test_an_xrechnung_document_is_owed_xrechnungs_rules_and_not_peppols(self):
        _document, report = validate(sample("xrechnung-invoice.xml"))
        self.assertEqual(sorted(report.not_built), ["en16931", "xrechnung"])
        self.assertEqual(len(report.not_built["xrechnung"]), 55)
        self.assertEqual(report.verdict, "not judged")

    def test_one_failing_rule_is_invalid(self):
        _document, report = validate(changed(INVOICE, ">1190.00</cbc:PayableAmount>",
                                             ">1189.00</cbc:PayableAmount>"))
        self.assertEqual(report.verdict, "invalid")
        self.assertEqual([f.code for f in report.failures], ["BR-CO-16"])

    def test_what_the_reader_said_is_first_and_an_error_of_its_counts(self):
        _document, report = validate(changed(
            INVOICE, "<cbc:ID>GLX-4711</cbc:ID>\n  <cbc:IssueDate>",
            "<cbc:ID>GLX-4711</cbc:ID><cbc:ID>again</cbc:ID><cbc:UBLVersionID>2.1"
            "</cbc:UBLVersionID>\n  <cbc:IssueDate>"))
        self.assertEqual([(f.level, f.code) for f in report.findings],
                         [("error", "REPEATED"), ("warning", "UNHELD"), ("fatal", "BR-02")])
        self.assertEqual(report.verdict, "invalid")
        # The rule that takes one number cannot be computed with two.
        self.assertEqual([f.code for f in report.failures], ["REPEATED", "BR-02"])

    def test_a_warning_alone_is_not_invalid(self):
        _document, report = validate(changed(
            INVOICE, "<cbc:IssueDate>", "<cbc:UBLVersionID>2.1</cbc:UBLVersionID><cbc:IssueDate>"))
        self.assertEqual(([f.code for f in report.findings], report.verdict),
                         (["UNHELD"], "not judged"))

    def test_valid_is_only_said_when_no_fatal_rule_is_left_unasked(self):
        self.assertEqual(Report("peppol").verdict, "valid")
        self.assertEqual(Report("peppol", not_built={"peppol": {"X": "warning"}}).verdict, "valid")
        self.assertEqual(Report("peppol", not_built={"peppol": {"X": "fatal"}}).verdict,
                         "not judged")
        self.assertEqual(Report("peppol", [Finding("fatal", "X", "/", "x")]).verdict, "invalid")

    def test_a_specification_nobody_named_is_an_error(self):
        document, _specification, _findings = read(INVOICE)
        with self.assertRaises(ValueError):
            check(document, "en16931")


class TheArithmetic(unittest.TestCase):
    """XPath's, which is what the published rules compute with."""

    def test_a_tie_rounds_towards_positive_infinity(self):
        for number, rounded in (("2.5", "3"), ("-2.5", "-2"), ("0.5", "1"), ("-0.5", "0"),
                                ("2.4", "2"), ("-2.6", "-3"), ("3", "3")):
            self.assertEqual(xpath_round(Decimal(number)), Decimal(rounded), number)

    def test_cents_are_rounded_the_same_way(self):
        for number, rounded in (("1.005", "1.01"), ("-1.005", "-1.00"), ("1.004", "1.00"),
                                ("-1.006", "-1.01"), ("190", "190")):
            self.assertEqual(cents(Decimal(number)), Decimal(rounded), number)
        self.assertIsNone(cents(None))

    def test_the_digits_after_the_point_are_counted_in_the_text_as_written(self):
        for text, count in (("10", 0), ("10.", 0), ("10.5", 1), ("10.50", 2), ("10.500", 3),
                            ("10.50 ", 3), ("", 0), ("1.2.3", 3)):
            self.assertEqual(decimals_after_point(text), count, text)


class EachRuleFailsAlone(unittest.TestCase):
    """The invoice all of them pass, changed in one place: exactly that rule.

    Where one change must fail two rules because both compute with the amount
    changed, that is the last class in this file, and says which.

    Four of these rules are published twice: BR-CO-21 to BR-CO-24 have the
    same test as BR-33, BR-38, BR-42 and BR-44, so each fails with its twin.
    """
    TWINS = {"BR-CO-21": "BR-33", "BR-CO-22": "BR-38", "BR-CO-23": "BR-42", "BR-CO-24": "BR-44"}
    # And five change what the standard rated category's breakdown must come
    # to, so its own rules fail beside them (`test_vat_rules.py`).
    VAT = {"BR-CO-04": ["BR-S-08"], "BR-CO-11": ["BR-S-08"], "BR-CO-12": ["BR-S-08"],
           "BR-CO-13": ["BR-S-08"], "BR-CO-17": ["BR-S-08", "BR-S-09"]}
    CASES = {
        "BR-CO-03": ("<cbc:DocumentCurrencyCode>", "<cbc:TaxPointDate>2026-10-02</cbc:TaxPointDate>"
                     "<cbc:DocumentCurrencyCode>",
                     "<cac:OrderReference>", "<cac:InvoicePeriod><cbc:DescriptionCode>35"
                     "</cbc:DescriptionCode></cac:InvoicePeriod><cac:OrderReference>"),
        "BR-CO-04": (VAT_CATEGORY, ""),
        "BR-CO-09": ("<cbc:CompanyID>DE987654321", "<cbc:CompanyID>987654321"),
        "BR-CO-10": (">800.00</cbc:LineExtensionAmount>", ">800.01</cbc:LineExtensionAmount>"),
        "BR-CO-11": ('<cbc:Amount currencyID="EUR">10.00</cbc:Amount>\n    <cbc:BaseAmount',
                     '<cbc:Amount currencyID="EUR">11.00</cbc:Amount>\n    <cbc:BaseAmount'),
        "BR-CO-12": ('<cbc:AllowanceChargeReason>Freight</cbc:AllowanceChargeReason>\n'
                     '    <cbc:Amount currencyID="EUR">10.00',
                     '<cbc:AllowanceChargeReason>Freight</cbc:AllowanceChargeReason>\n'
                     '    <cbc:Amount currencyID="EUR">12.00'),
        "BR-CO-13": (">10.00</cbc:ChargeTotalAmount>", ">20.00</cbc:ChargeTotalAmount>",
                     '<cbc:AllowanceChargeReason>Freight</cbc:AllowanceChargeReason>\n'
                     '    <cbc:Amount currencyID="EUR">10.00',
                     '<cbc:AllowanceChargeReason>Freight</cbc:AllowanceChargeReason>\n'
                     '    <cbc:Amount currencyID="EUR">20.00'),
        "BR-CO-14": ('<cbc:TaxAmount currencyID="EUR">190.00</cbc:TaxAmount>\n      <cac:TaxCategory>',
                     '<cbc:TaxAmount currencyID="EUR">190.50</cbc:TaxAmount>\n      <cac:TaxCategory>'),
        "BR-CO-15": ('<cbc:TaxAmount currencyID="EUR">190.00</cbc:TaxAmount>\n    <cac:TaxSubtotal>',
                     '<cbc:TaxAmount currencyID="USD">190.00</cbc:TaxAmount>\n    <cac:TaxSubtotal>'),
        "BR-CO-16": (">1190.00</cbc:PayableAmount>", ">1189.00</cbc:PayableAmount>"),
        "BR-CO-17": ("<cbc:Percent>19</cbc:Percent>\n        <cac:TaxScheme>\n          <cbc:ID>VAT"
                     "</cbc:ID>\n        </cac:TaxScheme>\n      </cac:TaxCategory>\n    </cac:TaxSubtotal>",
                     "<cbc:Percent>25</cbc:Percent>\n        <cac:TaxScheme>\n          <cbc:ID>VAT"
                     "</cbc:ID>\n        </cac:TaxScheme>\n      </cac:TaxCategory>\n    </cac:TaxSubtotal>"),
        "BR-CO-19": ("<cac:OrderReference>", "<cac:InvoicePeriod/><cac:OrderReference>"),
        "BR-CO-20": ("<cac:OrderLineReference>", "<cac:InvoicePeriod/><cac:OrderLineReference>"),
        "BR-CO-21": ("<cbc:AllowanceChargeReasonCode>95</cbc:AllowanceChargeReasonCode>\n"
                     "    <cbc:AllowanceChargeReason>Discount</cbc:AllowanceChargeReason>", ""),
        "BR-CO-22": ("<cbc:AllowanceChargeReason>Freight</cbc:AllowanceChargeReason>", ""),
        "BR-CO-23": ("<cbc:AllowanceChargeReason>Introductory</cbc:AllowanceChargeReason>", ""),
        "BR-CO-24": ("<cac:Item>\n      <cbc:Description>",
                     LINE_CHARGE % '<cbc:Amount currencyID="EUR">0.00</cbc:Amount>'),
        "BR-DEC-01": ('<cbc:Amount currencyID="EUR">10.00</cbc:Amount>\n    <cbc:BaseAmount',
                      '<cbc:Amount currencyID="EUR">10.000</cbc:Amount>\n    <cbc:BaseAmount'),
        "BR-DEC-02": (">1000.00</cbc:BaseAmount>", ">1000.000</cbc:BaseAmount>"),
        "BR-DEC-05": ('Freight</cbc:AllowanceChargeReason>\n    <cbc:Amount currencyID="EUR">10.00',
                      'Freight</cbc:AllowanceChargeReason>\n    <cbc:Amount currencyID="EUR">10.000'),
        "BR-DEC-06": ('Freight</cbc:AllowanceChargeReason>\n    <cbc:Amount currencyID="EUR">10.00'
                      "</cbc:Amount>",
                      'Freight</cbc:AllowanceChargeReason>\n    <cbc:Amount currencyID="EUR">10.00'
                      '</cbc:Amount><cbc:BaseAmount currencyID="EUR">100.000</cbc:BaseAmount>'),
        "BR-DEC-09": (">1000.00</cbc:LineExtensionAmount>\n    <cbc:TaxExclusiveAmount",
                      ">1000.000</cbc:LineExtensionAmount>\n    <cbc:TaxExclusiveAmount"),
        "BR-DEC-10": (">10.00</cbc:AllowanceTotalAmount>", ">10.000</cbc:AllowanceTotalAmount>"),
        "BR-DEC-11": (">10.00</cbc:ChargeTotalAmount>", ">10.000</cbc:ChargeTotalAmount>"),
        "BR-DEC-12": (">1000.00</cbc:TaxExclusiveAmount>", ">1000.000</cbc:TaxExclusiveAmount>"),
        "BR-DEC-14": (">1190.00</cbc:TaxInclusiveAmount>", ">1190.000</cbc:TaxInclusiveAmount>"),
        "BR-DEC-16": ("<cbc:PayableAmount", '<cbc:PrepaidAmount currencyID="EUR">0.000'
                      "</cbc:PrepaidAmount><cbc:PayableAmount"),
        "BR-DEC-17": ("<cbc:PayableAmount", '<cbc:PayableRoundingAmount currencyID="EUR">0.000'
                      "</cbc:PayableRoundingAmount><cbc:PayableAmount"),
        "BR-DEC-18": (">1190.00</cbc:PayableAmount>", ">1190.000</cbc:PayableAmount>"),
        "BR-DEC-19": (">1000.00</cbc:TaxableAmount>", ">1000.000</cbc:TaxableAmount>"),
        "BR-DEC-20": ('<cbc:TaxAmount currencyID="EUR">190.00</cbc:TaxAmount>\n      <cac:TaxCategory>',
                      '<cbc:TaxAmount currencyID="EUR">190.000</cbc:TaxAmount>\n      <cac:TaxCategory>'),
        "BR-DEC-23": (">800.00</cbc:LineExtensionAmount>", ">800.000</cbc:LineExtensionAmount>"),
        "BR-DEC-24": (LINE_ALLOWANCE, LINE_ALLOWANCE.replace("50.00", "50.000")),
        "BR-DEC-25": (LINE_ALLOWANCE, LINE_ALLOWANCE + '<cbc:BaseAmount currencyID="EUR">250.000'
                      "</cbc:BaseAmount>"),
        "BR-DEC-27": ("<cac:Item>\n      <cbc:Description>",
                      LINE_CHARGE % ("<cbc:AllowanceChargeReason>Rush</cbc:AllowanceChargeReason>"
                                     '<cbc:Amount currencyID="EUR">0.000</cbc:Amount>')),
        "BR-DEC-28": ("<cac:Item>\n      <cbc:Description>",
                      LINE_CHARGE % ("<cbc:AllowanceChargeReason>Rush</cbc:AllowanceChargeReason>"
                                     '<cbc:Amount currencyID="EUR">0.00</cbc:Amount>'
                                     '<cbc:BaseAmount currencyID="EUR">1.000</cbc:BaseAmount>')),
    }
    # Separate, because they take more than a replacement or cannot be made to fail.
    APART = ("BR-CO-18", "BR-CO-26", "BR-CO-05", "BR-CO-06", "BR-CO-07", "BR-CO-08",
             "BR-DEC-13", "BR-DEC-15")

    def test_the_invoice_they_are_changed_from_fails_none(self):
        self.assertEqual(found(INVOICE), [])
        self.assertEqual(found(CREDIT_NOTE), [])
        self.assertEqual(found(sample("xrechnung-invoice.xml").decode()), [])

    def test_every_rule_built_has_a_case(self):
        self.assertEqual(set(self.CASES) | set(self.APART),
                         {i for i in REGISTRY["en16931"] if i.startswith(("BR-CO-", "BR-DEC-"))})

    def expected(self, identifier: str) -> list:
        return sorted({identifier, self.TWINS.get(identifier, identifier)}
                      | set(self.VAT.get(identifier, ())))

    def test_each_change_fails_its_rule_and_no_other(self):
        for identifier, pairs in self.CASES.items():
            with self.subTest(rule=identifier):
                self.assertEqual(failing(changed(INVOICE, *pairs)), self.expected(identifier))

    def test_the_same_changes_fail_the_same_rules_in_a_credit_note(self):
        for identifier in ("BR-CO-10", "BR-CO-16", "BR-CO-20", "BR-CO-23", "BR-DEC-23", "BR-DEC-24"):
            with self.subTest(rule=identifier):
                pairs = [text.replace("InvoiceLine", "CreditNoteLine") for text in self.CASES[identifier]]
                self.assertEqual(failing(changed(CREDIT_NOTE, *pairs)),
                                 self.expected(identifier))

    def test_no_vat_breakdown_fails_only_the_rule_that_wants_one(self):
        start, end = INVOICE.index("    <cac:TaxSubtotal>"), INVOICE.index("  </cac:TaxTotal>")
        # And the one that wants a breakdown for the category the lines are in.
        self.assertEqual(failing(INVOICE[:start] + INVOICE[end:]), ["BR-CO-18", "BR-S-01"])

    def test_an_empty_vat_breakdown_is_one_as_the_publishers_own_tests_have_it(self):
        self.assertNotIn("BR-CO-18", failing(invoice("<cac:TaxTotal><cac:TaxSubtotal/></cac:TaxTotal>")))

    def test_a_seller_nothing_identifies_fails_only_that(self):
        text = changed(
            INVOICE,
            '<cac:PartyIdentification>\n        <cbc:ID schemeID="0088">4012345000009</cbc:ID>\n'
            "      </cac:PartyIdentification>", "",
            "<cac:PartyTaxScheme>\n        <cbc:CompanyID>DE123456789</cbc:CompanyID>\n"
            "        <cac:TaxScheme>\n          <cbc:ID>VAT</cbc:ID>\n        </cac:TaxScheme>\n"
            "      </cac:PartyTaxScheme>", "",
            '<cbc:CompanyID schemeID="0204">HRB 12345</cbc:CompanyID>', "")
        # The creditor identifier and the other tax registration are still there.
        self.assertEqual(found(text), [("BR-CO-26", "BG-4")])

    def test_the_rules_published_with_a_test_that_cannot_fail_never_do(self):
        for identifier in ("BR-CO-05", "BR-CO-06", "BR-CO-07", "BR-CO-08", "BR-DEC-13", "BR-DEC-15"):
            self.assertIn("cannot fail", REGISTRY["en16931"][identifier].about)
        # Three decimals on the total VAT amount, which BR-DEC-13 is about.
        text = changed(INVOICE, '<cbc:TaxAmount currencyID="EUR">190.00</cbc:TaxAmount>\n    <cac:TaxSubtotal>',
                       '<cbc:TaxAmount currencyID="EUR">190.000</cbc:TaxAmount>\n    <cac:TaxSubtotal>')
        self.assertEqual(found(text), [])


class WhatTheTestsSayExactly(unittest.TestCase):
    """The corners of the published tests, each from reading the test."""

    def totals(self, inside: str, rest: str = "") -> str:
        return invoice("<cac:LegalMonetaryTotal>%s</cac:LegalMonetaryTotal>%s" % (inside, rest))

    def amount(self, name: str, value: str) -> str:
        return '<cbc:%s currencyID="EUR">%s</cbc:%s>' % (name, value, name)

    def test_a_total_that_is_not_there_equals_nothing_so_its_rule_fails(self):
        self.assertIn(("BR-CO-10", "BT-106"), found(self.totals("")))
        document, _findings = parse(self.totals(""))
        finding = next(f for f in rules.run(document, "en16931") if f.code == "BR-CO-10")
        self.assertIn("it is nothing and the lines come to 0", finding.text)

    def test_without_the_totals_element_the_rules_about_it_are_not_asked(self):
        asked = [i for i in failing(invoice("<cbc:ID>1</cbc:ID>")) if not i[3:].isdigit()]
        self.assertEqual(asked, ["BR-CO-18"])

    def test_no_lines_sum_to_nought(self):
        self.assertNotIn("BR-CO-10", failing(self.totals(self.amount("LineExtensionAmount", "0"))))
        self.assertIn("BR-CO-10", failing(self.totals(self.amount("LineExtensionAmount", "1"))))

    def test_equal_is_equal_as_numbers_whatever_the_digits(self):
        text = self.totals(self.amount("LineExtensionAmount", "100") + self.amount("TaxExclusiveAmount", "100.0"),
                           "<cac:InvoiceLine>%s</cac:InvoiceLine>" % self.amount("LineExtensionAmount", "100.00"))
        self.assertEqual([c for c in failing(text) if c in ("BR-CO-10", "BR-CO-13")], [])

    def test_the_sum_of_the_lines_is_rounded_to_cents_before_it_is_compared(self):
        lines = "".join("<cac:InvoiceLine>%s</cac:InvoiceLine>" % self.amount("LineExtensionAmount", v)
                        for v in ("0.005", "1.00"))
        self.assertNotIn("BR-CO-10", failing(self.totals(self.amount("LineExtensionAmount", "1.01"), lines)))
        self.assertIn("BR-CO-10", failing(self.totals(self.amount("LineExtensionAmount", "1.005"), lines)))
        credit = lines.replace("0.005", "-0.005").replace("1.00", "-1.00")
        # A tie on a negative sum rounds up, towards nought: -1.005 is -1.00.
        self.assertNotIn("BR-CO-10", failing(self.totals(self.amount("LineExtensionAmount", "-1.00"), credit)))
        self.assertIn("BR-CO-10", failing(self.totals(self.amount("LineExtensionAmount", "-1.01"), credit)))

    def test_a_sum_of_allowances_with_no_allowances_must_be_nought_and_none_needs_none(self):
        self.assertNotIn("BR-CO-11", failing(self.totals("")))
        self.assertNotIn("BR-CO-11", failing(self.totals(self.amount("AllowanceTotalAmount", "0.00"))))
        self.assertIn("BR-CO-11", failing(self.totals(self.amount("AllowanceTotalAmount", "5.00"))))
        allowance = ("<cac:AllowanceCharge><cbc:ChargeIndicator>false</cbc:ChargeIndicator>%s"
                     "</cac:AllowanceCharge>" % self.amount("Amount", "5.00"))
        self.assertIn("BR-CO-11", failing(self.totals("", allowance)))
        self.assertNotIn("BR-CO-11", failing(self.totals(self.amount("AllowanceTotalAmount", "5"), allowance)))
        # A charge is not an allowance.
        self.assertIn("BR-CO-11", failing(self.totals(self.amount("AllowanceTotalAmount", "5"),
                                                      allowance.replace("false", "true"))))

    def test_the_total_without_vat_takes_whichever_of_allowances_and_charges_are_there(self):
        def with_(excl, **parts):
            inside = self.amount("LineExtensionAmount", "100.00") + self.amount("TaxExclusiveAmount", excl)
            inside += "".join(self.amount(name, value) for name, value in parts.items())
            return "BR-CO-13" in failing(self.totals(inside))
        self.assertFalse(with_("100.00"))
        self.assertTrue(with_("99.00"))
        self.assertFalse(with_("90.00", AllowanceTotalAmount="10.00"))
        self.assertFalse(with_("105.00", ChargeTotalAmount="5.00"))
        self.assertFalse(with_("95.00", AllowanceTotalAmount="10.00", ChargeTotalAmount="5.00"))
        self.assertTrue(with_("105.00", AllowanceTotalAmount="10.00", ChargeTotalAmount="5.00"))
        self.assertTrue(with_("100.00", AllowanceTotalAmount="10.00"))

    def test_the_amount_due_with_and_without_a_paid_amount_and_a_rounding_amount(self):
        def due(payable, incl="1189.60", **parts):
            inside = self.amount("TaxInclusiveAmount", incl) + self.amount("PayableAmount", payable)
            inside += "".join(self.amount(name, value) for name, value in parts.items())
            return "BR-CO-16" not in failing(self.totals(inside))
        self.assertTrue(due("1189.60"))
        self.assertFalse(due("1189.61"))
        self.assertTrue(due("1089.60", PrepaidAmount="100.00"))
        self.assertFalse(due("1189.60", PrepaidAmount="100.00"))
        self.assertTrue(due("1190.00", PayableRoundingAmount="0.40"))
        self.assertFalse(due("1190.00", PayableRoundingAmount="0.30"))
        self.assertTrue(due("1090.00", PrepaidAmount="100.00", PayableRoundingAmount="0.40"))
        self.assertFalse(due("1189.60", PayableRoundingAmount="0.40"))

    def test_the_vat_total_must_be_there_once_in_the_invoice_currency(self):
        def text(*totals):
            return invoice(
                "<cbc:DocumentCurrencyCode>EUR</cbc:DocumentCurrencyCode>"
                + "".join('<cac:TaxTotal><cbc:TaxAmount currencyID="%s">%s</cbc:TaxAmount>'
                          "</cac:TaxTotal>" % pair for pair in totals)
                + "<cac:LegalMonetaryTotal>%s%s</cac:LegalMonetaryTotal>" % (
                    self.amount("TaxExclusiveAmount", "100.00"),
                    self.amount("TaxInclusiveAmount", "119.00")))
        self.assertNotIn("BR-CO-15", failing(text(("EUR", "19.00"))))
        self.assertIn("BR-CO-15", failing(text(("EUR", "19.01"))))
        self.assertIn("BR-CO-15", failing(text()))
        self.assertIn("BR-CO-15", failing(text(("EUR", "19.00"), ("EUR", "19.00"))))
        self.assertIn("BR-CO-15", failing(text(("eur", "19.00"))))
        # Totals that are not there are not equal to each other for both being absent.
        self.assertIn("BR-CO-15", failing(invoice(
            "<cbc:DocumentCurrencyCode>EUR</cbc:DocumentCurrencyCode><cac:TaxTotal>"
            '<cbc:TaxAmount currencyID="EUR">19.00</cbc:TaxAmount></cac:TaxTotal>')))
        # With no invoice currency there is nothing the test is asked about.
        self.assertNotIn("BR-CO-15", failing(text(("EUR", "1.00")).replace(
            "<cbc:DocumentCurrencyCode>EUR</cbc:DocumentCurrencyCode>", "")))

    def test_the_tax_of_a_category_is_allowed_to_be_within_one_of_what_the_rate_gives(self):
        def category(taxable, tax, rate='<cbc:Percent>19</cbc:Percent>'):
            return "BR-CO-17" not in failing(invoice(
                "<cac:TaxTotal><cac:TaxSubtotal>%s%s<cac:TaxCategory><cbc:ID>S</cbc:ID>%s"
                "<cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:TaxCategory>"
                "</cac:TaxSubtotal></cac:TaxTotal>" % (
                    self.amount("TaxableAmount", taxable) if taxable else "",
                    self.amount("TaxAmount", tax) if tax else "", rate)))
        self.assertTrue(category("1000.00", "190.00"))
        self.assertTrue(category("1000.00", "190.99"))
        self.assertTrue(category("1000.00", "189.01"))
        self.assertFalse(category("1000.00", "191.00"))      # one away is not within one
        self.assertFalse(category("1000.00", "189.00"))
        self.assertTrue(category("-1000.00", "-190.00"))     # a credit, compared without its sign
        self.assertFalse(category("", "190.00"))
        self.assertFalse(category("1000.00", ""))
        # A rate that rounds to nought, or none: the tax rounds to nought.
        self.assertTrue(category("1000.00", "0.00", "<cbc:Percent>0</cbc:Percent>"))
        self.assertTrue(category("1000.00", "0.49", "<cbc:Percent>0.4</cbc:Percent>"))
        self.assertFalse(category("1000.00", "0.50", "<cbc:Percent>0</cbc:Percent>"))
        self.assertTrue(category("1000.00", "0", ""))
        self.assertFalse(category("1000.00", "5.00", ""))
        # Half a percent rounds to one, so it is a rate; less than half rounds
        # to nought, and then the tax it really gives is too much to pass.
        self.assertTrue(category("1000.00", "5.00", "<cbc:Percent>0.5</cbc:Percent>"))
        self.assertFalse(category("1000.00", "4.00", "<cbc:Percent>0.4</cbc:Percent>"))

    def test_a_vat_identifiers_prefix_is_looked_for_the_way_the_published_test_looks(self):
        def seller(identifier, scheme="VAT"):
            return "BR-CO-09" not in failing(invoice(
                "<cac:AccountingSupplierParty><cac:Party><cac:PartyTaxScheme><cbc:CompanyID>%s"
                "</cbc:CompanyID><cac:TaxScheme><cbc:ID>%s</cbc:ID></cac:TaxScheme>"
                "</cac:PartyTaxScheme></cac:Party></cac:AccountingSupplierParty>" % (identifier, scheme)))
        self.assertTrue(seller("DE123456789"))
        self.assertTrue(seller("EL123456789"))       # Greece writes itself EL
        self.assertTrue(seller("XI123456789"))
        self.assertFalse(seller("XX123456789"))
        self.assertFalse(seller("de123456789"))
        self.assertFalse(seller("123456789"))
        self.assertTrue(seller("DE123456789", " vat "))
        self.assertTrue(seller("123456789", "FC"))   # not a VAT identifier, so not asked
        # A buyer's registration under another scheme is held where its VAT
        # identifier would be, and is not one.
        buyer = invoice(
            "<cac:AccountingCustomerParty><cac:Party><cac:PartyTaxScheme><cbc:CompanyID>123"
            "</cbc:CompanyID><cac:TaxScheme><cbc:ID>%s</cbc:ID></cac:TaxScheme>"
            "</cac:PartyTaxScheme></cac:Party></cac:AccountingCustomerParty>")
        self.assertNotIn("BR-CO-09", failing(buyer % "FC"))
        self.assertIn(("BR-CO-09", "BT-48"), found(buyer % "VAT"))
        # The test is "is the prefix in this string of codes", which a prefix
        # shorter than two letters is.
        self.assertTrue(seller("D"))
        self.assertTrue(seller(""))

    def test_a_number_that_is_not_one_makes_its_rules_incomputable_which_is_a_failure(self):
        text = self.totals(self.amount("LineExtensionAmount", "1,000.00"))
        document, findings = parse(text)
        self.assertEqual([f.code for f in findings], ["NOT-DECIMAL"])
        said = {f.code: f.text for f in rules.run(document, "en16931")}
        self.assertIn("BR-CO-10", said)
        self.assertIn("could not be computed: BT-106 is '1,000.00', which is not a decimal number",
                      said["BR-CO-10"])
        self.assertIn("BR-CO-13", said)
        self.assertNotIn("BR-CO-16", [c for c in said if "BT-106" in said[c]])

    def test_an_amount_twice_makes_its_rules_incomputable_too(self):
        text = self.totals(self.amount("PayableAmount", "1.00") * 2)
        said = {f.code: f.text for f in rules.run(parse(text)[0], "en16931")}
        self.assertIn("BT-115 occurs 2 times where the rule takes one", said["BR-CO-16"])
        self.assertIn("BT-115 occurs 2 times where the rule takes one", said["BR-DEC-18"])

    def test_a_space_after_the_digits_counts_as_the_published_test_counts_it(self):
        self.assertIn("BR-DEC-18", failing(self.totals(self.amount("PayableAmount", "1.00 "))))
        self.assertNotIn("BR-DEC-18", failing(self.totals(self.amount("PayableAmount", " 1.00"))))

    def test_a_seller_is_identified_by_any_one_of_three_things(self):
        def seller(inside):
            return "BR-CO-26" not in failing(invoice(
                "<cac:AccountingSupplierParty><cac:Party>%s</cac:Party></cac:AccountingSupplierParty>" % inside))
        identifier = '<cac:PartyIdentification><cbc:ID schemeID="%s">X</cbc:ID></cac:PartyIdentification>'
        self.assertFalse(seller(""))
        self.assertFalse(seller("<cac:PartyName><cbc:Name>Globex</cbc:Name></cac:PartyName>"))
        self.assertTrue(seller(identifier % "0088"))
        self.assertFalse(seller(identifier % "SEPA"))
        self.assertTrue(seller(identifier % "sepa"))     # the test asks for SEPA exactly
        self.assertTrue(seller("<cac:PartyLegalEntity><cbc:CompanyID>HRB 1</cbc:CompanyID></cac:PartyLegalEntity>"))
        self.assertTrue(seller("<cac:PartyTaxScheme><cbc:CompanyID>DE1</cbc:CompanyID><cac:TaxScheme>"
                               "<cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:PartyTaxScheme>"))
        self.assertFalse(seller("<cac:PartyTaxScheme><cbc:CompanyID>1</cbc:CompanyID><cac:TaxScheme>"
                                "<cbc:ID>FC</cbc:ID></cac:TaxScheme></cac:PartyTaxScheme>"))
        # With no seller at all the rule has nothing to ask.
        self.assertNotIn("BR-CO-26", failing(invoice("<cbc:ID>1</cbc:ID>")))
        # A payee's identifier is not the seller's, whatever case its scheme is in.
        self.assertIn("BR-CO-26", failing(invoice(
            "<cac:AccountingSupplierParty><cac:Party><cac:PartyName><cbc:Name>Globex</cbc:Name>"
            "</cac:PartyName></cac:Party></cac:AccountingSupplierParty><cac:PayeeParty>%s"
            "</cac:PayeeParty>" % (identifier % "sepa"))))

    def test_a_period_needs_a_date_and_the_documents_may_have_the_code_instead(self):
        def document(inside):
            return "BR-CO-19" not in failing(invoice("<cac:InvoicePeriod>%s</cac:InvoicePeriod>" % inside))
        self.assertFalse(document(""))
        self.assertFalse(document("<cbc:Description>October</cbc:Description>"))
        self.assertTrue(document("<cbc:StartDate>2026-10-01</cbc:StartDate>"))
        self.assertTrue(document("<cbc:EndDate>2026-10-31</cbc:EndDate>"))
        self.assertTrue(document("<cbc:DescriptionCode>35</cbc:DescriptionCode>"))
        line = invoice("<cac:InvoiceLine><cac:InvoicePeriod>%s</cac:InvoicePeriod></cac:InvoiceLine>")
        self.assertIn(("BR-CO-20", "BG-25/BG-26"), found(line % ""))
        self.assertNotIn("BR-CO-19", failing(line % ""))         # a line's period is the line's rule
        self.assertNotIn("BR-CO-20", failing(line % "<cbc:EndDate>2026-10-31</cbc:EndDate>"))

    def test_a_failure_on_one_of_several_says_which(self):
        text = changed(INVOICE, "<cbc:Name>Installation</cbc:Name>\n      " + VAT_CATEGORY,
                       "<cbc:Name>Installation</cbc:Name>")
        self.assertEqual(found(text), [("BR-CO-04", "BG-25[2]"), ("BR-S-08", "BG-23")])
        text = changed(INVOICE, LINE_ALLOWANCE, LINE_ALLOWANCE.replace("50.00", "50.000"))
        self.assertEqual(found(text), [("BR-DEC-24", "BG-25[2]/BG-27/BT-136")])


class ChangesThatFailTwoRules(unittest.TestCase):
    """One amount, two rules that compute with it: written down, as #3 asks."""

    def test_each_total_changed_alone(self):
        for old, new, expected in (
                (">1000.00</cbc:LineExtensionAmount>\n    <cbc:TaxExclusiveAmount",
                 ">1000.01</cbc:LineExtensionAmount>\n    <cbc:TaxExclusiveAmount",
                 ["BR-CO-10", "BR-CO-13"]),
                (">10.00</cbc:AllowanceTotalAmount>", ">11.00</cbc:AllowanceTotalAmount>",
                 ["BR-CO-11", "BR-CO-13"]),
                (">10.00</cbc:ChargeTotalAmount>", ">11.00</cbc:ChargeTotalAmount>",
                 ["BR-CO-12", "BR-CO-13"]),
                (">1000.00</cbc:TaxExclusiveAmount>", ">1001.00</cbc:TaxExclusiveAmount>",
                 ["BR-CO-13", "BR-CO-15"]),
                ('<cbc:TaxAmount currencyID="EUR">190.00</cbc:TaxAmount>\n    <cac:TaxSubtotal>',
                 '<cbc:TaxAmount currencyID="EUR">191.00</cbc:TaxAmount>\n    <cac:TaxSubtotal>',
                 ["BR-CO-14", "BR-CO-15"]),
                (">1190.00</cbc:TaxInclusiveAmount>", ">1191.00</cbc:TaxInclusiveAmount>",
                 ["BR-CO-15", "BR-CO-16"])):
            with self.subTest(changed=new):
                self.assertEqual(failing(changed(INVOICE, old, new)), expected)


if __name__ == "__main__":
    unittest.main()
