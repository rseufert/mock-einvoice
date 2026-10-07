"""XRechnung 3.0: the rules the German public sector adds to the EN 16931 core.

The 34 rules of a standard XRechnung document (`BR-DE-*`, `BR-TMP-2`,
`BR-TMP-6`). Thirty-one of them are the tests Peppol also has for Germany,
and are written once, in `german.py`. The other three are here.

The rules of XRechnung Extension (`BR-DEX-*`) and of XRechnung CVD
(`BR-DE-CVD-*`, `BR-TMP-CVD-01`) are not built. Each is published to apply
only to a document that names that specification, and such a document is
refused by name before any rule is asked (`specification.py`): they add
elements the model has no place for. `SCOPES` says so, and a standard
XRechnung document does not wait on them.

What the published tests say that one might not expect
------------------------------------------------------
- **Unlike Peppol's, these are asked of every XRechnung document**, whatever
  the seller's and buyer's countries.
- **`BR-DE-TMP-32` is information, not a warning or an error**: a document
  with no delivery date and no invoicing period is told so and stays valid.
  A document with no lines at all passes it, since every one of none has a
  period.
- **`BR-TMP-6` asks that a date looks like `YYYY-MM-DD` and no more**: the
  thirtieth of February passes it. The core has nothing that says a date is
  a date, except where it compares two.
"""
from __future__ import annotations

import functools
import re
from typing import Callable, Dict, Iterator

from .. import specification
from . import Failure, german, rule
from .calculation import normalize_space
from .peppol import named
from .tree import At, elements, texts

xrechnung = functools.partial(rule, "xrechnung", over="tree")

# XRechnung's name for each rule Peppol numbers `DE-R-nnn`.
NAMES = {key: "BR-DE-%s" % key.lstrip("0").replace("-1", "-a").replace("-2", "-b")
         for key in ("001", "002", "003", "004", "005", "006", "007", "008", "009", "010", "011",
                     "014", "015", "016", "017", "018", "019", "020", "022", "023-1", "023-2",
                     "024-1", "024-2", "025-1", "025-2", "026", "027", "028", "030", "031")}
NAMES["T02"] = "BR-TMP-2"

german.build(lambda key, about: xrechnung(NAMES[key], about))

SPECIFICATIONS = (specification.XRECHNUNG, specification.XRECHNUNG_EXTENSION,
                  specification.XRECHNUNG_CVD)
DATES = ("cbc:IssueDate", "cbc:DueDate", "cbc:StartDate", "cbc:EndDate", "cbc:ActualDeliveryDate",
         "cbc:TaxPointDate", "cbc:PaymentDueDate")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


@xrechnung("BR-DE-21", "the specification identifier (BT-24) is XRechnung 3.0's, or its "
                       "Extension's or its CVD's, exactly")
def br_de_21(root: At) -> Iterator[Failure]:
    stated = texts(elements(root, "cbc:CustomizationID"))
    if not any(text in SPECIFICATIONS for text in stated):
        yield "%s/cbc:CustomizationID" % root.path, "it is %r" % (stated[0] if stated else "")


@xrechnung("BR-DE-TMP-32", "the document says when it was delivered: a delivery date "
                           "(BT-72), an invoicing period (BG-14), or a period on every line "
                           "(BG-26)")
def br_de_tmp_32(root: At) -> Iterator[Failure]:
    # Any line, invoice's or credit note's, whichever the document is.
    every_line = elements(root, "cac:InvoiceLine") + elements(root, "cac:CreditNoteLine")
    if (elements(root, "cac:Delivery/cbc:ActualDeliveryDate") or elements(root, "cac:InvoicePeriod")
            or all(elements(line, "cac:InvoicePeriod") for line in every_line)):
        return
    yield root.path, "it does not"


@xrechnung("BR-TMP-6", "a date is written `YYYY-MM-DD`")
def br_tmp_6(root: At) -> Iterator[Failure]:
    for at in named(root, *DATES):
        if not DATE.fullmatch(normalize_space(at.text)):
            yield at.path, "it is %r" % at.text


def names(text: str) -> Callable[[At], bool]:
    """Whether a document's specification identifier is exactly this one."""
    return lambda root: text in texts(elements(root, "cbc:CustomizationID"))


# The rule sets that are for another specification's documents only. Every
# one of their published rules asks first that the document names it.
SCOPES: Dict[str, Callable[[At], bool]] = {
    "BR-DEX-": names(specification.XRECHNUNG_EXTENSION),
    "BR-DE-CVD-": names(specification.XRECHNUNG_CVD),
    "BR-TMP-CVD-": names(specification.XRECHNUNG_CVD),
}
