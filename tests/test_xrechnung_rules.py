"""XRechnung 3.0's rules for a standard document: BR-DE, BR-TMP-2, BR-TMP-6."""
import unittest

from mockeinvoice import Refused, check, read, validate
from mockeinvoice.rules import REGISTRY, SCOPES, could_apply, published, run
from mockeinvoice.rules.tree import top
from mockeinvoice.rules.xrechnung import NAMES
from mockeinvoice.ubl import parse_tree, tree

from . import sample, test_peppol_de_rules
from .test_rules import INVOICE, changed

XRECHNUNG = sample("xrechnung-invoice.xml").decode("utf-8")
STANDARD = sorted(i for i in published.XRECHNUNG
                  if not i.startswith(("BR-DEX-", "BR-DE-CVD-", "BR-TMP-CVD-")))
PEPPOLS = ("urn:cen.eu:en16931:2017#compliant#urn:fdc:peppol.eu:2017:poacc:billing:3.0",
           "ACME-PO-4500000017")
XRECHNUNGS = ("urn:cen.eu:en16931:2017#compliant#urn:xeinkauf.de:kosit:xrechnung_3.0",
              "04011000-12345-06")
ONLY_XRECHNUNGS = ("BR-DE-21", "BR-DE-TMP-32", "BR-TMP-6")


def found(text: str) -> list:
    """XRechnung's rules that a document fails as sent, with where."""
    document, _findings, sent = parse_tree(text)
    return [(f.code, f.path) for f in run(document, "xrechnung", sent)]


def failing(text: str) -> list:
    return sorted({code for code, _path in found(text)})


def as_xrechnung(text: str) -> str:
    """Peppol's sample, which is XRechnung's but for two values."""
    for peppols, xrechnungs in zip(PEPPOLS, XRECHNUNGS):
        text = text.replace(peppols, xrechnungs)
    return text


class WhatIsBuilt(unittest.TestCase):
    def test_the_34_rules_of_a_standard_document(self):
        self.assertEqual(len(STANDARD), 34)
        self.assertEqual(sorted(REGISTRY["xrechnung"]), STANDARD)
        flags = [published.XRECHNUNG[i] for i in STANDARD]
        self.assertEqual((flags.count("fatal"), flags.count("warning"), flags.count("information")),
                         (25, 8, 1))

    def test_31_are_germanys_under_xrechnungs_names(self):
        self.assertEqual(len(NAMES), 31)
        self.assertEqual(sorted(set(STANDARD) - set(NAMES.values())), sorted(ONLY_XRECHNUNGS))
        self.assertEqual((NAMES["001"], NAMES["023-1"], NAMES["025-2"], NAMES["T02"]),
                         ("BR-DE-1", "BR-DE-23-a", "BR-DE-25-b", "BR-TMP-2"))
        for key, name in NAMES.items():
            self.assertIn("DE-R-" + key, REGISTRY["peppol"])
            self.assertEqual(REGISTRY["peppol"]["DE-R-" + key].about, REGISTRY["xrechnung"][name].about)

    def test_two_of_them_are_flagged_otherwise_than_peppols(self):
        differing = {key: (published.PEPPOL["DE-R-" + key], published.XRECHNUNG[name])
                     for key, name in NAMES.items()
                     if published.PEPPOL["DE-R-" + key] != published.XRECHNUNG[name]}
        self.assertEqual(differing, {"T02": ("warning", "fatal")})

    def test_the_sample_fails_none_and_is_peppols_sample_but_for_two_values(self):
        self.assertEqual(found(XRECHNUNG), [])
        self.assertEqual(as_xrechnung(INVOICE), XRECHNUNG)


class GermanysRulesUnderXRechnungsNames(unittest.TestCase):
    """Every document Peppol's German rules are tested with, asked again as
    an XRechnung document: the same rules fail, under XRechnung's names."""

    def test_every_document_of_the_german_tests_fails_the_same_rules(self):
        seen, compared = set(), [0]
        peppols = test_peppol_de_rules.failing

        def both(text):
            german = peppols(text)
            # Not the ones with a party moved abroad: Peppol asks nothing of
            # those, and XRechnung asks all the same.
            if "<cbc:IdentificationCode>AT" not in text:
                wanted = sorted(NAMES[code[len("DE-R-"):]] for code in german)
                got = [code for code in failing(as_xrechnung(text)) if code not in ONLY_XRECHNUNGS]
                self.assertEqual(got, wanted, text[:200])
                seen.update(wanted)
                compared[0] += 1
            return german
        test_peppol_de_rules.failing = both
        try:
            cases = test_peppol_de_rules.EachRule()
            for name in sorted(n for n in dir(cases) if n.startswith("test_") and "zz" not in n):
                getattr(cases, name)()
        finally:
            test_peppol_de_rules.failing = peppols
        self.assertEqual(compared[0], 96)
        self.assertEqual(sorted(seen), sorted(NAMES.values()))

    def test_they_are_asked_whatever_the_countries(self):
        bare = changed(XRECHNUNG, "<cbc:Telephone>+49 40 000000</cbc:Telephone>", "")
        self.assertEqual(failing(bare), ["BR-DE-27", "BR-DE-6"])
        self.assertEqual(failing(bare.replace("<cbc:IdentificationCode>DE<",
                                              "<cbc:IdentificationCode>FR<")),
                         ["BR-DE-27", "BR-DE-6"])


class XRechnungsOwnThree(unittest.TestCase):
    def test_the_specification_identifier_is_exactly_one_of_three(self):
        name = XRECHNUNGS[0]
        for other in (name + "#conformant#urn:xeinkauf.de:kosit:extension:xrechnung_3.0",
                      name + "#compliant#urn:xeinkauf.de:kosit:xrechnung:cvd_0.9"):
            self.assertEqual(failing(changed(XRECHNUNG, name + "<", other + "<")), [])
        for other in (name + " ", name.replace("3.0", "2.3"), PEPPOLS[0], name.upper()):
            self.assertEqual(found(changed(XRECHNUNG, name + "<", other + "<")),
                             [("BR-DE-21", "/Invoice/cbc:CustomizationID")], other)
        self.assertEqual(published.XRECHNUNG["BR-DE-21"], "warning")

    def test_a_document_that_does_not_say_when_it_was_delivered_is_told_so(self):
        delivery = "<cbc:ActualDeliveryDate>2026-09-30</cbc:ActualDeliveryDate>"
        without = changed(XRECHNUNG, delivery, "<cbc:ID>x</cbc:ID>").replace(
            "<cbc:ID>x</cbc:ID>", "<cac:DeliveryLocation><cbc:ID>4012345000016</cbc:ID>"
            "</cac:DeliveryLocation>")
        self.assertEqual(found(without), [("BR-DE-TMP-32", "/Invoice")])
        period = "<cac:InvoicePeriod><cbc:StartDate>2026-09-01</cbc:StartDate></cac:InvoicePeriod>"
        self.assertEqual(failing(changed(without, "<cac:OrderReference>",
                                         period + "<cac:OrderReference>")), [])
        # A period on one line of two is not one on every line.
        one = changed(without, "<cac:OrderLineReference>", period + "<cac:OrderLineReference>")
        self.assertEqual(failing(one), ["BR-DE-TMP-32"])
        self.assertEqual(failing(changed(one, "<cac:AllowanceCharge>\n      <cbc:ChargeIndicator>"
                                         "false</cbc:ChargeIndicator>\n      "
                                         "<cbc:AllowanceChargeReason>Introductory",
                                         period + "<cac:AllowanceCharge>\n      "
                                         "<cbc:ChargeIndicator>false</cbc:ChargeIndicator>\n      "
                                         "<cbc:AllowanceChargeReason>Introductory")), [])
        # It is information: said, and no fault.
        _document, report = validate(without)
        self.assertEqual([(f.level, f.code) for f in report.findings],
                         [("information", "BR-DE-TMP-32")])
        self.assertEqual((report.failures, report.verdict), ([], "valid"))

    def test_a_date_looks_like_a_date_and_no_more_is_asked(self):
        for name, good in (("IssueDate", "2026-10-02"), ("DueDate", "2026-11-01"),
                           ("ActualDeliveryDate", "2026-09-30")):
            for date, right in ((" 2026-10-02\n", True), ("2026-02-30", True), ("9999-99-99", True),
                                ("2026-10-2", False), ("02.10.2026", False),
                                ("2026-10-02Z", False), ("2026-10-02+01:00", False)):
                text = changed(XRECHNUNG, "<cbc:%s>%s" % (name, good), "<cbc:%s>%s" % (name, date))
                self.assertEqual("BR-TMP-6" in failing(text), not right, (name, date))
        self.assertEqual(found(changed(XRECHNUNG, "<cbc:DueDate>2026-11-01", "<cbc:DueDate>soon")),
                         [("BR-TMP-6", "/Invoice/cbc:DueDate")])
        self.assertEqual(published.XRECHNUNG["BR-TMP-6"], "warning")
        # A credit note's due date is in its payment instructions, and is asked.
        from .test_ubl_rules import document
        self.assertIn(("BR-TMP-6", "/CreditNote/cac:PaymentMeans/cbc:PaymentDueDate"), found(document(
            "<cac:PaymentMeans><cbc:PaymentDueDate>soon</cbc:PaymentDueDate></cac:PaymentMeans>",
            "CreditNote")))

    def test_an_external_location_that_is_no_url_is_fatal_here(self):
        text = changed(XRECHNUNG, "<cac:AccountingSupplierParty>", test_peppol_de_rules.ATTACHED % (
            "T-1", "<cac:ExternalReference><cbc:URI>example.org/a.pdf</cbc:URI>"
            "</cac:ExternalReference>") + "<cac:AccountingSupplierParty>")
        _document, report = validate(text)
        self.assertEqual([(f.level, f.code) for f in report.findings], [("fatal", "BR-TMP-2")])
        self.assertEqual(report.verdict, "invalid")


class ExtensionAndCvd(unittest.TestCase):
    """Their rules are not built, and their documents are refused by name."""

    def root(self, text: str):
        return top(tree(text))

    def test_their_22_rules_are_not_built(self):
        others = [i for i in published.XRECHNUNG if i not in STANDARD]
        self.assertEqual(len(others), 22)
        self.assertFalse(set(others) & set(REGISTRY["xrechnung"]))
        self.assertEqual(sorted(SCOPES["xrechnung"]), ["BR-DE-CVD-", "BR-DEX-", "BR-TMP-CVD-"])

    def test_they_could_apply_only_to_a_document_that_names_them(self):
        standard = self.root(XRECHNUNG)
        extension = self.root(changed(XRECHNUNG, XRECHNUNGS[0] + "<", XRECHNUNGS[0]
                                      + "#conformant#urn:xeinkauf.de:kosit:extension:xrechnung_3.0<"))
        cvd = self.root(changed(XRECHNUNG, XRECHNUNGS[0] + "<", XRECHNUNGS[0]
                                + "#compliant#urn:xeinkauf.de:kosit:xrechnung:cvd_0.9<"))
        for rule, in_extension, in_cvd in (("BR-DEX-01", True, False), ("BR-DE-CVD-01", False, True),
                                           ("BR-TMP-CVD-01", False, True)):
            self.assertFalse(could_apply("xrechnung", rule, standard), rule)
            self.assertEqual(could_apply("xrechnung", rule, extension), in_extension, rule)
            self.assertEqual(could_apply("xrechnung", rule, cvd), in_cvd, rule)
        self.assertTrue(could_apply("xrechnung", "BR-DE-1", standard))

    def test_a_document_that_names_them_is_refused_before_any_rule(self):
        for suffix, code in (("#conformant#urn:xeinkauf.de:kosit:extension:xrechnung_3.0",
                              "XRECHNUNG-EXTENSION"),
                             ("#compliant#urn:xeinkauf.de:kosit:xrechnung:cvd_0.9", "XRECHNUNG-CVD")):
            text = changed(XRECHNUNG, XRECHNUNGS[0] + "<", XRECHNUNGS[0] + suffix + "<")
            with self.assertRaises(Refused) as caught:
                validate(text)
            self.assertEqual(caught.exception.code, code)

    def test_and_one_held_to_xrechnung_all_the_same_waits_on_their_rules(self):
        # Nobody gets a verdict of valid by being checked as what they are not.
        text = changed(XRECHNUNG, XRECHNUNGS[0] + "<", XRECHNUNGS[0]
                       + "#conformant#urn:xeinkauf.de:kosit:extension:xrechnung_3.0<")
        document, _findings, sent = parse_tree(text)
        report = check(document, "xrechnung", (), sent)
        self.assertEqual(report.verdict, "not judged")
        self.assertEqual(len(report.not_built["xrechnung"]), 14)
        self.assertEqual(report.unasked, 13)


class TheVerdict(unittest.TestCase):
    def test_a_standard_xrechnung_document_with_nothing_wrong_is_valid(self):
        document, specification, findings = read(XRECHNUNG)
        self.assertEqual((specification, findings), ("xrechnung", []))
        _document, report = validate(XRECHNUNG)
        self.assertEqual((report.findings, report.verdict), ([], "valid"))
        self.assertEqual(report.not_built, {"en16931": {}, "xrechnung": {}})
        self.assertEqual(len(report.ran), 979 + 34)

    def test_one_fatal_rule_of_xrechnungs_is_invalid(self):
        _document, report = validate(changed(XRECHNUNG, "<cbc:BuyerReference>04011000-12345-06"
                                                        "</cbc:BuyerReference>", ""))
        self.assertEqual([f.code for f in report.failures], ["BR-DE-15"])
        self.assertEqual(report.verdict, "invalid")

    def test_peppols_rules_are_not_asked_of_it_nor_xrechnungs_of_peppols(self):
        _document, report = validate(XRECHNUNG)
        self.assertFalse(any(i.startswith(("PEPPOL-", "DE-R-")) for i in report.ran))
        _document, report = validate(INVOICE)
        self.assertFalse(any(i.startswith("BR-DE-") or i.startswith("BR-TMP-") for i in report.ran))
