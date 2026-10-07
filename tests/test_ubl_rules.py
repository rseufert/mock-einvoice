"""The rules of EN 16931 about the UBL document itself: UBL-CR, UBL-DT, UBL-SR.

Nearly all of them have no unit test from their publisher, so they are held
here to a second reading of their paths: the standard library's own path
language, which shares no code with `rules/tree.py`.
"""
import unittest
import xml.etree.ElementTree as ET

from mockeinvoice import check, read, validate, write
from mockeinvoice.model import Document
from mockeinvoice.rules import REGISTRY, published, run, unsaid
from mockeinvoice.rules.tree import NAMESPACES, At, contexts, select, top
from mockeinvoice.rules.ublsyntax import ABSENT, AT_MOST_ONE
from mockeinvoice.ubl import parse_tree, tree

from .test_rules import CREDIT_NOTE, INVOICE, changed

UBL_RULES = [i for i in published.EN16931 if i.startswith("UBL-")]
ROOTS = {"Invoice": "ubl", "CreditNote": "cn"}
DECLARED = " ".join('xmlns:%s="%s"' % pair for pair in NAMESPACES.items()
                    if pair[0] not in ("ubl", "cn"))


def document(inside: str, kind: str = "Invoice") -> str:
    return '<%s xmlns="%s" %s>%s</%s>' % (kind, NAMESPACES[ROOTS[kind]], DECLARED, inside, kind)


def fired(text: str, among=UBL_RULES) -> list:
    """The rules about the XML that a document fails as sent, with where."""
    parsed, _findings, sent = parse_tree(text)
    return [(f.code, f.path) for f in run(parsed, "en16931", sent) if f.code in among]


def codes(text: str, among=UBL_RULES) -> list:
    return sorted({code for code, _path in fired(text, among)})


def steps(path: str, kind: str) -> list:
    """A published path as the names to nest, for one kind of document:
    `(cac:InvoiceLine|cac:CreditNoteLine)` is whichever that document has."""
    line = "cac:InvoiceLine" if kind == "Invoice" else "cac:CreditNoteLine"
    names = [line if step.startswith("(") else step for step in path.lstrip("/").split("/")]
    # An attribute "anywhere" has to be on something.
    return ["cbc:Note"] + names if names[0].startswith("@") else names


def nested(names: list, innermost: str = "x") -> str:
    """Elements one inside another, the last holding text, with an attribute
    on it if the path ends in one."""
    attribute = ""
    if not names:
        return innermost
    if names[-1].startswith("@"):
        attribute, names = ' %s="x"' % names[-1][1:], names[:-1]
    text = innermost
    for depth, name in enumerate(reversed(names)):
        text = "<%s%s>%s</%s>" % (name, attribute if depth == 0 else "", text, name)
    return text


def by_the_library(root: ET.Element, path: str) -> int:
    """How many things a published path finds, by `xml.etree`'s reading."""
    anywhere, parts = path.startswith("//"), path.lstrip("/").split("/")
    attribute = parts.pop()[1:] if parts[-1].startswith("@") else None
    if not parts:       # `//@name`: the attribute on any element, the root too
        return sum(1 for element in root.iter() if attribute in element.attrib)
    alternatives = parts[0].strip("()").split("|")
    total = 0
    for first in alternatives:
        query = "/".join([first] + parts[1:])
        found = root.findall((".//" if anywhere else "") + query, NAMESPACES)
        total += sum(1 for element in found if attribute is None or attribute in element.attrib)
    return total


class TheThreeFamilies(unittest.TestCase):
    def test_there_are_756_of_them_and_all_are_built_over_the_documents_elements(self):
        self.assertEqual(len(UBL_RULES), 756)
        families = {family: sum(1 for i in UBL_RULES if i.startswith(family))
                    for family in ("UBL-CR-", "UBL-DT-", "UBL-SR-")}
        self.assertEqual(families, {"UBL-CR-": 678, "UBL-DT-": 24, "UBL-SR-": 54})
        self.assertTrue(all(REGISTRY["en16931"][i].over == "tree" for i in UBL_RULES))
        fatal = [i for i in UBL_RULES if published.EN16931[i] == "fatal"]
        self.assertEqual(len(fatal), 59)
        self.assertEqual([i for i in fatal if i.startswith("UBL-CR")], ["UBL-CR-666", "UBL-CR-673"])

    def test_all_but_26_are_one_of_two_tests_and_no_rule_is_both(self):
        self.assertEqual((len(ABSENT), len(AT_MOST_ONE)), (693, 37))
        self.assertFalse(set(ABSENT) & set(AT_MOST_ONE))
        self.assertEqual(len(set(UBL_RULES) - set(ABSENT) - set(AT_MOST_ONE)), 26)
        self.assertLessEqual(set(ABSENT) | set(AT_MOST_ONE), set(UBL_RULES))

    def test_the_paths_say_whose_they_are(self):
        from mockeinvoice.rules import ublsyntax
        self.assertIn("European Union Public\nLicence 1.2", ublsyntax.__doc__)
        self.assertIn("Do not edit by hand", ublsyntax.__doc__)

    def test_the_documents_this_project_wrote_fail_none_of_them(self):
        for text in (INVOICE, CREDIT_NOTE):
            self.assertEqual(fired(text), [])

    def test_a_finding_says_where_in_the_document_as_sent(self):
        text = changed(INVOICE, "<cbc:IssueDate>", "<cbc:UUID>1</cbc:UUID><cbc:IssueDate>")
        parsed, _findings, sent = parse_tree(text)
        finding, = run(parsed, "en16931", sent)
        self.assertEqual((finding.level, finding.code, finding.path),
                         ("warning", "UBL-CR-005", "/Invoice/cbc:UUID"))
        self.assertEqual(finding.text, "the element cbc:UUID is not used at the head of the "
                         "document: it is there")
        self.assertIn("validation-1.3.16", finding.link)


class WhatIsNotToBeThere(unittest.TestCase):
    """693 rules, each one path. A document is made with that path in it and
    nothing else, and every one of the 693 is asked of it twice: by the rules
    and by the standard library."""

    def expected(self, text: str) -> list:
        root = ET.fromstring(text)
        return sorted(identifier for identifier, path in ABSENT.items()
                      if by_the_library(root, path))

    def test_each_rule_fires_on_its_own_path_and_agrees_with_the_library_on_every_other(self):
        for kind in ROOTS:
            for identifier, path in ABSENT.items():
                text = document(nested(steps(path, kind)), kind)
                found = codes(text, ABSENT)
                self.assertIn(identifier, found, (kind, path))
                self.assertEqual(found, self.expected(text), (kind, identifier, path))

    def test_most_fire_alone_and_the_rest_are_the_same_place_said_two_ways(self):
        together = {}
        for identifier, path in ABSENT.items():
            found = codes(document(nested(steps(path, "Invoice"))), ABSENT)
            if found != [identifier]:
                together[identifier] = [other for other in found if other != identifier]
        # A path from the root and a path from anywhere that end alike.
        self.assertEqual(together, {
            "UBL-CR-430": ["UBL-CR-664"], "UBL-CR-431": ["UBL-CR-664"],
            "UBL-CR-633": ["UBL-CR-669"], "UBL-CR-634": ["UBL-CR-670"],
            "UBL-CR-635": ["UBL-CR-671"]})
        for identifier, others in together.items():
            for other in others:
                self.assertTrue(ABSENT[other].startswith("//") or ABSENT[identifier].startswith("//")
                                or ABSENT[identifier].startswith(ABSENT[other]),
                                (identifier, other))

    def test_where_it_is_found_is_the_element_or_the_attribute(self):
        self.assertEqual(fired(document(nested(["cac:InvoicePeriod", "cbc:StartTime"])), ABSENT),
                         [("UBL-CR-012", "/Invoice/cac:InvoicePeriod/cbc:StartTime")])
        self.assertEqual(fired(document('<cbc:ID schemeName="x">1</cbc:ID>'), ABSENT),
                         [("UBL-DT-08", "/Invoice/cbc:ID/@schemeName")])

    def test_each_place_is_reported(self):
        text = document("<cbc:UUID>1</cbc:UUID><cbc:UUID>2</cbc:UUID>")
        self.assertEqual(fired(text, ABSENT), [("UBL-CR-005", "/Invoice/cbc:UUID[1]"),
                                               ("UBL-CR-005", "/Invoice/cbc:UUID[2]")])

    def test_anywhere_is_anywhere_and_from_the_root_is_from_the_root(self):
        deep = "<cac:InvoiceLine><cac:Price>%s</cac:Price></cac:InvoiceLine>"
        # `//cac:FinancialInstitution`, wherever.
        self.assertEqual(codes(document(deep % "<cac:FinancialInstitution/>"), ABSENT),
                         ["UBL-CR-664"])
        # `cbc:UUID` is the head's; in a price it is nobody's rule.
        self.assertEqual(codes(document(deep % "<cbc:UUID>1</cbc:UUID>"), ABSENT), [])
        # An attribute anywhere is found on the root too.
        self.assertEqual(codes('<Invoice xmlns="%s" languageID="en"/>' % NAMESPACES["ubl"], ABSENT),
                         ["UBL-DT-19"])

    def test_a_line_is_whichever_line_the_document_has(self):
        for kind, line in (("Invoice", "cac:InvoiceLine"), ("CreditNote", "cac:CreditNoteLine")):
            self.assertEqual(codes(document(nested([line, "cbc:UUID"]), kind), ABSENT),
                             ["UBL-CR-515"])


class AtMostOnce(unittest.TestCase):
    """37 rules, each a path from an element that may be there once."""

    def around(self, context: str, inside: str, kind: str) -> str:
        """The element a rule is asked of, holding `inside`."""
        if context == "/ubl:Invoice | /cn:CreditNote":
            return inside
        name = context.split(" | ")[0 if kind == "Invoice" else -1]
        if "[" in name:
            name, _, predicate = name.partition("[")
            inside = "<cbc:ChargeIndicator>%s</cbc:ChargeIndicator>%s" % (
                "true" if "true()" in predicate else "false", inside)
        return "<%s>%s</%s>" % (name, inside, name)

    def test_once_passes_and_twice_fails_at_the_second(self):
        for kind in ROOTS:
            for identifier, (context, path) in AT_MOST_ONE.items():
                names = path.split("/")
                once = nested(names)
                self.assertEqual(codes(document(self.around(context, once, kind), kind),
                                       AT_MOST_ONE), [], (identifier, kind))
                twice = nested(names[:-1], nested(names[-1:]) * 2)
                found = fired(document(self.around(context, twice, kind), kind), [identifier])
                self.assertEqual(len(found), 1, (identifier, kind))
                self.assertTrue(found[0][1].endswith(names[-1] + "[2]"), found)

    def test_twice_is_twice_whichever_element_on_the_way_is_doubled(self):
        for identifier, (context, path) in AT_MOST_ONE.items():
            names = path.split("/")
            for depth in range(len(names)):
                doubled = nested(names[:depth], nested(names[depth:]) * 2)
                text = document(self.around(context, doubled, "Invoice"))
                self.assertIn(identifier, codes(text, AT_MOST_ONE), (identifier, depth))

    def test_the_count_is_within_each_element_the_rule_is_asked_of(self):
        # Two lines with a note each are two lines with one note.
        line = "<cac:InvoiceLine><cbc:Note>a</cbc:Note></cac:InvoiceLine>"
        self.assertEqual(codes(document(line * 2), AT_MOST_ONE), [])
        self.assertEqual(fired(document(line + line.replace("</cbc:Note>", "</cbc:Note><cbc:Note/>")),
                               AT_MOST_ONE),
                         [("UBL-SR-34", "/Invoice/cac:InvoiceLine[2]/cbc:Note[2]")])

    def test_an_allowances_rule_is_not_asked_of_a_charge(self):
        reasons = "<cbc:AllowanceChargeReason>a</cbc:AllowanceChargeReason>" * 2
        for indicator, rule in (("false", "UBL-SR-30"), ("0", "UBL-SR-30"),
                                ("true", "UBL-SR-31"), (" 1 ", "UBL-SR-31")):
            text = document("<cac:AllowanceCharge><cbc:ChargeIndicator>%s</cbc:ChargeIndicator>%s"
                            "</cac:AllowanceCharge>" % (indicator, reasons))
            self.assertEqual(codes(text, AT_MOST_ONE), [rule], indicator)
        # Neither true nor false: the two rules cannot be computed.
        text = document("<cac:AllowanceCharge><cbc:ChargeIndicator>yes</cbc:ChargeIndicator>%s"
                        "</cac:AllowanceCharge>" % reasons)
        parsed, _findings, sent = parse_tree(text)
        found = [f for f in run(parsed, "en16931", sent) if f.code in ("UBL-SR-30", "UBL-SR-31")]
        self.assertEqual(len(found), 2)
        self.assertTrue(all("could not be computed" in f.text for f in found))


class TheRulesWrittenByHand(unittest.TestCase):
    HAND = sorted(set(UBL_RULES) - set(ABSENT) - set(AT_MOST_ONE))

    def only(self, text: str, kind: str = "Invoice") -> list:
        return codes(document(text, kind), self.HAND)

    def test_every_one_of_them_fails_in_this_class(self):
        self.assertEqual(self.HAND, sorted(
            ["UBL-CR-002", "UBL-CR-412", "UBL-CR-665", "UBL-CR-666", "UBL-CR-673",
             "UBL-DT-01", "UBL-DT-06", "UBL-DT-07", "UBL-DT-18",
             "UBL-SR-04", "UBL-SR-07", "UBL-SR-12", "UBL-SR-13", "UBL-SR-18", "UBL-SR-19",
             "UBL-SR-20", "UBL-SR-21", "UBL-SR-29", "UBL-SR-42", "UBL-SR-43", "UBL-SR-44",
             "UBL-SR-46", "UBL-SR-47", "UBL-SR-48", "UBL-SR-51", "UBL-SR-53"]))

    def test_the_ubl_version(self):
        self.assertEqual(self.only("<cbc:UBLVersionID>2.1</cbc:UBLVersionID>"), [])
        self.assertEqual(self.only("<cbc:UBLVersionID>2.2</cbc:UBLVersionID>"), ["UBL-CR-002"])
        self.assertEqual(self.only("<cbc:UBLVersionID> 2.1</cbc:UBLVersionID>"), ["UBL-CR-002"])
        self.assertEqual(self.only(""), [])

    def test_a_due_date_in_the_payment_instructions_is_a_credit_notes(self):
        means = "<cac:PaymentMeans><cbc:PaymentDueDate>2026-11-01</cbc:PaymentDueDate></cac:PaymentMeans>"
        self.assertEqual(self.only(means), ["UBL-CR-412"])
        self.assertEqual(self.only(means, "CreditNote"), [])

    def reference(self, inside: str, type_code=None) -> str:
        return "<cac:AdditionalDocumentReference>%s%s</cac:AdditionalDocumentReference>" % (
            inside, "" if type_code is None else
            "<cbc:DocumentTypeCode>%s</cbc:DocumentTypeCode>" % type_code)

    def test_a_scheme_on_a_reference_is_the_invoiced_objects(self):
        schemed = '<cbc:ID schemeID="ABZ">M-1</cbc:ID>'
        self.assertEqual(self.only(self.reference(schemed, "130")), [])
        self.assertEqual(self.only(self.reference(schemed)), ["UBL-CR-665", "UBL-SR-43"])
        self.assertEqual(self.only(self.reference(schemed, "916")), ["UBL-CR-665", "UBL-SR-43"])
        self.assertEqual(self.only(self.reference("<cbc:ID>T-1</cbc:ID>")), [])
        # A type code that is neither is a failure with or without a scheme.
        self.assertEqual(self.only(self.reference("<cbc:ID>T-1</cbc:ID>", "916")), ["UBL-SR-43"])
        # 50 is the project, on a credit note and nowhere else.
        self.assertEqual(self.only(self.reference("<cbc:ID>P-1</cbc:ID>", "50"), "CreditNote"), [])
        self.assertEqual(self.only(self.reference("<cbc:ID>P-1</cbc:ID>", "50")), ["UBL-SR-43"])
        self.assertEqual(self.only(self.reference(schemed, " 130 ")), ["UBL-CR-665", "UBL-SR-43"])

    def test_an_invoiced_object_has_no_attachment_and_no_description_and_one_identifier(self):
        identifier = "<cbc:ID>M-1</cbc:ID>"
        self.assertEqual(self.only(self.reference(identifier + "<cac:Attachment/>", "130")),
                         ["UBL-CR-666"])
        self.assertEqual(self.only(self.reference(
            identifier + "<cbc:DocumentDescription>d</cbc:DocumentDescription>", "130")),
            ["UBL-CR-673"])
        self.assertEqual(self.only(self.reference(
            identifier + "<cbc:DocumentDescription>d</cbc:DocumentDescription><cac:Attachment/>")),
            [])
        self.assertEqual(self.only(self.reference(identifier * 2, "130")), ["UBL-SR-04"])
        self.assertEqual(self.only(self.reference(identifier, "130") * 2), ["UBL-SR-04"])
        self.assertEqual(self.only(self.reference(identifier * 2)), [])
        both = published.EN16931
        self.assertEqual((both["UBL-CR-666"], both["UBL-CR-673"], both["UBL-CR-665"]),
                         ("fatal", "fatal", "warning"))

    def test_any_amount_has_two_decimals_but_a_price_and_its_allowance(self):
        def amount(name, value="1.234"):
            return "<cbc:%s>%s</cbc:%s>" % (name, value, name)
        self.assertEqual(fired(document(amount("PayableAmount")), ["UBL-DT-01"]),
                         [("UBL-DT-01", "/Invoice/cbc:PayableAmount")])
        self.assertEqual(self.only(amount("PayableAmount", "1.23")), [])
        self.assertEqual(self.only(amount("PayableAmount", "1.23 ")), ["UBL-DT-01"])
        # Any element named so, whether or not the standard has it.
        self.assertEqual(codes(document(
            "<cac:InvoiceLine><cac:TaxTotal>%s</cac:TaxTotal></cac:InvoiceLine>"
            % amount("TaxAmount")), ["UBL-DT-01"]), ["UBL-DT-01"])
        self.assertEqual(self.only(amount("MinimumAmount")), ["UBL-DT-01"])
        price = "<cac:InvoiceLine><cac:Price>%s</cac:Price></cac:InvoiceLine>"

        def in_a_price(inside):
            return codes(document(price % inside), ["UBL-DT-01"])
        self.assertEqual(in_a_price(amount("PriceAmount")), [])
        allowance = "<cac:AllowanceCharge>%s%s</cac:AllowanceCharge>" % (
            amount("Amount"), amount("BaseAmount"))
        self.assertEqual(in_a_price(allowance), [])
        # The exception is for anything in a price that has an allowance.
        self.assertEqual(in_a_price(amount("BaseAmount")), ["UBL-DT-01"])
        self.assertEqual(in_a_price(amount("BaseAmount") + "<cac:AllowanceCharge/>"), [])
        self.assertEqual(self.only("<cac:AllowanceCharge>%s</cac:AllowanceCharge>" % amount("Amount")),
                         ["UBL-DT-01"])

    def test_an_attachment_says_its_mime_type_and_file_name(self):
        def attached(attributes):
            return self.only(self.reference(
                "<cbc:ID>T-1</cbc:ID><cac:Attachment><cbc:EmbeddedDocumentBinaryObject%s>eA=="
                "</cbc:EmbeddedDocumentBinaryObject></cac:Attachment>" % attributes))
        self.assertEqual(attached(' mimeCode="text/csv" filename="a.csv"'), [])
        self.assertEqual(attached(' filename="a.csv"'), ["UBL-DT-06"])
        self.assertEqual(attached(' mimeCode="text/csv"'), ["UBL-DT-07"])
        self.assertEqual(attached(""), ["UBL-DT-06", "UBL-DT-07"])
        self.assertEqual(attached(' mimeCode="" filename=""'), [])

    def test_only_a_payment_means_code_says_what_it_means(self):
        means = "<cac:PaymentMeans><cbc:PaymentMeansCode%s>30</cbc:PaymentMeansCode></cac:PaymentMeans>"
        self.assertEqual(self.only(means % ' name="Credit transfer"'), [])
        self.assertEqual(fired(document('<cbc:ID name="n">1</cbc:ID>'), ["UBL-DT-18"]),
                         [("UBL-DT-18", "/Invoice/cbc:ID/@name")])
        # And only one of them does.
        self.assertEqual(self.only(means % ' name="a"' * 2), ["UBL-SR-46"])
        self.assertEqual(self.only(means % ' name="a"' + means % ""), [])

    def test_two_payment_instructions_say_the_same(self):
        def means(code, reference=""):
            return ("<cac:PaymentMeans><cbc:PaymentMeansCode>%s</cbc:PaymentMeansCode>%s"
                    "</cac:PaymentMeans>" % (code, "<cbc:PaymentID>%s</cbc:PaymentID>" % reference
                                             if reference else ""))
        self.assertEqual(self.only(means("30", "R1") + means("30", "R1")), [])
        self.assertEqual(self.only(means("30", "R1") + means("58", "R1")), ["UBL-SR-47"])
        self.assertEqual(self.only(means("30", "R1") + means("30", "R2")), ["UBL-SR-44"])
        self.assertEqual(self.only(means("30", "R1") + means("30")), [])
        self.assertEqual(self.only(means("30") + means("30 ")), ["UBL-SR-47"])
        self.assertEqual(fired(document(means("30") + means("58") + means("49")), ["UBL-SR-47"]),
                         [("UBL-SR-47", "/Invoice/cac:PaymentMeans[2]/cbc:PaymentMeansCode")])

    def party(self, who: str, inside: str) -> str:
        return "<cac:%s><cac:Party>%s</cac:Party></cac:%s>" % (who, inside, who)

    def registered(self, identifier="DE1", scheme="VAT") -> str:
        return ("<cac:PartyTaxScheme>%s%s</cac:PartyTaxScheme>" % (
            "" if identifier is None else "<cbc:CompanyID>%s</cbc:CompanyID>" % identifier,
            "" if scheme is None else "<cac:TaxScheme><cbc:ID>%s</cbc:ID></cac:TaxScheme>" % scheme))

    def test_a_party_has_one_vat_identifier_and_the_seller_one_other_registration(self):
        seller = functools_partial(self.party, "AccountingSupplierParty")
        buyer = functools_partial(self.party, "AccountingCustomerParty")
        self.assertEqual(self.only(seller(self.registered() + self.registered("1", "FC"))), [])
        self.assertEqual(self.only(seller(self.registered() * 2)), ["UBL-SR-12"])
        self.assertEqual(self.only(seller(self.registered("1", "vat") * 2)), ["UBL-SR-12"])
        self.assertEqual(self.only(seller(self.registered("1", "FC") * 2)), ["UBL-SR-13"])
        self.assertEqual(self.only(buyer(self.registered() * 2)), ["UBL-SR-18"])
        self.assertEqual(self.only(buyer(self.registered("1", "FC") * 2)), [])
        # Not trimmed here: ` VAT` is another scheme to these three rules.
        self.assertEqual(self.only(seller(self.registered("1", " VAT") * 2)), ["UBL-SR-13"])
        # A scheme with no name is not VAT either, and one registration that
        # names VAT and another scheme is both.
        nameless = ("<cac:PartyTaxScheme><cbc:CompanyID>1</cbc:CompanyID><cac:TaxScheme/>"
                    "</cac:PartyTaxScheme>")
        self.assertEqual(self.only(seller(nameless * 2)), ["UBL-SR-13", "UBL-SR-53"])
        both = ("<cac:PartyTaxScheme><cbc:CompanyID>1</cbc:CompanyID><cac:TaxScheme><cbc:ID>VAT"
                "</cbc:ID></cac:TaxScheme><cac:TaxScheme><cbc:ID>FC</cbc:ID></cac:TaxScheme>"
                "</cac:PartyTaxScheme>")
        self.assertEqual(self.only(seller(both * 2)), ["UBL-SR-12", "UBL-SR-13"])
        self.assertEqual(self.only(seller(self.registered() + self.registered("1", "FC")
                                          + self.registered("2", "XX"))),
                         ["UBL-SR-13", "UBL-SR-42"])
        self.assertEqual(fired(document(seller(self.registered() * 3)), ["UBL-SR-42"]), [
            ("UBL-SR-42", "/Invoice/cac:AccountingSupplierParty/cac:Party/cac:PartyTaxScheme[3]")])

    def test_a_tax_registration_has_an_identifier_and_names_its_scheme(self):
        seller = functools_partial(self.party, "AccountingSupplierParty")
        self.assertEqual(self.only(seller(self.registered())), [])
        self.assertEqual(self.only(seller(self.registered(None))), ["UBL-SR-53"])
        self.assertEqual(self.only(seller(self.registered("DE1", None))), ["UBL-SR-53"])
        self.assertEqual(self.only("<cac:TaxRepresentativeParty>%s</cac:TaxRepresentativeParty>"
                                   % self.registered("DE1", None)), ["UBL-SR-53"])
        self.assertEqual(self.only(seller(
            "<cac:PartyTaxScheme><cbc:CompanyID>1</cbc:CompanyID><cac:TaxScheme/>"
            "</cac:PartyTaxScheme>")), ["UBL-SR-53"])

    def payee(self, inside: str, sellers_name="Globex GmbH") -> list:
        seller = self.party("AccountingSupplierParty", (
            "<cac:PartyLegalEntity><cbc:RegistrationName>%s</cbc:RegistrationName>"
            "</cac:PartyLegalEntity>" % sellers_name) if sellers_name else "")
        return self.only(seller + "<cac:PayeeParty>%s</cac:PayeeParty>" % inside)

    def test_a_payee_has_a_name_that_is_not_the_sellers_legal_name(self):
        name = "<cac:PartyName><cbc:Name>%s</cbc:Name></cac:PartyName>"
        all_three = ["UBL-SR-19", "UBL-SR-20", "UBL-SR-21"]
        self.assertEqual(self.payee(name % "Factor AG"), [])
        self.assertEqual(self.payee(name % "Globex GmbH"), all_three)
        self.assertEqual(self.payee(name % "globex gmbh"), [])
        # A name that is not there is not different from anything.
        self.assertEqual(self.payee(""), all_three)
        self.assertEqual(self.payee(name % "Factor AG", sellers_name=""), all_three)

    def test_a_payee_has_one_name_one_identifier_and_one_legal_registration(self):
        name = "<cac:PartyName><cbc:Name>Factor AG</cbc:Name></cac:PartyName>"
        identifier = '<cac:PartyIdentification><cbc:ID%s>1</cbc:ID></cac:PartyIdentification>'
        legal = "<cac:PartyLegalEntity><cbc:CompanyID>1</cbc:CompanyID></cac:PartyLegalEntity>"
        self.assertEqual(self.payee(name + identifier % "" + legal), [])
        self.assertEqual(self.payee(name * 2), ["UBL-SR-19"])
        self.assertEqual(self.payee(name + identifier % "" * 2), ["UBL-SR-20"])
        self.assertEqual(self.payee(name + identifier % ' schemeID="0088"' * 2), ["UBL-SR-20"])
        # Its creditor identifier is not counted with the others.
        self.assertEqual(self.payee(name + identifier % "" + identifier % ' schemeID="sepa"'), [])
        self.assertEqual(self.payee(name + legal * 2), ["UBL-SR-21"])

    def test_one_creditor_identifier_in_the_document(self):
        sepa = '<cac:PartyIdentification><cbc:ID schemeID="%s">DE98ZZZ0</cbc:ID></cac:PartyIdentification>'
        seller = self.party("AccountingSupplierParty", sepa % "SEPA")
        self.assertEqual(self.only(seller), [])
        self.assertEqual(self.only(self.party("AccountingSupplierParty", sepa % "SEPA" + sepa % "Sepa")),
                         ["UBL-SR-29"])
        self.assertEqual(fired(document(seller + self.party("AccountingCustomerParty", sepa % "SEPA")),
                               ["UBL-SR-29"]),
                         [("UBL-SR-29", "/Invoice/cac:AccountingCustomerParty/cac:Party/"
                                        "cac:PartyIdentification/cbc:ID")])

    def test_a_line_has_exactly_one_vat_category(self):
        def line(categories: int, kind="Invoice"):
            name = "cac:InvoiceLine" if kind == "Invoice" else "cac:CreditNoteLine"
            return fired(document("<%s><cac:Item>%s</cac:Item></%s>" % (
                name, "<cac:ClassifiedTaxCategory/>" * categories, name), kind), ["UBL-SR-48"])
        self.assertEqual(line(1), [])
        self.assertEqual(line(0), [("UBL-SR-48", "/Invoice/cac:InvoiceLine")])
        self.assertEqual(line(2), [("UBL-SR-48", "/Invoice/cac:InvoiceLine/cac:Item/"
                                                 "cac:ClassifiedTaxCategory[2]")])
        self.assertEqual(line(0, "CreditNote"), [("UBL-SR-48", "/CreditNote/cac:CreditNoteLine")])

    def test_an_address_has_one_third_line_wherever_the_address_is(self):
        lines = "<cac:AddressLine><cbc:Line>a</cbc:Line></cac:AddressLine>"
        for around in ("<cac:AccountingSupplierParty><cac:Party><cac:PostalAddress>%s"
                       "</cac:PostalAddress></cac:Party></cac:AccountingSupplierParty>",
                       "<cac:Delivery><cac:DeliveryLocation><cac:Address>%s</cac:Address>"
                       "</cac:DeliveryLocation></cac:Delivery>",
                       "<cac:TaxRepresentativeParty><cac:PostalAddress>%s</cac:PostalAddress>"
                       "</cac:TaxRepresentativeParty>"):
            self.assertEqual(self.only(around % lines), [], around)
            self.assertEqual(self.only(around % (lines * 2)), ["UBL-SR-51"], around)

    def test_a_preceding_invoice_reference_has_the_invoices_number(self):
        self.assertEqual(self.only("<cac:BillingReference/>") + codes(document(
            "<cac:BillingReference/>"), ["UBL-SR-07"]), ["UBL-SR-07"] * 2)
        self.assertEqual(codes(document(
            "<cac:BillingReference><cac:InvoiceDocumentReference><cbc:ID/>"
            "</cac:InvoiceDocumentReference></cac:BillingReference>"), ["UBL-SR-07"]), [])


def functools_partial(function, *arguments):
    import functools
    return functools.partial(function, *arguments)


class WhatTheReaderSaidAndWhatARuleSays(unittest.TestCase):
    """An element that is not held is reported once: under the published
    rule's name where there is one, and in the reader's words where not."""

    def test_an_unheld_element_a_rule_names_is_reported_as_the_rules(self):
        text = changed(INVOICE, "<cbc:IssueDate>", "<cbc:UBLVersionID>2.1</cbc:UBLVersionID>"
                       "<cbc:UUID>1</cbc:UUID><cbc:IssueDate>")
        _document, _specification, reading = read(text)
        self.assertEqual([(f.code, f.path) for f in reading],
                         [("UNHELD", "/Invoice/cbc:UBLVersionID"), ("UNHELD", "/Invoice/cbc:UUID")])
        _document, report = validate(text)
        # The version is allowed by its rule, so the reader's word stands.
        self.assertEqual([(f.level, f.code, f.path) for f in report.findings],
                         [("warning", "UNHELD", "/Invoice/cbc:UBLVersionID"),
                          ("warning", "UBL-CR-005", "/Invoice/cbc:UUID")])
        self.assertEqual(report.verdict, "valid")       # warnings, both of them

    def test_one_inside_an_unheld_element_covers_it(self):
        text = changed(INVOICE, "<cac:PaymentTerms>", "<cac:PaymentTerms><cac:SettlementPeriod>"
                       "<cbc:StartDate>2026-10-01</cbc:StartDate></cac:SettlementPeriod>")
        _document, report = validate(text)
        self.assertEqual([(f.code, f.path) for f in report.findings], [
            ("UBL-CR-466", "/Invoice/cac:PaymentTerms/cac:SettlementPeriod")])

    def test_a_repeat_a_rule_names_is_reported_as_the_rules_and_is_fatal(self):
        text = changed(INVOICE, "<cbc:IssueDate>", "<cbc:IssueDate>2026-10-02</cbc:IssueDate>"
                       "<cbc:IssueDate>")
        _document, report = validate(text)
        # No published rule says an issue date is there once: the reader does.
        self.assertEqual([(f.level, f.code) for f in report.findings],
                         [("error", "REPEATED"), ("fatal", "BR-03")])
        text = changed(INVOICE, "<cac:PartyLegalEntity>\n        <cbc:RegistrationName>Globex",
                       "<cac:PartyLegalEntity>\n        <cbc:RegistrationName>Globex AG"
                       "</cbc:RegistrationName><cbc:RegistrationName>Globex")
        _document, report = validate(text)
        self.assertEqual([(f.level, f.code, f.path.rpartition("/")[2]) for f in report.findings], [
            ("fatal", "BR-06", ""), ("fatal", "UBL-SR-09", "cbc:RegistrationName[2]")])
        self.assertIn("could not be computed", report.findings[0].text)

    def test_what_no_rule_names_stays_the_readers(self):
        reading = read(changed(INVOICE, "<cbc:IssueDate>", "<cbc:Madeup>1</cbc:Madeup>"
                               "<cbc:IssueDate>"))[2]
        self.assertEqual(unsaid(reading, []), list(reading))
        other = [f for f in reading if f.code == "UNHELD"]
        self.assertEqual(len(other), 1)
        _document, report = validate(changed(INVOICE, "<cbc:IssueDate>", "<cbc:Madeup>1"
                                             "</cbc:Madeup><cbc:IssueDate>"))
        self.assertEqual([(f.code, f.path) for f in report.findings],
                         [("UNHELD", "/Invoice/cbc:Madeup")])

    def test_a_neighbour_with_a_longer_name_is_not_covered(self):
        from mockeinvoice.model import Finding
        reading = [Finding("warning", "UNHELD", "/Invoice/cbc:ID", "x"),
                   Finding("warning", "TEXT", "/Invoice/cbc:UUID", "x")]
        found = [Finding("warning", "UBL-CR-005", "/Invoice/cbc:IDx", "x"),
                 Finding("warning", "UBL-CR-005", "/Invoice/cbc:UUID", "x"),
                 Finding("fatal", "BR-02", "BT-1", "x")]
        self.assertEqual(unsaid(reading, found), reading)
        found.append(Finding("warning", "UBL-DT-08", "/Invoice/cbc:ID/@schemeName", "x"))
        self.assertEqual(unsaid(reading, found), reading[1:])


class AModelAloneIsAskedAsItWouldBeWritten(unittest.TestCase):
    def test_a_document_read_and_checked_without_what_was_sent(self):
        text = changed(INVOICE, "<cbc:IssueDate>", "<cbc:UUID>1</cbc:UUID><cbc:IssueDate>")
        parsed, specification, reading = read(text)
        # The UUID is not held, so it is not in what would be written, so the
        # rule about it has nothing to find; the reader's word is all there is.
        report = check(parsed, specification, reading)
        self.assertEqual([f.code for f in report.findings], ["UNHELD"])
        self.assertNotIn(b"UUID", write(parsed))

    def test_a_document_made_by_hand_is_asked_too(self):
        made = Document(kind="Invoice")
        made.add("BT-24", "urn:cen.eu:en16931:2017#compliant#urn:fdc:peppol.eu:2017:poacc:billing:3.0")
        line = made.new("BG-25")
        line.add("BT-126", "1")
        report = check(made, "peppol")
        fired_codes = [f.code for f in report.findings]
        self.assertIn("UBL-SR-48", fired_codes)      # its line has no VAT category
        self.assertIn("BR-02", fired_codes)
        finding = next(f for f in report.findings if f.code == "UBL-SR-48")
        self.assertEqual(finding.path, "/Invoice/cac:InvoiceLine")

    def test_run_without_what_was_sent_is_the_same_as_with_what_would_be_written(self):
        parsed, _findings, _sent = parse_tree(INVOICE)
        line = parsed.all("BG-25")[0]
        line.terms.pop("BT-151")
        line.terms.pop("BT-152")
        written = tree(write(parsed))
        self.assertEqual(list(run(parsed, "en16931")), list(run(parsed, "en16931", written)))
        self.assertIn("UBL-SR-48", [f.code for f in run(parsed, "en16931")])


class TheWalker(unittest.TestCase):
    def root(self, inside: str) -> At:
        return top(tree(document(inside)))

    def test_paths_number_what_repeats(self):
        root = self.root("<cbc:Note>a</cbc:Note><cbc:Note>b</cbc:Note><cbc:ID>1</cbc:ID>")
        self.assertEqual([at.path for at in root.everything()],
                         ["/Invoice", "/Invoice/cbc:Note[1]", "/Invoice/cbc:Note[2]",
                          "/Invoice/cbc:ID"])
        self.assertEqual(select(root, "cbc:Note"), [("/Invoice/cbc:Note[1]", "a"),
                                                    ("/Invoice/cbc:Note[2]", "b")])

    def test_an_attribute_is_found_with_its_value(self):
        root = self.root('<cbc:ID schemeID="s">1</cbc:ID><cbc:ID>2</cbc:ID>')
        self.assertEqual(select(root, "cbc:ID/@schemeID"), [("/Invoice/cbc:ID[1]/@schemeID", "s")])
        self.assertEqual(select(root, "//@schemeID"), [("/Invoice/cbc:ID[1]/@schemeID", "s")])
        self.assertEqual(select(root, "cbc:ID/@other"), [])
        # Anywhere is the root too, if that is its name.
        self.assertEqual(select(root, "//ubl:Invoice"), [("/Invoice", "")])

    def test_a_context_is_an_element_wherever_or_one_inside_another(self):
        root = self.root(
            "<cac:AccountingSupplierParty><cac:Party><cac:PostalAddress/></cac:Party>"
            "</cac:AccountingSupplierParty><cac:AccountingCustomerParty><cac:Party/>"
            "</cac:AccountingCustomerParty><cac:Delivery><cac:DeliveryLocation><cac:Address/>"
            "</cac:DeliveryLocation></cac:Delivery>")
        self.assertEqual([at.path for at in contexts(root, "cac:AccountingSupplierParty/cac:Party")],
                         ["/Invoice/cac:AccountingSupplierParty/cac:Party"])
        self.assertEqual(len(contexts(root, "cac:Party")), 2)
        self.assertEqual(len(contexts(root, "//cac:PostalAddress | //cac:Address")), 2)
        self.assertEqual(contexts(root, "/ubl:Invoice | /cn:CreditNote"), [root])
