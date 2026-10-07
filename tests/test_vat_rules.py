"""The VAT category rules of EN 16931: ten families, one to a category."""
import unittest
from decimal import Decimal

from mockeinvoice.model import Group, Value
from mockeinvoice.rules import REGISTRY, published, run
from mockeinvoice.rules.calculation import Incomputable, nudged
from mockeinvoice.rules.en16931_vat import BY_RATE, FAMILIES, ZERO_RATED
from mockeinvoice.ubl import parse

from .test_reading import invoice

VAT_RULES = sorted(i for i in published.EN16931
                   if i.split("-")[1] in FAMILIES and i.count("-") == 2)
REASON_OWED = ("E", "AE", "IC", "G", "O")


def amount(name: str, value: str) -> str:
    return '<cbc:%s currencyID="EUR">%s</cbc:%s>' % (name, value, name)


def category(tag: str, code, rate, more: str = "") -> str:
    if code is None:
        return ""
    return "<cac:%s>%s%s%s<cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:%s>" % (
        tag, "<cbc:ID>%s</cbc:ID>" % code, "" if rate is None else
        "<cbc:Percent>%s</cbc:Percent>" % rate, more, tag)


def registration(identifier: str, scheme: str = "VAT") -> str:
    return ("<cac:PartyTaxScheme><cbc:CompanyID>%s</cbc:CompanyID><cac:TaxScheme><cbc:ID>%s"
            "</cbc:ID></cac:TaxScheme></cac:PartyTaxScheme>" % (identifier, scheme))


def line(net: str, code, rate, origin: str = "") -> str:
    return "<cac:InvoiceLine>%s<cac:Item>%s%s</cac:Item></cac:InvoiceLine>" % (
        amount("LineExtensionAmount", net),
        "<cac:OriginCountry><cbc:IdentificationCode>%s</cbc:IdentificationCode>"
        "</cac:OriginCountry>" % origin if origin else "",
        category("ClassifiedTaxCategory", code, rate))


def allowance(value: str, code, rate, charge: bool = False) -> str:
    return ("<cac:AllowanceCharge><cbc:ChargeIndicator>%s</cbc:ChargeIndicator>%s%s"
            "</cac:AllowanceCharge>" % ("true" if charge else "false", amount("Amount", value),
                                        category("TaxCategory", code, rate)))


def breakdown(taxable, tax, code, rate, reason: bool = False) -> str:
    return "<cac:TaxSubtotal>%s%s%s</cac:TaxSubtotal>" % (
        "" if taxable is None else amount("TaxableAmount", taxable),
        "" if tax is None else amount("TaxAmount", tax),
        category("TaxCategory", code, rate, "<cbc:TaxExemptionReason>Because</cbc:TaxExemptionReason>"
                 if reason else ""))


def document(family: str, **changes) -> str:
    """An invoice wholly in one VAT category that its family's rules pass:
    a line of 100.00, an allowance of 10.00 and a charge of 5.00.

    `changes` replace a part by name. A part that is a rate or a code is
    given as text, and None leaves its element out.
    """
    code = FAMILIES[family][0]
    rate = None if family == "O" else "19" if family in BY_RATE else "0"
    parts = dict(
        code=code, rate=rate,
        seller=registration("DE123456789") if family != "O" else "",
        representative="",
        buyer=registration("FR12345678901") if family in ("AE", "IC") else "",
        buyer_legal="",
        delivery="<cbc:ActualDeliveryDate>2026-10-02</cbc:ActualDeliveryDate>",
        delivered_to="IT" if family == "B" else "FR",
        seller_country="IT" if family == "B" else "DE",
        lines=None, allowances=None, charges=None, breakdowns=None,
        taxable="95.00", tax="18.05" if family in BY_RATE else "0.00",
        reason=family in REASON_OWED, more="")
    parts.update(changes)
    code, rate = parts["code"], parts["rate"]
    if parts["lines"] is None:
        parts["lines"] = line("100.00", code, rate)
    if parts["allowances"] is None:
        parts["allowances"] = allowance("10.00", code, rate)
    if parts["charges"] is None:
        parts["charges"] = allowance("5.00", code, rate, charge=True)
    if parts["breakdowns"] is None:
        parts["breakdowns"] = breakdown(parts["taxable"], parts["tax"], code, rate,
                                        parts["reason"])
    country = "<cac:Country><cbc:IdentificationCode>%s</cbc:IdentificationCode></cac:Country>"
    return invoice(
        "<cac:AccountingSupplierParty><cac:Party><cac:PostalAddress>%s</cac:PostalAddress>%s"
        "</cac:Party></cac:AccountingSupplierParty>" % (country % parts["seller_country"],
                                                        parts["seller"])
        + "<cac:AccountingCustomerParty><cac:Party>%s%s</cac:Party></cac:AccountingCustomerParty>"
        % (parts["buyer"], "<cac:PartyLegalEntity><cbc:CompanyID>%s</cbc:CompanyID>"
           "</cac:PartyLegalEntity>" % parts["buyer_legal"] if parts["buyer_legal"] else "")
        + ("<cac:TaxRepresentativeParty>%s</cac:TaxRepresentativeParty>" % parts["representative"]
           if parts["representative"] else "")
        + "<cac:Delivery>%s%s</cac:Delivery>" % (
            parts["delivery"], "<cac:DeliveryLocation><cac:Address>%s</cac:Address>"
            "</cac:DeliveryLocation>" % (country % parts["delivered_to"])
            if parts["delivered_to"] else "")
        + parts["allowances"] + parts["charges"]
        + "<cac:TaxTotal>%s</cac:TaxTotal>" % parts["breakdowns"] + parts["lines"]
        + parts["more"])


def vat(text: str) -> list:
    """The VAT category rules a document fails, of every family."""
    parsed, _findings = parse(text)
    return sorted({f.code for f in run(parsed, "en16931") if f.code in VAT_RULES})


def of(family: str, *numbers: str) -> list:
    return sorted("BR-%s-%s" % (family, number) for number in numbers)


class TheFamilies(unittest.TestCase):
    def test_there_are_98_rules_in_ten_families_and_all_are_built(self):
        self.assertEqual(len(VAT_RULES), 98)
        self.assertLessEqual(set(VAT_RULES), set(REGISTRY["en16931"]))
        sizes = {family: sum(1 for i in VAT_RULES if i.split("-")[1] == family)
                 for family in FAMILIES}
        self.assertEqual(sizes, {"S": 10, "Z": 10, "E": 10, "AE": 10, "IC": 12, "G": 10, "O": 14,
                                 "AF": 10, "AG": 10, "B": 2})
        self.assertTrue(all(published.EN16931[i] == "fatal" for i in VAT_RULES))

    def test_a_document_wholly_in_one_category_fails_no_rule_of_any_family(self):
        for family in FAMILIES:
            self.assertEqual(vat(document(family)), [], family)

    def test_a_finding_names_the_category_and_where(self):
        parsed, _findings = parse(document("E", tax="1.00"))
        finding = next(f for f in run(parsed, "en16931") if f.code == "BR-E-09")
        self.assertEqual((finding.level, finding.path), ("fatal", "BG-23"))
        self.assertEqual(finding.text, "the tax amount (BT-117) of the VAT breakdown for E is "
                         "nought: it is 1.00")


class EachRuleOfEachFamily(unittest.TestCase):
    """The family's own document, changed in one part."""

    def families(self):
        return [family for family in FAMILIES if family != "B"]

    def test_01_no_breakdown_for_a_category_that_is_used(self):
        for family in self.families():
            self.assertEqual(vat(document(family, breakdowns="")), of(family, "01"), family)

    def test_02_to_04_the_seller_is_not_identified_where_the_category_is_used(self):
        for family in self.families():
            if family == "O":
                changes = dict(seller=registration("DE123456789"))
            else:
                changes = dict(seller="")
            self.assertEqual(vat(document(family, **changes)), of(family, "02", "03", "04"), family)
            # Each of the three is about its own place.
            self.assertEqual(vat(document(family, allowances="", taxable="105.00",
                                          tax="19.95" if family in BY_RATE else "0.00",
                                          **changes)), of(family, "02", "04"), family)
            self.assertEqual(vat(document(family, charges="", taxable="90.00",
                                          tax="17.10" if family in BY_RATE else "0.00",
                                          **changes)), of(family, "02", "03"), family)

    def test_05_to_07_the_rate(self):
        for family in self.families():
            code = FAMILIES[family][0]
            good = None if family == "O" else "19" if family in BY_RATE else "0"
            bad = "0" if family in ("O", "S") else "-1" if family in BY_RATE else "5"
            # A place at another rate is no longer in a by-rate breakdown's
            # sum, so its taxable amount is moved to keep that rule out of it.
            by_rate = family in BY_RATE
            for number, part, text, taxable in (
                    ("05", "lines", line("100.00", code, bad), "-5.00"),
                    ("06", "allowances", allowance("10.00", code, bad), "105.00"),
                    ("07", "charges", allowance("5.00", code, bad, charge=True), "90.00")):
                changes = {part: text}
                if by_rate:
                    changes["taxable"] = taxable
                    changes["tax"] = format(Decimal(taxable) * Decimal("0.19"), ".2f")
                self.assertEqual(vat(document(family, **changes)), of(family, number),
                                 (family, number))
            self.assertEqual(vat(document(family, rate=good)), [])

    def test_08_the_taxable_amount(self):
        for family in self.families():
            self.assertEqual(vat(document(family, taxable="97.00",
                                          tax="18.43" if family in BY_RATE else "0.00")),
                             of(family, "08"), family)

    def test_09_the_tax_amount(self):
        for family in self.families():
            self.assertEqual(vat(document(family, tax="20.00" if family in BY_RATE else "0.01")),
                             of(family, "09"), family)
            self.assertEqual(vat(document(family, tax=None)), of(family, "09"), family)

    def test_10_the_reason_for_exemption_is_owed_or_forbidden(self):
        for family in self.families():
            self.assertEqual(vat(document(family, reason=family not in REASON_OWED)),
                             of(family, "10"), family)

    def test_10_a_reason_code_is_a_reason(self):
        coded = "<cbc:TaxExemptionReasonCode>VATEX-EU-132</cbc:TaxExemptionReasonCode>"
        for family in self.families():
            text = document(family, reason=True).replace(
                "<cbc:TaxExemptionReason>Because</cbc:TaxExemptionReason>", coded)
            self.assertIn(coded, text)
            self.assertEqual(vat(text), [] if family in REASON_OWED else of(family, "10"), family)

    def test_every_rule_has_failed_in_this_file(self):
        """Kept honest by hand: the numbers the tests above and below name."""
        named = set()
        for family in self.families():
            named.update(of(family, *("%02d" % n for n in range(1, 11))))
        named.update(of("IC", "11", "12") + of("O", "11", "12", "13", "14") + of("B", "01", "02"))
        self.assertEqual(sorted(named), VAT_RULES)


class TheBreakdownOfACategory(unittest.TestCase):
    def test_most_families_want_exactly_one_and_count_it_by_its_code(self):
        two = breakdown("95.00", "0.00", "E", "0", True) * 2
        self.assertIn("BR-E-01", vat(document("E", breakdowns=two)))
        # A breakdown nothing is in is still one breakdown.
        self.assertNotIn("BR-E-01", vat(document("E", lines=line("100.00", "Z", "0"),
                                                 allowances="", charges="")))
        # Trimmed, wherever it is.
        self.assertEqual(vat(document("E", breakdowns=breakdown("95.00", "0.00", " E ", "0", True))),
                         [])

    def test_an_allowance_alone_is_a_use_of_its_category(self):
        self.assertIn("BR-E-01", vat(document("Z", allowances=allowance("0.00", "E", "0"))))
        self.assertIn("BR-S-01", vat(document("Z", charges=allowance("0.00", "S", "19", True))))
        self.assertIn("BR-AF-01", vat(document("Z", allowances=allowance("0.00", "L", "7"))))

    def test_the_families_with_a_rate_may_have_one_to_each_rate(self):
        for family in BY_RATE:
            code = FAMILIES[family][0]
            text = document(
                family, lines=line("100.00", code, "19") + line("50.00", code, "7"),
                allowances="", charges="",
                breakdowns=breakdown("100.00", "19.00", code, "19")
                + breakdown("50.00", "3.50", code, "7"))
            self.assertEqual(vat(text), [], family)
            # And none where the category is not used.
            unused = document(family, lines=line("100.00", "E", "0"), allowances="", charges="")
            self.assertIn("BR-%s-01" % family, vat(unused))

    def test_two_families_look_for_the_breakdown_by_its_code_as_written(self):
        def spaced(family):
            code = FAMILIES[family][0]
            return vat(document(family, breakdowns=breakdown("95.00", "18.05", " %s " % code, "19")))
        self.assertEqual(spaced("S"), [])
        self.assertEqual(spaced("AF"), ["BR-AF-01"])
        self.assertEqual(spaced("AG"), ["BR-AG-01"])
        # Not used, a breakdown is found trimmed all the same.
        self.assertIn("BR-AF-01", vat(document(
            "AF", lines=line("100.00", "E", "0"), allowances="", charges="",
            breakdowns=breakdown("95.00", "18.05", " L ", "19"))))


class TheParties(unittest.TestCase):
    def only(self, family: str, **changes) -> bool:
        """Whether the family's rule about lines passes."""
        return "BR-%s-02" % family not in vat(document(family, **changes))

    def test_most_families_take_any_tax_registration_of_the_sellers(self):
        other = registration("22/333/44444", "FC")
        for family in ("S", "Z", "E", "AE", "AF", "AG"):
            self.assertTrue(self.only(family, seller=other), family)
        for family in ("G", "IC"):
            self.assertFalse(self.only(family, seller=other), family)
            self.assertTrue(self.only(family, seller=registration("DE1", " vat ")), family)

    def test_a_tax_representatives_vat_identifier_serves_for_the_sellers(self):
        for family in ("S", "Z", "E", "AE", "IC", "G", "AF", "AG"):
            self.assertTrue(self.only(family, seller="", representative=registration("FR1")),
                            family)
            self.assertFalse(self.only(family, seller="",
                                       representative=registration("FR1", "FC")), family)

    def test_reverse_charge_and_intra_community_supply_want_the_buyer_identified(self):
        self.assertFalse(self.only("AE", buyer=""))
        self.assertTrue(self.only("AE", buyer="", buyer_legal="HRB 1"))
        self.assertFalse(self.only("AE", buyer=registration("X", "FC")))
        self.assertFalse(self.only("IC", buyer=""))
        self.assertFalse(self.only("IC", buyer="", buyer_legal="HRB 1"))
        for family in ("S", "Z", "E", "G", "AF", "AG"):
            self.assertTrue(self.only(family, buyer=""), family)

    def test_not_subject_to_vat_wants_no_vat_identifier_on_anyone(self):
        self.assertTrue(self.only("O"))
        self.assertTrue(self.only("O", seller=registration("22/333", "FC")))
        self.assertFalse(self.only("O", buyer=registration("FR1")))
        self.assertFalse(self.only("O", representative=registration("FR1")))
        parsed, _findings = parse(document("O", seller=registration("DE1"),
                                           buyer=registration("FR1")))
        finding = next(f for f in run(parsed, "en16931") if f.code == "BR-O-02")
        self.assertIn("a VAT identifier is given (BT-31, BT-48)", finding.text)

    def test_one_rule_is_let_off_by_a_code_that_is_not_exactly_its_own(self):
        def spaced(family, number, charge):
            code = " %s " % FAMILIES[family][0]
            part = {"charges" if charge else "allowances": allowance("5.00", code, "19", charge)}
            return "BR-%s-%s" % (family, number) in vat(document(family, seller="", **part))
        self.assertFalse(spaced("AF", "04", True))
        self.assertTrue(spaced("AF", "03", False))
        self.assertTrue(spaced("AG", "04", True))
        self.assertTrue(spaced("S", "04", True))


class TheRate(unittest.TestCase):
    def line_rate(self, family: str, rate) -> bool:
        return "BR-%s-05" % family not in vat(document(
            family, lines=line("100.00", FAMILIES[family][0], rate)))

    def test_what_each_family_allows(self):
        for family in ZERO_RATED:
            self.assertTrue(self.line_rate(family, "0.00"), family)
            self.assertFalse(self.line_rate(family, "0.01"), family)
            self.assertFalse(self.line_rate(family, None), family)
        self.assertTrue(self.line_rate("S", "0.01"))
        self.assertFalse(self.line_rate("S", "0"))
        self.assertFalse(self.line_rate("S", None))
        for family in ("AF", "AG"):
            self.assertTrue(self.line_rate(family, "0"), family)
            self.assertFalse(self.line_rate(family, "-0.01"), family)
            self.assertFalse(self.line_rate(family, None), family)
        self.assertTrue(self.line_rate("O", None))
        self.assertFalse(self.line_rate("O", ""))

    def test_a_rate_that_is_no_number_cannot_be_computed(self):
        for family in ("E", "S"):
            parsed, _findings = parse(document(family, lines=line(
                "100.00", FAMILIES[family][0], "none")))
            finding = next(f for f in run(parsed, "en16931") if f.code == "BR-%s-05" % family)
            self.assertIn("could not be computed", finding.text)


class TheTaxableAmount(unittest.TestCase):
    def test_without_a_rate_it_is_exact_and_all_rates_are_one_sum(self):
        for family in ZERO_RATED + ("O",):
            self.assertIn("BR-%s-08" % family, vat(document(family, taxable="95.01")), family)
            self.assertNotIn("BR-%s-08" % family, vat(document(family, taxable="95")), family)
            self.assertIn("BR-%s-08" % family, vat(document(family, taxable=None)), family)
            # No lines, no taxable amount that is right.
            self.assertIn("BR-%s-08" % family, vat(document(
                family, lines="", allowances="", taxable="5.00")), family)

    def test_by_rate_it_is_within_one_unit_and_only_what_is_at_the_rate_counts(self):
        for family in BY_RATE:
            rule = "BR-%s-08" % family
            self.assertNotIn(rule, vat(document(family, taxable="95.99")), family)
            self.assertNotIn(rule, vat(document(family, taxable="94.01")), family)
            self.assertIn(rule, vat(document(family, taxable="96.00")), family)
            self.assertIn(rule, vat(document(family, taxable="94.00")), family)
            self.assertIn(rule, vat(document(family, taxable=None)), family)
            # A breakdown that names no rate is asked nothing.
            code = FAMILIES[family][0]
            self.assertNotIn(rule, vat(document(family, breakdowns=breakdown(
                "1.00", "0.00", code, None))), family)
            # At another rate than everything, the sum is nought.
            self.assertIn(rule, vat(document(family, breakdowns=breakdown(
                "95.00", "6.65", code, "7"))), family)
            # 19 and 19.0 are one rate.
            self.assertNotIn(rule, vat(document(family, breakdowns=breakdown(
                "95.00", "18.05", code, "19.0"))), family)

    def test_the_one_unit_is_measured_as_a_double_as_the_published_test_does(self):
        def passes(taxable, net):
            return "BR-S-08" not in vat(document(
                "S", taxable=taxable, lines=line(net, "S", "19"), allowances="", charges=""))
        # 100.00 less one is 99 exactly, which is not less than 99.00.
        self.assertFalse(passes("100.00", "99.00"))
        # 100.10 less one is a hair under 99.10 as a double, which is.
        self.assertTrue(passes("100.10", "99.10"))
        self.assertEqual(nudged(self.amount("100.10"), "BT-116", -1),
                         Decimal("99.099999999999994315658113919198513031005859375"))

    def amount(self, *texts: str) -> Group:
        group = Group()
        for text in texts:
            group.add("BT-116", Value(text))
        return group

    def test_an_amount_and_one(self):
        self.assertEqual(nudged(self.amount("100.00"), "BT-116", 1), Decimal(101))
        self.assertEqual(nudged(self.amount(" 1e2 "), "BT-116", -1), Decimal(99))
        self.assertIsNone(nudged(self.amount(), "BT-116", 1))
        for texts in (("1", "2"), ("x",), ("NaN",), ("INF",), ("-INF",)):
            with self.assertRaises(Incomputable, msg=texts):
                nudged(self.amount(*texts), "BT-116", 1)

    def test_standard_rated_is_also_met_by_its_allowances_and_charges_alone(self):
        # The published test has a second way to pass, written for the other
        # kind of document: the charges less the allowances, without the lines.
        self.assertNotIn("BR-S-08", vat(document("S", taxable="-5.00", tax="-0.95")))
        self.assertIn("BR-AF-08", vat(document("AF", taxable="-5.00", tax="-0.95")))
        # It needs an allowance or a charge at the rate to be met that way.
        self.assertIn("BR-S-08", vat(document("S", taxable="0.00", tax="0.00",
                                              allowances="", charges="")))

    def test_standard_rated_wants_something_at_the_breakdowns_rate(self):
        def second(family):
            code = FAMILIES[family][0]
            return "BR-%s-08" % family in vat(document(family, breakdowns=breakdown(
                "95.00", "18.05", code, "19") + breakdown("0.00", "0.00", code, "7")))
        # Nothing is at 7%, and nought is within one of nothing's sum: the
        # other two families pass that, and standard rated does not.
        self.assertTrue(second("S"))
        self.assertFalse(second("AF"))
        self.assertFalse(second("AG"))

    def test_a_document_with_no_lines(self):
        for family in ("AF", "AG"):
            self.assertIn("BR-%s-08" % family, vat(document(
                family, lines="", taxable="-5.00", tax="-0.95")), family)
        self.assertNotIn("BR-S-08", vat(document("S", lines="", taxable="-5.00", tax="-0.95")))


class TheTaxAmount(unittest.TestCase):
    def test_by_rate_it_is_within_one_unit_of_the_taxable_amount_at_the_rate(self):
        for family in BY_RATE:
            rule = "BR-%s-09" % family
            for tax, passes in (("18.05", True), ("19.04", True), ("17.06", True),
                                ("19.05", False), ("17.05", False), ("-18.05", True)):
                self.assertEqual(rule not in vat(document(family, tax=tax)), passes, (family, tax))
            code = FAMILIES[family][0]
            self.assertIn(rule, vat(document(family, breakdowns=breakdown(
                "95.00", "0.00", code, None))), family)
            self.assertIn(rule, vat(document(family, breakdowns=breakdown(
                None, "18.05", code, "19"))), family)

    def test_elsewhere_it_is_nought_however_written(self):
        for family in ZERO_RATED + ("O",):
            self.assertNotIn("BR-%s-09" % family, vat(document(family, tax="0")), family)
            self.assertNotIn("BR-%s-09" % family, vat(document(family, tax="-0.000")), family)


class WhatOnlyTwoFamiliesAsk(unittest.TestCase):
    def test_an_intra_community_supply_says_when_it_was_delivered_or_over_what_period(self):
        period = "<cac:InvoicePeriod>%s</cac:InvoicePeriod>"
        self.assertEqual(vat(document("IC", delivery="")), ["BR-IC-11"])
        self.assertEqual(vat(document("IC", delivery="", more=period % (
            "<cbc:StartDate>2026-10-01</cbc:StartDate>"))), [])
        self.assertEqual(vat(document("IC", delivery="", more=period % (
            "<cbc:DescriptionCode>35</cbc:DescriptionCode>"))), [])
        self.assertEqual(vat(document("IC", delivery="", more=period % "")), ["BR-IC-11"])
        # The date is measured and not read: two characters of anything will do.
        date = "<cbc:ActualDeliveryDate>%s</cbc:ActualDeliveryDate>"
        self.assertEqual(vat(document("IC", delivery=date % "no")), [])
        self.assertEqual(vat(document("IC", delivery=date % "2")), ["BR-IC-11"])
        parsed, _findings = parse(document("IC", delivery=date % "2026-10-02" * 2))
        finding = next(f for f in run(parsed, "en16931") if f.code == "BR-IC-11")
        self.assertIn("could not be computed: BT-72 occurs 2 times", finding.text)

    def test_an_intra_community_supply_says_what_country_it_was_delivered_to(self):
        self.assertEqual(vat(document("IC", delivered_to="")), ["BR-IC-12"])
        self.assertEqual(vat(document("IC", delivered_to="F")), ["BR-IC-12"])
        # Neither is asked of a document with no breakdown for K.
        self.assertEqual(vat(document("E", delivery="", delivered_to="")), [])

    def test_a_document_not_subject_to_vat_is_wholly_that(self):
        self.assertIn("BR-O-11", vat(document("O", breakdowns=breakdown("95.00", "0.00", "O", None, True)
                                              + breakdown("0.00", "0.00", "E", "0", True))))
        self.assertIn("BR-O-12", vat(document("O", lines=line("100.00", "O", None)
                                              + line("0.00", "E", "0"))))
        self.assertIn("BR-O-13", vat(document("O", allowances=allowance("10.00", "O", None)
                                              + allowance("0.00", "E", "0"))))
        self.assertIn("BR-O-14", vat(document("O", charges=allowance("5.00", "O", None, True)
                                              + allowance("0.00", "E", "0", True))))
        # A category with a rate and no code is not O.
        self.assertIn("BR-O-12", vat(document("O", lines=line("100.00", "O", None)
                                              + line("0.00", "", "0"))))
        # Nor is one with a rate alone, or with nothing but its scheme.
        for inside in ("<cbc:Percent>0</cbc:Percent>", ""):
            bare = line("0.00", "?", None).replace("<cbc:ID>?</cbc:ID>", inside)
            self.assertIn("BR-O-12", vat(document("O", lines=line("100.00", "O", None) + bare)),
                          inside)
        # A line with no category at all is in no other category.
        self.assertNotIn("BR-O-12", vat(document("O", lines=line("100.00", "O", None)
                                                 + line("0.00", None, None))))
        # And none of it is asked where no breakdown is for O.
        mixed = vat(document("E", lines=line("100.00", "E", "0") + line("0.00", "O", None)))
        self.assertEqual([i for i in mixed if i in of("O", "11", "12", "13", "14")], [])

    def test_each_of_the_four_is_about_its_own_place(self):
        def others(**changes):
            return [i for i in vat(document("O", **changes)) if i in of("O", "11", "12", "13", "14")]
        self.assertEqual(others(lines=line("100.00", "O", None) + line("0.00", "E", "0")),
                         ["BR-O-12"])
        self.assertEqual(others(allowances=allowance("10.00", "O", None)
                                + allowance("0.00", "E", "0")), ["BR-O-13"])
        self.assertEqual(others(charges=allowance("5.00", "O", None, True)
                                + allowance("0.00", "E", "0", True)), ["BR-O-14"])
        self.assertEqual(others(breakdowns=breakdown("95.00", "0.00", "O", None, True)
                                + breakdown("0.00", "0.00", "E", "0", True)), ["BR-O-11"])


class SplitPayment(unittest.TestCase):
    """Italy's, and the two rules no unit test is published for."""

    def test_every_country_code_in_the_document_is_italys(self):
        self.assertEqual(vat(document("B", delivered_to="IT")), [])
        self.assertEqual(vat(document("B", delivered_to="DE")), ["BR-B-01"])
        self.assertEqual(vat(document("B", delivered_to="IT", seller_country="it")), ["BR-B-01"])
        self.assertEqual(vat(document("B", delivered_to="", lines=line(
            "100.00", "B", "0", origin="CN"))), ["BR-B-01"])
        self.assertEqual(vat(document("B", delivered_to="")), [])
        # Not asked of a document that does not name the category, which is
        # compared as written.
        self.assertNotIn("BR-B-01", vat(document("E", delivered_to="DE")))
        self.assertEqual(vat(document("B", code=" B ", delivered_to="DE")), [])

    def test_it_is_not_mixed_with_the_standard_rate(self):
        for part, text in (("lines", line("100.00", "B", "0") + line("0.00", "S", "19")),
                           ("allowances", allowance("10.00", "B", "0") + allowance("0.00", "S", "19")),
                           ("breakdowns", breakdown("95.00", "0.00", "B", "0")
                            + breakdown("0.00", "0.00", "S", "19"))):
            self.assertIn("BR-B-02", vat(document("B", delivered_to="IT", **{part: text})), part)
        self.assertNotIn("BR-B-02", vat(document("B", delivered_to="IT", lines=line(
            "100.00", "B", "0") + line("0.00", "E", "0"))))
        self.assertNotIn("BR-B-02", vat(document("S")))
