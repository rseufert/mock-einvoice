"""Which specification a document says it follows, and whether it is taken.

EN 16931 is a core that nobody sends bare. A document names, in its
specification identifier (BT-24, UBL's `CustomizationID`), the set of rules it
was written to, and that decides which rules it is held to. Two are taken:

    Peppol BIS Billing 3.0
    XRechnung 3.0

Anything else is refused by name. An identifier this package does not know is
not quietly held to the core alone: passing a document on rules that were not
run is the one thing a validator must not do.
"""
from __future__ import annotations

from .model import Document, Refused

EN16931 = "urn:cen.eu:en16931:2017"
PEPPOL = EN16931 + "#compliant#urn:fdc:peppol.eu:2017:poacc:billing:3.0"
XRECHNUNG = EN16931 + "#compliant#urn:xeinkauf.de:kosit:xrechnung_3.0"
XRECHNUNG_EXTENSION = XRECHNUNG + "#conformant#urn:xeinkauf.de:kosit:extension:xrechnung_3.0"
XRECHNUNG_CVD = XRECHNUNG + "#compliant#urn:xeinkauf.de:kosit:xrechnung:cvd_0.9"

NAMES = {"peppol": "Peppol BIS Billing 3.0", "xrechnung": "XRechnung 3.0"}


def identify(document: Document) -> str:
    """`"peppol"` or `"xrechnung"`, or `Refused` saying what it is instead.

    Peppol's own rule compares the identifier with the space around it taken
    off; XRechnung's validator matches it as written. Each is done its way.
    Peppol's rule also lets more follow the identifier, which is how a
    national variant names itself; those are refused here, because their
    rules are not built.
    """
    values = document.values("BT-24")
    if not values:
        raise Refused("NO-SPECIFICATION", "the document has no specification identifier "
                      "(BT-24, cbc:CustomizationID), so there is no saying which rules "
                      "it should be held to")
    if len(values) > 1:
        raise Refused("SPECIFICATION", "the document has %d specification identifiers "
                      "(BT-24, cbc:CustomizationID), and one is what says which rules it "
                      "should be held to" % len(values))
    said = values[0].text
    if said.strip() == PEPPOL:
        return "peppol"
    if said == XRECHNUNG:
        return "xrechnung"
    if said == XRECHNUNG_EXTENSION:
        raise Refused("XRECHNUNG-EXTENSION", "the document is an XRechnung Extension "
                      "invoice (%r), which is not built: XRechnung 3.0 without the "
                      "extension is" % said)
    if said == XRECHNUNG_CVD:
        raise Refused("XRECHNUNG-CVD", "the document is an XRechnung CVD invoice (%r), "
                      "which is not built: XRechnung 3.0 without it is" % said)
    raise Refused("SPECIFICATION", "the specification identifier %r is %s; what is taken "
                  "is %s (%r) and %s (%r)" % (said, what_it_is(said), NAMES["peppol"],
                                              PEPPOL, NAMES["xrechnung"], XRECHNUNG))


def what_it_is(said: str) -> str:
    """The nearest thing to say about an identifier that is not taken."""
    bare = said.strip()
    if bare == XRECHNUNG:
        return "XRechnung 3.0's with space around it, which its validator does not match"
    if bare == EN16931:
        return "EN 16931 with no specification on top of it, which nobody is held to alone"
    if bare.startswith(PEPPOL):
        return "a variant of Peppol BIS Billing 3.0, whose own rules are not built"
    if "xrechnung" in bare.lower():
        return "another version or kind of XRechnung"
    if "peppol" in bare.lower():
        return "another Peppol specification"
    return "not one this package knows"
