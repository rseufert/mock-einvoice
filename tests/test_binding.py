"""The binding as data: that a reader with it and nothing else names every
element of a document, and comes to the terms and values the package's own
reader comes to."""
import collections
import json
import re
import unittest
import xml.etree.ElementTree as ET

from mockeinvoice.model import ATTRIBUTE_TERMS, GROUPS, TERMS, Refused
from mockeinvoice.ubl import BINDINGS, Many, When, Wrap, described, parse

from . import external, sample

OWN = ("peppol-invoice.xml", "xrechnung-invoice.xml", "peppol-creditnote.xml")
NOTE = re.compile(r"#(\S+?)#(.*)", re.S)


def nodes(tree):
    """Every node of a described binding, each with the path of elements to it."""
    def walk(node, path):
        here = path + "/" + node["element"]
        yield here, node
        for child in node.get("children", ()):
            yield from walk(child, here)
    return list(walk(tree, ""))


class ByTheBindingAlone:
    """A reader that knows the served binding and nothing of this package:
    `xml.etree` for the XML, and JSON that has been to text and back."""

    def __init__(self, data: bytes):
        self.root = ET.fromstring(data)
        kind = self.root.tag.split("}")[-1]
        self.binding = json.loads(json.dumps(described(kind)))
        self.spaces = {space: prefix for prefix, space in self.binding["prefixes"].items()}
        self.values = collections.Counter()     # (term, text) and how often
        self.groups = collections.Counter()     # a repeating group and how often
        self.unnamed = []                       # elements the binding has no node for
        assert self.binding["namespace"] == self.root.tag[1:].split("}")[0]
        self.children(self.root, self.binding["children"], kind)

    def name(self, element) -> str:
        space, _, local = element.tag[1:].partition("}")
        return "%s:%s" % (self.spaces[space], local) if space in self.spaces else element.tag

    def holds(self, element, when) -> bool:
        if "path" not in when:
            # The one test said in words and by name: which of two tax totals.
            cbc, cac = (self.binding["prefixes"][prefix] for prefix in ("cbc", "cac"))
            amount = element.find("{%s}TaxAmount" % cbc)
            currency = amount.get("currencyID", "") if amount is not None else ""
            accounting = (self.root.findtext("{%s}TaxCurrencyCode" % cbc) or "").strip()
            document = (self.root.findtext("{%s}DocumentCurrencyCode" % cbc) or "").strip()
            is_accounting = bool(accounting and currency == accounting and currency != document
                                 and element.find("{%s}TaxSubtotal" % cac) is None)
            return {"tax-total-in-accounting-currency": is_accounting,
                    "tax-total-in-document-currency": not is_accounting}[when["name"]]
        found = element
        for step in when["path"].split("/"):
            prefix, _, local = step.partition(":")
            found = found.find("{%s}%s" % (self.binding["prefixes"][prefix], local))
            if found is None:
                return False
        said = found.get(when["attribute"], "") if "attribute" in when else (
            found.text or "").strip()
        among = when["in"]
        if when.get("ignoring_case"):
            said, among = said.upper(), [one.upper() for one in among]
        return said in among

    def children(self, parent, entries, path):
        for element in parent:
            name = self.name(element)
            node = next((one for one in entries if one["element"] == name
                         and ("when" not in one or self.holds(element, one["when"]))), None)
            if node is None:
                self.unnamed.append(path + "/" + name)
                continue
            if node.get("repeats"):
                self.groups[node["group"]] += 1
            text = element.text or ""
            if "subject" in node:
                split = NOTE.fullmatch(text) if text.startswith("#") else None
                if split:
                    self.values[(node["subject"], split.group(1))] += 1
                    text = split.group(2)
            for key in ("term", "ubl"):
                if key in node and "children" not in node and node[key] != "TaxScheme/ID":
                    self.values[(node[key], text.strip())] += 1
            for attribute, term in node.get("attributes", {}).items():
                if term and attribute in element.attrib:
                    self.values[(term, element.get(attribute).strip())] += 1
            self.children(element, node.get("children", []), path + "/" + name)


def held(document):
    """What the package's own reader holds: the same two counts."""
    values, groups = collections.Counter(), collections.Counter()

    def walk(group):
        for term, found in group.terms.items():
            for value in found:
                values[(term, value.text.strip())] += 1
        # A term that is an attribute of another's element is held there.
        for term in ATTRIBUTE_TERMS:
            for value in group.values(term):
                values[(term, value.text.strip())] += 1
        for name, made in group.groups.items():
            groups[name] += len(made)
            for one in made:
                walk(one)

    walk(document)
    return values, groups


class ReadByTheBindingAlone(unittest.TestCase):
    def agrees(self, name, data):
        alone = ByTheBindingAlone(data)
        document, findings = parse(data)
        values, groups = held(document)
        self.assertEqual(alone.values, values, name)
        self.assertEqual(alone.groups, groups, name)
        unheld = [found for found in findings if found.code == "UNHELD"
                  and "attribute" not in found.text]
        self.assertEqual(len(alone.unnamed), len(unheld), (name, alone.unnamed))
        return alone

    def test_this_projects_samples(self):
        for name in OWN:
            alone = self.agrees(name, sample(name))
            self.assertEqual(alone.unnamed, [], name)
            self.assertGreater(len(alone.values), 40, name)

    def test_what_it_names_in_the_sample_invoice(self):
        alone = ByTheBindingAlone(sample("peppol-invoice.xml"))
        for pair in (("BT-1", "GLX-4711"), ("BT-106", "1000.00"), ("BT-13", "4500000017"),
                     ("BT-21", "AAI"), ("BT-22", "Goods remain ours until paid for."),
                     ("BT-31", "DE123456789"), ("BT-32", "22/333/44444"),
                     ("BT-90", "DE98ZZZ09999999999"), ("BT-29", "4012345000009"),
                     ("BT-130", "C62"), ("BT-158-1", "STI"), ("BT-99", "10.00"),
                     ("BT-92", "10.00"), ("BT-136", "50.00")):
            self.assertEqual(alone.values[pair], 1, pair)
        self.assertEqual((alone.groups["BG-25"], alone.groups["BG-20"], alone.groups["BG-21"],
                          alone.groups["BG-27"], alone.groups["BG-1"]), (2, 1, 1, 1, 2))

    def test_the_documents_others_published(self):
        read_some = unnamed = 0
        for directory in ("en16931", "xrechnung/business-cases/standard"):
            for name, data in external(directory):
                try:
                    parse(data)
                except Refused:             # the one CII document among them
                    continue
                unnamed += len(self.agrees(name, data).unnamed)
                read_some += 1
        # Among them are documents with elements the standard has no term
        # for, and the binding has no node for those either.
        self.assertGreaterEqual(read_some, 50)
        self.assertGreater(unnamed, 0)


class TheTree(unittest.TestCase):
    def test_every_test_that_picks_an_entry_can_be_said(self):
        def walk(entries):
            for entry in entries:
                when = getattr(entry, "when", None)
                if when is not None:
                    self.assertIsInstance(when, When)
                    yield when
                yield from walk(getattr(entry, "children", ()))
        for kind in BINDINGS:
            found = list(walk(BINDINGS[kind]))
            self.assertGreater(len(found), 8)
            for when in found:
                said = when.described()
                self.assertTrue(said["text"])
                self.assertEqual("path" in said, "in" in said)
                self.assertNotEqual("path" in said, "name" in said)

    def test_a_test_said_as_data_is_the_test(self):
        from mockeinvoice.ubl import document_type, indicator, sepa, tree
        charge = tree(b"<a xmlns:cbc='urn:oasis:names:specification:ubl:schema:xsd:"
                      b"CommonBasicComponents-2'><cbc:ChargeIndicator> 1 </cbc:ChargeIndicator>"
                      b"<cbc:DocumentTypeCode>130</cbc:DocumentTypeCode>"
                      b"<cbc:ID schemeID='sepa'>x</cbc:ID></a>")
        self.assertEqual(indicator(("true", "1")).described(), {
            "text": "cbc:ChargeIndicator is true or 1", "path": "cbc:ChargeIndicator",
            "in": ["true", "1"]})
        self.assertEqual(document_type("130").described(), {
            "text": "cbc:DocumentTypeCode is 130", "path": "cbc:DocumentTypeCode",
            "in": ["130"]})
        self.assertEqual(sepa.described(), {
            "text": "cbc:ID has the schemeID SEPA, in capitals or not", "path": "cbc:ID",
            "attribute": "schemeID", "in": ["SEPA"], "ignoring_case": True})
        self.assertEqual([test(charge, None) for test in (
            indicator(("true", "1")), indicator(("false", "0")), document_type("130"),
            document_type("50"), sepa)], [True, False, True, False, True])

    def test_the_head_of_it(self):
        for kind, space in (("Invoice", "Invoice-2"), ("CreditNote", "CreditNote-2")):
            said = described(kind)
            self.assertEqual((said["kind"], said["element"], sorted(said["prefixes"])),
                             (kind, kind, ["cac", "cbc"]))
            self.assertTrue(said["namespace"].endswith(space))
            self.assertEqual(said["children"][0], {"element": "cbc:CustomizationID",
                                                   "term": "BT-24"})
        with self.assertRaises(ValueError):
            described("Order")

    def test_every_term_and_group_has_a_place_in_both(self):
        for kind in BINDINGS:
            found = nodes(described(kind))
            terms = {node["term"] for _path, node in found if "term" in node}
            terms |= {node["subject"] for _path, node in found if "subject" in node}
            terms |= {term for _path, node in found
                      for term in node.get("attributes", {}).values() if term}
            self.assertEqual(terms, set(TERMS) | set(ATTRIBUTE_TERMS), kind)
            groups = {node["group"] for _path, node in found if "group" in node}
            # Process control is a group with no element of its own.
            self.assertEqual(groups, set(GROUPS) - {"BG-2"}, kind)

    def test_a_group_repeats_as_the_model_keeps_it(self):
        for _path, node in nodes(described("Invoice")):
            if "group" in node:
                self.assertEqual(node["repeats"], GROUPS[node["group"]][1], node["group"])

    def test_where_some_things_are(self):
        invoice = {path: node for path, node in nodes(described("Invoice"))}
        credit = {path: node for path, node in nodes(described("CreditNote"))}
        self.assertEqual(invoice["/Invoice/cac:LegalMonetaryTotal/cbc:LineExtensionAmount"],
                         {"element": "cbc:LineExtensionAmount", "term": "BT-106",
                          "attributes": {"currencyID": None}})
        self.assertEqual(invoice["/Invoice/cac:InvoiceLine/cbc:InvoicedQuantity"],
                         {"element": "cbc:InvoicedQuantity", "term": "BT-129",
                          "attributes": {"unitCode": "BT-130"}})
        self.assertEqual(credit["/CreditNote/cac:CreditNoteLine/cbc:CreditedQuantity"]["term"],
                         "BT-129")
        self.assertEqual(invoice["/Invoice/cbc:DueDate"], {"element": "cbc:DueDate",
                                                           "term": "BT-9"})
        self.assertEqual(credit["/CreditNote/cac:PaymentMeans/cbc:PaymentDueDate"],
                         {"element": "cbc:PaymentDueDate", "term": "BT-9", "on_document": True})
        self.assertNotIn("/CreditNote/cbc:DueDate", credit)
        self.assertEqual(invoice["/Invoice/cbc:Note"], {
            "element": "cbc:Note", "group": "BG-1", "repeats": True, "term": "BT-22",
            "subject": "BT-21"})
        self.assertEqual(invoice["/Invoice/cac:PaymentMeans/cac:CardAccount/cbc:NetworkID"],
                         {"element": "cbc:NetworkID", "ubl": "ubl:NetworkID"})
        line = invoice["/Invoice/cac:InvoiceLine"]
        self.assertEqual((line["group"], line["repeats"]), ("BG-25", True))
        seller = invoice["/Invoice/cac:AccountingSupplierParty"]
        self.assertEqual((seller["group"], seller["repeats"]), ("BG-4", False))

    def test_entries_with_one_element_are_in_the_readers_order_with_their_tests(self):
        def named(tree, element, under=None):
            return [node for node in (under or tree)["children"] if node["element"] == element]
        invoice, credit = described("Invoice"), described("CreditNote")
        allowance, charge = named(invoice, "cac:AllowanceCharge")
        self.assertEqual((allowance["group"], allowance["when"]["in"], charge["group"],
                          charge["when"]["in"]),
                         ("BG-20", ["false", "0"], "BG-21", ["true", "1"]))
        self.assertEqual(allowance["children"][0], {
            "element": "cbc:ChargeIndicator", "fixed": "false", "accepts": ["false", "0"]})
        self.assertEqual([(node.get("ubl"), node.get("group"), node.get("when", {}).get("in"))
                          for node in named(invoice, "cac:AdditionalDocumentReference")],
                         [("ubl:InvoicedObjectReference", None, ["130"]), (None, "BG-24", None)])
        self.assertEqual([(node.get("ubl"), node.get("group"), node.get("when", {}).get("in"))
                          for node in named(credit, "cac:AdditionalDocumentReference")],
                         [("ubl:InvoicedObjectReference", None, ["130"]),
                          ("ubl:ProjectReference", None, ["50"]), (None, "BG-24", None)])
        first, second = named(invoice, "cac:TaxTotal")
        self.assertEqual((first["when"]["name"], second["when"]["name"], set(first["when"]),
                          second["children"]), (
                              "tax-total-in-document-currency",
                              "tax-total-in-accounting-currency", {"text", "name"}, [
                              {"element": "cbc:TaxAmount", "term": "BT-111",
                               "attributes": {"currencyID": None}}]))
        (party,) = named(invoice, "cac:Party", named(invoice, "cac:AccountingSupplierParty")[0])
        creditor, identifier = named(invoice, "cac:PartyIdentification", party)
        self.assertEqual((creditor["once_per"], creditor["when"]["attribute"],
                          identifier["once_per"], "when" in identifier),
                         ("BT-90", "schemeID", "BT-29", False))

    def test_a_tax_registration_is_two_entries_told_apart_by_the_scheme(self):
        def registrations(party, inner=True):
            (found,) = [node for node in described("Invoice")["children"]
                        if node["element"] == party]
            if inner:
                (found,) = found["children"]
            return [node for node in found["children"]
                    if node["element"] == "cac:PartyTaxScheme"]
        vat, other = registrations("cac:AccountingSupplierParty")
        self.assertEqual(vat, {
            "element": "cac:PartyTaxScheme",
            "when": {"text": "cac:TaxScheme/cbc:ID is VAT, in capitals or not",
                     "path": "cac:TaxScheme/cbc:ID", "in": ["VAT"], "ignoring_case": True},
            "children": [{"element": "cbc:CompanyID", "term": "BT-31"},
                         {"element": "cac:TaxScheme", "children": [
                             {"element": "cbc:ID", "fixed": "VAT", "accepts": ["VAT"]}]}]})
        self.assertEqual(other, {
            "element": "cac:PartyTaxScheme",
            "children": [{"element": "cbc:CompanyID", "term": "BT-32"},
                         {"element": "cac:TaxScheme", "children": [
                             {"element": "cbc:ID", "ubl": "TaxScheme/ID"}]}]})
        # A buyer and a tax representative have no term for another
        # registration, and one is held as the VAT identifier.
        for party, term, inner in (("cac:AccountingCustomerParty", "BT-48", True),
                                   ("cac:TaxRepresentativeParty", "BT-63", False)):
            self.assertEqual([node["children"][0]["term"]
                              for node in registrations(party, inner)], [term, term])

    def test_it_is_made_from_the_table_each_time(self):
        self.assertEqual(described("Invoice"), described("Invoice"))
        self.assertIsNot(described("Invoice"), described("Invoice"))
        line = next(entry for entry in BINDINGS["Invoice"]
                    if isinstance(entry, Many) and entry.group == "BG-25")
        kept, line.children = line.children, line.children[:1]
        try:
            (served,) = [node for node in described("Invoice")["children"]
                         if node.get("group") == "BG-25"]
            self.assertEqual(served["children"], [{"element": "cbc:ID", "term": "BT-126"}])
        finally:
            line.children = kept
        self.assertIsInstance(BINDINGS["Invoice"][-2], Wrap)


if __name__ == "__main__":
    unittest.main()
