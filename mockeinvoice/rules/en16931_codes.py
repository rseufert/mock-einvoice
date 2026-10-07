"""The EN 16931 core's code list rules: a term's value is one of a list.

`BR-CL-01` to `BR-CL-26`, with 02, 09 and 12 not published. The lists are in
`codelists.py`, which is generated from the published rules and is under
their licence, not this package's.

How a code is compared
----------------------
All but two of the published tests are the same test: trim the value, and it
has no space in it and is in the list. So ` EUR ` is a currency and `eur` is
not. The two that differ:

- `BR-CL-08`, on a note's subject code, takes whatever is between the first
  two `#` of the note and, if that is three characters long, looks for it in
  the list's text without the spaces either side. So ` AA` is found, in the
  middle of ` AAA`. A subject that is not three characters is not asked.
- `BR-CL-24`, on an attachment's MIME type, compares the value as written
  with each of six.

And `BR-CL-22`, on a VAT exemption reason code, is the one test that takes
the value without regard to case.

Asked whether or not the qualifier is there
-------------------------------------------
An amount's currency (`BR-CL-03`) is asked of every amount, so an amount with
no `currencyID` fails. A scheme, a list or a unit (`BR-CL-07`, `-10`, `-11`,
`-13`, `-21`, `-23`, `-24`, `-25`, `-26`) is asked only where the attribute is
there; that it must be there is another rule's to say.

Where this departs from the published tests, beyond what `en16931.py` lists
---------------------------------------------------------------------------
- **A code in an element that is not held.** The tests are on an element
  wherever it occurs (any `Country`, any `TaxCategory`). They are asked here
  of the places the standard has for one.
- **A type code of 130 with spaces around it.** `BR-CL-07` picks the invoiced
  object's reference by its type code as written. The reader picks it
  trimmed, and says so (`FIXED`) where the two differ.
"""
from __future__ import annotations

import functools
from typing import Callable, Iterator, List, Tuple

from ..model import TERMS, Document, Group, Value
from . import Failure, rule
from .calculation import normalize_space
from .codelists import LISTS

en16931 = functools.partial(rule, "en16931")

Found = Tuple[str, Value]


def listed(text: str, codes: str) -> bool:
    """Trimmed, with no space in it, and in the list with a space either side."""
    trimmed = normalize_space(text)
    return " " not in trimmed and " %s " % trimmed in codes


def everywhere(document: Document, terms: Tuple[str, ...]) -> Iterator[Found]:
    """Every value of these terms, wherever in the document, with where."""
    def walk(group: Group, path: str) -> Iterator[Found]:
        for term in terms:
            for value in group.terms.get(term, ()):
                yield "/".join(part for part in (path, term) if part), value
        for name, groups in group.groups.items():
            for number, inner in enumerate(groups, start=1):
                place = "%s[%d]" % (name, number) if len(groups) > 1 else name
                yield from walk(inner, "/".join(part for part in (path, place) if part))
    return walk(document, "")


def coded(identifier: str, about: str, *terms: str, attribute: str = "",
          lowered: bool = False, always: bool = False) -> None:
    """A rule that a code is in its list.

    The code is the value of each of `terms`, or `attribute` beside it. An
    attribute that is not there is not asked, unless `always`.
    """
    codes, = LISTS[identifier]

    @en16931(identifier, about)
    def check(document: Document) -> Iterator[Failure]:
        for path, value in everywhere(document, terms):
            if attribute and attribute not in value.attributes and not always:
                continue
            text = value.attributes.get(attribute, "") if attribute else value.text
            if not listed(text.upper() if lowered else text, codes):
                yield path, ("%r is not in the list" % text if attribute in value.attributes
                             or not attribute else "it has none")


@en16931("BR-CL-01", "the type code (BT-3) is one the list has for an invoice, or for a "
                     "credit note, whichever the document is")
def br_cl_01(document: Document) -> Iterator[Failure]:
    invoices, credit_notes = LISTS["BR-CL-01"]
    for code in document.values("BT-3"):
        if not listed(code.text, invoices if document.kind == "Invoice" else credit_notes):
            yield "BT-3", "%r is not in the list for %s" % (
                code.text, "an invoice" if document.kind == "Invoice" else "a credit note")


AMOUNTS = tuple(term for term, (_name, _group, kind) in TERMS.items()
                if kind in ("amount", "price"))

coded("BR-CL-03", "every amount's currency is an ISO 4217 code", *AMOUNTS,
      attribute="currencyID", always=True)
coded("BR-CL-04", "the invoice currency (BT-5) is an ISO 4217 code", "BT-5")
coded("BR-CL-05", "the VAT accounting currency (BT-6) is an ISO 4217 code", "BT-6")
coded("BR-CL-06", "the VAT point date code (BT-8) is 3, 35 or 432", "BT-8")
coded("BR-CL-07", "the scheme of an invoiced object identifier (BT-18, BT-128) is a UNTDID "
                  "1153 code", "BT-18", "BT-128", attribute="schemeID")


@en16931("BR-CL-08", "a note's subject code (BT-21) is a UNTDID 4451 code")
def br_cl_08(document: Document) -> Iterator[Failure]:
    codes, = LISTS["BR-CL-08"]
    for number, note in enumerate(document.all("BG-1"), start=1):
        # The note as it was written: the reader took a subject from its
        # front, and the published test looks for one anywhere in it.
        subject, text = note.text("BT-21"), note.text("BT-22")
        written = "#%s#%s" % (subject, text) if note.values("BT-21") else text
        if "#" not in written:
            continue
        subject = written.partition("#")[2].partition("#")[0]
        if len(subject) == 3 and subject not in codes:
            yield "BG-1[%d]" % number if len(document.all("BG-1")) > 1 else "BG-1", (
                "%r is not in the list" % subject)


@en16931("BR-CL-10", "the scheme of a party's identifier (BT-29, BT-46, BT-60) is an ISO 6523 "
                     "ICD code, or SEPA on the seller or the payee (BT-90)")
def br_cl_10(document: Document) -> Iterator[Failure]:
    icd, sepa = LISTS["BR-CL-10"]
    # Every identifier held as BT-90 was on the seller or the payee: on the
    # buyer, one with the scheme SEPA is a buyer identifier like any other.
    for path, value in everywhere(document, ("BT-29", "BT-46", "BT-60", "BT-90")):
        if "schemeID" not in value.attributes:
            continue
        scheme = value.attributes["schemeID"]
        if not (listed(scheme, icd) or (path == "BT-90" and listed(scheme, sepa))):
            yield path, "%r is not in the list" % scheme


coded("BR-CL-11", "the scheme of a legal registration identifier (BT-30, BT-47, BT-61) is an "
                  "ISO 6523 ICD code", "BT-30", "BT-47", "BT-61", attribute="schemeID")
coded("BR-CL-13", "the scheme of an item classification (BT-158) is a UNTDID 7143 code",
      "BT-158", attribute="listID")
coded("BR-CL-14", "a country code (BT-40, BT-55, BT-69, BT-80) is an ISO 3166-1 code",
      "BT-40", "BT-55", "BT-69", "BT-80")
coded("BR-CL-15", "an item's country of origin (BT-159) is an ISO 3166-1 code", "BT-159")
coded("BR-CL-16", "a payment means code (BT-81) is a UNTDID 4461 code", "BT-81")
coded("BR-CL-17", "the VAT category code of an allowance, a charge or a VAT breakdown (BT-95, "
                  "BT-102, BT-118) is one of the ten the standard has",
      "BT-95", "BT-102", "BT-118")
coded("BR-CL-18", "a line's VAT category code (BT-151) is one of the ten the standard has",
      "BT-151")
coded("BR-CL-19", "an allowance's reason code (BT-98, BT-140) is a UNTDID 5189 code",
      "BT-98", "BT-140")
coded("BR-CL-20", "a charge's reason code (BT-105, BT-145) is a UNTDID 7161 code",
      "BT-105", "BT-145")
coded("BR-CL-21", "the scheme of an item's standard identifier (BT-157) is an ISO 6523 ICD "
                  "code", "BT-157", attribute="schemeID")
coded("BR-CL-22", "a VAT exemption reason code (BT-121) is a VATEX code, in either case",
      "BT-121", lowered=True)
coded("BR-CL-23", "a unit of measure (BT-130, BT-150) is a UN/ECE Recommendation 20 or 21 code",
      "BT-129", "BT-149", attribute="unitCode")


@en16931("BR-CL-24", "an attachment's MIME type (BT-125) is one of the six the standard allows")
def br_cl_24(document: Document) -> Iterator[Failure]:
    for path, value in everywhere(document, ("BT-125",)):
        if "mimeCode" in value.attributes and value.attributes["mimeCode"] not in LISTS["BR-CL-24"]:
            yield path, "%r is not one of them" % value.attributes["mimeCode"]


coded("BR-CL-25", "the scheme of an electronic address (BT-34, BT-49) is an EAS code",
      "BT-34", "BT-49", attribute="schemeID")
coded("BR-CL-26", "the scheme of a delivery location identifier (BT-71) is an ISO 6523 ICD code",
      "BT-71", attribute="schemeID")
