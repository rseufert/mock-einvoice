"""Write `mockeinvoice/rules/ublsyntax.py` from the published EN 16931 Schematron.

    python tools/ubl_syntax.py EN16931.sch

The file is not in this repository. It is, at the version the README pins,
ConnectingEurope/eInvoicing-EN16931, tag validation-1.3.16,
ubl/schematron/preprocessed/EN16931-UBL-validation-preprocessed.sch.

Most of the rules about the UBL document itself (`UBL-CR-*`, `UBL-DT-*`,
`UBL-SR-*`) are one of two tests with a different path in each: this element
or attribute is not there, or it is there at most once. What is taken is the
path of each such rule, and for the second kind the element it is asked of.
The few rules that are neither are written by hand in `en16931_ubl.py`, and
this tool stops if their number changes, so a new one is not missed.

The paths are the publisher's, under the EUPL 1.2, and the file written says so.
"""
import re
import sys
import xml.etree.ElementTree as ET

SCHEMATRON = "{http://purl.oclc.org/dsdl/schematron}"
STEP = r"(?:\((?:\w+:\w+\|)+\w+:\w+\)|\w+:\w+|@\w+)"
ABSENT = re.compile(r"not\(((?://)?%s(?:/%s)*)\)" % (STEP, STEP))
AT_MOST_ONE = re.compile(r"\(?count\((\w+:\w+(?:/\w+:\w+)*)\) ?<= ?1\)?")
BY_HAND = 26

HEAD = '''"""The paths of the EN 16931 rules about the UBL document itself. Generated.

By `tools/ubl_syntax.py`, from the Schematron file at the version in
`published.SOURCES["en16931"]`. Do not edit by hand.

`ABSENT` has, for each rule that says an element or attribute is not to be
there, its path from the document's root (`//` is anywhere). `AT_MOST_ONE`
has, for each rule that says an element is there no more than once, the
element the rule is asked of and the path from it.

Licence
-------
These paths are not this project's. They are from the EN 16931 validation
artefacts, copyright their authors, and are under the European Union Public
Licence 1.2, whose text is beside this file in `LICENSE-EUPL-1.2.txt`. The
rest of this package is under the licence in its own LICENSE file.
"""

'''


def squeezed(text):
    return re.sub(r"\s+", " ", text).strip()


def rules(path):
    absent, at_most_one, by_hand = {}, {}, []
    for rule in ET.parse(path).getroot().iter(SCHEMATRON + "rule"):
        context = squeezed(rule.get("context"))
        for element in rule.iter(SCHEMATRON + "assert"):
            identifier, test = element.get("id", ""), squeezed(element.get("test"))
            if not identifier.startswith("UBL-"):
                continue
            if identifier in absent or identifier in at_most_one or identifier in by_hand:
                sys.exit("%s is there twice" % identifier)
            found = ABSENT.fullmatch(test)
            if found and context == "/ubl:Invoice | /cn:CreditNote":
                absent[identifier] = found.group(1)
                continue
            found = AT_MOST_ONE.fullmatch(test)
            if found:
                at_most_one[identifier] = (context, found.group(1))
                continue
            by_hand.append(identifier)
    if len(by_hand) != BY_HAND:
        sys.exit("%d rules are neither kind, where %d are written by hand: %s"
                 % (len(by_hand), BY_HAND, " ".join(sorted(by_hand))))
    return absent, at_most_one


def main(arguments):
    if len(arguments) != 1:
        sys.exit(__doc__)
    absent, at_most_one = rules(arguments[0])
    out = [HEAD, "ABSENT = {\n"]
    for identifier, path in absent.items():
        out.append("    %r: %r,\n" % (identifier, path))
    out.append("}\n\nAT_MOST_ONE = {\n")
    for identifier, (context, path) in at_most_one.items():
        out.append("    %r: (%r,\n                  %r),\n" % (identifier, context, path))
    out.append("}\n")
    with open("mockeinvoice/rules/ublsyntax.py", "w", encoding="utf-8", newline="\n") as handle:
        handle.write("".join(out))


if __name__ == "__main__":
    main(sys.argv[1:])
