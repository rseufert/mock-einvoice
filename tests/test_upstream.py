"""Held to what others published: the rules to their publishers' unit tests,
and the reader, the writer and the rules to documents this project did not
write. `tests/samples/external/*/README.md` says where each came from."""
import os
import unittest

from mockeinvoice import Refused, read, validate, write
from mockeinvoice.rules import REGISTRY, published, run
from mockeinvoice.ubl import parse, parse_tree

from . import EXTERNAL, upstream
from .test_writing import leaves, unnumbered

XRECHNUNG = os.path.join(EXTERNAL, "xrechnung")
PEPPOL = os.path.join(upstream.FETCHED, "peppol", "rules")
HAVE_PEPPOL = os.path.isdir(PEPPOL)
WITHOUT_PEPPOL = "Peppol's files are not in this repository: python tools/fetch_peppol.py"


def documents(folder: str):
    for name in sorted(os.listdir(folder)):
        if name.endswith(".xml"):
            with open(os.path.join(folder, name), "rb") as handle:
                yield name, handle.read()


class TheRulesAndTheirPublishersUnitTests(unittest.TestCase):
    """The counts are written out, so that a rule being built moves a number
    here and nothing moves one by accident."""

    def test_the_en16931_unit_tests(self):
        counts, disagreements, not_built = upstream.tally("en16931")
        self.assertEqual(disagreements, [])
        self.assertEqual(dict(counts), {
            "files": 278, "cases": 1137, "expectations": 1139,
            "agree": 1126,          # every case for a rule that is built
            "unpublished": 12,      # BR-CO-25, which the pinned rule file does not have
            "not held": 1})         # see `upstream.NOT_HELD`
        self.assertEqual(not_built, {})        # every rule of the core is built
        self.assertTrue(set(not_built).isdisjoint(REGISTRY["en16931"]))
        self.assertLessEqual(set(not_built), set(published.EN16931))

    def test_every_built_rule_that_has_published_cases_was_compared(self):
        named = set()
        for _label, path in upstream.files("en16931"):
            for _number, expectations, _data in upstream.cases(path):
                named.update(identifier for _kind, identifier in expectations)
        compared = named & set(REGISTRY["en16931"])
        # The publisher has cases for 19 of the 23 calculation rules built,
        # for every one of the 58 plain business rules and for 95 of the 98
        # VAT category rules, for 19 of the 23 code list rules, and for 9 of
        # the 756 rules about the UBL document itself.
        self.assertEqual(len(compared), 19 + 58 + 95 + 19 + 9)
        self.assertEqual(sum(1 for i in compared if i.startswith("BR-CO-")), 19)
        # No cases are published for the four that cannot fail, for any of
        # the decimals rules, for the two split payment rules, for the
        # exemption reason of an intra-community supply or for four of the
        # code lists: those rest on this project's own tests.
        without = set(REGISTRY["en16931"]) - named
        self.assertEqual(sum(1 for i in without if i.startswith("UBL-")), 747)
        self.assertEqual(sorted(i for i in without if not i.startswith("UBL-")), sorted(
            ["BR-CO-05", "BR-CO-06", "BR-CO-07", "BR-CO-08", "BR-B-01", "BR-B-02", "BR-IC-10",
             "BR-CL-08", "BR-CL-22", "BR-CL-25", "BR-CL-26"]
            + [i for i in REGISTRY["en16931"] if i.startswith("BR-DEC-")]))

    def test_a_rule_that_stops_working_is_a_disagreement_and_not_a_smaller_count(self):
        """The comparison itself: break a rule each way and it must say so."""
        import dataclasses
        built = REGISTRY["en16931"]
        whole = {"BR-CO-10": built["BR-CO-10"], "BR-CO-18": built["BR-CO-18"]}
        try:
            built["BR-CO-10"] = dataclasses.replace(whole["BR-CO-10"], check=lambda document: [])
            built["BR-CO-18"] = dataclasses.replace(
                whole["BR-CO-18"], check=lambda document: [("BG-23", "always")])
            counts, disagreements, _not_built = upstream.tally("en16931")
        finally:
            built.update(whole)
        silenced = [d for d in disagreements if d[3] == "BR-CO-10"]
        always = [d for d in disagreements if d[3] == "BR-CO-18"]
        # Silenced, it fails every case that expects an error; always firing,
        # every case that expects success.
        self.assertTrue(silenced and all(d[2] == "error" and d[4] == "did not fire"
                                         for d in silenced), silenced)
        self.assertTrue(always and all(d[2] == "success" and d[4] == "fatal"
                                       for d in always), always)
        self.assertEqual(len(disagreements), len(silenced) + len(always))
        self.assertEqual(counts["agree"] + counts["disagree"], 1126)
        self.assertEqual({d[0] for d in silenced}, {"Invoice-unit-UBL/BR-CO-10.xml"})
        self.assertEqual(upstream.tally("en16931")[1], [])       # and whole again, none

    def test_a_case_held_to_be_wrong_is_counted_apart_and_only_that_case(self):
        import dataclasses
        built = REGISTRY["en16931"]
        whole = built["BR-CO-18"]
        try:
            built["BR-CO-18"] = dataclasses.replace(whole, check=lambda document: [("BG-23", "x")])
            _counts, disagreements, _not_built = upstream.tally("en16931")
            first = disagreements[0]
            upstream.KNOWN_WRONG[(first[0], first[1], first[3])] = "for this test only"
            counts, fewer, _not_built = upstream.tally("en16931")
        finally:
            built["BR-CO-18"] = whole
            upstream.KNOWN_WRONG.clear()        # it has nothing of its own in it
        self.assertEqual((counts["known wrong"], len(fewer)), (1, len(disagreements) - 1))

    def test_a_warning_is_not_an_error_to_a_case_that_expects_one(self):
        self.assertEqual(upstream.EXPECTED, {"success": None, "error": "fatal",
                                             "warning": "warning"})
        flag = published.EN16931["BR-CO-10"]
        try:
            published.EN16931["BR-CO-10"] = "warning"
            _counts, disagreements, _not_built = upstream.tally("en16931")
        finally:
            published.EN16931["BR-CO-10"] = flag
        self.assertTrue(disagreements)
        self.assertEqual({d[2:] for d in disagreements}, {("error", "BR-CO-10", "warning")})

    def test_nothing_is_held_to_be_wrong_without_a_reason(self):
        self.assertEqual(upstream.KNOWN_WRONG, {})
        for case, reason in upstream.NOT_HELD.items():
            self.assertGreater(len(reason), 40, case)

    def test_the_one_case_in_a_document_that_is_not_ubls(self):
        """A credit note with an invoice's line in it: the published rule
        fires on the code inside, and here the line is not held."""
        (label, number, identifier), = upstream.NOT_HELD
        folder, _layers = upstream.SETS["en16931"]
        data = next(data for n, _expectations, data in upstream.cases(
            os.path.join(folder, *label.split("/"))) if n == number)
        document, findings = parse(data)
        self.assertEqual(document.kind, "CreditNote")
        self.assertEqual([(f.code, f.path) for f in findings],
                         [("UNHELD", "/CreditNote/cac:InvoiceLine")])
        self.assertEqual(document.all("BG-25"), [])
        # Said of the line a credit note does have, the same code fails.
        as_it_should_be = data.replace(b"InvoiceLine", b"CreditNoteLine")
        fired = [f.code for f in run(parse(as_it_should_be)[0], "en16931")]
        self.assertIn(identifier, fired)

    def test_a_case_is_not_excused_as_not_held_unless_the_reader_said_so(self):
        case = ("Invoice-unit-UBL/BR-CO-10.xml", 2, "BR-CO-10")
        import dataclasses
        built = REGISTRY["en16931"]
        whole = built["BR-CO-10"]
        try:
            built["BR-CO-10"] = dataclasses.replace(whole, check=lambda document: [])
            upstream.NOT_HELD[case] = "for this test only"
            counts, disagreements, _not_built = upstream.tally("en16931")
        finally:
            built["BR-CO-10"] = whole
            del upstream.NOT_HELD[case]
        self.assertEqual(counts["not held"], 1)     # the real one, and not this
        self.assertTrue(disagreements)

    @unittest.skipUnless(HAVE_PEPPOL, WITHOUT_PEPPOL)
    def test_peppols_unit_tests(self):
        counts, disagreements, not_built = upstream.tally("peppol")
        self.assertEqual(disagreements, [])
        self.assertEqual(dict(counts), {
            "files": 90, "cases": 400, "expectations": 396,
            "agree": 396,           # every case, for Peppol's own rules and Germany's
            "not ours": 4})         # documents that are not an invoice or credit note
        self.assertEqual(not_built, {})

    def test_the_list_of_peppols_files_is_the_examples_and_two_sets_of_unit_tests(self):
        import importlib.util
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        spec = importlib.util.spec_from_file_location(
            "fetch_peppol", os.path.join(here, "tools", "fetch_peppol.py"))
        tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tool)
        listed = list(tool.listed())
        # The examples, two sets of unit tests, and the rule file itself,
        # which a test reads Peppol's code lists from.
        self.assertEqual(len(listed), 101)
        folders = sorted({path.rsplit("/", 1)[0] for _blob, _size, path in listed})
        self.assertEqual(folders, ["rules/examples", "rules/sch", "rules/unit-UBL-DE",
                                   "rules/unit-UBL-PEPPOL"])
        for blob, size, path in listed:
            self.assertRegex(blob, "^[0-9a-f]{40}$")
            self.assertGreater(size, 0)
            self.assertTrue(path.endswith(".xml") or path == "rules/sch/PEPPOL-EN16931-UBL.sch")
        # The hash is git's for a blob, so a file can be checked against the list.
        self.assertEqual(tool.blob_hash(b"hello\n"), "ce013625030ba8dba906f756967f9e9ca394464a")
        self.assertIn(tool.COMMIT, published.SOURCES["peppol"][1])


class DocumentsThisProjectDidNotWrite(unittest.TestCase):
    verdicts = {}
    informed = 0

    def taken(self, name, data, specification):
        """Read with nothing to say, written back whole, and no rule failing."""
        document, said, findings = read(data)
        self.assertEqual((said, findings), (specification, []), name)
        written = write(document)
        self.assertEqual(parse(written), (document, []), name)
        before, after = leaves(data), leaves(written)
        self.assertEqual(before - after, type(before)(), name)
        self.assertEqual(after - before, type(before)(), name)
        # Not a failure and not a warning, of any rule that is built. The one
        # thing said is XRechnung's piece of information, which is no fault.
        _document, report = validate(data)
        self.assertEqual([f for f in report.findings if f.level != "information"], [], name)
        self.assertLessEqual({f.code for f in report.findings}, {"BR-DE-TMP-32"}, name)
        type(self).informed += len(report.findings)
        self.assertGreaterEqual(len(report.ran), 979)
        self.verdicts[name] = report.verdict
        return sum(before.values())

    def test_no_rule_of_the_core_has_anything_to_say_of_the_en16931_examples(self):
        """They name no specification this takes, so they are not validated;
        the core's rules are asked of them as they were sent all the same."""
        count = 0
        for name, data in documents(os.path.join(EXTERNAL, "en16931")):
            document, _findings, sent = parse_tree(data)
            self.assertEqual(list(run(document, "en16931", sent)), [], name)
            count += 1
        self.assertEqual(count, 17)

    def test_the_xrechnung_test_suites_valid_documents_are_taken_whole(self):
        elements = count = 0
        type(self).informed = 0
        for folder in ("business-cases/standard", "technical-cases/cius"):
            for name, data in documents(os.path.join(XRECHNUNG, *folder.split("/"))):
                with self.subTest(name=name):
                    elements += self.taken(name, data, "xrechnung")
                count += 1
        self.assertEqual(count, 39)
        self.assertGreater(elements, 4000)
        # Every one of them is valid. Seventeen are told that they do not say
        # when they were delivered, which XRechnung publishes as information.
        for folder in ("business-cases/standard", "technical-cases/cius"):
            for name, _data in documents(os.path.join(XRECHNUNG, *folder.split("/"))):
                self.assertEqual(self.verdicts[name], "valid", name)
        self.assertEqual(type(self).informed, 17)

    def test_its_extension_and_cvd_documents_are_refused_by_name(self):
        for folder, code, count in (("business-cases/extension", "XRECHNUNG-EXTENSION", 5),
                                    ("technical-cases/cvd", "XRECHNUNG-CVD", 1)):
            seen = 0
            for name, data in documents(os.path.join(XRECHNUNG, *folder.split("/"))):
                with self.assertRaises(Refused) as caught:
                    read(data)
                self.assertEqual(caught.exception.code, code, name)
                # As UBL they are read all the same; it is their rules that are not built.
                parse(data)
                seen += 1
            self.assertEqual(seen, count)

    @unittest.skipUnless(HAVE_PEPPOL, WITHOUT_PEPPOL)
    def test_peppols_examples_are_taken_whole(self):
        count = 0
        for name, data in documents(os.path.join(PEPPOL, "examples")):
            with self.subTest(name=name):
                self.taken(name, data, "peppol")
            count += 1
        self.assertEqual(count, 10)
        # Nine are valid: every fatal rule that could apply to them ran and
        # found nothing. The tenth is from a seller in Sweden, whose rules
        # are not built, so it is not judged.
        names = [name for name, _data in documents(os.path.join(PEPPOL, "examples"))]
        waiting = [name for name in names if self.verdicts[name] != "valid"]
        self.assertEqual(waiting, ["vat-category-O.xml"])
        self.assertEqual(self.verdicts["vat-category-O.xml"], "not judged")
        _document, report = validate(dict(documents(os.path.join(PEPPOL, "examples")))[
            "vat-category-O.xml"])
        self.assertTrue(all(i.startswith("SE-R-") for i in report.not_built["peppol"]))


if __name__ == "__main__":
    unittest.main()
