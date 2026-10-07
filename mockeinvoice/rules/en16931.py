"""The EN 16931 core: the rules every document is held to.

Built so far: the rules on what a document must have in it (`BR-01` to
`BR-65`), the calculation rules (`BR-CO-*`) and the rules on how many decimals
an amount carries (`BR-DEC-*`). The VAT category rules are in
`en16931_vat.py` and the code list rules in `en16931_codes.py`. Read `rules/__init__.py` first.

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
  amounts are repeats, and the first point applies. The same goes for every
  element the standard has once and the model holds as one: two seller
  addresses are one address here, with what was in both.
- **A tax category with no tax scheme.** `BR-32`, `BR-37`, `BR-47` and `BR-48`
  look for a category whose scheme is VAT, and a category that names no scheme
  at all is not one. The model does not hold whether a scheme was named, so
  here such a category counts. UBL's schema requires the scheme.
- **What is not held is not asked.** A rule whose context is an element
  wherever it occurs (`BR-52` on any `AdditionalDocumentReference`, `BR-53` on
  any `TaxTotal`) is asked here of the places the standard has for it. One on
  a line, say, the reader has already reported as not held.
- **A charge indicator that is neither.** The allowance and charge rules pick
  their elements by comparing `ChargeIndicator` with a boolean, which is an
  XPath error on text that is not one. The reader does not hold such an
  element, and says so; no rule is asked of it.

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

from ..model import (INVOICED_OBJECT_REFERENCE, PARTY_ROLE, PROJECT_REFERENCE, Document, Group,
                     Value)
from . import Failure, rule
from .calculation import (Incomputable, cents, decimals_after_point, doubles, equal, minus,
                          normalize_space, numbered, one, plus, said, shown, total, xpath_round,
                          xs_date)

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


# -- BR: what a document must have in it -------------------------------------
#
# The published tests ask one of two things of an element and the difference
# matters: that it has something in it (`normalize-space(cbc:X) != ''`), or
# only that it is there (`exists(cbc:X)`), which an empty element is. `named`
# is the first and `given` the second.

Where = Tuple[str, Group]


def whole(document: Document) -> List[Where]:
    return [("", document)]


def if_there(group: str):
    """The document, if it has a group that occurs once: the rule's context
    is that group's element."""
    return lambda document: [(group, document)] if document.has(group) else []


def each(group: str):
    return lambda document: list(numbered(document.all(group), group))


def each_in_lines(group: str):
    return lambda document: list(within(document, group))


def lines_with(group: str):
    return lambda document: [("%s/%s" % (path, group), line)
                             for path, line in lines(document) if line.has(group)]


def named(identifier: str, about: str, term: str, where=whole) -> None:
    @en16931(identifier, about)
    def check(document: Document) -> Iterator[Failure]:
        for path, group in where(document):
            if said(group, term) == "":
                yield path or term, ("it is there with nothing in it" if group.values(term)
                                     else "it is not there")


def given(identifier: str, about: str, *terms: str, where=whole) -> None:
    """One of the terms is there, though it may be empty."""
    @en16931(identifier, about)
    def check(document: Document) -> Iterator[Failure]:
        for path, group in where(document):
            if not any(group.values(term) for term in terms):
                yield path or terms[0], "it is not there"


def qualified(identifier: str, about: str, term: str, attribute: str, where=whole) -> None:
    """Every value of a term has an attribute beside it."""
    @en16931(identifier, about)
    def check(document: Document) -> Iterator[Failure]:
        for path, group in where(document):
            for value in group.values(term):
                if attribute not in value.attributes:
                    yield "/".join(part for part in (path, term) if part), (
                        "%r has none" % value.text)


named("BR-01", "the document names its specification (BT-24)", "BT-24")
named("BR-02", "the document has a number (BT-1)", "BT-1")
named("BR-03", "the document has an issue date (BT-2)", "BT-2")
named("BR-04", "the document has a type code (BT-3)", "BT-3")
named("BR-05", "the document has a currency code (BT-5)", "BT-5")
named("BR-06", "the seller has a name (BT-27)", "BT-27")
named("BR-07", "the buyer has a name (BT-44)", "BT-44")


def has_group(identifier: str, about: str, group: str, where=whole) -> None:
    @en16931(identifier, about)
    def check(document: Document) -> Iterator[Failure]:
        for path, holder in where(document):
            if not holder.has(group):
                yield path or group, "it is not there"


has_group("BR-08", "the seller has a postal address (BG-5)", "BG-5")
named("BR-09", "the seller's postal address has a country code (BT-40)", "BT-40",
      if_there("BG-5"))
has_group("BR-10", "the buyer has a postal address (BG-8)", "BG-8")
named("BR-11", "the buyer's postal address has a country code (BT-55)", "BT-55",
      if_there("BG-8"))
given("BR-12", "the document totals have the sum of line net amounts (BT-106)", "BT-106",
      where=if_there("BG-22"))
given("BR-13", "the document totals have the total without VAT (BT-109)", "BT-109",
      where=if_there("BG-22"))
given("BR-14", "the document totals have the total with VAT (BT-112)", "BT-112",
      where=if_there("BG-22"))
given("BR-15", "the document totals have the amount due (BT-115)", "BT-115",
      where=if_there("BG-22"))
has_group("BR-16", "the document has at least one line (BG-25)", "BG-25")


@en16931("BR-17", "a payee (BG-10) has a name (BT-59), and is not the seller: neither its "
                  "name nor any identifier of its is one of the seller's")
def br_17(document: Document) -> Iterator[Failure]:
    if not document.has("BG-10"):
        return
    # The seller's name here is its trading name (BT-28), which is the
    # element the published test compares with, and not BT-27.
    def texts(values: List[Value]) -> List[str]:
        return [value.text for value in values]

    def identifiers(term: str, payee: bool) -> List[str]:
        return texts(document.values(term)) + [
            value.text for value in document.values("BT-90")
            if (value.attributes.get(PARTY_ROLE) == "payee") == payee]

    names = texts(document.values("BT-59"))
    if not names:
        yield "BT-59", "it has no name"
        return
    for name in names:
        if name in texts(document.values("BT-28")):
            yield "BT-59", "its name, %r, is the seller's trading name (BT-28)" % name
            return
    for identifier in identifiers("BT-60", True):
        if identifier in identifiers("BT-29", False):
            yield "BT-60", "its identifier %r is one of the seller's" % identifier
            return


named("BR-18", "a seller's tax representative (BG-11) has a name (BT-62)", "BT-62",
      if_there("BG-11"))
has_group("BR-19", "a seller's tax representative (BG-11) has a postal address (BG-12)",
          "BG-12", if_there("BG-11"))
named("BR-20", "a tax representative's postal address has a country code (BT-69)", "BT-69",
      if_there("BG-12"))
named("BR-21", "each line has an identifier (BT-126)", "BT-126", each("BG-25"))
given("BR-22", "each line has a quantity (BT-129)", "BT-129", where=each("BG-25"))
given("BR-23", "each line's quantity has a unit of measure (BT-130)", "BT-130",
      where=each("BG-25"))
given("BR-24", "each line has a net amount (BT-131)", "BT-131", where=each("BG-25"))
named("BR-25", "each line's item has a name (BT-153)", "BT-153", each("BG-25"))
given("BR-26", "each line has a net price (BT-146)", "BT-146", where=each("BG-25"))


@en16931("BR-27", "a line's net price (BT-146) is not negative")
def br_27(document: Document) -> Iterator[Failure]:
    for path, line in lines(document):
        prices = doubles(line, "BT-146")
        # A price that is not there is not "not negative": compared with an
        # empty sequence, nothing is. So this fails beside BR-26.
        if not any(price is not None and price >= 0 for price in prices):
            yield path, ("the price is %s" % line.text("BT-146") if prices
                         else "there is no price")


@en16931("BR-28", "a line's gross price (BT-148) is not negative")
def br_28(document: Document) -> Iterator[Failure]:
    for path, line in lines(document):
        prices = doubles(line, "BT-148")
        if prices and not any(price is not None and price >= 0 for price in prices):
            yield path, "the gross price is %s" % line.text("BT-148")


def ends_after_it_starts(identifier: str, name: str, where, start: str, end: str) -> None:
    @en16931(identifier, "%s does not end (%s) before it starts (%s)" % (name, end, start))
    def check(document: Document) -> Iterator[Failure]:
        for path, group in where(document):
            if not group.values(start) or not group.values(end):
                continue
            if not xs_date(group, end) >= xs_date(group, start):
                yield path, "it runs from %s to %s" % (group.text(start), group.text(end))


ends_after_it_starts("BR-29", "the invoicing period (BG-14)", if_there("BG-14"),
                     "BT-73", "BT-74")
ends_after_it_starts("BR-30", "a line's period (BG-26)", lines_with("BG-26"),
                     "BT-134", "BT-135")

given("BR-31", "a document level allowance has an amount (BT-92)", "BT-92",
      where=each("BG-20"))
given("BR-32", "a document level allowance has a VAT category code (BT-95)", "BT-95",
      where=each("BG-20"))
given("BR-33", "a document level allowance has a reason (BT-97) or a reason code (BT-98)",
      "BT-97", "BT-98", where=each("BG-20"))
given("BR-36", "a document level charge has an amount (BT-99)", "BT-99", where=each("BG-21"))
given("BR-37", "a document level charge has a VAT category code (BT-102)", "BT-102",
      where=each("BG-21"))
given("BR-38", "a document level charge has a reason (BT-104) or a reason code (BT-105)",
      "BT-104", "BT-105", where=each("BG-21"))
given("BR-41", "a line allowance has an amount (BT-136)", "BT-136",
      where=each_in_lines("BG-27"))
given("BR-42", "a line allowance has a reason (BT-139) or a reason code (BT-140)",
      "BT-139", "BT-140", where=each_in_lines("BG-27"))
given("BR-43", "a line charge has an amount (BT-141)", "BT-141", where=each_in_lines("BG-28"))
given("BR-44", "a line charge has a reason (BT-144) or a reason code (BT-145)",
      "BT-144", "BT-145", where=each_in_lines("BG-28"))
given("BR-45", "a VAT breakdown has a taxable amount (BT-116)", "BT-116", where=each("BG-23"))
given("BR-46", "a VAT breakdown has a tax amount (BT-117)", "BT-117", where=each("BG-23"))
given("BR-47", "a VAT breakdown has a VAT category code (BT-118)", "BT-118",
      where=each("BG-23"))


@en16931("BR-48", "a VAT breakdown has a rate (BT-119), unless its category (BT-118) is O, "
                  "not subject to VAT")
def br_48(document: Document) -> Iterator[Failure]:
    for path, breakdown in numbered(document.all("BG-23"), "BG-23"):
        if not breakdown.values("BT-119") and not any(
                normalize_space(code.text) == "O" for code in breakdown.values("BT-118")):
            yield path, "it has none, and its category is %r" % breakdown.text("BT-118")


given("BR-49", "a payment instruction has a payment means code (BT-81)", "BT-81",
      where=each("BG-16"))

TRANSFERS = ("30", "58")        # credit transfer, and SEPA credit transfer


@en16931("BR-50", "the account of a payment by credit transfer has an identifier (BT-84)")
def br_50(document: Document) -> Iterator[Failure]:
    for path, payment in numbered(document.all("BG-16"), "BG-16"):
        # The code is compared here as it is written, spaces and all, which
        # is not how BR-61 compares it.
        if (payment.has("BG-17") and any(code.text in TRANSFERS
                                         for code in payment.values("BT-81"))
                and said(payment, "BT-84") == ""):
            yield path, "it has none"


@en16931("BR-51", "no more than the last digits of a payment card's number (BT-87) are given")
def br_51(document: Document) -> Iterator[Failure]:
    for path, payment in numbered(document.all("BG-16"), "BG-16"):
        for number in payment.values("BT-87"):
            if len(normalize_space(number.text)) > 10:
                yield path, "%d characters are given" % len(normalize_space(number.text))


@en16931("BR-52", "a supporting document (BG-24), and any other additional document "
                  "reference, has an identifier (BT-122)")
def br_52(document: Document) -> Iterator[Failure]:
    for path, reference in numbered(document.all("BG-24"), "BG-24"):
        if said(reference, "BT-122") == "":
            yield path, "it has none"
    # The same element with a type code is the invoiced object (BT-18) or, on
    # a credit note, the project (BT-11), and the rule is asked of those too.
    typed = [(INVOICED_OBJECT_REFERENCE, "BT-18")]
    if document.kind == "CreditNote":
        typed.append((PROJECT_REFERENCE, "BT-11"))
    for reference, term in typed:
        if document.has(reference) and said(document, term) == "":
            yield term, "the reference is there and it has none"


@en16931("BR-53", "if a VAT accounting currency (BT-6) is named, there is a total VAT amount "
                  "in it (BT-111)")
def br_53(document: Document) -> Iterator[Failure]:
    amounts = document.values("BT-110") + document.values("BT-111")
    for currency in document.values("BT-6"):
        if not any(amount.attributes.get("currencyID") == currency.text for amount in amounts):
            yield "BT-111", "no total VAT amount is in %r" % currency.text


@en16931("BR-54", "an item attribute (BG-32) has a name (BT-160) and a value (BT-161)")
def br_54(document: Document) -> Iterator[Failure]:
    for path, attribute in within(document, "BG-32"):
        missing = [term for term in ("BT-160", "BT-161") if not attribute.values(term)]
        if missing:
            yield path, "it has no %s" % " or ".join(missing)


given("BR-55", "a preceding invoice reference (BG-3) has the invoice's number (BT-25)",
      "BT-25", where=each("BG-3"))


@en16931("BR-56", "a seller's tax representative (BG-11) has a VAT identifier (BT-63)")
def br_56(document: Document) -> Iterator[Failure]:
    if document.has("BG-11") and not any(
            value.attributes.get("TaxScheme/ID", "VAT").strip().upper() == "VAT"
            for value in document.values("BT-63")):
        yield "BT-63", "it has none"


given("BR-57", "a deliver to address (BG-15) has a country code (BT-80)", "BT-80",
      where=if_there("BG-15"))


@en16931("BR-61", "a payment by credit transfer (BT-81 is 30 or 58) has the account's "
                  "identifier (BT-84)")
def br_61(document: Document) -> Iterator[Failure]:
    for path, payment in numbered(document.all("BG-16"), "BG-16"):
        if said(payment, "BT-81") in TRANSFERS and not payment.values("BT-84"):
            yield path, "it has none"


qualified("BR-62", "the seller's electronic address (BT-34) names its scheme", "BT-34",
          "schemeID")
qualified("BR-63", "the buyer's electronic address (BT-49) names its scheme", "BT-49",
          "schemeID")
qualified("BR-64", "an item's standard identifier (BT-157) names its scheme", "BT-157",
          "schemeID", each("BG-25"))
qualified("BR-65", "an item's classification (BT-158) names its scheme", "BT-158", "listID",
          each("BG-25"))


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
    other_case = [value for value in document.values("BT-90")
                  if value.attributes.get(PARTY_ROLE) != "payee"
                  and value.attributes.get("schemeID") != "SEPA"]
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
