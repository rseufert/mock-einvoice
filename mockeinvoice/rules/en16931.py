"""The EN 16931 core: the rules every document is held to.

Built so far: the calculation rules (`BR-CO-*`) and the rules on how many
decimals an amount carries (`BR-DEC-*`). Read `rules/__init__.py` first.

Each function is its rule's published test, restated against the model. The
tests are XPath over UBL, and where the model is further from UBL than the
test assumes, the difference is listed here and not papered over.

Where this departs from the published tests
-------------------------------------------
- **A tax scheme that is not VAT.** Several tests look at a tax category only
  if its `TaxScheme/ID` is `VAT`. The reader holds a category's scheme as VAT
  whatever it said, with a `FIXED` finding where it said otherwise. So a
  document with another scheme there is judged here as if it had said VAT.
- **An element twice.** A test that casts one element to a number is an XPath
  error if there are two. Here that is a failure of the rule, saying so; the
  reader has already reported the repeat.
- **Two totals elements.** The tests on the document totals run once for each
  `LegalMonetaryTotal`. The model holds one set of totals, so with two the
  amounts are repeats, and the first point applies.

Rules that cannot fail
----------------------
`BR-CO-05` to `BR-CO-08` are published with the test `true()`. `BR-DEC-13` and
`BR-DEC-15` are published with a test that compares a tax amount's currency
with an element the tax amount does not have, so it selects nothing and
passes. They are registered here because they are published and they do run;
they find nothing, as they find nothing anywhere else.
"""
from __future__ import annotations

import functools
from typing import Iterator, List, Tuple

from ..model import Document, Group
from . import Failure, rule
from .calculation import (Incomputable, cents, decimals_after_point, equal, minus, numbered,
                          one, plus, shown, total, xpath_round)

en16931 = functools.partial(rule, "en16931")

# The prefixes BR-CO-09 takes for a VAT identifier: ISO 3166-1 alpha-2, with
# `EL` for Greece, `XI` for Northern Ireland and `1A` for Kosovo. Kept as the
# one string the published test searches, spaces and all, because the test is
# "is the prefix somewhere in this string" and that is not quite "is it one of
# these codes": an identifier of one letter passes, and so does an empty one.
VAT_PREFIXES = " " + " ".join((
    "1A AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ BL BM BN BO",
    "BQ BR BS BT BV BW BY BZ CA CC CD CF CG CH CI CK CL CM CN CO CR CU CV CW CX CY CZ DE DJ DK",
    "DM DO DZ EC EE EG EH EL ER ES ET FI FJ FK FM FO FR GA GB GD GE GF GG GH GI GL GM GN GP GQ",
    "GR GS GT GU GW GY HK HM HN HR HT HU ID IE IL IM IN IO IQ IR IS IT JE JM JO JP KE KG KH KI",
    "KM KN KP KR KW KY KZ LA LB LC LI LK LR LS LT LU LV LY MA MC MD ME MF MG MH MK ML MM MN MO",
    "MP MQ MR MS MT MU MV MW MX MY MZ NA NC NE NF NG NI NL NO NP NR NU NZ OM PA PE PF PG PH PK",
    "PL PM PN PR PS PT PW PY QA RE RO RS RU RW SA SB SC SD SE SG SH SI SJ SK SL SM SN SO SR SS",
    "ST SV SX SY SZ TC TD TF TG TH TJ TK TL TM TN TO TR TT TV TW TZ UA UG UM US UY UZ VA VC VE",
    "VG VI VN VU WF WS XI YE YT ZA ZM ZW")) + " "


def lines(document: Document) -> List[Tuple[str, Group]]:
    return list(numbered(document.all("BG-25"), "BG-25"))


def within(document: Document, line_group: str) -> Iterator[Tuple[str, Group]]:
    """Each line's allowances (BG-27) or charges (BG-28), with where it is."""
    for path, line in lines(document):
        for inner, group in numbered(line.all(line_group), line_group):
            yield "%s/%s" % (path, inner), group


# -- BR-CO: the calculations -------------------------------------------------

@en16931("BR-CO-03", "the VAT point date (BT-7) and the VAT point date code (BT-8) "
                     "are not both given")
def br_co_03(document: Document) -> Iterator[Failure]:
    if document.values("BT-7") and document.values("BT-8"):
        yield "BT-7", "both are given"


@en16931("BR-CO-04", "each line has a VAT category code (BT-151)")
def br_co_04(document: Document) -> Iterator[Failure]:
    for path, line in lines(document):
        if not line.values("BT-151"):
            yield path, "it has none"


def cannot_fail(identifier: str, what: str) -> None:
    @en16931(identifier, "%s (published with a test that cannot fail)" % what)
    def never(_document: Document) -> Iterator[Failure]:
        return iter(())


cannot_fail("BR-CO-05", "a document level allowance's reason and reason code say the same")
cannot_fail("BR-CO-06", "a document level charge's reason and reason code say the same")
cannot_fail("BR-CO-07", "a line allowance's reason and reason code say the same")
cannot_fail("BR-CO-08", "a line charge's reason and reason code say the same")


@en16931("BR-CO-09", "a VAT identifier (BT-31, BT-48, BT-63) starts with the two letters of "
                     "the country that issued it")
def br_co_09(document: Document) -> Iterator[Failure]:
    for term in ("BT-31", "BT-48", "BT-63"):
        for value in document.values(term):
            if value.attributes.get("TaxScheme/ID", "VAT").strip().upper() != "VAT":
                continue        # another scheme's registration, which the reader put here
            if value.text[:2] not in VAT_PREFIXES:
                yield term, "%r starts with %r" % (value.text, value.text[:2])


@en16931("BR-CO-10", "the sum of line net amounts (BT-106) is the lines' net amounts "
                     "(BT-131) added up")
def br_co_10(document: Document) -> Iterator[Failure]:
    if not document.has("BG-22"):
        return
    expected = cents(total(document.all("BG-25"), "BT-131"))
    stated = one(document, "BT-106")
    if not equal(stated, expected):
        yield "BT-106", "it is %s and the lines come to %s" % (shown(stated), shown(expected))


def sum_of(identifier: str, name: str, stated_term: str, group: str, term: str) -> None:
    """BR-CO-11 and BR-CO-12: a total of the document's allowances or charges."""
    @en16931(identifier, "the sum of %s on document level (%s) is their amounts (%s) "
                         "added up, or there are none and no sum" % (name, stated_term, term))
    def check(document: Document) -> Iterator[Failure]:
        if not document.has("BG-22"):
            return
        each = document.all(group)
        stated, expected = one(document, stated_term), cents(total(each, term))
        if equal(stated, expected) or (not document.values(stated_term) and not each):
            return
        yield stated_term, "it is %s and the %d %s come to %s" % (
            shown(stated), len(each), name, shown(expected))


sum_of("BR-CO-11", "allowances", "BT-107", "BG-20", "BT-92")
sum_of("BR-CO-12", "charges", "BT-108", "BG-21", "BT-99")


@en16931("BR-CO-13", "the total without VAT (BT-109) is the sum of line net amounts (BT-106) "
                     "less the allowances (BT-107) plus the charges (BT-108)")
def br_co_13(document: Document) -> Iterator[Failure]:
    if not document.has("BG-22"):
        return
    net = one(document, "BT-106")
    allowances, charges = one(document, "BT-107"), one(document, "BT-108")
    if charges is not None and allowances is not None:
        expected = cents(minus(plus(net, charges), allowances))
    elif allowances is not None:
        expected = cents(minus(net, allowances))
    elif charges is not None:
        expected = cents(plus(net, charges))
    else:
        expected = net              # as stated: this arm of the test rounds nothing
    stated = one(document, "BT-109")
    if not equal(stated, expected):
        yield "BT-109", "it is %s and the parts come to %s" % (shown(stated), shown(expected))


@en16931("BR-CO-14", "the total VAT amount (BT-110) is the VAT breakdown's tax amounts "
                     "(BT-117) added up")
def br_co_14(document: Document) -> Iterator[Failure]:
    breakdown = document.all("BG-23")
    if not breakdown:
        return                      # a tax total with no breakdown is not asked
    stated, expected = one(document, "BT-110"), cents(total(breakdown, "BT-117"))
    if not equal(stated, expected):
        yield "BT-110", "it is %s and the breakdown comes to %s" % (shown(stated), shown(expected))


@en16931("BR-CO-15", "there is one total VAT amount in the invoice currency (BT-5), and the "
                     "total with VAT (BT-112) is the total without (BT-109) plus it")
def br_co_15(document: Document) -> Iterator[Failure]:
    for currency in document.values("BT-5"):
        in_currency = [value for value in document.values("BT-110") + document.values("BT-111")
                       if value.attributes.get("currencyID") == currency.text]
        for value in in_currency:
            if value.number is None:
                raise Incomputable("a total VAT amount is %r, which is not a decimal number"
                                   % value.text)
        if len(in_currency) != 1:
            yield "BT-110", "there are %d total VAT amounts in %s" % (
                len(in_currency), currency.text)
            continue
        stated = one(document, "BT-112")
        expected = cents(plus(one(document, "BT-109"), in_currency[0].number))
        if not equal(stated, expected):
            yield "BT-112", "it is %s and the parts come to %s" % (shown(stated), shown(expected))


@en16931("BR-CO-16", "the amount due (BT-115) is the total with VAT (BT-112) less what is "
                     "paid (BT-113) plus the rounding amount (BT-114)")
def br_co_16(document: Document) -> Iterator[Failure]:
    if not document.has("BG-22"):
        return
    due, with_vat = one(document, "BT-115"), one(document, "BT-112")
    paid, rounding = one(document, "BT-113"), one(document, "BT-114")
    owed = with_vat if paid is None else cents(minus(with_vat, paid))
    # With a rounding amount the test takes it off the amount due and rounds
    # that; without one it compares the amount due as it stands.
    stated = due if rounding is None else cents(minus(due, rounding))
    if not equal(stated, owed):
        yield "BT-115", "it is %s%s and the parts come to %s" % (
            shown(due), "" if rounding is None else " (%s before rounding)" % shown(stated),
            shown(owed))


@en16931("BR-CO-17", "a VAT category's tax amount (BT-117) is its taxable amount (BT-116) "
                     "times its rate (BT-119), to within one unit of currency")
def br_co_17(document: Document) -> Iterator[Failure]:
    for path, category in numbered(document.all("BG-23"), "BG-23"):
        rate = one(category, "BT-119")
        tax, taxable = one(category, "BT-117"), one(category, "BT-116")
        if rate is None or xpath_round(rate) == 0:
            # No rate, or one that rounds to nought: the tax rounds to nought.
            if tax is not None and xpath_round(tax) == 0:
                continue
            yield path, "the rate is %s and the tax amount is %s" % (shown(rate), shown(tax))
            continue
        expected = cents(None if taxable is None else abs(taxable) * (rate / 100))
        if (tax is not None and expected is not None
                and abs(tax) - 1 < expected and abs(tax) + 1 > expected):
            continue
        yield path, "the tax amount is %s and %s at %s%% is %s" % (
            shown(tax), shown(taxable), shown(rate), shown(expected))


@en16931("BR-CO-18", "there is at least one VAT breakdown (BG-23)")
def br_co_18(document: Document) -> Iterator[Failure]:
    if not document.all("BG-23"):
        yield "BG-23", "there is none"


@en16931("BR-CO-19", "an invoicing period (BG-14) has a start date (BT-73), an end date "
                     "(BT-74) or a VAT point date code (BT-8)")
def br_co_19(document: Document) -> Iterator[Failure]:
    if document.has("BG-14") and not any(document.values(term)
                                         for term in ("BT-73", "BT-74", "BT-8")):
        yield "BG-14", "it has none of them"


@en16931("BR-CO-20", "a line's period (BG-26) has a start date (BT-134) or an end date "
                     "(BT-135)")
def br_co_20(document: Document) -> Iterator[Failure]:
    for path, line in lines(document):
        if line.has("BG-26") and not line.values("BT-134") and not line.values("BT-135"):
            yield path + "/BG-26", "it has neither"


def has_a_reason(identifier: str, name: str, group: str, reason: str, code: str,
                 on_line: bool) -> None:
    """BR-CO-21 to BR-CO-24: an allowance or charge says why."""
    @en16931(identifier, "a %s has a reason (%s) or a reason code (%s)" % (name, reason, code))
    def check(document: Document) -> Iterator[Failure]:
        each = within(document, group) if on_line else numbered(document.all(group), group)
        for path, found in each:
            if not found.values(reason) and not found.values(code):
                yield path, "it has neither"


has_a_reason("BR-CO-21", "document level allowance", "BG-20", "BT-97", "BT-98", False)
has_a_reason("BR-CO-22", "document level charge", "BG-21", "BT-104", "BT-105", False)
has_a_reason("BR-CO-23", "line allowance", "BG-27", "BT-139", "BT-140", True)
has_a_reason("BR-CO-24", "line charge", "BG-28", "BT-144", "BT-145", True)


@en16931("BR-CO-26", "the seller can be identified: by an identifier (BT-29), a legal "
                     "registration identifier (BT-30) or a VAT identifier (BT-31)")
def br_co_26(document: Document) -> Iterator[Failure]:
    if not document.has("BG-4"):
        return
    # The test takes any party identifier whose scheme is not exactly `SEPA`.
    # The reader files `sepa` in any case under the creditor identifier, so
    # one written in another case is looked for there, if it is the seller's.
    sellers_own = not any(document.values(term) for term in ("BT-59", "BT-60", "BT-61"))
    other_case = [value for value in document.values("BT-90")
                  if sellers_own and value.attributes.get("schemeID") != "SEPA"]
    if not (document.values("BT-29") or document.values("BT-30")
            or document.values("BT-31") or other_case):
        yield "BG-4", "it has none of them"


# -- BR-DEC: how many decimals an amount carries -------------------------------

def two_decimals(identifier: str, term: str, group: str = "", line_group: str = "") -> None:
    """An amount has at most two digits after the point, as it was written."""
    @en16931(identifier, "%s has at most two decimals" % term)
    def check(document: Document) -> Iterator[Failure]:
        if line_group:
            each = within(document, line_group)
        elif group == "BG-25":
            each = iter(lines(document))
        elif group:
            each = numbered(document.all(group), group)
        else:
            each = iter([("", document)])
        for path, found in each:
            values = found.values(term)
            if len(values) > 1:
                raise Incomputable("%s occurs %d times where the rule takes one"
                                   % (term, len(values)))
            if values and decimals_after_point(values[0].text) > 2:
                yield (path + "/" if path else "") + term, "it is %r" % values[0].text


two_decimals("BR-DEC-01", "BT-92", "BG-20")
two_decimals("BR-DEC-02", "BT-93", "BG-20")
two_decimals("BR-DEC-05", "BT-99", "BG-21")
two_decimals("BR-DEC-06", "BT-100", "BG-21")
two_decimals("BR-DEC-09", "BT-106")
two_decimals("BR-DEC-10", "BT-107")
two_decimals("BR-DEC-11", "BT-108")
two_decimals("BR-DEC-12", "BT-109")
cannot_fail("BR-DEC-13", "BT-110 has at most two decimals")
two_decimals("BR-DEC-14", "BT-112")
cannot_fail("BR-DEC-15", "BT-111 has at most two decimals")
two_decimals("BR-DEC-16", "BT-113")
two_decimals("BR-DEC-17", "BT-114")
two_decimals("BR-DEC-18", "BT-115")
two_decimals("BR-DEC-19", "BT-116", "BG-23")
two_decimals("BR-DEC-20", "BT-117", "BG-23")
two_decimals("BR-DEC-23", "BT-131", "BG-25")
two_decimals("BR-DEC-24", "BT-136", line_group="BG-27")
two_decimals("BR-DEC-25", "BT-137", line_group="BG-27")
two_decimals("BR-DEC-27", "BT-141", line_group="BG-28")
two_decimals("BR-DEC-28", "BT-142", line_group="BG-28")
