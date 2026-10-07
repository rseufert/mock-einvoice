"""Write `mockeinvoice/rules/codelists.py` from the published EN 16931 Schematron.

    python tools/code_lists.py EN16931.sch

The file is not in this repository. It is, at the version the README pins,
ConnectingEurope/eInvoicing-EN16931, tag validation-1.3.16,
ubl/schematron/preprocessed/EN16931-UBL-validation-preprocessed.sch.

What is taken is, for each code list rule (`BR-CL-*`), the list its test
searches: the string exactly as the test has it, because the test is "is this
code, with a space either side, somewhere in this string" and a list with two
spaces together in it would pass an empty code. No rule's wording is taken.

The lists are the publisher's, under the EUPL 1.2, and the file written says so.
"""
import re
import sys
import xml.etree.ElementTree as ET

SCHEMATRON = "{http://purl.oclc.org/dsdl/schematron}"
WIDTH = 88

HEAD = '''"""The code lists of the EN 16931 code list rules (`BR-CL-*`). Generated.

By `tools/code_lists.py`, from the Schematron file at the version in
`published.SOURCES["en16931"]`. Do not edit by hand.

Each rule has the strings its published test searches, in the test's order
and exactly as the test has them. A code is in a list if it is in the string
with a space either side; `BR-CL-24` compares with each of its strings whole.

Licence
-------
These lists are not this project's. They are from the EN 16931 validation
artefacts, copyright their authors, and are under the European Union Public
Licence 1.2, whose text is beside this file in `LICENSE-EUPL-1.2.txt`. The
rest of this package is under the licence in its own LICENSE file.
"""

LISTS = {
'''


def literals(test):
    """The string literals of an XPath test, in order."""
    return re.findall(r"'([^']*)'", test)


def lists(path):
    """{rule: (list, ...)} for each BR-CL assertion, in the file's order."""
    found = {}
    for element in ET.parse(path).getroot().iter(SCHEMATRON + "assert"):
        identifier = element.get("id", "")
        if not identifier.startswith("BR-CL-"):
            continue
        strings = literals(element.get("test"))
        if identifier == "BR-CL-24":
            kept = strings      # whole values, each compared with `=`
        else:
            # A list is a string with a space at each end and something between.
            kept = [s for s in strings if len(s) > 2 and s[0] == " " and s[-1] == " "]
        if not kept or identifier in found:
            sys.exit("%s: %d lists found, or the rule is there twice" % (identifier, len(kept)))
        found[identifier] = tuple(kept)
    return found


def written(string):
    """A string as Python source, in pieces short enough for a line."""
    pieces = [string[at:at + WIDTH] for at in range(0, len(string), WIDTH)] or [""]
    return "\n".join("        %r" % piece for piece in pieces)


def main(arguments):
    if len(arguments) != 1:
        sys.exit(__doc__)
    out = [HEAD]
    for identifier, strings in sorted(lists(arguments[0]).items()):
        out.append('    "%s": (\n' % identifier)
        for string in strings:
            out.append(written(string) + ",\n")
        out.append("    ),\n")
    out.append("}\n")
    with open("mockeinvoice/rules/codelists.py", "w", encoding="utf-8", newline="\n") as handle:
        handle.write("".join(out))


if __name__ == "__main__":
    main(sys.argv[1:])
