"""The EN 16931 core's VAT category rules: ten families, one to a category.

Each VAT category code has a family of rules named for it, and the families
ask the same ten questions of their category: is there one breakdown for it,
are the parties identified as the category needs, what may the rate be on a
line, an allowance and a charge, do the breakdown's amounts come to what the
lines say, and is a reason for exemption owed or forbidden.

They are near copies and not copies. The published tests differ from family
to family in ways that look like accidents and are built as published, and
each difference is named where it is made:

- which seller identifier counts: any tax registration, or only a VAT one;
- whether the buyer must be identified too, and by what;
- whether the taxable amount must be exact or within one unit, by rate or not;
- whether a code is compared trimmed or as written (`BR-AF-01`, `BR-AF-04`,
  and both `BR-B` rules, compare it as written in one place).

Where this departs from the published tests, beyond what `en16931.py` lists
---------------------------------------------------------------------------
- **A tax category on a line's allowance or charge.** The standard has none
  and the reader does not hold one, so the tests that look at every
  `AllowanceCharge` see the document's here and not a line's.
- **A tax category with nothing in it but its scheme.** The rules for
  category O count the categories that are not O, and one with no code is
  not O. The model knows a category was there by its code, its rate or its
  exemption reason; one with none of those is not counted.
- **An invoicing period that holds only what is not held.** `BR-IC-11` is
  satisfied by an invoicing period with anything in it. Here that is a start
  date, an end date or a VAT point date code.
"""
from __future__ import annotations

import functools
from decimal import Decimal
from typing import Callable, Iterator, List, Optional, Tuple

from ..model import Document, Group, Value
from . import Failure, rule
from .calculation import (Incomputable, cents, doubles, equal, normalize_space, nudged,
                          numbered, one, said, shown)
from .en16931 import lines

en16931 = functools.partial(rule, "en16931")

# The families, by the letters in their rules' names, with the category code
# each is about and what the standard calls it.
FAMILIES = {
    "S": ("S", "standard rated"),
    "Z": ("Z", "zero rated"),
    "E": ("E", "exempt from VAT"),
    "AE": ("AE", "reverse charge"),
    "IC": ("K", "intra-community supply"),
    "G": ("G", "export outside the EU"),
    "O": ("O", "not subject to VAT"),
    "AF": ("L", "IGIC, the Canary Islands' tax"),
    "AG": ("M", "IPSI, the tax of Ceuta and Melilla"),
    "B": ("B", "split payment"),
}
ZERO_RATED = ("Z", "E", "AE", "IC", "G")        # the rate must be nought
BY_RATE = ("S", "AF", "AG")                     # a breakdown to each rate


# -- where a category is named -------------------------------------------------

LINE, ALLOWANCE, CHARGE, BREAKDOWN = (("BT-151", "BT-152"), ("BT-95", "BT-96"),
                                      ("BT-102", "BT-103"), ("BT-118", "BT-119"))
Place = Tuple[str, Group, Tuple[str, str]]


def on_lines(document: Document) -> List[Place]:
    return [(path, line, LINE) for path, line in lines(document)]


def on_allowances(document: Document) -> List[Place]:
    return [(path, group, ALLOWANCE) for path, group in numbered(document.all("BG-20"), "BG-20")]


def on_charges(document: Document) -> List[Place]:
    return [(path, group, CHARGE) for path, group in numbered(document.all("BG-21"), "BG-21")]


def in_breakdown(document: Document) -> List[Place]:
    return [(path, group, BREAKDOWN) for path, group in numbered(document.all("BG-23"), "BG-23")]


def everywhere(document: Document) -> List[Place]:
    return (on_allowances(document) + on_charges(document) + in_breakdown(document)
            + on_lines(document))


def trimmed(place: Place, code: str) -> bool:
    """`[normalize-space(cbc:ID) = 'S']`: an error if the category has two."""
    _path, group, (term, _rate) = place
    return said(group, term) == code


def any_trimmed(place: Place, code: str) -> bool:
    """`cbc:ID[normalize-space(.) = 'S']`: any of them, and no error."""
    _path, group, (term, _rate) = place
    return any(normalize_space(value.text) == code for value in group.values(term))


def as_written(place: Place, code: str) -> bool:
    """`cbc:ID = 'S'`: any of them, spaces and all."""
    _path, group, (term, _rate) = place
    return any(value.text == code for value in group.values(term))


def with_code(places: List[Place], code: str, how: Callable = trimmed) -> List[Place]:
    return [place for place in places if how(place, code)]


def category_is_there(place: Place) -> bool:
    """Whether the place has a tax category element at all, as far as the
    model can tell: see the head of this file."""
    _path, group, (code, rate) = place
    terms = (code, rate) + (("BT-120", "BT-121") if code == "BT-118" else ())
    return any(group.values(term) for term in terms) or (code == "BT-151" and group.has("BG-30"))


# -- 01: the category has its breakdown ---------------------------------------

def one_breakdown(family: str, code: str, name: str) -> None:
    @en16931("BR-%s-01" % family, "a document that names the VAT category %s (%s) anywhere "
                                  "has exactly one VAT breakdown for it" % (code, name))
    def check(document: Document) -> Iterator[Failure]:
        if not with_code(everywhere(document), code, any_trimmed):
            return
        # Counted by code, not by breakdown: one breakdown that names the
        # code twice is two.
        count = sum(1 for _path, group, _terms in in_breakdown(document)
                    for value in group.values("BT-118") if normalize_space(value.text) == code)
        if count != 1:
            yield "BG-23", "it has %d" % count


def a_breakdown_if_used(family: str, code: str, name: str) -> None:
    """S, AF and AG may have a breakdown to each rate, so the test is that
    there is one where the category is used and none where it is not."""
    @en16931("BR-%s-01" % family, "a document has a VAT breakdown for the category %s (%s) if "
                                  "a line, an allowance or a charge is in it, and none if "
                                  "none is" % (code, name))
    def check(document: Document) -> Iterator[Failure]:
        used = len(with_code(on_allowances(document) + on_charges(document)
                             + on_lines(document), code))
        # BR-AF-01 and BR-AG-01 look for the breakdown of a category that is
        # used by its code as written, and BR-S-01 by its code trimmed.
        found = len(with_code(in_breakdown(document), code,
                              trimmed if family == "S" else as_written))
        if used and not found:
            yield "BG-23", "it is used %d times and has no breakdown" % used
        elif not used and with_code(in_breakdown(document), code):
            yield "BG-23", "it has a breakdown and nothing is in it"


@en16931("BR-B-01", "a document that names the VAT category B (split payment) has no country "
                    "code in it that is not IT")
def br_b_01(document: Document) -> Iterator[Failure]:
    if not with_code(everywhere(document), "B", as_written):
        return
    countries: List[Value] = [value for term in ("BT-40", "BT-55", "BT-69", "BT-80")
                              for value in document.values(term)]
    for _path, line in lines(document):
        countries += line.values("BT-159")
    for country in countries:
        if country.text != "IT":
            yield "BG-23", "it names %r" % country.text
            return


@en16931("BR-B-02", "a document that names the VAT category B (split payment) does not also "
                    "name the category S")
def br_b_02(document: Document) -> Iterator[Failure]:
    if (with_code(everywhere(document), "B", as_written)
            and with_code(everywhere(document), "S", as_written)):
        yield "BG-23", "it names both"


# -- 02 to 04: the parties are identified as the category needs -----------------

def vat_identifiers(document: Document, term: str) -> List[Value]:
    return [value for value in document.values(term)
            if value.attributes.get("TaxScheme/ID", "VAT").strip().upper() == "VAT"]


def parties(family: str, document: Document) -> Optional[str]:
    """What is wrong with how the parties are identified, for a category."""
    seller_vat = bool(vat_identifiers(document, "BT-31"))
    # Most families take any tax registration of the seller's, whatever its
    # scheme; G, IC and O ask for a VAT identifier.
    seller_any = bool(document.values("BT-31") or document.values("BT-32"))
    representative = bool(vat_identifiers(document, "BT-63"))
    buyer_vat = bool(vat_identifiers(document, "BT-48"))
    if family == "O":
        named = [term for term, there in (("BT-31", seller_vat), ("BT-63", representative),
                                          ("BT-48", buyer_vat)) if there]
        return "a VAT identifier is given (%s)" % ", ".join(named) if named else None
    if not ((seller_vat if family in ("G", "IC") else seller_any) or representative):
        return "the seller has none"
    if family == "IC" and not buyer_vat:
        return "the buyer has no VAT identifier (BT-48)"
    if family == "AE" and not (buyer_vat or document.values("BT-47")):
        return "the buyer has neither a VAT identifier (BT-48) nor a legal registration (BT-47)"
    return None


WANTED = {
    "O": "neither the seller, its tax representative nor the buyer has a VAT identifier",
    "G": "the seller (BT-31) or its tax representative (BT-63) has a VAT identifier",
    "IC": "the seller (BT-31) or its tax representative (BT-63) has a VAT identifier, and so "
          "has the buyer (BT-48)",
    "AE": "the seller has a tax registration (BT-31, BT-32) or its tax representative a VAT "
          "identifier (BT-63), and the buyer has a VAT identifier (BT-48) or a legal "
          "registration (BT-47)",
}
SELLER = ("the seller has a tax registration (BT-31, BT-32) or its tax representative a VAT "
          "identifier (BT-63)")


def identified(family: str, code: str, number: str, what: str, places: Callable) -> None:
    @en16931("BR-%s-%s" % (family, number), "where %s is in the VAT category %s, %s"
             % (what, code, WANTED.get(family, SELLER)))
    def check(document: Document) -> Iterator[Failure]:
        using = with_code(places(document), code)
        if family == "AF" and number == "04":
            # BR-AF-04 alone is let off by a code that is not exactly `L`.
            using = with_code(using, code, as_written)
        wrong = parties(family, document) if using else None
        if wrong:
            yield using[0][0], wrong


# -- 05 to 07: the rate ---------------------------------------------------------

def rated(family: str, code: str, number: str, what: str, places: Callable) -> None:
    wanted = ("has no rate" if family == "O" else "has a rate of nought" if family in ZERO_RATED
              else "has a rate above nought" if family == "S" else "has a rate of nought or more")

    @en16931("BR-%s-%s" % (family, number), "%s in the VAT category %s %s"
             % (what, code, wanted))
    def check(document: Document) -> Iterator[Failure]:
        for path, group, (_code, rate) in with_code(places(document), code):
            if family == "O":
                passes = not group.values(rate)
            elif family in ZERO_RATED:
                passes = equal(one(group, rate), Decimal(0))
            else:
                # Compared as doubles, and with any of them, as the test has it.
                passes = any(number is not None and (number > 0 if family == "S" else number >= 0)
                             for number in doubles(group, rate))
            if not passes:
                yield path, ("its rate is %s" % group.text(rate) if group.values(rate)
                             else "it has none")


# -- 08: the taxable amount -------------------------------------------------------

def rate_is(place: Place, rate: Decimal) -> bool:
    """`[cac:TaxCategory/xs:decimal(cbc:Percent) = $rate]`."""
    _path, group, (_code, term) = place
    return equal(one(group, term), rate)


def net(document: Document, code: str, rate: Optional[Decimal], with_lines: bool = True) -> Decimal:
    """The lines' net amounts, plus the charges, less the allowances, of a
    category: and of one rate of it, where a rate is given."""
    def amounts(places: List[Place], term: str) -> Decimal:
        total = Decimal(0)
        for place in with_code(places, code):
            if rate is None or rate_is(place, rate):
                total += one(place[1], term) or Decimal(0)
        return total
    return ((amounts(on_lines(document), "BT-131") if with_lines else Decimal(0))
            + amounts(on_charges(document), "BT-99") - amounts(on_allowances(document), "BT-92"))


def within_one(breakdown: Group, expected: Decimal) -> bool:
    low, high = nudged(breakdown, "BT-116", -1), nudged(breakdown, "BT-116", 1)
    return low is not None and high is not None and low < expected < high


def taxable_amount(family: str, code: str) -> None:
    exact = family not in BY_RATE
    about = ("the taxable amount (BT-116) of the VAT breakdown for %s is the net amounts of "
             "its lines (BT-131), plus its charges (BT-99), less its allowances (BT-92)%s"
             % (code, "" if exact else ", at the breakdown's rate and to within one unit"))

    @en16931("BR-%s-08" % family, about)
    def check(document: Document) -> Iterator[Failure]:
        for path, breakdown, _terms in with_code(in_breakdown(document), code):
            if exact:
                # Exactly, and whatever the rates; and a document with no
                # lines has no taxable amount that is right.
                expected = net(document, code, None)
                if document.all("BG-25") and equal(one(breakdown, "BT-116"), expected):
                    continue
                yield path, "it is %s and they come to %s" % (
                    shown(one(breakdown, "BT-116")), shown(expected))
                continue
            rate = one(breakdown, "BT-119")
            if rate is None:
                continue        # "every rate of none": nothing is asked
            expected = net(document, code, rate)
            if family == "S":
                # BR-S-08 asks that something is at this rate, and is also
                # met by the allowances and charges alone, without the lines.
                used = any(rate_is(place, rate) for place in with_code(
                    on_allowances(document) + on_charges(document), code))
                on_a_line = any(rate_is(place, rate)
                                for place in with_code(on_lines(document), code))
                passes = ((used or on_a_line) and within_one(breakdown, expected)) or (
                    used and within_one(breakdown, net(document, code, rate, with_lines=False)))
            else:
                passes = bool(document.all("BG-25")) and within_one(breakdown, expected)
            if not passes:
                yield path, "it is %s and at %s%% they come to %s" % (
                    breakdown.text("BT-116") or "nothing", shown(rate), shown(expected))


# -- 09 and 10: the tax amount, and the reason for exemption ---------------------

def tax_amount(family: str, code: str) -> None:
    if family in BY_RATE:
        about = ("the tax amount (BT-117) of a VAT breakdown for %s is its taxable amount "
                 "(BT-116) times its rate (BT-119), to within one unit" % code)
    else:
        about = "the tax amount (BT-117) of the VAT breakdown for %s is nought" % code

    @en16931("BR-%s-09" % family, about)
    def check(document: Document) -> Iterator[Failure]:
        for path, breakdown, _terms in with_code(in_breakdown(document), code):
            tax = one(breakdown, "BT-117")
            if family not in BY_RATE:
                if not equal(tax, Decimal(0)):
                    yield path, "it is %s" % shown(tax)
                continue
            taxable, rate = one(breakdown, "BT-116"), one(breakdown, "BT-119")
            expected = (None if taxable is None or rate is None
                        else cents(abs(taxable) * (rate / 100)))
            if tax is None or expected is None or not (
                    abs(tax) - 1 < expected and abs(tax) + 1 > expected):
                yield path, "it is %s and %s at %s%% is %s" % (
                    shown(tax), shown(taxable), shown(rate), shown(expected))


def exemption_reason(family: str, code: str) -> None:
    owed = family in ("E", "AE", "IC", "G", "O")

    @en16931("BR-%s-10" % family, "the VAT breakdown for %s %s" % (code, (
        "has a reason for exemption (BT-120) or its code (BT-121)" if owed else
        "has neither a reason for exemption (BT-120) nor its code (BT-121)")))
    def check(document: Document) -> Iterator[Failure]:
        for path, breakdown, _terms in with_code(in_breakdown(document), code):
            given = bool(breakdown.values("BT-120") or breakdown.values("BT-121"))
            if given != owed:
                yield path, "it has one" if given else "it has neither"


# -- 11 to 14: what only two families ask -----------------------------------------

def broken_down(document: Document, code: str) -> bool:
    return bool(with_code(in_breakdown(document), code, any_trimmed))


@en16931("BR-IC-11", "a document with a VAT breakdown for K (intra-community supply) has a "
                     "delivery date (BT-72) or an invoicing period (BG-14)")
def br_ic_11(document: Document) -> Iterator[Failure]:
    if not broken_down(document, "K"):
        return
    # The date is measured, not read: more than one character of anything.
    dates = document.values("BT-72")
    if len(dates) > 1:
        raise_twice("BT-72", len(dates))
    if dates and len(dates[0].text) > 1:
        return
    if any(document.values(term) for term in ("BT-73", "BT-74", "BT-8")):
        return
    yield "BG-13", "it has neither"


@en16931("BR-IC-12", "a document with a VAT breakdown for K (intra-community supply) has the "
                     "country it was delivered to (BT-80)")
def br_ic_12(document: Document) -> Iterator[Failure]:
    if not broken_down(document, "K"):
        return
    countries = document.values("BT-80")
    if len(countries) > 1:
        raise_twice("BT-80", len(countries))
    if not countries or len(countries[0].text) <= 1:
        yield "BG-15", "it has none"


def raise_twice(term: str, count: int) -> None:
    raise Incomputable("%s occurs %d times where the rule takes one" % (term, count))


def only_o(number: str, what: str, places: Callable) -> None:
    @en16931("BR-O-%s" % number, "a document with a VAT breakdown for O (not subject to VAT) "
                                 "has no %s in another VAT category" % what)
    def check(document: Document) -> Iterator[Failure]:
        if not broken_down(document, "O"):
            return
        for place in places(document):
            if category_is_there(place) and not trimmed(place, "O"):
                yield place[0], "its category is %r" % place[1].text(place[2][0])
                return


for _family, (_code, _name) in FAMILIES.items():
    if _family == "B":
        continue
    (a_breakdown_if_used if _family in BY_RATE else one_breakdown)(_family, _code, _name)
    for _number, _what, _places in (("02", "a line", on_lines),
                                    ("03", "a document level allowance", on_allowances),
                                    ("04", "a document level charge", on_charges)):
        identified(_family, _code, _number, _what, _places)
    for _number, _what, _places in (("05", "a line", on_lines),
                                    ("06", "a document level allowance", on_allowances),
                                    ("07", "a document level charge", on_charges)):
        rated(_family, _code, _number, _what, _places)
    taxable_amount(_family, _code)
    tax_amount(_family, _code)
    exemption_reason(_family, _code)

only_o("11", "VAT breakdown", in_breakdown)
only_o("12", "line", on_lines)
only_o("13", "document level allowance", on_allowances)
only_o("14", "document level charge", on_charges)
