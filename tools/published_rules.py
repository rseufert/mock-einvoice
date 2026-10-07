"""Write `mockeinvoice/rules/published.py` from the published Schematron files.

    python tools/published_rules.py EN16931.sch PEPPOL.sch XRECHNUNG.sch

The three files are not in this repository. They are, at the versions the
README pins:

    EN 16931   ConnectingEurope/eInvoicing-EN16931, tag validation-1.3.16,
               ubl/schematron/preprocessed/EN16931-UBL-validation-preprocessed.sch
    Peppol     OpenPEPPOL/peppol-bis-invoice-3, commit 806866b (3.0.21),
               rules/sch/PEPPOL-EN16931-UBL.sch
    XRechnung  itplr-kosit/xrechnung-schematron, tag v2.6.0,
               src/validation/schematron/ubl/XRechnung-UBL-validation.sch

What is taken from them is each rule's identifier and its flag, and nothing
else: no rule's wording and no rule's test.
"""
import sys
import xml.etree.ElementTree as ET

SCHEMATRON = "{http://purl.oclc.org/dsdl/schematron}"

HEAD = '''"""Every published rule's identifier and flag, by layer. Generated.

By `tools/published_rules.py`, from the Schematron files at the versions in
`SOURCES`. This is the list a document is owed: what `mockeinvoice.rules` has
built is held against it, so that what is not built is a list to read and not
a silence. Do not edit by hand.
"""

SOURCES = {
    "en16931": ("EN 16931 validation artefacts 1.3.16",
                "https://github.com/ConnectingEurope/eInvoicing-EN16931/blob/validation-1.3.16/"
                "ubl/schematron/preprocessed/EN16931-UBL-validation-preprocessed.sch"),
    "peppol": ("Peppol BIS Billing 3.0.21",
               "https://github.com/OpenPEPPOL/peppol-bis-invoice-3/blob/"
               "806866bd2bd91d7e9623b68f08164e8fbe9e67a0/rules/sch/PEPPOL-EN16931-UBL.sch"),
    "xrechnung": ("XRechnung Schematron 2.6.0",
                  "https://github.com/itplr-kosit/xrechnung-schematron/blob/v2.6.0/"
                  "src/validation/schematron/ubl/XRechnung-UBL-validation.sch"),
}

'''


def rules(path):
    """(identifier, flag) for each assertion, in the file's order, once each.

    Read as XML and not as text: a rule that is commented out is not
    published, and a test may have a `>` in it.
    """
    found = {}
    for element in ET.parse(path).getroot().iter():
        if element.tag in (SCHEMATRON + "assert", SCHEMATRON + "report") and element.get("id"):
            found.setdefault(element.get("id"), element.get("flag") or "fatal")
    return found


def main(arguments):
    if len(arguments) != 3:
        sys.exit(__doc__)
    out = [HEAD]
    for layer, path in zip(("en16931", "peppol", "xrechnung"), arguments):
        found = rules(path)
        out.append("%s = dict(line.split() for line in '''\n" % layer.upper())
        out.extend("%s %s\n" % pair for pair in found.items())
        out.append("'''.splitlines() if line)\n\n")
    out.append('LAYERS = {"en16931": EN16931, "peppol": PEPPOL, "xrechnung": XRECHNUNG}\n')
    with open("mockeinvoice/rules/published.py", "w", encoding="utf-8") as handle:
        handle.write("".join(out))


if __name__ == "__main__":
    main(sys.argv[1:])
