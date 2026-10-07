"""Writing UBL: read then written, a document says the same thing."""
import collections
import unittest
import xml.etree.ElementTree as ET
from decimal import Decimal

from mockeinvoice import write
from mockeinvoice import ubl
from mockeinvoice.model import TERMS, Document, Group, Value
from mockeinvoice.ubl import BINDINGS, Fixed, Leaf, Many, Note, TaxRegistration, Wrap, parse

from . import external, sample
from .test_reading import invoice

OWN = ("peppol-invoice.xml", "xrechnung-invoice.xml", "peppol-creditnote.xml")


def leaves(data: bytes):
    """Every element of a document that holds no other: where it is, its text
    and its attributes. Read with `xml.etree`, not with the reader under test."""
    found = collections.Counter()

    def walk(element, path):
        here = path + "/" + element.tag.split("}")[-1]
        if len(element) == 0:
            found[(here, element.text or "", tuple(sorted(element.attrib.items())))] += 1
        for child in element:
            walk(child, here)

    walk(ET.fromstring(data), "")
    return found


def unnumbered(path: str) -> str:
    """A finding's path as `leaves` writes one: no prefixes, no positions."""
    steps = [step.split("[")[0].split(":")[-1] for step in path.split("/")]
    return "/".join(steps)


def every_term(kind: str) -> Document:
    """A document with a value for every place the binding has, each its own."""
    document = Document(kind=kind)
    counter = [0]

    def value(entry: Leaf) -> Value:
        counter[0] += 1
        attributes = {name: "%s%d" % (name[:3].upper(), counter[0]) for name in entry.attributes}
        text = "%d.%02d" % (counter[0], counter[0] % 100) if entry.kind in (
            "amount", "price", "quantity", "percentage") else "%s-%d" % (entry.term, counter[0])
        return Value(text, attributes)

    def fill(entries, group):
        for entry in entries:
            if isinstance(entry, Leaf) and entry.root:
                if not document.terms.get(entry.term):      # once, however many groups
                    document.add(entry.term, value(entry))
            elif isinstance(entry, Leaf) and entry.term == "BT-90":
                # One identifier with two places, known by its scheme, and
                # here in both: the seller's first, then the payee's.
                noted = dict([entry.noting]) if entry.noting else {}
                document.add("BT-90", Value("CRED", dict(noted, schemeID="SEPA")))
            elif isinstance(entry, Leaf):
                group.add(entry.term, value(entry))
            elif isinstance(entry, Wrap):
                fill(entry.children, group)
            elif isinstance(entry, Many):
                for _ in range(2):
                    fill(entry.children, group.new(entry.group))
            elif isinstance(entry, Note):
                for subject in ("AAI", ""):
                    note = group.new("BG-1")
                    if subject:
                        note.add("BT-21", subject)
                    counter[0] += 1
                    note.add("BT-22", "note %d" % counter[0])
            elif isinstance(entry, TaxRegistration):
                counter[0] += 1
                group.add(entry.vat, "VAT%d" % counter[0])
                if entry.other:
                    group.add(entry.other, Value("TAX%d" % counter[0], {"TaxScheme/ID": "FC"}))

    fill(BINDINGS[kind], document)
    # The second VAT total is told from the first by its currency being the
    # accounting currency, so the three have to agree for it to be itself.
    document.terms["BT-5"], document.terms["BT-6"] = [Value("EUR")], [Value("SEK")]
    document.term("BT-110").attributes["currencyID"] = "EUR"
    document.term("BT-111").attributes["currencyID"] = "SEK"
    return document


class ReadThenWritten(unittest.TestCase):
    def test_this_projects_samples_are_the_same_documents(self):
        for name in OWN:
            with self.subTest(name=name):
                document, findings = parse(sample(name))
                again, again_findings = parse(write(document))
                self.assertEqual(again, document)
                self.assertEqual((findings, again_findings), ([], []))

    def test_this_projects_samples_come_back_element_for_element(self):
        for name in OWN:
            with self.subTest(name=name):
                data = sample(name)
                self.assertEqual(leaves(write(parse(data)[0])), leaves(data))

    def test_the_published_examples_are_the_same_documents(self):
        names = []
        for name, data in external("en16931"):
            with self.subTest(name=name):
                document, _findings = parse(data)
                again, again_findings = parse(write(document))
                self.assertEqual(again, document)
                # What is written has nothing left in it to remark on.
                self.assertEqual(again_findings, [])
            names.append(name)
        self.assertEqual(len(names), 17)

    def test_the_published_examples_lose_nothing_that_was_not_said(self):
        """Element for element, by a reader that is not ours: whatever is in
        the example and not in what is written back has a finding at its
        place, and nothing is written that was not in the example unless the
        binding fixes its value."""
        compared = 0
        for name, data in external("en16931"):
            with self.subTest(name=name):
                document, findings = parse(data)
                said = {unnumbered(f.path) for f in findings}
                before, after = leaves(data), leaves(write(document))
                compared += sum(before.values())
                for path, _text, _attributes in (before - after):
                    self.assertTrue(any(path == place or path.startswith(place + "/")
                                        for place in said), "%s was lost unsaid" % path)
                for path, text, _attributes in (after - before):
                    self.assertIn(path, said, "%s=%r was written from nowhere" % (path, text))
        self.assertGreater(compared, 2000)

    def test_a_document_with_every_term_is_written_and_read_back_whole(self):
        for kind in ("Invoice", "CreditNote"):
            with self.subTest(kind=kind):
                document = every_term(kind)
                written = write(document)
                again, findings = parse(written)
                self.assertEqual(findings, [])
                self.assertEqual(again, document)
                # Every business term of the standard is in it somewhere.
                held = set()

                def collect(group: Group):
                    held.update(group.terms)
                    for groups in group.groups.values():
                        for inner in groups:
                            collect(inner)

                collect(again)
                attribute_terms = {"BT-82", "BT-130", "BT-150"}
                self.assertEqual({t for t in held if t.startswith("BT-")} | attribute_terms,
                                 set(TERMS))


class WhatIsWritten(unittest.TestCase):
    def test_it_is_utf8_xml_with_the_documents_namespace_as_the_default(self):
        written = write(parse(sample("peppol-invoice.xml"))[0])
        self.assertTrue(written.startswith(
            b'<?xml version="1.0" encoding="UTF-8"?>\n<Invoice xmlns="urn:oasis:names:'
            b'specification:ubl:schema:xsd:Invoice-2" xmlns:cac='))
        self.assertIn(b"\n  <cbc:ID>GLX-4711</cbc:ID>\n", written)
        credit = write(parse(sample("peppol-creditnote.xml"))[0])
        self.assertIn(b"<CreditNote xmlns=", credit)
        self.assertIn(b"<cac:CreditNoteLine>", credit)
        self.assertIn(b'<cbc:CreditedQuantity unitCode="C62">40</cbc:CreditedQuantity>', credit)

    def test_text_and_attributes_are_escaped(self):
        document = Document()
        document.add("BT-1", "A&B <1> \"q\"")
        document.new("BG-16").add("BT-81", Value("30", {"name": 'a "b" <c> & d'}))
        written = write(document)
        self.assertIn(b"<cbc:ID>A&amp;B &lt;1&gt; \"q\"</cbc:ID>", written)
        again, _findings = parse(written)
        self.assertEqual(again, document)
        self.assertEqual(ET.fromstring(written)[0].text, "A&B <1> \"q\"")

    def test_non_ascii_text_goes_out_as_utf8(self):
        document = Document()
        document.add("BT-27", "Müller & Söhne €")
        written = write(document)
        self.assertIn("Müller &amp; Söhne €".encode("utf-8"), written)
        self.assertEqual(parse(written)[0], document)

    def test_an_amount_goes_out_with_the_digits_it_came_in_with(self):
        document, _findings = parse(invoice(
            '<cac:LegalMonetaryTotal><cbc:PayableAmount currencyID="EUR">1190.50'
            "</cbc:PayableAmount></cac:LegalMonetaryTotal>"))
        self.assertIn(b'<cbc:PayableAmount currencyID="EUR">1190.50</cbc:PayableAmount>',
                      write(document))
        made = Document()
        made.add("BT-115", Value.of(Decimal("7.10"), currencyID="EUR"))
        self.assertIn(b'<cbc:PayableAmount currencyID="EUR">7.10</cbc:PayableAmount>', write(made))

    def test_the_elements_come_out_in_the_schemas_order_whatever_order_they_were_added_in(self):
        document = Document()
        line = document.new("BG-25")
        for term, text in (("BT-146", "1.00"), ("BT-153", "Widget"), ("BT-131", "1.00"),
                           ("BT-129", "1"), ("BT-126", "1")):
            line.add(term, text)
        document.add("BT-115", "1.00")
        document.add("BT-5", "EUR")
        document.add("BT-1", "X")
        order = [element.tag.split("}")[1] for element in ET.fromstring(write(document)).iter()]
        self.assertEqual(order, ["Invoice", "ID", "DocumentCurrencyCode", "LegalMonetaryTotal",
                                 "PayableAmount", "InvoiceLine", "ID", "InvoicedQuantity",
                                 "LineExtensionAmount", "Item", "Name", "Price", "PriceAmount"])

    def test_what_the_binding_fixes_is_written_only_where_there_is_something_to_fix_it_to(self):
        empty = write(Document())
        self.assertEqual(leaves(empty), collections.Counter({("/Invoice", "", ()): 1}))
        document = Document()
        document.new("BG-25").add("BT-151", "S")
        document.new("BG-21").add("BT-99", "1.00")
        written = leaves(write(document))
        self.assertEqual(sorted(path for path, _text, _attributes in written), [
            "/Invoice/AllowanceCharge/Amount", "/Invoice/AllowanceCharge/ChargeIndicator",
            "/Invoice/InvoiceLine/Item/ClassifiedTaxCategory/ID",
            "/Invoice/InvoiceLine/Item/ClassifiedTaxCategory/TaxScheme/ID"])
        self.assertIn(("/Invoice/AllowanceCharge/ChargeIndicator", "true", ()), written)
        self.assertIn(("/Invoice/InvoiceLine/Item/ClassifiedTaxCategory/TaxScheme/ID", "VAT", ()),
                      written)

    def test_a_tax_registration_is_written_under_the_scheme_it_was_read_under(self):
        document, _findings = parse(sample("peppol-invoice.xml"))
        written = leaves(write(document))
        party = "/Invoice/AccountingSupplierParty/Party/PartyTaxScheme/"
        self.assertEqual(sorted((p, t) for p, t, _a in written if p.startswith(party)), [
            (party + "CompanyID", "22/333/44444"), (party + "CompanyID", "DE123456789"),
            (party + "TaxScheme/ID", "FC"), (party + "TaxScheme/ID", "VAT")])
        self.assertNotIn(b"TaxScheme/ID=", write(document))

    def test_the_creditor_identifier_is_written_on_the_party_it_was_read_from(self):
        """It has one term and two places. A document with a payee may still
        have it on the seller: the XRechnung test suite has one that does."""
        seller = "/Invoice/AccountingSupplierParty/Party/PartyIdentification/ID"
        payee = "/Invoice/PayeeParty/PartyIdentification/ID"
        document = Document()
        document.add("BT-90", Value("CRED", {"schemeID": "SEPA"}))
        document.add("BT-59", "Factor")
        self.assertEqual(sorted(p for p, _t, _a in leaves(write(document))),
                         [seller, "/Invoice/PayeeParty/PartyName/Name"])
        self.assertEqual(parse(write(document))[0], document)
        self.assertTrue(document.has("BG-4"))

        document = Document()
        document.add("BT-90", Value("CRED", {"schemeID": "SEPA", "Party/role": "payee"}))
        written = write(document)
        self.assertEqual([p for p, _t, _a in leaves(written)], [payee])
        self.assertNotIn(b"role", written)
        self.assertEqual(parse(written)[0], document)
        self.assertEqual((document.has("BG-4"), document.has("BG-10")), (False, True))

        both = Document()
        both.add("BT-90", Value("OURS", {"schemeID": "SEPA"}))
        both.add("BT-90", Value("THEIRS", {"schemeID": "SEPA", "Party/role": "payee"}))
        self.assertEqual(sorted((p, t) for p, t, _a in leaves(write(both))),
                         [(seller, "OURS"), (payee, "THEIRS")])
        self.assertEqual(parse(write(both))[0], both)

    def test_a_credit_notes_due_date_is_written_though_it_has_no_payment_means(self):
        document = Document(kind="CreditNote")
        document.add("BT-9", "2026-11-01")
        written = write(document)
        self.assertEqual([p for p, _t, _a in leaves(written)],
                         ["/CreditNote/PaymentMeans/PaymentDueDate"])
        # UBL has no other place for it, so what is written has a payment
        # instruction the document did not: the date is kept, and so is that.
        again, findings = parse(written)
        self.assertEqual(findings, [])
        self.assertEqual(again.text("BT-9"), "2026-11-01")
        self.assertEqual(len(again.all("BG-16")), 1)
        self.assertTrue(again.all("BG-16")[0].empty())
        self.assertEqual(parse(write(again))[0], again)

    def test_a_credit_notes_due_date_is_written_once_however_many_payment_means(self):
        document = Document(kind="CreditNote")
        document.add("BT-9", "2026-11-01")
        document.new("BG-16").add("BT-81", "30")
        document.new("BG-16").add("BT-81", "58")
        written = write(document)
        self.assertEqual(written.count(b"<cbc:PaymentDueDate>"), 1)
        self.assertEqual(parse(written)[0], document)

    def test_something_that_is_neither_document_is_not_written(self):
        with self.assertRaises(ValueError):
            write(Document(kind="Order"))

    def test_nothing_in_the_package_says_float_but_the_one_rule_that_is_published_with_one(self):
        import inspect
        import mockeinvoice
        from mockeinvoice import model, rules, specification
        from mockeinvoice.rules import (calculation, en16931, en16931_codes, en16931_ubl,
                                        en16931_vat, peppol, tree)
        # `double_sum` is the published tests' `xs:decimal(cbc:X + 1)`, which is
        # a double's sum, and says so. No amount is held as a float anywhere.
        allowed = inspect.getsource(calculation.double_sum)
        self.assertEqual(allowed.count("float("), 2)
        for module in (mockeinvoice, model, specification, ubl, rules, calculation, en16931,
                       en16931_codes, en16931_ubl, en16931_vat, peppol, tree):
            source = inspect.getsource(module).replace(allowed, "")
            code = "\n".join(line.split("#")[0] for line in source.splitlines())
            self.assertNotIn("float(", code, module.__name__)


class TheBindingItself(unittest.TestCase):
    def terms(self, kind):
        found = collections.Counter()

        def walk(entries):
            for entry in entries:
                if isinstance(entry, Leaf):
                    found[entry.term] += 1
                elif isinstance(entry, TaxRegistration):
                    found[entry.vat] += 1
                    if entry.other:
                        found[entry.other] += 1
                elif isinstance(entry, Note):
                    found["BT-21"] += 1
                    found["BT-22"] += 1
                elif not isinstance(entry, Fixed):
                    walk(entry.children)

        walk(BINDINGS[kind])
        return found

    def test_every_term_has_one_place_in_each_document_but_the_one_with_two(self):
        for kind in ("Invoice", "CreditNote"):
            with self.subTest(kind=kind):
                found = self.terms(kind)
                business = {t: n for t, n in found.items() if t.startswith("BT-")}
                # The creditor identifier is on the payee or the seller.
                self.assertEqual({t: n for t, n in business.items() if n != 1}, {"BT-90": 2})
                self.assertEqual(set(business) | {"BT-82", "BT-130", "BT-150"}, set(TERMS))
                self.assertEqual({t for t in found if not t.startswith("BT-")},
                                 {"ubl:NetworkID"})


if __name__ == "__main__":
    unittest.main()
