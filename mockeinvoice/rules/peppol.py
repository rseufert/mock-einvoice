"""Peppol BIS Billing 3.0: the rules Peppol adds to the EN 16931 core.

Here: Peppol's own 63 rules, asked of every Peppol document
(`PEPPOL-EN16931-*` and `PEPPOL-COMMON-*`). Germany's are in `peppol_de.py`,
and the rules for a seller in one of seven other countries (`DK-R`, `SE-R`
and the rest) in `peppol_national.py`.

All of these are asked of the document's elements (`tree.py`), as the rules
about UBL itself are: many of them are about what the model does not keep,
such as whether a charge indicator said `true` or `1`.

Nothing here is copied from Peppol's rule file, which may not be
redistributed. The rules are written from reading its tests. Where a test
holds a value to a code list, the list is the EN 16931 one already in this
package, with the handful of codes Peppol's differs by named below; a test
compares the result with Peppol's own lists where its files have been fetched.

What the published tests say that one might not expect
------------------------------------------------------
- **`true` and `false`, not `1` and `0`.** The core takes either for a charge
  indicator. Peppol's tests compare the text, so `1` is neither
  (`PEPPOL-EN16931-R043`), and an allowance marked `0` is not counted in its
  line's net amount (`PEPPOL-EN16931-R120`).
- **An allowance with a percentage and no base amount fails one rule and is
  then asked nothing else** (`R041`, and `R042` the other way round). The
  three rules on allowances are three rules of one pattern, and an element is
  asked the first of a pattern that fits it.
- **An empty element anywhere is fatal** (`R008`), attributes or not.
- **A checksum is asked of an identifier by its scheme** wherever the
  identifier is: an electronic address, a party identifier, a legal or tax
  registration.
- **A GLN is any number of digits** with a right check digit (`COMMON-R040`).

Where this departs from the published tests
-------------------------------------------
- **Division.** `R120` divides a price by its base quantity. XPath leaves the
  number of digits of a decimal division to the implementation; here it is 60
  significant digits. The rule allows two cents either way.
- **A date with no time zone** is compared as UTC, as in the core.
"""
from __future__ import annotations

import functools
import re
from decimal import Decimal
from typing import Callable, Iterator, List, Optional, Sequence, Tuple

from . import Failure, rule
from .calculation import (Incomputable, cents, date_of, decimal_of, double_sum, doubles_of,
                          normalize_space)
from .codelists import LISTS
from .tree import At, contexts, elements, tag, texts

peppol = functools.partial(rule, "peppol", over="tree")

INVOICE, CREDIT_NOTE = tag("ubl:Invoice"), tag("cn:CreditNote")
BILLING = "urn:cen.eu:en16931:2017#compliant#urn:fdc:peppol.eu:2017:poacc:billing:3.0"
PROFILES = {
    "urn:fdc:peppol.eu:2017:poacc:billing:01:1.0": "01",
    "urn:peppol:france:billing:regulated": "01",
    "urn:peppol:france:billing:non-regulated": "01",
    "urn:peppol:bis:billing_with_response": "02",
}
SELLER, BUYER = "cac:AccountingSupplierParty/cac:Party", "cac:AccountingCustomerParty/cac:Party"
COUNTRY = "cac:PostalAddress/cac:Country/cbc:IdentificationCode"
TWO_CENTS = Decimal("0.02")

# -- the code lists -------------------------------------------------------------
#
# Peppol's are the core's, but for two. Its currencies have the dobra's new
# code and not its old one, and its electronic address schemes are the core's
# without twenty-one of them.

def codes(identifier: str) -> frozenset:
    return frozenset(LISTS[identifier][0].split())


CURRENCIES = (codes("BR-CL-04") - {"STD"}) | {"STN"}
ADDRESS_SCHEMES = codes("BR-CL-25") - frozenset(
    "0037 0147 0154 0170 0177 0193 0194 0202 0203 0205 0212 0213 0215 0217 0219 0220 "
    "AN AQ AS AU EM".split())
MIME_TYPES = frozenset(LISTS["BR-CL-24"])
ALLOWANCE_REASONS, CHARGE_REASONS = codes("BR-CL-19"), codes("BR-CL-20")
VAT_POINT_CODES = codes("BR-CL-06")
INVOICE_TYPES = frozenset("71 80 82 84 102 218 219 326 331 380 382 383 384 386 388 393 395 553 "
                          "575 623 780 817 870 875 876 877".split())
CREDIT_NOTE_TYPES = frozenset("381 396 81 83 532".split())


# -- reading the elements ---------------------------------------------------------

def said(at: At, path: str) -> str:
    """`normalize-space(a/b)`: "" if it is not there, an error if it is twice."""
    found = elements(at, path)
    if len(found) > 1:
        raise Incomputable("%s occurs %d times where the rule takes one" % (path, len(found)))
    return normalize_space(found[0].text) if found else ""


def number(at: At, path: str) -> Optional[Decimal]:
    """`xs:decimal(a/b)`: None if it is not there."""
    found = elements(at, path)
    if len(found) > 1:
        raise Incomputable("%s occurs %d times where the rule takes one" % (path, len(found)))
    return decimal_of(found[0].text, path) if found else None


def named(root: At, *names: str) -> List[At]:
    """Every element with one of these names, wherever it is."""
    wanted = {tag(name) for name in names}
    return [at for at in root.everything() if at.node.tag in wanted]


def lines(root: At) -> List[At]:
    """The lines a document of its kind has: an invoice's are invoice lines."""
    return elements(root, "cac:InvoiceLine" if root.node.tag == INVOICE else "cac:CreditNoteLine")


def is_de(root: At, party: str) -> bool:
    return said(root, "%s/%s" % (party, COUNTRY)).upper() == "DE"


def both_german(root: At) -> bool:
    return is_de(root, SELLER) and is_de(root, BUYER)


def profile(root: At) -> str:
    return PROFILES.get(said(root, "cbc:ProfileID"), "Unknown")


# -- the head of the document ------------------------------------------------------

@peppol("PEPPOL-EN16931-R001", "the document names its business process (BT-23)")
def r001(root: At) -> Iterator[Failure]:
    if not elements(root, "cbc:ProfileID"):
        yield root.path, "it does not"


@peppol("PEPPOL-EN16931-R007", "the business process (BT-23) is one of Peppol's")
def r007(root: At) -> Iterator[Failure]:
    if profile(root) == "Unknown":
        yield "%s/cbc:ProfileID" % root.path, "it is %r" % said(root, "cbc:ProfileID")


@peppol("PEPPOL-EN16931-R002", "the document has at most one note (BT-22), unless seller and "
                               "buyer are both in Germany")
def r002(root: At) -> Iterator[Failure]:
    notes = elements(root, "cbc:Note")
    if len(notes) > 1 and not both_german(root):
        yield notes[1].path, "it has %d" % len(notes)


@peppol("PEPPOL-EN16931-R003", "the document has a buyer reference (BT-10) or an order "
                               "reference (BT-13)")
def r003(root: At) -> Iterator[Failure]:
    if not elements(root, "cbc:BuyerReference") and not elements(root, "cac:OrderReference/cbc:ID"):
        yield root.path, "it has neither"


@peppol("PEPPOL-EN16931-R004", "the specification identifier (BT-24) is Peppol BIS Billing "
                               "3.0's, or an extension of it written without `::`")
def r004(root: At) -> Iterator[Failure]:
    stated = said(root, "cbc:CustomizationID")
    if not stated.startswith(BILLING) or "::" in stated:
        yield "%s/cbc:CustomizationID" % root.path, "it is %r" % stated


@peppol("PEPPOL-EN16931-R005", "the VAT accounting currency (BT-6) is not the invoice "
                               "currency (BT-5)")
def r005(root: At) -> Iterator[Failure]:
    for code in named(root, "cbc:TaxCurrencyCode"):
        if code.parent and normalize_space(code.text) == said(code.parent,
                                                              "cbc:DocumentCurrencyCode"):
            yield code.path, "both are %r" % normalize_space(code.text)


@peppol("PEPPOL-EN16931-R008", "no element is empty")
def r008(root: At) -> Iterator[Failure]:
    for at in root.everything():
        if not at.children and not normalize_space(at.text):
            yield at.path, "it is"


def has_an_address(identifier: str, party: str, who: str, term: str) -> None:
    @peppol(identifier, "the %s has an electronic address (%s)" % (who, term))
    def check(root: At) -> Iterator[Failure]:
        for at in contexts(root, party):
            if not elements(at, "cbc:EndpointID"):
                yield at.path, "it has none"


has_an_address("PEPPOL-EN16931-R010", BUYER, "buyer", "BT-49")
has_an_address("PEPPOL-EN16931-R020", SELLER, "seller", "BT-34")


# -- VAT totals ---------------------------------------------------------------------

def tax_totals(root: At, with_breakdown: bool) -> List[At]:
    return [total for total in elements(root, "cac:TaxTotal")
            if bool(elements(total, "cac:TaxSubtotal")) == with_breakdown]


@peppol("PEPPOL-EN16931-R053", "exactly one VAT total has the VAT breakdown")
def r053(root: At) -> Iterator[Failure]:
    found = tax_totals(root, True)
    if len(found) != 1:
        yield (found[1].path if found else root.path), "%d have" % len(found)


@peppol("PEPPOL-EN16931-R054", "there is one VAT total with no breakdown if a VAT accounting "
                               "currency (BT-6) is named, and none if it is not")
def r054(root: At) -> Iterator[Failure]:
    found, wanted = tax_totals(root, False), 1 if elements(root, "cbc:TaxCurrencyCode") else 0
    if len(found) != wanted:
        yield (found[wanted].path if len(found) > wanted else root.path), (
            "there are %d" % len(found))


@peppol("PEPPOL-EN16931-R055", "the VAT total in the accounting currency (BT-111) has the "
                               "same sign as the one in the invoice currency (BT-110)")
def r055(root: At) -> Iterator[Failure]:
    if not elements(root, "cbc:TaxCurrencyCode"):
        return

    def amounts(currency: str) -> List[Optional[Decimal]]:
        wanted = said(root, currency)
        return [n for amount in elements(root, "cac:TaxTotal/cbc:TaxAmount")
                if amount.node.attributes.get("currencyID") == wanted
                for n in doubles_of([amount.text], "a VAT total")]

    accounting, invoice = amounts("cbc:TaxCurrencyCode"), amounts("cbc:DocumentCurrencyCode")

    def some(numbers: Sequence[Optional[Decimal]], test: Callable[[Decimal], bool]) -> bool:
        return any(n is not None and test(n) for n in numbers)
    if not ((some(accounting, lambda n: n <= 0) and some(invoice, lambda n: n <= 0))
            or (some(accounting, lambda n: n >= 0) and some(invoice, lambda n: n >= 0))):
        yield root.path, "they are %s and %s" % (
            ", ".join(str(n) for n in accounting) or "nothing",
            ", ".join(str(n) for n in invoice) or "nothing")


# -- allowances and charges ------------------------------------------------------------

def allowances(root: At) -> List[At]:
    """The document's and its lines' allowances and charges: not a price's."""
    return elements(root, "cac:AllowanceCharge") + [
        found for line in lines(root) for found in elements(line, "cac:AllowanceCharge")]


def shape(allowance: At) -> Tuple[bool, bool]:
    return (bool(elements(allowance, "cbc:MultiplierFactorNumeric")),
            bool(elements(allowance, "cbc:BaseAmount")))


@peppol("PEPPOL-EN16931-R041", "an allowance or charge with a percentage (BT-94, BT-101, "
                               "BT-138, BT-143) has a base amount")
def r041(root: At) -> Iterator[Failure]:
    for allowance in allowances(root):
        if shape(allowance) == (True, False):
            yield allowance.path, "it has none"


@peppol("PEPPOL-EN16931-R042", "an allowance or charge with a base amount (BT-93, BT-100, "
                               "BT-137, BT-142) has a percentage")
def r042(root: At) -> Iterator[Failure]:
    for allowance in allowances(root):
        if shape(allowance) == (False, True):
            yield allowance.path, "it has none"


def the_rest(root: At) -> List[At]:
    """The allowances and charges that the two rules above did not take: an
    element is asked the first rule of a pattern that fits it, and no other."""
    return [allowance for allowance in allowances(root)
            if shape(allowance) in ((True, True), (False, False))]


@peppol("PEPPOL-EN16931-R040", "an allowance's or charge's amount is its base amount times "
                               "its percentage, to within two cents")
def r040(root: At) -> Iterator[Failure]:
    for allowance in the_rest(root):
        if shape(allowance) != (True, True):
            continue
        expected = (number(allowance, "cbc:BaseAmount")
                    * number(allowance, "cbc:MultiplierFactorNumeric")) / 100
        amounts = elements(allowance, "cbc:Amount")
        if len(amounts) > 1:
            raise Incomputable("cbc:Amount occurs %d times where the rule takes one"
                               % len(amounts))
        # The amount is read as a double here, as the published test reads it.
        text = amounts[0].text if amounts else "0"
        if not (double_sum(text, "0.02") >= expected and double_sum(text, "-0.02") <= expected):
            yield allowance.path, "it is %s and they come to %s" % (
                normalize_space(text) if amounts else "not there", format(expected, "f"))


@peppol("PEPPOL-EN16931-R043", "an allowance or charge says which it is with `true` or "
                               "`false`")
def r043(root: At) -> Iterator[Failure]:
    for allowance in the_rest(root):
        if said(allowance, "cbc:ChargeIndicator") not in ("true", "false"):
            yield allowance.path, "it says %r" % said(allowance, "cbc:ChargeIndicator")


@peppol("PEPPOL-EN16931-R044", "the allowance on a price is an allowance (`false`)")
def r044(root: At) -> Iterator[Failure]:
    for allowance in contexts(root, "cac:Price/cac:AllowanceCharge"):
        if said(allowance, "cbc:ChargeIndicator") != "false":
            yield allowance.path, "it says %r" % said(allowance, "cbc:ChargeIndicator")


@peppol("PEPPOL-EN16931-R046", "a net price (BT-146) is the gross price (BT-148) less the "
                               "discount (BT-147)")
def r046(root: At) -> Iterator[Failure]:
    for allowance in contexts(root, "cac:Price/cac:AllowanceCharge"):
        if not elements(allowance, "cbc:BaseAmount") or allowance.parent is None:
            continue
        net = number(allowance.parent, "cbc:PriceAmount")
        gross, discount = number(allowance, "cbc:BaseAmount"), number(allowance, "cbc:Amount")
        if net is None or gross is None or discount is None or net != gross - discount:
            yield allowance.path, "the net price is %s, the gross %s and the discount %s" % (
                net, gross, discount)


# -- payment, currency, periods ------------------------------------------------------------

@peppol("PEPPOL-EN16931-R061", "a direct debit (payment means 49 or 59) has a mandate "
                               "reference (BT-89)")
def r061(root: At) -> Iterator[Failure]:
    for means in contexts(root, "cac:PaymentMeans"):
        if (said(means, "cbc:PaymentMeansCode") in ("49", "59")
                and not elements(means, "cac:PaymentMandate/cbc:ID")):
            yield means.path, "it has none"


AMOUNTS = ("cbc:Amount", "cbc:BaseAmount", "cbc:PriceAmount", "cbc:TaxableAmount",
           "cbc:LineExtensionAmount", "cbc:TaxExclusiveAmount", "cbc:TaxInclusiveAmount",
           "cbc:AllowanceTotalAmount", "cbc:ChargeTotalAmount", "cbc:PrepaidAmount",
           "cbc:PayableRoundingAmount", "cbc:PayableAmount")
TAX_AMOUNT, TAX_TOTAL, TAX_SUBTOTAL = (tag("cbc:TaxAmount"), tag("cac:TaxTotal"),
                                       tag("cac:TaxSubtotal"))


@peppol("PEPPOL-EN16931-R051", "every amount is in the invoice currency (BT-5), but the VAT "
                               "total in the accounting currency")
def r051(root: At) -> Iterator[Failure]:
    currencies = texts(elements(root, "cbc:DocumentCurrencyCode"))
    for at in named(root, "cbc:TaxAmount", *AMOUNTS):
        if at.node.tag == TAX_AMOUNT:
            # A VAT amount in a breakdown, or the total that has the breakdown.
            parent = at.parent
            if parent is None or not (parent.node.tag == TAX_SUBTOTAL or (
                    parent.node.tag == TAX_TOTAL and elements(parent, "cac:TaxSubtotal"))):
                continue
        if at.node.attributes.get("currencyID") not in currencies:
            yield at.path, "it is in %r" % at.node.attributes.get("currencyID", "")


def within_the_documents_period(identifier: str, name: str, what: str, after: bool) -> None:
    @peppol(identifier, "a line's period does not %s the document's (%s)" % (
        "start before" if after else "end after", what))
    def check(root: At) -> Iterator[Failure]:
        whole = elements(root, "cac:InvoicePeriod/%s" % name)
        if not whole:
            return
        for line in lines(root):
            for date in elements(line, "cac:InvoicePeriod/%s" % name):
                if len(whole) > 1:
                    raise Incomputable("the document has %d of %s" % (len(whole), name))
                mine, theirs = date_of(date.text, name), date_of(whole[0].text, name)
                if not (mine >= theirs if after else mine <= theirs):
                    yield date.path, "it is %s and the document's is %s" % (
                        normalize_space(date.text), normalize_space(whole[0].text))


within_the_documents_period("PEPPOL-EN16931-R110", "cbc:StartDate", "BT-134, BT-73", True)
within_the_documents_period("PEPPOL-EN16931-R111", "cbc:EndDate", "BT-135, BT-74", False)


@peppol("PEPPOL-EN16931-R080", "a credit note has at most one project reference (BT-11)")
def r080(root: At) -> Iterator[Failure]:
    if root.node.tag != CREDIT_NOTE:
        return
    found = [reference for reference in elements(root, "cac:AdditionalDocumentReference")
             if "50" in texts(elements(reference, "cbc:DocumentTypeCode"))]
    if len(found) > 1:
        yield found[1].path, "it has %d" % len(found)


# -- lines ------------------------------------------------------------------------------

def quantity_name(root: At) -> str:
    return "cbc:InvoicedQuantity" if root.node.tag == INVOICE else "cbc:CreditedQuantity"


@peppol("PEPPOL-EN16931-R120", "a line's net amount (BT-131) is its quantity times its price "
                               "for the base quantity, plus its charges, less its allowances, "
                               "to within two cents")
def r120(root: At) -> Iterator[Failure]:
    for line in contexts(root, "cac:InvoiceLine | cac:CreditNoteLine"):
        def or_else(path: str, otherwise: int) -> Decimal:
            found = number(line, path)
            return Decimal(otherwise) if found is None else found
        net = or_else("cbc:LineExtensionAmount", 0)
        quantity = or_else(quantity_name(root), 1)
        price = or_else("cac:Price/cbc:PriceAmount", 0)
        base = or_else("cac:Price/cbc:BaseQuantity", 1) or Decimal(1)

        def total(indicator: str) -> Decimal:
            # By the text of the indicator: `1` and `0` are neither.
            found = [a for a in elements(line, "cac:AllowanceCharge")
                     if said(a, "cbc:ChargeIndicator") == indicator]
            return cents(sum((decimal_of(amount.text, "cbc:Amount") for a in found
                              for amount in elements(a, "cbc:Amount")), Decimal(0)))
        expected = quantity * (price / base) + total("true") - total("false")
        if not (net + TWO_CENTS >= expected and net - TWO_CENTS <= expected):
            yield line.path, "it is %s and they come to %s" % (
                format(net, "f"), format(expected, "f"))


@peppol("PEPPOL-EN16931-R121", "a price's base quantity (BT-149) is more than nought")
def r121(root: At) -> Iterator[Failure]:
    for line in contexts(root, "cac:InvoiceLine | cac:CreditNoteLine"):
        base = number(line, "cac:Price/cbc:BaseQuantity")
        if base is not None and not base > 0:
            yield line.path, "it is %s" % base


@peppol("PEPPOL-EN16931-R100", "a line has at most one document reference")
def r100(root: At) -> Iterator[Failure]:
    for line in contexts(root, "cac:InvoiceLine | cac:CreditNoteLine"):
        found = elements(line, "cac:DocumentReference")
        if len(found) > 1:
            yield found[1].path, "it has %d" % len(found)


@peppol("PEPPOL-EN16931-R101", "a line's document reference is to an invoiced object (type "
                               "code 130)")
def r101(root: At) -> Iterator[Failure]:
    for line in contexts(root, "cac:InvoiceLine | cac:CreditNoteLine"):
        found = elements(line, "cac:DocumentReference")
        if found and "130" not in texts(elements(line, "cac:DocumentReference/cbc:DocumentTypeCode")):
            yield found[0].path, "it is not"


@peppol("PEPPOL-EN16931-R130", "a price's base quantity (BT-149) is in the unit of the "
                               "line's quantity (BT-130)")
def r130(root: At) -> Iterator[Failure]:
    for base in contexts(root, "cac:Price/cbc:BaseQuantity"):
        line = base.parent.parent if base.parent else None
        if "unitCode" not in base.node.attributes or line is None:
            continue
        if not (elements(line, "cbc:InvoicedQuantity") or elements(line, "cbc:CreditedQuantity")):
            continue
        units = [quantity.node.attributes.get("unitCode")
                 for quantity in elements(line, quantity_name(root))]
        if base.node.attributes["unitCode"] not in units:
            yield base.path, "it is in %r and the quantity in %r" % (
                base.node.attributes["unitCode"], units[0] if units else "")


# -- checksums, by the scheme of an identifier ---------------------------------------------

def digits(text: str) -> bool:
    return bool(re.fullmatch(r"[0-9]+", text))


def integer(text: str) -> bool:
    """`castable as xs:integer`."""
    return bool(re.fullmatch(r"\s*[+-]?[0-9]+\s*", text))


def gln(value: str) -> bool:
    """The last digit checks the rest, weighted 3 and 1 from the right."""
    body = [int(c) for c in reversed(value[:-1])]
    weighted = sum(digit * (3 if place % 2 == 0 else 1) for place, digit in enumerate(body))
    return (10 - weighted % 10) % 10 == int(value[-1])


def mod11(value: str) -> bool:
    """Weights 2 to 7 from the right; a remainder that would want a check
    digit of ten has no digit that fits."""
    body = [int(c) for c in reversed(value[:-1])]
    weighted = sum(digit * (place % 6 + 2) for place, digit in enumerate(body))
    return int(value) > 0 and (11 - weighted % 11) % 11 == int(value[-1])


def belgian(value: str) -> bool:
    return int(value[8:10]) == 97 - int(value[:8]) % 97


def luhn_total(value: str) -> int:
    """Every other digit from the left doubled and its digits added."""
    return sum(int("0246813579"[int(c)]) if place % 2 else int(c)
               for place, c in enumerate(value))


def swedish(value: str) -> bool:
    if not digits(value):
        return False
    body = value[:9]
    total = sum(int("0246813579"[int(c)]) if place % 2 == 0 else int(c)
                for place, c in enumerate(reversed(body)))
    return (10 - total % 10) % 10 == int(value[9:10] or "-1")


def australian(value: str) -> bool:
    weights = (10, 1, 3, 5, 7, 9, 11, 13, 15, 17, 19)
    return sum((int(c) - (1 if place == 0 else 0)) * weight
               for place, (c, weight) in enumerate(zip(value, weights))) % 89 == 0


LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"


def only(text: str, allowed: str) -> bool:
    return all(c in allowed for c in text)


def codice_fiscale(value: str) -> bool:
    if len(value) == 11:
        return integer(value)
    return (len(value) == 16 and only(value[:6], LETTERS) and integer(value[6:8])
            and only(value[8:9], LETTERS) and integer(value[9:11]) and integer(value[14:15])
            and only(value[15:16], LETTERS))


def partita_iva(value: str) -> bool:
    """Asked only of one that starts `IT`: eleven digits that add up."""
    if value[:2] not in ("IT", "it"):
        return True
    code = value[2:]
    if len(code) != 11:
        return False
    if not integer(code):
        return False
    if not digits(code):
        raise Incomputable("%r has a sign or a space in it" % value)
    return luhn_total(code) % 10 == 0


def danish(value: str, bare: bool) -> bool:
    prefixed = len(value) == 10 and value[:2] == "DK" and only(value[2:10], "1234567890")
    return prefixed or (bare and len(value) == 8 and only(value, "1234567890"))


def pattern(expression: str) -> Callable[[str], bool]:
    return lambda value: bool(re.fullmatch(expression, value))


# Scheme, rule, what it asks, the test, and whether the text is trimmed first.
SCHEMES = (
    ("0088", "R040", "a GLN is digits with a right check digit",
     lambda v: digits(v) and gln(v), True),
    ("0192", "R041", "a Norwegian organisation number is nine digits with a right check digit",
     lambda v: bool(re.fullmatch(r"[0-9]{9}", v)) and mod11(v), True),
    ("0184", "R042", "a Danish CVR number is eight digits, with or without `DK` before them",
     lambda v: danish(v, True), False),
    ("0096", "R052", "a Danish P number is ten digits",
     lambda v: len(v) == 10 and only(v, "1234567890"), False),
    ("0198", "R053", "a Danish SE number is `DK` and eight digits",
     lambda v: danish(v, False), False),
    ("0208", "R043", "a Belgian enterprise number is ten digits with right check digits",
     lambda v: bool(re.fullmatch(r"[0-9]{10}", v)) and belgian(v), True),
    ("0201", "R044", "an Italian IPA code is six letters or digits",
     lambda v: len(v) == 6 and only(v, LETTERS + "0123456789"), True),
    ("0210", "R045", "an Italian tax code is sixteen characters of the right kinds, or eleven "
                     "digits", codice_fiscale, True),
    ("0211", "R047", "an Italian VAT number is `IT` and eleven digits that add up",
     partita_iva, True),
    ("0007", "R049", "a Swedish organisation number is ten digits with a right check digit",
     lambda v: len(v) == 10 and swedish(v), True),
    ("0151", "R050", "an Australian business number is eleven digits that add up",
     lambda v: bool(re.fullmatch(r"[0-9]{11}", v)) and australian(v), True),
    ("0106", "R054", "a Dutch chamber of commerce number is eight digits",
     pattern(r"[0-9]{8}"), True),
    ("0190", "R055", "a Dutch OIN is twenty digits", pattern(r"[0-9]{20}"), True),
    ("9944", "R056-1", "a Dutch VAT number is `NL`, nine digits, `B` and two digits",
     pattern(r"NL[0-9]{9}B[0-9]{2}"), True),
    ("0217", "R057", "a Dutch KvK establishment number is twelve digits",
     pattern(r"[0-9]{12}"), True),
)
BY_SCHEME = {scheme for scheme, *_rest in SCHEMES}
PARTY_IDENTIFICATION, PARTY_TAX_SCHEME = tag("cac:PartyIdentification"), tag("cac:PartyTaxScheme")
ENDPOINT, IDENTIFIER, COMPANY = tag("cbc:EndpointID"), tag("cbc:ID"), tag("cbc:CompanyID")


def identifiers(root: At, scheme: str) -> List[At]:
    """An electronic address, a party identifier or a company identifier
    under a scheme, wherever it is."""
    return [at for at in root.everything()
            if at.node.attributes.get("schemeID") == scheme and (
                at.node.tag in (ENDPOINT, COMPANY) or (
                    at.node.tag == IDENTIFIER and at.parent is not None
                    and at.parent.node.tag == PARTY_IDENTIFICATION))]


def by_scheme(scheme: str, short: str, about: str, test: Callable[[str], bool],
              trimmed: bool, register: Callable = peppol) -> None:
    """A rule on an identifier by its scheme. Peppol asks these of every one
    of its documents, an invoice or a response to one, so `register` says
    which layer's rule this is."""
    @register("PEPPOL-COMMON-%s" % short, "%s (scheme %s)" % (about, scheme))
    def check(root: At) -> Iterator[Failure]:
        for at in identifiers(root, scheme):
            if not test(normalize_space(at.text) if trimmed else at.text):
                yield at.path, "%r is not" % at.text


for _scheme in SCHEMES:
    by_scheme(*_scheme)


def italian_address(root: At) -> Iterator[Failure]:
    for at in named(root, "cbc:EndpointID"):
        if (at.node.attributes.get("schemeID") == "9907"
                and not codice_fiscale(normalize_space(at.text))):
            yield at.path, "%r is not" % at.text


def dutch_vat(root: At) -> Iterator[Failure]:
    for at in named(root, "cbc:CompanyID"):
        if at.parent is None or at.parent.node.tag != PARTY_TAX_SCHEME:
            continue
        if said(at.parent, "cac:TaxScheme/cbc:ID") != "VAT":
            continue
        # An identifier that names a scheme with a rule of its own was asked
        # that rule, which is earlier in the pattern, and is asked no other.
        if at.node.attributes.get("schemeID") in BY_SCHEME:
            continue
        value = normalize_space(at.text)
        if value.startswith("NL") and not re.fullmatch(r"NL[0-9]{9}B[0-9]{2}", value):
            yield at.path, "%r is not" % at.text


# Two more by scheme, which like the fifteen above are asked of a response too.
OTHERS = (
    ("PEPPOL-COMMON-R046", "an electronic address under scheme 9907 is an Italian tax code: "
                           "sixteen characters of the right kinds, or eleven digits",
     italian_address),
    ("PEPPOL-COMMON-R056-2", "a VAT identifier that starts `NL` is `NL`, nine digits, `B` and "
                             "two digits", dutch_vat),
)
for _identifier, _about, _check in OTHERS:
    peppol(_identifier, _about)(_check)


# -- code lists, type codes, dates -----------------------------------------------------------

@peppol("PEPPOL-EN16931-CL001", "an attachment's MIME type (BT-125) is one of the six Peppol "
                                "allows")
def cl001(root: At) -> Iterator[Failure]:
    for at in named(root, "cbc:EmbeddedDocumentBinaryObject"):
        if "mimeCode" in at.node.attributes and at.node.attributes["mimeCode"] not in MIME_TYPES:
            yield at.path, "%r is not" % at.node.attributes["mimeCode"]


def reason_coded(identifier: str, indicator: str, allowed: frozenset, what: str) -> None:
    @peppol(identifier, "%s reason code is in its code list" % what)
    def check(root: At) -> Iterator[Failure]:
        for at in named(root, "cac:AllowanceCharge"):
            # Picked by the indicator as written, not trimmed.
            if indicator not in texts(elements(at, "cbc:ChargeIndicator")):
                continue
            for code in elements(at, "cbc:AllowanceChargeReasonCode"):
                if normalize_space(code.text) not in allowed:
                    yield code.path, "%r is not" % code.text


reason_coded("PEPPOL-EN16931-CL002", "false", ALLOWANCE_REASONS, "an allowance's")
reason_coded("PEPPOL-EN16931-CL003", "true", CHARGE_REASONS, "a charge's")


@peppol("PEPPOL-EN16931-CL006", "the VAT point date code (BT-8) is 3, 35 or 432")
def cl006(root: At) -> Iterator[Failure]:
    for at in contexts(root, "cac:InvoicePeriod/cbc:DescriptionCode"):
        if normalize_space(at.text) not in VAT_POINT_CODES:
            yield at.path, "%r is not" % at.text


@peppol("PEPPOL-EN16931-CL007", "every amount's currency is an ISO 4217 code")
def cl007(root: At) -> Iterator[Failure]:
    for at in named(root, "cbc:TaxAmount", *AMOUNTS):
        if at.node.attributes.get("currencyID") not in CURRENCIES:
            yield at.path, "%r is not" % at.node.attributes.get("currencyID", "")


@peppol("PEPPOL-EN16931-CL008", "the scheme of an electronic address (BT-34, BT-49) is one "
                                "Peppol has")
def cl008(root: At) -> Iterator[Failure]:
    for at in named(root, "cbc:EndpointID"):
        if "schemeID" in at.node.attributes and at.node.attributes["schemeID"] not in ADDRESS_SCHEMES:
            yield at.path, "%r is not" % at.node.attributes["schemeID"]


def type_coded(identifier: str, name: str, allowed: frozenset, what: str) -> None:
    @peppol(identifier, "%s type code (BT-3) is one Peppol allows" % what)
    def check(root: At) -> Iterator[Failure]:
        if profile(root) == "Unknown":
            return
        for at in named(root, name):
            if normalize_space(at.text) not in allowed:
                yield at.path, "%r is not" % at.text


type_coded("PEPPOL-EN16931-P0100", "cbc:InvoiceTypeCode", INVOICE_TYPES, "an invoice's")
type_coded("PEPPOL-EN16931-P0101", "cbc:CreditNoteTypeCode", CREDIT_NOTE_TYPES, "a credit note's")


@peppol("PEPPOL-EN16931-P0112", "the invoice type codes 326 and 384 are used only between a "
                                "seller and a buyer both in Germany")
def p0112(root: At) -> Iterator[Failure]:
    for at in named(root, "cbc:InvoiceTypeCode"):
        if normalize_space(at.text) in ("326", "384") and not both_german(root):
            yield at.path, "it is %s" % normalize_space(at.text)


def exempt_as(identifier: str, reason: str, category: str) -> None:
    @peppol(identifier, "a VAT category whose exemption reason code is %s is the category %s"
            % (reason, category))
    def check(root: At) -> Iterator[Failure]:
        for at in named(root, "cac:TaxCategory"):
            reasons = elements(at, "cbc:TaxExemptionReasonCode")
            if len(reasons) > 1:
                raise Incomputable("a VAT category has %d exemption reason codes" % len(reasons))
            if reasons and reasons[0].text.upper() == reason and said(at, "cbc:ID") != category:
                yield at.path, "it is %r" % said(at, "cbc:ID")


for _number, _reason, _category in (("04", "G", "G"), ("05", "O", "O"), ("06", "IC", "K"),
                                    ("07", "AE", "AE"), ("08", "D", "E"), ("09", "F", "E"),
                                    ("10", "I", "E"), ("11", "J", "E")):
    exempt_as("PEPPOL-EN16931-P01%s" % _number, "VATEX-EU-%s" % _reason, _category)

DATES = ("cbc:IssueDate", "cbc:DueDate", "cbc:TaxPointDate", "cbc:StartDate", "cbc:EndDate",
         "cbc:ActualDeliveryDate")


@peppol("PEPPOL-EN16931-F001", "a date is ten characters, `YYYY-MM-DD`")
def f001(root: At) -> Iterator[Failure]:
    for at in named(root, *DATES):
        try:
            well_formed = len(at.text) == 10 and date_of(at.text) is not None
        except Incomputable:
            well_formed = False
        if not well_formed:
            yield at.path, "it is %r" % at.text
