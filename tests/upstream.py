"""The rules held to their publishers' own unit tests.

    python -m tests.upstream

prints how every published case came out. `tests/test_upstream.py` holds the
same counts as a test.

The format
----------
EN 16931 and Peppol publish their unit tests in one format: a `testSet` of
`test`s, each a small document with an `assert` saying what a rule should make
of it. `success` is a rule that must not fire on the document, `error` one
that must fire as fatal, `warning` one that must fire as a warning. The
documents are fragments, with only what the rule looks at, so every other
rule fails on them and only the rules a case names are compared.

What a case comes to
--------------------
`agree`        the rule is built and did what the case says
`disagree`     the rule is built and did not: a failure of this project until
               it is shown, from the published rule, that the case is wrong
`not built`    the rule is published and not built yet; nothing was compared
`unpublished`  the case names a rule that is not in the rule file at the
               pinned version, so there is nothing to build
`not ours`     the case's document is not an invoice or a credit note

A case for a rule that is not built is never counted as agreeing.
"""
import collections
import os
import xml.etree.ElementTree as ET

from mockeinvoice import Refused, rules
from mockeinvoice.rules import REGISTRY, published
from mockeinvoice.ubl import parse

from . import EXTERNAL, SAMPLES

VEFA = "{http://difi.no/xsd/vefa/validator/1.0}"
EXPECTED = {"success": None, "error": "fatal", "warning": "warning"}
FETCHED = os.path.join(SAMPLES, "fetched")

# The sets of unit tests: where they are, and the layers their rules are in.
SETS = {
    "en16931": (os.path.join(EXTERNAL, "en16931", "unit"), ("en16931",)),
    "peppol": (os.path.join(FETCHED, "peppol", "rules"), ("en16931", "peppol")),
}
# Peppol's are fetched, not carried: see tools/fetch_peppol.py.
PEPPOL_DIRECTORIES = ("unit-UBL-PEPPOL", "unit-UBL-DE")

# Cases this project holds to be wrong, by (file, number of the test in it,
# rule): the reason, with the published rule's own test to show it. None yet.
KNOWN_WRONG = {}


def files(name: str):
    folder, _layers = SETS[name]
    for directory in sorted(os.listdir(folder)) if os.path.isdir(folder) else ():
        inside = os.path.join(folder, directory)
        if not os.path.isdir(inside) or (name == "peppol"
                                         and directory not in PEPPOL_DIRECTORIES):
            continue
        for entry in sorted(os.listdir(inside)):
            if entry.endswith(".xml"):
                yield "%s/%s" % (directory, entry), os.path.join(inside, entry)


def cases(path: str):
    """Each test in a file: its number, what it expects of which rules, and
    its document as bytes."""
    root = ET.parse(path).getroot()
    if root.tag != VEFA + "testSet":
        raise ValueError("%s is a %s, not a testSet" % (path, root.tag))
    for number, test in enumerate(root.findall(VEFA + "test"), start=1):
        asserted = test.find(VEFA + "assert")
        expectations = [(element.tag[len(VEFA):], (element.text or "").strip())
                        for element in (asserted if asserted is not None else ())
                        if element.tag[len(VEFA):] in EXPECTED]
        documents = [child for child in test if child.tag != VEFA + "assert"]
        if len(documents) != 1:
            raise ValueError("%s test %d has %d documents" % (path, number, len(documents)))
        yield number, expectations, ET.tostring(documents[0])


def tally(name: str):
    """How a set of unit tests came out: counts, and each disagreement."""
    _folder, layers = SETS[name]
    counts = collections.Counter()
    disagreements, not_built = [], collections.Counter()
    for label, path in files(name):
        counts["files"] += 1
        for number, expectations, data in cases(path):
            counts["cases"] += 1
            try:
                document, _findings = parse(data)
            except Refused:
                counts["not ours"] += 1
                continue
            fired = {finding.code: finding.level
                     for layer in layers for finding in rules.run(document, layer)}
            for kind, identifier in expectations:
                counts["expectations"] += 1
                layer = next((l for l in layers if identifier in published.LAYERS[l]), None)
                if layer is None:
                    counts["unpublished"] += 1
                elif identifier not in REGISTRY[layer]:
                    counts["not built"] += 1
                    not_built[identifier] += 1
                elif fired.get(identifier) == EXPECTED[kind]:
                    counts["agree"] += 1
                elif (label, number, identifier) in KNOWN_WRONG:
                    counts["known wrong"] += 1
                else:
                    counts["disagree"] += 1
                    disagreements.append((label, number, kind, identifier,
                                          fired.get(identifier, "did not fire")))
    return counts, disagreements, not_built


def main() -> None:
    for name in SETS:
        counts, disagreements, not_built = tally(name)
        if not counts["files"]:
            print("%-8s not here%s" % (name, " (python tools/fetch_peppol.py fetches it)"
                                       if name == "peppol" else ""))
            continue
        print("%-8s %d files, %d cases, %d expectations: %d agree, %d disagree, %d for %d "
              "rules not built, %d for rules not published, %d documents not ours"
              % (name, counts["files"], counts["cases"], counts["expectations"],
                 counts["agree"], counts["disagree"], counts["not built"], len(not_built),
                 counts["unpublished"], counts["not ours"]))
        for disagreement in disagreements:
            print("  DISAGREE %s test %d: %s %s, and it %s" % disagreement)


if __name__ == "__main__":
    main()
