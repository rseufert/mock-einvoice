"""Peppol BIS Billing 3.0: the rules for a seller in one of seven countries.

Denmark 14, Greece 19, Iceland 10, Italy 4, the Netherlands 9, Norway 2 and
Sweden 13: 71 rules, 61 fatal. Germany's are in `peppol_de.py`.

Each set is asked only of a document from its country, and the sets do not
agree on what that means. `seller_country` and the functions after it are the
five ways a document is taken to be from somewhere, and each rule below says
which it goes by.

Nothing here is copied from Peppol's rule file, which may not be
redistributed. The rules are written from reading it and its tests.

What the published tests say that one might not expect
------------------------------------------------------
- **Where the seller is, is first where its VAT identifier says.** For Norway,
  Italy and Greece the seller's country is the first two letters of its VAT
  identifier, then of its tax representative's, and only then the country of
  its address. A seller in Oslo with a Swedish VAT number is not Norwegian.
- **Denmark, Iceland and Sweden compare the country as written.** `dk` is not
  Denmark and ` DK ` is not either. The Netherlands takes both.
- **Most Danish rules are for a Danish buyer too**, and the seven about how to
  pay are asked of an invoice only, not of a credit note.
- **A Greek tax number is its first nine characters.** The check is made of
  those, whatever follows them (`GR-R-003`, `GR-R-006`).
- **An Icelandic final due date is compared as text** (`IS-R-010`), and a
  credit note that has one always fails `IS-R-009`: the rule looks for the due
  date where an invoice has it, and a credit note has no such element.
- **A Dutch credit note that takes money from the buyer needs a means of
  payment, and one that gives it back does not** (`NL-R-007`); for an invoice
  it is the other way round.
- **Two Swedish rules ask nothing** (`SE-R-011`, `SE-R-012`): a means of
  payment they are asked of fails them by being there.

Where this departs from the published tests
-------------------------------------------
- **Iceland has no published unit tests.** Its ten rules are held only to the
  tests of this project, which were written from the same reading as the
  rules. Say so when one of them surprises you.
- **Order of evaluation.** Where a published test would end in an XPath error
  in one half and be decided by the other, XPath leaves which happens to the
  implementation. Here the halves are taken left to right.
"""
from __future__ import annotations

import functools
import re
from typing import Callable, Iterator, List, Optional

from . import Failure, rule
from .calculation import Incomputable, date_of, normalize_space
from .peppol import (BUYER, COUNTRY, CREDIT_NOTE, INVOICE, SELLER, lines, mod11, named, number,
                     said, swedish)
from .tree import At, contexts, elements

peppol = functools.partial(rule, "peppol", over="tree")

REPRESENTATIVE = "cac:TaxRepresentativeParty"
TAX_SCHEME, TAX_ID = "cac:PartyTaxScheme", "cac:TaxScheme/cbc:ID"
LEGAL_ID = "cac:PartyLegalEntity/cbc:CompanyID"
ADDRESS = "cac:PostalAddress"
# `number('...')`: what XPath reads as a double.
NUMBER = re.compile(r"[+-]?([0-9]+(\.[0-9]*)?|\.[0-9]+)([eE][+-]?[0-9]+)?|-?INF")


# -- reading the elements ---------------------------------------------------------

def one(at: At, path: str) -> Optional[At]:
    """The element a path finds, where a rule takes one: None if it is not
    there, an XPath error if it is there twice."""
    found = elements(at, path)
    if len(found) > 1:
        raise Incomputable("%s occurs %d times where the rule takes one" % (path, len(found)))
    return found[0] if found else None


def text(at: At, path: str) -> str:
    """`string(a/b)`: the text as written, "" if it is not there."""
    found = one(at, path)
    return found.text if found is not None else ""


def scheme(at: At, path: str) -> str:
    """`normalize-space(a/b/@schemeID)`."""
    found = one(at, path)
    return normalize_space(found.node.attributes.get("schemeID", "")) if found is not None else ""


def numeric(value: str) -> bool:
    """`string(number(x)) != 'NaN'`."""
    return bool(NUMBER.fullmatch(normalize_space(value)))


def as_number(value: str) -> Optional[float]:
    """`number(x)`: None where it is not a number, which compares false."""
    trimmed = normalize_space(value)
    if not NUMBER.fullmatch(trimmed):
        return None
    return float(trimmed.replace("INF", "inf"))


def vat_identifiers(party: Optional[At], exact: bool) -> List[At]:
    """A party's VAT identifiers. `exact` is whether its scheme must say
    `VAT` to the letter, or may have space around it: the rules differ."""
    if party is None:
        return []
    return [company for registration in elements(party, TAX_SCHEME)
            if any((found.text if exact else normalize_space(found.text)) == "VAT"
                   for found in elements(registration, TAX_ID))
            for company in elements(registration, "cbc:CompanyID")]


# -- where a document is from ---------------------------------------------------------

def prefix(root: At, party: str) -> str:
    """The first two letters of a party's VAT identifier, "" if it has none."""
    found = vat_identifiers(one(root, party), exact=True)
    starts = [company.text[:2] for company in found]
    if len(starts) > 1:
        raise Incomputable("%s has %d VAT identifiers where the rule takes one"
                           % (party, len(starts)))
    return starts[0] if starts else ""


def country(root: At, *parties: str) -> str:
    """The country of the first of these that says: a party by the start of
    its VAT identifier, or an address (a path ending in the country)."""
    for party in parties:
        found = text(root, party) if party.endswith(COUNTRY) else prefix(root, party)
        if found:
            return normalize_space(found).upper()
    return "XX"


def seller_country(root: At) -> str:
    """By the seller's VAT identifier, then its tax representative's, then
    the seller's address. Norway, Italy and Greece go by this."""
    return country(root, SELLER, REPRESENTATIVE, "%s/%s" % (SELLER, COUNTRY))


def buyer_country(root: At) -> str:
    return country(root, BUYER, "%s/%s" % (BUYER, COUNTRY))


def written(root: At, party: str) -> str:
    """The country of a party's address exactly as written. Denmark and
    Iceland go by this."""
    return text(root, "%s/%s" % (party, COUNTRY))


def address_is(root: At, party: str, code: str) -> bool:
    """Whether a party's address names a country, however it is written. The
    Netherlands goes by this."""
    return normalize_space(text(root, "%s/%s" % (party, COUNTRY))).upper() == code


def greek_seller(root: At) -> bool:
    return seller_country(root) in ("GR", "EL")


def greek_both(root: At) -> bool:
    return greek_seller(root) and buyer_country(root) in ("GR", "EL")


def greek_address(root: At) -> bool:
    return greek_seller(root) and any(
        at.text == "GR" for at in elements(root, "%s/%s" % (SELLER, COUNTRY)))


def asked(within: Callable[[At], bool]) -> Callable:
    """Asked only of a document `within` says is one of the set's."""
    def gate(check):
        @functools.wraps(check)
        def gated(root: At) -> Iterator[Failure]:
            if within(root):
                yield from check(root)
        return gated
    return gate


def national(identifier: str, about: str, within: Callable[[At], bool]) -> Callable:
    return lambda check: peppol(identifier, about)(asked(within)(check))


def lacking(address: At, *names: str) -> List[str]:
    """Which of these an address does not have."""
    return [name for name in names if not elements(address, name)]


# -- Norway --------------------------------------------------------------------------------

norway = functools.partial(national, within=lambda root: seller_country(root) == "NO")


@norway("NO-R-002", "a Norwegian seller's tax registration (BT-32) says `Foretaksregisteret`")
def no_r_002(root: At) -> Iterator[Failure]:
    for party in contexts(root, SELLER):
        registered = [company for registration in elements(party, TAX_SCHEME)
                      if said(registration, TAX_ID) == "TAX"
                      for company in elements(registration, "cbc:CompanyID")]
        if len(registered) > 1:
            raise Incomputable("the seller has %d tax registrations where the rule takes one"
                               % len(registered))
        if not registered or normalize_space(registered[0].text) != "Foretaksregisteret":
            yield party.path, ("it says %r" % registered[0].text if registered
                               else "it has none")


@norway("NO-R-001", "a Norwegian seller's VAT identifier (BT-31) that starts `NO` is `NO`, a "
                    "valid organisation number of nine digits, and `MVA`")
def no_r_001(root: At) -> Iterator[Failure]:
    for party in contexts(root, SELLER):
        found = vat_identifiers(party, exact=False)
        if not any(company.text[:2] == "NO" for company in found):
            continue
        if len(found) > 1:
            raise Incomputable("the seller has %d VAT identifiers where the rule takes one"
                               % len(found))
        value = found[0].text
        if not (re.fullmatch(r"[0-9]{9}MVA", value[2:]) and mod11(value[2:11])):
            yield found[0].path, "%r is not" % value


# -- Denmark ---------------------------------------------------------------------------------

def danish_seller(root: At) -> bool:
    return written(root, SELLER) == "DK"


def danish_both(root: At) -> bool:
    return danish_seller(root) and written(root, BUYER) == "DK"


def danish_invoice(root: At) -> bool:
    return root.node.tag == INVOICE and danish_both(root)


denmark = functools.partial(national, within=danish_seller)
denmark_both = functools.partial(national, within=danish_both)
denmark_paying = functools.partial(national, within=danish_invoice)
DANISH_MEANS = " 1 10 31 42 48 49 50 58 59 93 97 "
UNSPSC_VERSIONS = ("19.05.01", "19.0501", "26.08.01", "26.0801")


@denmark("DK-R-002", "a Danish seller gives its legal registration, the CVR number (BT-30)")
def dk_r_002(root: At) -> Iterator[Failure]:
    if not normalize_space(text(root, "%s/%s" % (SELLER, LEGAL_ID))):
        yield root.path, "it gives none"


@denmark("DK-R-014", "a Danish seller's legal registration (BT-30) is under scheme `0184`")
def dk_r_014(root: At) -> Iterator[Failure]:
    path = "%s/%s" % (SELLER, LEGAL_ID)
    if elements(root, path) and scheme(root, path) != "0184":
        yield one(root, path).path, "its scheme is %r" % scheme(root, path)


@denmark("DK-R-016", "a Danish seller's credit note to a Danish buyer does not have a "
                     "negative amount due (BT-115)")
def dk_r_016(root: At) -> Iterator[Failure]:
    if root.node.tag != CREDIT_NOTE or written(root, BUYER) != "DK":
        return
    due = one(root, "cac:LegalMonetaryTotal/cbc:PayableAmount")
    amount = as_number(due.text) if due is not None else None
    if amount is not None and amount < 0:
        yield due.path, "it is %s" % normalize_space(due.text)


@denmark_both("DK-R-013", "between a Danish seller and a Danish buyer, an identifier of "
                          "either (BT-29, BT-46) names its scheme")
def dk_r_013(root: At) -> Iterator[Failure]:
    for party in (SELLER, BUYER):
        for identification in elements(root, "%s/cac:PartyIdentification" % party):
            if elements(identification, "cbc:ID") and not scheme(identification, "cbc:ID"):
                yield identification.path, "it names none"


def paying(identifier: str, about: str) -> Callable:
    """A rule asked of each means of payment of a Danish invoice to a Danish
    buyer: the check is handed the means of payment and its code as written."""
    def register(check):
        @denmark_paying(identifier, about)
        def each(root: At) -> Iterator[Failure]:
            for means in elements(root, "cac:PaymentMeans"):
                yield from check(means, text(means, "cbc:PaymentMeansCode"))
        return check
    return register


def filled(at: At, path: str) -> bool:
    return bool(normalize_space(text(at, path)))


@paying("DK-R-005", "between a Danish seller and a Danish buyer, an invoice's means of "
                    "payment (BT-81) is one of 1, 10, 31, 42, 48, 49, 50, 58, 59, 93 and 97")
def dk_r_005(means: At, code: str) -> Iterator[Failure]:
    if " %s " % code not in DANISH_MEANS:
        yield means.path, "it is %r" % code


@paying("DK-R-006", "a Danish credit transfer (means 31 or 42) names the account (BT-84) and "
                    "the bank's registration number (BT-86)")
def dk_r_006(means: At, code: str) -> Iterator[Failure]:
    account = "cac:PayeeFinancialAccount"
    if code in ("31", "42") and not (filled(means, account + "/cbc:ID") and filled(
            means, account + "/cac:FinancialInstitutionBranch/cbc:ID")):
        yield means.path, "it does not name both"


@paying("DK-R-007", "a Danish direct debit (means 49) names the mandate (BT-89) and the "
                    "account debited (BT-91)")
def dk_r_007(means: At, code: str) -> Iterator[Failure]:
    mandate = "cac:PaymentMandate"
    if code == "49" and not (filled(means, mandate + "/cbc:ID") and filled(
            means, mandate + "/cac:PayerFinancialAccount/cbc:ID")):
        yield means.path, "it does not name both"


@paying("DK-R-008", "a Danish giro payment (means 50) has a payment identifier (BT-83) that "
                    "starts `01#`, `04#` or `15#`, and a giro account (BT-84) of seven or "
                    "eight digits")
def dk_r_008(means: At, code: str) -> Iterator[Failure]:
    if code == "50" and not (
            text(means, "cbc:PaymentID")[:3] in ("01#", "04#", "15#")
            and re.fullmatch(r"[0-9]{7,8}", text(means, "cac:PayeeFinancialAccount/cbc:ID"))):
        yield means.path, "it has not"


@paying("DK-R-009", "a Danish giro payment identifier (BT-83) that starts `04#` or `15#` is "
                    "nineteen characters: the three and sixteen digits")
def dk_r_009(means: At, code: str) -> Iterator[Failure]:
    identifier = text(means, "cbc:PaymentID")
    if code == "50" and identifier[:3] in ("04#", "15#") and len(identifier) != 19:
        yield means.path, "%r is %d" % (identifier, len(identifier))


@paying("DK-R-010", "a Danish FIK payment (means 93) has a payment identifier (BT-83) that "
                    "starts `71#`, `73#` or `75#`, and a creditor account (BT-84) of eight "
                    "characters")
def dk_r_010(means: At, code: str) -> Iterator[Failure]:
    if code == "93" and not (
            text(means, "cbc:PaymentID")[:3] in ("71#", "73#", "75#")
            and len(text(means, "cac:PayeeFinancialAccount/cbc:ID")) == 8):
        yield means.path, "it has not"


@paying("DK-R-011", "a Danish FIK payment identifier (BT-83) that starts `71#` or `75#` is "
                    "eighteen or nineteen characters: the three and fifteen or sixteen digits")
def dk_r_011(means: At, code: str) -> Iterator[Failure]:
    identifier = text(means, "cbc:PaymentID")
    if code == "93" and identifier[:3] in ("71#", "75#") and len(identifier) not in (18, 19):
        yield means.path, "%r is %d" % (identifier, len(identifier))


@denmark_both("DK-R-017", "a Danish buyer's legal registration (BT-47), from a Danish "
                          "seller, is under scheme `0184`")
def dk_r_017(root: At) -> Iterator[Failure]:
    for party in elements(root, BUYER):
        if elements(party, LEGAL_ID) and scheme(party, LEGAL_ID) != "0184":
            yield party.path, "its scheme is %r" % scheme(party, LEGAL_ID)


@denmark_both("DK-R-003", "between a Danish seller and a Danish buyer, a line's UNSPSC "
                          "classification (BT-158, list `TST`) is of version 19.05.01 or "
                          "26.08.01")
def dk_r_003(root: At) -> Iterator[Failure]:
    for line in lines(root):
        found = elements(line, "cac:Item/cac:CommodityClassification/cbc:ItemClassificationCode")
        if (any(code.node.attributes.get("listID") == "TST" for code in found)
                and not any(code.node.attributes.get("listVersionID") in UNSPSC_VERSIONS
                            for code in found)):
            yield line.path, "none of its classifications names one"


@denmark_both("DK-R-004", "between a Danish seller and a Danish buyer, a charge or allowance "
                          "with reason code `ZZZ` (a tax that is not VAT) has as its reason "
                          "four digits, or text with a `#` inside it")
def dk_r_004(root: At) -> Iterator[Failure]:
    for allowance in named(root, "cac:AllowanceCharge"):
        if not any(code.text == "ZZZ"
                   for code in elements(allowance, "cbc:AllowanceChargeReasonCode")):
            continue
        reason = one(allowance, "cbc:AllowanceChargeReason")
        words = reason.text if reason is not None else ""
        amount = as_number(words)
        digits = (len(normalize_space(words)) == 4 and amount is not None
                  and 0 <= amount <= 9999)
        hashed = "#" in words and not words.startswith("#") and not words.endswith("#")
        if not (digits or hashed):
            yield allowance.path, ("its reason is %r" % words if reason is not None
                                   else "it has no reason")


# -- Italy -----------------------------------------------------------------------------------

italy = functools.partial(national, within=lambda root: seller_country(root) == "IT")


@italy("IT-R-001", "an Italian seller's tax registration (BT-32) is eleven to sixteen "
                   "capital letters and digits")
def it_r_001(root: At) -> Iterator[Failure]:
    for party in contexts(root, SELLER):
        for registration in elements(party, TAX_SCHEME):
            if said(registration, TAX_ID) == "VAT":
                continue
            value = said(registration, "cbc:CompanyID")
            if not re.fullmatch(r"[A-Z0-9]{11,16}", value):
                yield registration.path, "it is %r" % value


def italian_address(identifier: str, name: str, what: str) -> None:
    @italy(identifier, "an Italian seller's address has %s" % what)
    def check(root: At) -> Iterator[Failure]:
        for party in contexts(root, SELLER):
            if not elements(party, "%s/%s" % (ADDRESS, name)):
                yield party.path, "it has none"


italian_address("IT-R-002", "cbc:StreetName", "a first line (BT-35)")
italian_address("IT-R-003", "cbc:CityName", "a city (BT-37)")
italian_address("IT-R-004", "cbc:PostalZone", "a post code (BT-38)")


# -- Sweden ----------------------------------------------------------------------------------

def swedish_address(party: At) -> bool:
    return any(at.text == "SE" for at in elements(party, COUNTRY))


def swedish_vat(party: At) -> bool:
    """In Sweden by its address and by a VAT identifier that starts `SE`."""
    return swedish_address(party) and any(
        company.text[:2] == "SE" for company in vat_identifiers(party, exact=True))


def anywhere(root: At, party: str, test: Callable[[At], bool]) -> bool:
    return any(test(found) for found in contexts(root, party))


sweden = functools.partial(
    national, within=lambda root: anywhere(root, SELLER, swedish_address))
sweden_vat = functools.partial(
    national, within=lambda root: anywhere(root, SELLER, swedish_vat))


def the_swedish_vat(party: At) -> str:
    found = vat_identifiers(party, exact=True)
    if len(found) > 1:
        raise Incomputable("the seller has %d VAT identifiers where the rule takes one"
                           % len(found))
    return found[0].text


@sweden_vat("SE-R-001", "a Swedish seller's VAT identifier (BT-31) is fourteen characters")
def se_r_001(root: At) -> Iterator[Failure]:
    for party in contexts(root, SELLER):
        if swedish_vat(party) and len(normalize_space(the_swedish_vat(party))) != 14:
            yield party.path, "%r is %d" % (the_swedish_vat(party),
                                            len(normalize_space(the_swedish_vat(party))))


@sweden_vat("SE-R-002", "a Swedish seller's VAT identifier (BT-31) is a number after `SE`")
def se_r_002(root: At) -> Iterator[Failure]:
    for party in contexts(root, SELLER):
        if swedish_vat(party) and not numeric(the_swedish_vat(party)[2:14]):
            yield party.path, "%r is not" % the_swedish_vat(party)


def organisation_number(identifier: str, about: str, test: Callable[[str], bool]) -> None:
    @sweden(identifier, about)
    def check(root: At) -> Iterator[Failure]:
        for party in contexts(root, SELLER):
            if not swedish_address(party):
                continue
            for entity in elements(party, "cac:PartyLegalEntity"):
                if elements(entity, "cbc:CompanyID") and not test(text(entity, "cbc:CompanyID")):
                    yield entity.path, "%r is not" % text(entity, "cbc:CompanyID")


organisation_number("SE-R-003", "a Swedish seller's organisation number (BT-30) is a number",
                    numeric)
organisation_number("SE-R-004", "a Swedish seller's organisation number (BT-30) is ten "
                                "characters", lambda value: len(normalize_space(value)) == 10)
organisation_number("SE-R-013", "the last digit of a Swedish seller's organisation number "
                                "(BT-30) checks the nine before it",
                    lambda value: swedish(normalize_space(value)))


@sweden("SE-R-005", "a Swedish seller with an organisation number that gives a tax "
                    "registration (BT-32) says `Godkänd för F-skatt`")
def se_r_005(root: At) -> Iterator[Failure]:
    for party in contexts(root, SELLER):
        if not (swedish_address(party) and elements(party, LEGAL_ID)):
            continue
        for registration in elements(party, TAX_SCHEME):
            if normalize_space(text(registration, TAX_ID).upper()) == "VAT":
                continue
            for company in elements(registration, "cbc:CompanyID"):
                if normalize_space(company.text.upper()) != "GODKÄND FÖR F-SKATT":
                    yield company.path, "it says %r" % company.text


@sweden_vat("SE-R-006", "a Swedish seller's standard rate of VAT (category `S`) is 6, 12 or "
                        "25 per cent")
def se_r_006(root: At) -> Iterator[Failure]:
    for category in named(root, "cac:TaxCategory", "cac:ClassifiedTaxCategory"):
        if not any(found.text == "S" for found in elements(category, "cbc:ID")):
            continue
        rate = as_number(text(category, "cbc:Percent"))
        if rate not in (25, 12, 6):
            yield category.path, "it is %r" % text(category, "cbc:Percent")


def giro_accounts(root: At, giro: str) -> List[At]:
    """The accounts paid into by credit transfer (means 30) under a giro."""
    return [account for means in named(root, "cac:PaymentMeans")
            if said(means, "cbc:PaymentMeansCode") == "30" and said(
                means, "cac:PayeeFinancialAccount/cac:FinancialInstitutionBranch/cbc:ID") == giro
            for account in elements(means, "cac:PayeeFinancialAccount/cbc:ID")]


def giro(identifier: str, name: str, about: str, test: Callable[[str], bool]) -> None:
    @sweden(identifier, "a Swedish seller's %s account (BT-84) %s" % (name.capitalize(), about))
    def check(root: At) -> Iterator[Failure]:
        for account in giro_accounts(root, "SE:%s" % name.upper()):
            if not test(normalize_space(account.text)):
                yield account.path, "%r is not" % account.text


giro("SE-R-007", "plusgiro", "is a number", numeric)
giro("SE-R-010", "plusgiro", "is two to eight characters", lambda value: 2 <= len(value) <= 8)
giro("SE-R-008", "bankgiro", "is a number", numeric)
giro("SE-R-009", "bankgiro", "is seven or eight characters", lambda value: len(value) in (7, 8))


def paid_by(root: At, *codes: str) -> List[At]:
    return [means for means in named(root, "cac:PaymentMeans")
            if any(code.text in codes for code in elements(means, "cbc:PaymentMeansCode"))]


@sweden("SE-R-011", "a Swedish seller does not use means of payment 50 or 56 for a bankgiro "
                    "or a plusgiro: it is 30, with `SE:BANKGIRO` or `SE:PLUSGIRO` as the "
                    "bank (BT-86)")
def se_r_011(root: At) -> Iterator[Failure]:
    for means in paid_by(root, "50", "56"):
        yield means.path, "it is %s" % text(means, "cbc:PaymentMeansCode")


@sweden("SE-R-012", "between a Swedish seller and a Swedish buyer a credit transfer is "
                    "means of payment 30, not 31")
def se_r_012(root: At) -> Iterator[Failure]:
    if anywhere(root, BUYER, swedish_address):
        for means in paid_by(root, "31"):
            yield means.path, "it is 31"


# -- Greece ----------------------------------------------------------------------------------

greece = functools.partial(national, within=greek_seller)
greece_both = functools.partial(national, within=greek_both)
greece_address = functools.partial(national, within=greek_address)
GREEK_TYPES = ("1.1", "1.6", "2.1", "2.4", "5.1", "5.2")
GREEK_DATE = re.compile(r"(0?[1-9]|[12][0-9]|3[01])[-\\/ ]?(0?[1-9]|1[0-2])[-\\/ ]?"
                        r"(19|20)[0-9]{2}")
MARK, INVOICE_URL = "##M.AR.K##", "##INVOICE|URL##"


def tin(value: str) -> bool:
    """A Greek tax number: of its first nine characters, all digits, the
    ninth checks the eight before it. What follows them is not looked at."""
    first = value[:9]
    if len(first) < 9 or not re.fullmatch(r"[0-9]{9}", first):
        return False
    total = sum(int(digit) * 2 ** (8 - place) for place, digit in enumerate(first[:8]))
    return total % 11 % 10 == int(first[8])


def segments(root: At) -> Iterator[tuple]:
    """The document's number and its parts between `|`: of nothing, none."""
    for number_ in elements(root, "cbc:ID"):
        yield number_, (number_.text.split("|") if number_.text else [])


def segment(identifier: str, about: str, place: int,
            test: Callable[[At, str], bool]) -> None:
    """A rule about one part of a Greek seller's invoice number. A part that
    is not there fails it."""
    @greece(identifier, "a Greek seller's invoice number (BT-1) %s" % about)
    def check(root: At) -> Iterator[Failure]:
        for number_, parts in segments(root):
            part = parts[place - 1] if len(parts) >= place else None
            if part is None or not test(root, part):
                yield number_.path, ("part %d is %r" % (place, part) if part is not None
                                     else "it has no part %d" % place)


@greece("GR-R-001-1", "a Greek seller's invoice number (BT-1) is six parts with `|` between "
                      "them")
def gr_r_001_1(root: At) -> Iterator[Failure]:
    for number_, parts in segments(root):
        if len(parts) != 6:
            yield number_.path, "it is %d" % len(parts)


def sellers_tin(root: At, part: str) -> bool:
    known = [company.text[2:11] for party in (SELLER, REPRESENTATIVE)
             for company in vat_identifiers(one(root, party), exact=True)]
    # Nine characters of a VAT identifier, so the part is nine at most.
    return tin(part) and part in known


def issue_date(root: At, part: str) -> bool:
    if not normalize_space(part) or not GREEK_DATE.match(part):
        return False
    said_, issued = part.split("/"), text(root, "cbc:IssueDate").split("-")
    return len(said_) >= 3 and len(issued) >= 3 and said_[:3] == issued[2::-1]


def whole_number(root: At, part: str) -> bool:
    if not normalize_space(part) or not numeric(part):
        return False
    trimmed = normalize_space(part)
    if not re.fullmatch(r"[+-]?[0-9]+", trimmed):
        raise Incomputable("part 3 of the invoice number is %r, a number that is not a "
                           "whole one" % part)
    return int(trimmed) >= 0


segment("GR-R-001-2", "starts with the tax number of the seller or of its tax "
                      "representative, as in their VAT identifiers", 1, sellers_tin)
segment("GR-R-001-3", "has the issue date (BT-2) second, as day/month/year", 2, issue_date)
segment("GR-R-001-4", "has a whole number that is not negative third", 3, whole_number)
segment("GR-R-001-5", "has a Greek document type fourth: one of %s" % ", ".join(GREEK_TYPES),
        4, lambda root, part: bool(normalize_space(part)) and part in GREEK_TYPES)
segment("GR-R-001-6", "has something fifth", 5, lambda root, part: bool(part))
segment("GR-R-001-7", "has something sixth", 6, lambda root, part: bool(part))


def parties(root: At, role: str) -> List[At]:
    return contexts(root, "%s/cac:Party" % role)


def named_party(identifier: str, role: str, about: str) -> None:
    @greece(identifier, about)
    def check(root: At) -> Iterator[Failure]:
        for party in parties(root, role):
            if not text(party, "cac:PartyName/cbc:Name"):
                yield party.path, "it is not there"


named_party("GR-R-002", "cac:AccountingSupplierParty",
            "a Greek seller gives its name as it is registered (BT-28)")
named_party("GR-R-005", "cac:AccountingCustomerParty",
            "a Greek seller gives the buyer's name (BT-45)")


def greek_vat(party: At) -> bool:
    """One VAT identifier, `EL` and a tax number."""
    found = vat_identifiers(party, exact=False)
    return len(found) == 1 and found[0].text[:2] == "EL" and tin(found[0].text[2:])


@greece("GR-S-011", "a Greek seller gives one VAT identifier (BT-31): `EL` and its tax "
                    "number")
def gr_s_011(root: At) -> Iterator[Failure]:
    for party in parties(root, "cac:AccountingSupplierParty"):
        if not greek_vat(party):
            yield party.path, "it does not"


@greece("GR-R-003", "a Greek seller's VAT identifier (BT-31) is `EL` and a valid tax number")
def gr_r_003(root: At) -> Iterator[Failure]:
    for party in parties(root, "cac:AccountingSupplierParty"):
        for company in vat_identifiers(party, exact=False):
            if not (company.text[:2] == "EL" and tin(company.text[2:])):
                yield company.path, "%r is not" % company.text


def references(root: At, described: str) -> List[At]:
    return [reference for reference in elements(root, "cac:AdditionalDocumentReference")
            if any(found.text == described
                   for found in elements(reference, "cbc:DocumentDescription"))]


def referenced(identifier: str, about: str, described: str, allowed: tuple) -> None:
    @greece_address(identifier, about)
    def check(root: At) -> Iterator[Failure]:
        count = len(references(root, described))
        if count not in allowed:
            yield root.path, "it has %d" % count


referenced("GR-R-004-1", "a document from a seller in Greece has one M.AR.K number: one "
                         "document reference (BG-24) described as `%s`" % MARK, MARK, (1,))
referenced("GR-S-008-1", "a document from a seller in Greece has one invoice URL: one "
                         "document reference (BG-24) described as `%s`" % INVOICE_URL,
           INVOICE_URL, (1,))
referenced("GR-R-008-2", "a document from a seller in Greece has no more than one invoice "
                         "URL", INVOICE_URL, (0, 1))


@greece_address("GR-R-004-2", "a M.AR.K number starts with a digit from 1 to 9")
def gr_r_004_2(root: At) -> Iterator[Failure]:
    for reference in named(root, "cac:AdditionalDocumentReference"):
        if not any(found.text == MARK
                   for found in elements(reference, "cbc:DocumentDescription")):
            continue
        for number_ in elements(reference, "cbc:ID"):
            if not re.match(r"[1-9]", number_.text):
                yield number_.path, "it is %r" % number_.text


@greece("GR-R-008-3", "a Greek seller's invoice URL reference has the address (BT-124)")
def gr_r_008_3(root: At) -> Iterator[Failure]:
    for reference in named(root, "cac:AdditionalDocumentReference"):
        if (any(found.text == INVOICE_URL
                for found in elements(reference, "cbc:DocumentDescription"))
                and not said(reference, "cac:Attachment/cac:ExternalReference/cbc:URI")):
            yield reference.path, "it has none"


def tin_address(endpoint: At) -> bool:
    return endpoint.node.attributes.get("schemeID") == "9933" and tin(endpoint.text)


@peppol("GR-R-009", "a Greek seller's electronic address (BT-34) is its tax number, under "
                    "scheme 9933")
def gr_r_009(root: At) -> Iterator[Failure]:
    # By the seller's VAT identifier or its address: its tax representative
    # does not make it Greek for this rule.
    if country(root, SELLER, "%s/%s" % (SELLER, COUNTRY)) not in ("GR", "EL"):
        return
    for endpoint in contexts(root, "%s/cbc:EndpointID" % SELLER):
        if not tin_address(endpoint):
            yield endpoint.path, "%r is not" % endpoint.text


@greece_both("GR-R-006", "a Greek seller gives a Greek buyer's VAT identifier (BT-48): `EL` "
                         "and its tax number")
def gr_r_006(root: At) -> Iterator[Failure]:
    for party in parties(root, "cac:AccountingCustomerParty"):
        if not greek_vat(party):
            yield party.path, "it does not"


@greece_both("GR-R-010", "a Greek buyer's electronic address (BT-49), from a Greek seller, "
                         "is its tax number, under scheme 9933")
def gr_r_010(root: At) -> Iterator[Failure]:
    for endpoint in contexts(root, "%s/cbc:EndpointID" % BUYER):
        if not tin_address(endpoint):
            yield endpoint.path, "%r is not" % endpoint.text


# -- Iceland ---------------------------------------------------------------------------------

def icelandic_seller(root: At) -> bool:
    return written(root, SELLER) == "IS"


iceland = functools.partial(national, within=icelandic_seller)
iceland_both = functools.partial(
    national, within=lambda root: icelandic_seller(root) and written(root, BUYER) == "IS")
EINDAGI = "EINDAGI"         # the final due date, as a document reference


def kennitala(root: At, party: str) -> bool:
    """Whether a party has a legal registration under scheme `0196`."""
    return any(company.node.attributes.get("schemeID") == "0196"
               for company in elements(root, "%s/%s" % (party, LEGAL_ID)))


@iceland("IS-R-001", "an Icelandic seller's document is of type 380 or 381 (BT-3)")
def is_r_001(root: At) -> Iterator[Failure]:
    codes = [said(root, name) for name in ("cbc:InvoiceTypeCode", "cbc:CreditNoteTypeCode")]
    if not any(code in ("380", "381") for code in codes):
        yield root.path, "it is %r" % (codes[0] or codes[1])


@iceland("IS-R-002", "an Icelandic seller gives its legal registration, the kennitala "
                     "(BT-30), under scheme `0196`")
def is_r_002(root: At) -> Iterator[Failure]:
    if not kennitala(root, SELLER):
        yield root.path, "it does not"


def street_and_post_code(identifier: str, register: Callable, party: str, about: str) -> None:
    @register(identifier, about)
    def check(root: At) -> Iterator[Failure]:
        if not all(elements(root, "%s/%s/%s" % (party, ADDRESS, name))
                   for name in ("cbc:StreetName", "cbc:PostalZone")):
            yield root.path, "it does not"


street_and_post_code("IS-R-003", iceland, SELLER, "an Icelandic seller's address has a "
                                                  "street (BT-35) and a post code (BT-38)")


def account_of_twelve(identifier: str, code: str, about: str) -> None:
    @iceland(identifier, about)
    def check(root: At) -> Iterator[Failure]:
        paid = [means for means in elements(root, "cac:PaymentMeans")
                if any(found.text == code
                       for found in elements(means, "cbc:PaymentMeansCode"))]
        if not paid:
            return
        accounts = [account for means in paid
                    for account in elements(means, "cac:PayeeFinancialAccount/cbc:ID")]
        if len(accounts) > 1:
            raise Incomputable("there are %d accounts for means of payment %s where the "
                               "rule takes one" % (len(accounts), code))
        if not accounts or len(normalize_space(accounts[0].text)) != 12:
            yield paid[0].path, ("it is %r" % accounts[0].text if accounts
                                 else "it has no account")


account_of_twelve("IS-R-006", "9", "an Icelandic seller paid by claim (means 9) gives an "
                                   "account (BT-84) of twelve characters")
account_of_twelve("IS-R-007", "42", "an Icelandic seller paid by transfer (means 42) gives "
                                    "an account (BT-84) of twelve characters")


def eindagi(root: At) -> List[At]:
    return references(root, EINDAGI)


def final_dates(root: At) -> List[At]:
    return [found for reference in eindagi(root) for found in elements(reference, "cbc:ID")]


def is_a_date(value: str) -> bool:
    try:
        date_of(value)
    except Incomputable:
        return False
    return True


@iceland("IS-R-008", "an Icelandic seller's final due date (a document reference described "
                     "as `EINDAGI`) is a date written YYYY-MM-DD")
def is_r_008(root: At) -> Iterator[Failure]:
    if not eindagi(root):
        return
    dates = final_dates(root)
    if len(dates) > 1:
        raise Incomputable("there are %d final due dates where the rule takes one"
                           % len(dates))
    value = dates[0].text if dates else ""
    if not (len(value) == 10 and is_a_date(value)):
        yield eindagi(root)[0].path, "it is %r" % value


@iceland("IS-R-009", "an Icelandic seller's document with a final due date has a due date "
                     "(BT-9)")
def is_r_009(root: At) -> Iterator[Failure]:
    if eindagi(root) and not elements(root, "cbc:DueDate"):
        yield root.path, "it has none"


@iceland("IS-R-010", "an Icelandic seller's final due date is not before the due date "
                     "(BT-9)")
def is_r_010(root: At) -> Iterator[Failure]:
    if not eindagi(root):
        return
    due, final = elements(root, "cbc:DueDate"), final_dates(root)
    # Compared as text, which is right for two dates written the same way.
    if not any(one_.text <= other.text for one_ in due for other in final):
        yield eindagi(root)[0].path, "it is %r and the due date %r" % (
            final[0].text if final else "", due[0].text if due else "")


@iceland_both("IS-R-004", "an Icelandic buyer's legal registration, the kennitala (BT-47), "
                          "is given by an Icelandic seller, under scheme `0196`")
def is_r_004(root: At) -> Iterator[Failure]:
    if elements(root, "cac:AccountingCustomerParty") and not kennitala(root, BUYER):
        yield root.path, "it is not"


@iceland_both("IS-R-005", "an Icelandic buyer's address, from an Icelandic seller, has a "
                          "street (BT-50) and a post code (BT-53)")
def is_r_005(root: At) -> Iterator[Failure]:
    if elements(root, "cac:AccountingCustomerParty") and not all(
            elements(root, "%s/%s/%s" % (BUYER, ADDRESS, name))
            for name in ("cbc:StreetName", "cbc:PostalZone")):
        yield root.path, "it does not"


# -- the Netherlands -------------------------------------------------------------------------

def dutch_seller(root: At) -> bool:
    return address_is(root, SELLER, "NL")


def dutch_both(root: At) -> bool:
    return dutch_seller(root) and address_is(root, BUYER, "NL")


netherlands = functools.partial(national, within=dutch_seller)
netherlands_both = functools.partial(national, within=dutch_both)
DUTCH_MEANS = ("30", "48", "49", "57", "58", "59")
WHOLE_ADDRESS = ("cbc:StreetName", "cbc:CityName", "cbc:PostalZone")


@netherlands("NL-R-001", "a Dutch seller's credit note names the invoice it corrects (BT-25)")
def nl_r_001(root: At) -> Iterator[Failure]:
    if not elements(root, "cac:BillingReference/cac:InvoiceDocumentReference/cbc:ID"):
        for code in named(root, "cbc:CreditNoteTypeCode"):
            yield code.path, "it names none"


def whole_address(identifier: str, register: Callable, context: str, about: str) -> None:
    @register(identifier, "%s has a street, a city and a post code" % about)
    def check(root: At) -> Iterator[Failure]:
        for address in contexts(root, context):
            missing = lacking(address, *WHOLE_ADDRESS)
            if missing:
                yield address.path, "it has no %s" % " or ".join(missing)


def kvk_or_oin(identifier: str, register: Callable, party: str, about: str) -> None:
    @register(identifier, "%s is a KVK or an OIN number: under scheme `0106` or `0190`, and "
                          "not empty" % about)
    def check(root: At) -> Iterator[Failure]:
        for company in contexts(root, "%s/%s" % (party, LEGAL_ID)):
            under = " %s " % company.node.attributes.get("schemeID", "")
            if not ((" 0106 " in under or " 0190 " in under)
                    and normalize_space(company.text)):
                yield company.path, "it is %r under scheme %r" % (
                    company.text, company.node.attributes.get("schemeID", ""))


whole_address("NL-R-002", netherlands, "%s/%s" % (SELLER, ADDRESS),
              "a Dutch seller's address (BG-5)")
kvk_or_oin("NL-R-003", netherlands, SELLER, "a Dutch seller's legal registration (BT-30)")
whole_address("NL-R-004", netherlands_both, "%s/%s" % (BUYER, ADDRESS),
              "a Dutch buyer's address (BG-8), from a Dutch seller,")
kvk_or_oin("NL-R-005", netherlands_both, BUYER,
           "a Dutch buyer's legal registration (BT-47), from a Dutch seller,")
whole_address("NL-R-006", functools.partial(
    national, within=lambda root: dutch_seller(root) and address_is(root, REPRESENTATIVE, "NL")),
    "%s/%s" % (REPRESENTATIVE, ADDRESS),
    "a Dutch seller's tax representative's address in the Netherlands (BG-12)")


@netherlands("NL-R-007", "a Dutch seller says how it is to be paid (BG-16) where money is "
                         "owed to it: an invoice with an amount due (BT-115) above nothing, "
                         "or a credit note with one below")
def nl_r_007(root: At) -> Iterator[Failure]:
    for totals in named(root, "cac:LegalMonetaryTotal"):
        due = number(totals, "cbc:PayableAmount")
        settled = due is not None and (due <= 0 if root.node.tag == INVOICE else due >= 0)
        if not settled and not named(root, "cac:PaymentMeans"):
            yield totals.path, "it does not"


@netherlands_both("NL-R-008", "between a Dutch seller and a Dutch buyer, the means of "
                              "payment (BT-81) is one of %s" % ", ".join(DUTCH_MEANS))
def nl_r_008(root: At) -> Iterator[Failure]:
    for means in named(root, "cac:PaymentMeans"):
        if said(means, "cbc:PaymentMeansCode") not in DUTCH_MEANS:
            yield means.path, "it is %r" % text(means, "cbc:PaymentMeansCode")


@netherlands("NL-R-009", "a Dutch seller's document whose line names an order line (BT-132) "
                         "names the order (BT-13)")
def nl_r_009(root: At) -> Iterator[Failure]:
    if not elements(root, "cac:OrderReference/cbc:ID"):
        for line in contexts(root, "cac:OrderLineReference/cbc:LineID"):
            yield line.path, "it names none"
