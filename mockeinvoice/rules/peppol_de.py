"""Peppol BIS Billing 3.0: the rules for a seller and a buyer both in Germany.

`DE-R-001` to `DE-R-031` and `DE-R-T02`: 31 rules, 24 fatal. Every one is
asked only where the seller's address and the buyer's address both name
Germany, however `DE` is written. They are Peppol's rendering of XRechnung's
rules and are read from Peppol's tests, not assumed to be XRechnung's.

Written by hand from reading the tests, like the rest of Peppol's
(`peppol.py`): nothing is copied from its rule file.

What the published tests say that one might not expect
------------------------------------------------------
- **Both in Germany.** A German seller invoicing a buyer abroad is asked none
  of these.
- **A cash discount line must end in a line break** (`DE-R-018`). A payment
  term that starts with `#` has to be `#SKONTO#TAGE=..#PROZENT=..#`, and what
  follows the last such line has to begin with a new line.
- **The IBAN checks are warnings** (`DE-R-019`, `DE-R-020`), asked of SEPA
  credit transfers (58) and SEPA direct debits (59) only, and a small letter
  in an IBAN's body is not the letter it is in capitals: the test turns a
  character into a number by its code point.
- **`DE-R-016` is satisfied by a tax representative alone**, whether or not it
  has a VAT identifier.

Where this departs from the published tests
-------------------------------------------
- **Regular expressions** are Python's here and XPath's there. The five these
  rules use mean the same in both.
"""
from __future__ import annotations

import functools
import re
from typing import Iterator, List

from . import Failure, rule
from .calculation import Incomputable, normalize_space
from .peppol import BUYER, SELLER, both_german, said
from .tree import At, elements, texts

peppol = functools.partial(rule, "peppol", over="tree")

SKONTO = re.compile(r"(^|\r?\n)#(SKONTO)#TAGE=([0-9]+#PROZENT=[0-9]+\.[0-9]{2})"
                    r"(#BASISBETRAG=-?[0-9]+\.[0-9]{2})?#\Z")
EMAIL = re.compile(r"^[^@\s]+@([^@.\s]+\.)+[^@.\s]+\Z")
TELEPHONE = re.compile(r".*([0-9].*){3,}.*")
URL = re.compile(r"^([a-zA-Z])([a-zA-Z0-9+.-])+:.*")
IBAN = re.compile(r"[A-Z]{2}[0-9]{2}[a-zA-Z0-9]{0,30}")
VAT_CATEGORIES = ("S", "Z", "E", "AE", "K", "G", "L", "M")
TYPE_CODES = ("326", "380", "384", "389", "381", "875", "876", "877")
MEANS = "cac:PaymentMeans"


def german(check):
    """Asked only of a document whose seller and buyer are both in Germany."""
    @functools.wraps(check)
    def gated(root: At) -> Iterator[Failure]:
        if both_german(root):
            yield from check(root)
    return gated


def filled(at: At, name: str) -> bool:
    """`cbc:X[boolean(normalize-space(.))]`: one of them has something in it."""
    return any(normalize_space(text) for text in texts(elements(at, name)))


def de(identifier: str, about: str):
    return lambda check: peppol("DE-R-" + identifier, about)(german(check))


# -- the document ------------------------------------------------------------------

@de("001", "the document has payment instructions (BG-16)")
def r001(root: At) -> Iterator[Failure]:
    if not elements(root, MEANS):
        yield root.path, "it has none"


@de("015", "the document has a buyer reference (BT-10)")
def r015(root: At) -> Iterator[Failure]:
    if not filled(root, "cbc:BuyerReference"):
        yield root.path, "it has none"


@de("016", "a document with a line, an allowance or a charge in a VAT category other than "
           "O has a seller's tax registration (BT-31, BT-32) or a tax representative (BG-11)")
def r016(root: At) -> Iterator[Failure]:
    used: List[str] = []
    for allowance in elements(root, "cac:AllowanceCharge"):
        # By the indicator as written: `true` or `false`, and nothing else.
        if any(text in ("true", "false") for text in texts(elements(allowance,
                                                                    "cbc:ChargeIndicator"))):
            used += texts(elements(allowance, "cac:TaxCategory/cbc:ID"))
    for line in elements(root, "cac:InvoiceLine") + elements(root, "cac:CreditNoteLine"):
        used += texts(elements(line, "cac:Item/cac:ClassifiedTaxCategory/cbc:ID"))
    if not any(code in VAT_CATEGORIES for code in used):
        return
    if not (elements(root, "cac:TaxRepresentativeParty")
            or filled(root, "%s/cac:PartyTaxScheme/cbc:CompanyID" % SELLER)):
        yield "%s/cac:AccountingSupplierParty" % root.path, "it has neither"


@de("017", "the type code (BT-3) is one of the eight used in Germany")
def r017(root: At) -> Iterator[Failure]:
    if not (said(root, "cbc:InvoiceTypeCode") in TYPE_CODES
            or said(root, "cbc:CreditNoteTypeCode") in TYPE_CODES):
        yield root.path, "it is %r" % (said(root, "cbc:InvoiceTypeCode")
                                       or said(root, "cbc:CreditNoteTypeCode"))


@de("018", "a line of the payment terms (BT-20) that starts with `#` is a cash discount, "
           "`#SKONTO#TAGE=..#PROZENT=..#`, and ends in a line break")
def r018(root: At) -> Iterator[Failure]:
    notes = [found[0] for terms in elements(root, "cac:PaymentTerms")
             for found in [elements(terms, "cbc:Note")] if found]
    marked = [(note, line) for note in notes for line in re.split(r"\r?\n", note.text)
              if normalize_space(line).startswith("#")]
    if not marked:
        return
    if len(notes) > 1:
        raise Incomputable("the document has %d payment terms where the rule takes one"
                           % len(notes))
    # What is after the last `#...#` in the note begins with a line break.
    ends_in_a_line_break = bool(re.match(r"\s*\n", re.split(r"#.+#", notes[0].text)[-1]))
    for note, line in marked:
        if not SKONTO.search(normalize_space(line)):
            yield note.path, "%r is not one" % normalize_space(line)
        elif not ends_in_a_line_break:
            yield note.path, "no line break follows the last of them"


@de("022", "no two attached documents have the same file name")
def r022(root: At) -> Iterator[Failure]:
    seen: List[str] = []
    for reference in elements(root, "cac:AdditionalDocumentReference"):
        names = [at.node.attributes["filename"] for at in elements(
            reference, "cac:Attachment/cbc:EmbeddedDocumentBinaryObject")
            if "filename" in at.node.attributes]
        again = [name for name in names if name in seen]
        if again:
            yield reference.path, "%r is an earlier one's" % again[0]
        seen += names


@de("026", "a corrected invoice (type 384) refers to the invoice it corrects (BG-3)")
def r026(root: At) -> Iterator[Failure]:
    if ("384" in (said(root, "cbc:InvoiceTypeCode"), said(root, "cbc:CreditNoteTypeCode"))
            and not elements(root, "cac:BillingReference/cac:InvoiceDocumentReference")):
        yield root.path, "it does not"


def mandated(root: At) -> List[At]:
    return elements(root, "%s/cac:PaymentMandate" % MEANS)


@de("030", "a document with a direct debit mandate has the creditor's identifier (BT-90)")
def r030(root: At) -> Iterator[Failure]:
    if not mandated(root):
        return
    identifiers = (elements(root, "%s/cac:PartyIdentification/cbc:ID" % SELLER)
                   + elements(root, "cac:PayeeParty/cac:PartyIdentification/cbc:ID"))
    # The scheme as written: `SEPA`, in capitals.
    if not any(at.node.attributes.get("schemeID") == "SEPA" for at in identifiers):
        yield mandated(root)[0].path, "it has none"


@de("031", "a document with a direct debit mandate has the account to be debited (BT-91)")
def r031(root: At) -> Iterator[Failure]:
    if mandated(root) and not elements(
            root, "%s/cac:PaymentMandate/cac:PayerFinancialAccount/cbc:ID" % MEANS):
        yield mandated(root)[0].path, "it has none"


@de("T02", "an attached document's external location (BT-124) is a URL with a scheme")
def rt02(root: At) -> Iterator[Failure]:
    for reference in elements(root, "cac:AdditionalDocumentReference/cac:Attachment/"
                                    "cac:ExternalReference"):
        uris = elements(reference, "cbc:URI")
        if len(uris) > 1:
            raise Incomputable("an external reference has %d locations" % len(uris))
        if not URL.search(uris[0].text if uris else ""):
            yield reference.path, "it is %r" % (uris[0].text if uris else "")


# -- the parties ---------------------------------------------------------------------

@de("002", "the seller has a contact (BG-6)")
def r002(root: At) -> Iterator[Failure]:
    for seller in elements(root, "cac:AccountingSupplierParty"):
        if not elements(seller, "cac:Party/cac:Contact"):
            yield seller.path, "it has none"


def has(identifier: str, about: str, where: str, name: str) -> None:
    @de(identifier, about)
    def check(root: At) -> Iterator[Failure]:
        for at in elements(root, where):
            if not filled(at, name):
                yield at.path, "it has none"


SELLERS_ADDRESS, BUYERS_ADDRESS = SELLER + "/cac:PostalAddress", BUYER + "/cac:PostalAddress"
DELIVERY_ADDRESS = "cac:Delivery/cac:DeliveryLocation/cac:Address"
CONTACT = SELLER + "/cac:Contact"

has("003", "the seller's address has a city (BT-37)", SELLERS_ADDRESS, "cbc:CityName")
has("004", "the seller's address has a post code (BT-38)", SELLERS_ADDRESS, "cbc:PostalZone")
has("005", "the seller's contact has a name (BT-41)", CONTACT, "cbc:Name")
has("006", "the seller's contact has a telephone number (BT-42)", CONTACT, "cbc:Telephone")
has("007", "the seller's contact has an email address (BT-43)", CONTACT, "cbc:ElectronicMail")
has("008", "the buyer's address has a city (BT-52)", BUYERS_ADDRESS, "cbc:CityName")
has("009", "the buyer's address has a post code (BT-53)", BUYERS_ADDRESS, "cbc:PostalZone")
has("010", "a deliver to address has a city (BT-77)", DELIVERY_ADDRESS, "cbc:CityName")
has("011", "a deliver to address has a post code (BT-78)", DELIVERY_ADDRESS, "cbc:PostalZone")
has("014", "a VAT breakdown has a rate (BT-119)", "cac:TaxTotal/cac:TaxSubtotal",
    "cac:TaxCategory/cbc:Percent")


def looks_like(identifier: str, about: str, name: str, pattern) -> None:
    @de(identifier, about)
    def check(root: At) -> Iterator[Failure]:
        for contact in elements(root, CONTACT):
            if not pattern.search(said(contact, name)):
                yield contact.path, "it is %r" % said(contact, name)


looks_like("027", "the seller's telephone number (BT-42) has at least three digits",
           "cbc:Telephone", TELEPHONE)
looks_like("028", "the seller's email address (BT-43) is one: a name, `@`, and a domain "
                  "with a dot in it", "cbc:ElectronicMail", EMAIL)


# -- payment instructions, by their payment means -------------------------------------------

def paid_by(root: At, *codes: str) -> List[At]:
    return [means for means in elements(root, MEANS)
            if said(means, "cbc:PaymentMeansCode") in codes]


def iban(text: str) -> bool:
    """An IBAN whose check digits are right: the published test, which takes
    out all white space, moves the first four characters to the end, and
    reads each character as a number by its code point. So `a` is not `A`."""
    account = re.sub(r"\s", "", text)
    if not IBAN.fullmatch(account):
        return False
    moved = account[4:] + account[:4]
    return int("".join(str(ord(c) - (55 if ord(c) > 64 else 48)) for c in moved)) % 97 == 1


def right_iban(identifier: str, code: str, what: str, path: str) -> None:
    @de(identifier, "the %s of a SEPA %s (payment means %s) is an IBAN with right check digits"
        % (path.rpartition("Financial")[0].rpartition(":")[2].lower() + "'s account",
           what, code))
    def check(root: At) -> Iterator[Failure]:
        for means in paid_by(root, code):
            accounts = elements(means, path)
            if len(accounts) > 1:
                raise Incomputable("a payment instruction has %d accounts" % len(accounts))
            if not iban(accounts[0].text if accounts else ""):
                yield means.path, "it is %r" % (accounts[0].text if accounts else "")


right_iban("019", "58", "credit transfer", "cac:PayeeFinancialAccount/cbc:ID")
right_iban("020", "59", "direct debit", "cac:PaymentMandate/cac:PayerFinancialAccount/cbc:ID")

PARTS = {"cac:PayeeFinancialAccount": "an account to be paid into (BG-17)",
         "cac:CardAccount": "a payment card (BG-18)",
         "cac:PaymentMandate": "a direct debit mandate (BG-19)"}


def by_means(number: str, codes: tuple, what: str, wanted: str) -> None:
    others = [name for name in PARTS if name != wanted]

    @de("%s-1" % number, "a payment by %s has %s" % (what, PARTS[wanted]))
    def has_it(root: At) -> Iterator[Failure]:
        for means in paid_by(root, *codes):
            if not elements(means, wanted):
                yield means.path, "it has none"

    @de("%s-2" % number, "a payment by %s has neither %s nor %s"
        % (what, PARTS[others[0]], PARTS[others[1]]))
    def has_no_other(root: At) -> Iterator[Failure]:
        for means in paid_by(root, *codes):
            found = [name for name in others if elements(means, name)]
            if found:
                yield means.path, "it has %s" % PARTS[found[0]]


by_means("023", ("30", "58"), "credit transfer (30, 58)", "cac:PayeeFinancialAccount")
by_means("024", ("48", "54", "55"), "card (48, 54, 55)", "cac:CardAccount")
by_means("025", ("59",), "SEPA direct debit (59)", "cac:PaymentMandate")
