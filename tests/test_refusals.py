"""What is refused, and that each refusal names what was sent."""
import unittest

from mockeinvoice import Refused, read
from mockeinvoice.specification import (PEPPOL, XRECHNUNG, XRECHNUNG_CVD,
                                        XRECHNUNG_EXTENSION)
from mockeinvoice.ubl import parse

from . import external, sample
from .test_reading import invoice


def claiming(identifier: str) -> str:
    return invoice("<cbc:CustomizationID>%s</cbc:CustomizationID><cbc:ID>1</cbc:ID>" % identifier)


class NotADocumentThisReads(unittest.TestCase):
    def refused(self, data, reader=read):
        with self.assertRaises(Refused) as caught:
            reader(data)
        return caught.exception

    def test_what_is_not_xml(self):
        for data in (b"", b"ISA*00*", b"<Invoice", "<a></b>", b"{}", b"\xff\xfe\x00"):
            with self.subTest(data=data):
                error = self.refused(data)
                self.assertEqual(error.code, "NOT-XML")
                self.assertIn("not well-formed XML", error.reason)

    def test_a_document_with_a_dtd_is_refused_before_anything_in_it_is_expanded(self):
        bomb = ('<?xml version="1.0"?><!DOCTYPE Invoice [<!ENTITY a "aaaaaaaaaa">'
                '<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">]>' + claiming("&b;"))
        error = self.refused(bomb)
        self.assertEqual(error.code, "DTD")
        self.assertIn("DOCTYPE", error.reason)
        for other in ('<!DOCTYPE Invoice SYSTEM "file:///etc/passwd">' + claiming(PEPPOL),
                      "<!DOCTYPE Invoice>" + claiming(PEPPOL)):
            self.assertEqual(self.refused(other).code, "DTD")

    def test_a_cross_industry_invoice_is_named_as_one(self):
        error = self.refused(
            '<rsm:CrossIndustryInvoice xmlns:rsm="urn:un:unece:uncefact:data:standard:'
            'CrossIndustryInvoice:100"><rsm:ExchangedDocument/></rsm:CrossIndustryInvoice>')
        self.assertEqual(error.code, "CII")
        self.assertIn("Cross Industry Invoice", error.reason)
        self.assertIn("not built", error.reason)

    def test_another_ubl_document_is_named_as_what_it_is(self):
        error = self.refused('<Order xmlns="urn:oasis:names:specification:ubl:schema:xsd:Order-2"/>')
        self.assertEqual(error.code, "NOT-AN-INVOICE")
        self.assertIn("a UBL Order", error.reason)

    def test_anything_else_is_named_by_its_root_and_namespace(self):
        for data, said in (("<Invoice/>", "Invoice in namespace ''"),
                           ('<Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.001.001.09"/>',
                            "Document in namespace 'urn:iso:std:iso:20022:tech:xsd:pain.001.001.09'"),
                           # The right name in the other document's namespace is not it either.
                           ('<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:'
                            'CreditNote-2"/>', "a UBL Invoice")):
            with self.subTest(data=data):
                error = self.refused(data)
                self.assertIn(error.code, ("NOT-UBL", "NOT-AN-INVOICE"))
                self.assertIn(said, error.reason)

    def test_the_syntax_reader_refuses_the_same_without_asking_the_specification(self):
        self.assertEqual(self.refused(b"nonsense", parse).code, "NOT-XML")
        document, _findings = parse(claiming("anything at all"))
        self.assertEqual(document.text("BT-24"), "anything at all")


class WhichSpecification(unittest.TestCase):
    def refused(self, identifier):
        with self.assertRaises(Refused) as caught:
            read(claiming(identifier))
        return caught.exception

    def test_the_two_that_are_taken(self):
        self.assertEqual(read(claiming(PEPPOL))[1], "peppol")
        self.assertEqual(read(claiming(XRECHNUNG))[1], "xrechnung")
        self.assertEqual(read(sample("xrechnung-invoice.xml"))[1], "xrechnung")

    def test_peppols_is_taken_with_space_around_it_as_its_own_rule_takes_it(self):
        self.assertEqual(read(claiming("\n  %s  " % PEPPOL))[1], "peppol")

    def test_xrechnungs_is_not_as_its_validator_does_not_match_it(self):
        error = self.refused(" %s" % XRECHNUNG)
        self.assertEqual(error.code, "SPECIFICATION")
        self.assertIn("with space around it", error.reason)

    def test_the_xrechnung_extension_and_cvd_are_named(self):
        extension, cvd = self.refused(XRECHNUNG_EXTENSION), self.refused(XRECHNUNG_CVD)
        self.assertEqual((extension.code, cvd.code), ("XRECHNUNG-EXTENSION", "XRECHNUNG-CVD"))
        self.assertIn("XRechnung Extension", extension.reason)
        self.assertIn(XRECHNUNG_EXTENSION, extension.reason)
        self.assertIn("XRechnung CVD", cvd.reason)

    def test_no_identifier_is_refused_and_not_held_to_the_core_alone(self):
        with self.assertRaises(Refused) as caught:
            read(invoice("<cbc:ID>1</cbc:ID>"))
        self.assertEqual(caught.exception.code, "NO-SPECIFICATION")
        self.assertIn("cbc:CustomizationID", caught.exception.reason)

    def test_two_identifiers_are_refused(self):
        with self.assertRaises(Refused) as caught:
            read(invoice("<cbc:CustomizationID>%s</cbc:CustomizationID>"
                         "<cbc:CustomizationID>%s</cbc:CustomizationID>" % (PEPPOL, XRECHNUNG)))
        self.assertEqual(caught.exception.code, "SPECIFICATION")
        self.assertIn("2 specification identifiers", caught.exception.reason)

    def test_what_is_not_taken_is_told_what_it_looks_like_and_what_is(self):
        for identifier, looks_like in (
                ("urn:cen.eu:en16931:2017", "EN 16931 with no specification on top"),
                (PEPPOL + "#conformant#urn:example:national", "a variant of Peppol BIS Billing 3.0"),
                ("urn:cen.eu:en16931:2017#compliant#urn:xoev-de:kosit:standard:xrechnung_2.3",
                 "another version or kind of XRechnung"),
                ("urn:cen.eu:en16931:2017#compliant#urn:xeinkauf.de:kosit:xrechnung_3.1",
                 "another version or kind of XRechnung"),
                ("urn:fdc:peppol.eu:2017:poacc:selfbilling:3.0", "another Peppol specification"),
                ("urn:cen.eu:en16931:2017#conformant#urn:factur-x.eu:1p0:extended",
                 "not one this package knows"),
                ("", "not one this package knows")):
            with self.subTest(identifier=identifier):
                error = self.refused(identifier)
                self.assertEqual(error.code, "SPECIFICATION")
                self.assertIn(repr(identifier), error.reason)
                self.assertIn(looks_like, error.reason)
                self.assertIn(PEPPOL, error.reason)
                self.assertIn(XRECHNUNG, error.reason)

    def test_the_published_en16931_examples_claim_no_cius_but_the_two_that_claim_peppol(self):
        """All seventeen are read as UBL by the tests of the reader. Fifteen
        are EN 16931 with nothing on top, which this package is not asked to
        take, and each is told so."""
        taken, refused = [], []
        for name, data in external("en16931"):
            try:
                taken.append((name, read(data)[1]))
            except Refused as error:
                self.assertEqual(error.code, "SPECIFICATION", name)
                self.assertIn("EN 16931 with no specification on top", error.reason, name)
                refused.append(name)
        self.assertEqual(taken, [
            ("FT G2G_TD01 con Allegato, Bonifico e Split Payment.xml", "peppol"),
            ("issue116.xml", "peppol")])
        self.assertEqual(len(refused), 15)

if __name__ == "__main__":
    unittest.main()
