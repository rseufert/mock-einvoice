"""The invoice as EN 16931 describes it: business terms, in groups.

An invoice and a credit note are one thing here. Each value sits under the
number the standard gives its business term (`BT-1`, the invoice number) and
the groups that repeat are groups here too (`BG-25`, an invoice line), so a
rule is written once, against the standard's own names, and holds for both
documents and for whichever syntax they arrived in.

What is a group here and what is not
------------------------------------
Only a group that can occur more than once is kept as a `Group`: a note, a
preceding invoice, a payment instruction, an allowance, a charge, a line of the
VAT breakdown, a supporting document, an invoice line, and on a line its
allowances, charges and item attributes. The standard's other groups occur
once (the seller, the totals, a line's price), so their terms are held
directly by the document or the line they belong to, and `GROUPS` says which
group each term is in.

`BG-16`, the payment instructions, occurs once in the standard and is a group
here all the same: UBL writes one `PaymentMeans` for each account to be paid
to, so it does repeat on the wire, and the published rules are written about
each one.

Numbers
-------
Every amount, quantity, price and percentage is a `decimal.Decimal`, made from
the text as it was written. Nothing here is ever a float, and the digits after
the point are kept as sent: `Decimal("10.50")` is not `Decimal("10.5")` to the
rules that count them.
"""
from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, List, Optional

# What XML Schema calls a decimal: digits with at most one point, and a sign.
# No exponent, no infinity, no NaN, all of which `Decimal()` would take.
DECIMAL = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)")
DATE = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})")

# The kinds of value whose text is a number.
NUMERIC = ("amount", "price", "quantity", "percentage")


class Refused(Exception):
    """A document this package does not take, and why.

    `code` is short and stable, for a caller to tell refusals apart; the
    message names what was sent.
    """

    def __init__(self, code: str, reason: str):
        super().__init__(reason)
        self.code = code
        self.reason = reason


@dataclass(frozen=True)
class Finding:
    """Something to say about a document: where, and in what words.

    `code` is a published rule's identifier where a published rule is what
    found it (`BR-CO-15`). The reader's own findings have codes of its own, in
    capitals without a number, so the two cannot be mistaken for each other.
    """
    level: str          # "error" or "warning"
    code: str
    path: str           # where in the document as it was sent
    text: str


@dataclass
class Value:
    """One business term's value: its text as written, and what qualifies it.

    `attributes` holds what the syntax wrote beside the text: the currency of
    an amount (`currencyID`), the unit of a quantity (`unitCode`), the scheme
    of an identifier (`schemeID`). A key with a slash in it is not an XML
    attribute; it is something the syntax said in an element of its own that
    the standard has no term for and the document cannot be written without
    (`TaxScheme/ID` on a tax registration).
    """
    text: str
    attributes: Dict[str, str] = field(default_factory=dict)

    @property
    def number(self) -> Optional[Decimal]:
        """The text as a decimal, or None if it is not one."""
        text = self.text.strip()
        return Decimal(text) if DECIMAL.fullmatch(text) else None

    @property
    def date(self) -> Optional[datetime.date]:
        """The text as a date written `YYYY-MM-DD`, or None if it is not one."""
        match = DATE.fullmatch(self.text.strip())
        if not match:
            return None
        try:
            return datetime.date(*(int(part) for part in match.groups()))
        except ValueError:
            return None

    @classmethod
    def of(cls, value, **attributes: str) -> "Value":
        """A value made by hand. A float is refused: say it as text."""
        if isinstance(value, float):
            raise TypeError("a float is not an amount; write %r as text or a Decimal" % value)
        return cls(str(value), dict(attributes))


# A term that the syntax writes as an attribute of another term's element.
# `BT-130`, the unit of the invoiced quantity, is `BT-129`'s `unitCode`.
ATTRIBUTE_TERMS = {
    "BT-18-1": ("BT-18", "schemeID"), "BT-29-1": ("BT-29", "schemeID"),
    "BT-30-1": ("BT-30", "schemeID"), "BT-34-1": ("BT-34", "schemeID"),
    "BT-46-1": ("BT-46", "schemeID"), "BT-47-1": ("BT-47", "schemeID"),
    "BT-49-1": ("BT-49", "schemeID"), "BT-60-1": ("BT-60", "schemeID"),
    "BT-61-1": ("BT-61", "schemeID"), "BT-71-1": ("BT-71", "schemeID"),
    "BT-82": ("BT-81", "name"),
    "BT-125-1": ("BT-125", "mimeCode"), "BT-125-2": ("BT-125", "filename"),
    "BT-128-1": ("BT-128", "schemeID"), "BT-130": ("BT-129", "unitCode"),
    "BT-150": ("BT-149", "unitCode"), "BT-157-1": ("BT-157", "schemeID"),
    "BT-158-1": ("BT-158", "listID"), "BT-158-2": ("BT-158", "listVersionID"),
}


@dataclass
class Group:
    """Terms and the groups under them: a document, or one of its groups."""
    id: str = ""
    terms: Dict[str, List[Value]] = field(default_factory=dict)
    groups: Dict[str, List["Group"]] = field(default_factory=dict)

    def values(self, term: str) -> List[Value]:
        """Every value of a term here, in the order they were written."""
        if term in ATTRIBUTE_TERMS:
            holder, attribute = ATTRIBUTE_TERMS[term]
            return [Value(v.attributes[attribute]) for v in self.terms.get(holder, [])
                    if attribute in v.attributes]
        return list(self.terms.get(term, []))

    def term(self, term: str) -> Optional[Value]:
        """The value of a term here, or None. The first, if it was repeated."""
        found = self.values(term)
        return found[0] if found else None

    def text(self, term: str) -> str:
        """A term's text, or "" if it is not here."""
        found = self.term(term)
        return found.text if found else ""

    def all(self, group: str) -> List["Group"]:
        """Every group of one kind here: `document.all("BG-25")` is the lines."""
        return list(self.groups.get(group, []))

    def add(self, term: str, value) -> Value:
        """Give a term a value, after any it already has."""
        if not isinstance(value, Value):
            value = Value.of(value)
        self.terms.setdefault(term, []).append(value)
        return value

    def new(self, group: str) -> "Group":
        """A new, empty group of one kind, after any already here."""
        made = Group(group)
        self.groups.setdefault(group, []).append(made)
        return made

    def empty(self) -> bool:
        return not any(self.terms.values()) and not any(self.groups.values())


@dataclass
class Document(Group):
    """An invoice or a credit note. `kind` is "Invoice" or "CreditNote"."""
    kind: str = "Invoice"


# The standard's groups, by number. The ones marked True are kept as a
# `Group`; the terms of the others are held by the document or line itself.
GROUPS = {
    "BG-1": ("Invoice note", True),
    "BG-2": ("Process control", False),
    "BG-3": ("Preceding invoice reference", True),
    "BG-4": ("Seller", False),
    "BG-5": ("Seller postal address", False),
    "BG-6": ("Seller contact", False),
    "BG-7": ("Buyer", False),
    "BG-8": ("Buyer postal address", False),
    "BG-9": ("Buyer contact", False),
    "BG-10": ("Payee", False),
    "BG-11": ("Seller tax representative party", False),
    "BG-12": ("Seller tax representative postal address", False),
    "BG-13": ("Delivery information", False),
    "BG-14": ("Invoicing period", False),
    "BG-15": ("Deliver to address", False),
    "BG-16": ("Payment instructions", True),
    "BG-17": ("Credit transfer", False),
    "BG-18": ("Payment card information", False),
    "BG-19": ("Direct debit", False),
    "BG-20": ("Document level allowances", True),
    "BG-21": ("Document level charges", True),
    "BG-22": ("Document totals", False),
    "BG-23": ("VAT breakdown", True),
    "BG-24": ("Additional supporting documents", True),
    "BG-25": ("Invoice line", True),
    "BG-26": ("Invoice line period", False),
    "BG-27": ("Invoice line allowances", True),
    "BG-28": ("Invoice line charges", True),
    "BG-29": ("Price details", False),
    "BG-30": ("Line VAT information", False),
    "BG-31": ("Item information", False),
    "BG-32": ("Item attributes", True),
}

# Every business term: its name, the group the standard puts it in ("" for
# the document itself), and what kind of value it is. The names are the
# standard's, written out by hand; `tests/test_model.py` holds the numbering.
TERMS = {
    "BT-1": ("Invoice number", "", "identifier"),
    "BT-2": ("Invoice issue date", "", "date"),
    "BT-3": ("Invoice type code", "", "code"),
    "BT-5": ("Invoice currency code", "", "code"),
    "BT-6": ("VAT accounting currency code", "", "code"),
    "BT-7": ("Value added tax point date", "", "date"),
    "BT-8": ("Value added tax point date code", "", "code"),
    "BT-9": ("Payment due date", "", "date"),
    "BT-10": ("Buyer reference", "", "text"),
    "BT-11": ("Project reference", "", "identifier"),
    "BT-12": ("Contract reference", "", "identifier"),
    "BT-13": ("Purchase order reference", "", "identifier"),
    "BT-14": ("Sales order reference", "", "identifier"),
    "BT-15": ("Receiving advice reference", "", "identifier"),
    "BT-16": ("Despatch advice reference", "", "identifier"),
    "BT-17": ("Tender or lot reference", "", "identifier"),
    "BT-18": ("Invoiced object identifier", "", "identifier"),
    "BT-19": ("Buyer accounting reference", "", "text"),
    "BT-20": ("Payment terms", "", "text"),
    "BT-21": ("Invoice note subject code", "BG-1", "code"),
    "BT-22": ("Invoice note", "BG-1", "text"),
    "BT-23": ("Business process type", "BG-2", "text"),
    "BT-24": ("Specification identifier", "BG-2", "identifier"),
    "BT-25": ("Preceding Invoice reference", "BG-3", "identifier"),
    "BT-26": ("Preceding Invoice issue date", "BG-3", "date"),
    "BT-27": ("Seller name", "BG-4", "text"),
    "BT-28": ("Seller trading name", "BG-4", "text"),
    "BT-29": ("Seller identifier", "BG-4", "identifier"),
    "BT-30": ("Seller legal registration identifier", "BG-4", "identifier"),
    "BT-31": ("Seller VAT identifier", "BG-4", "identifier"),
    "BT-32": ("Seller tax registration identifier", "BG-4", "identifier"),
    "BT-33": ("Seller additional legal information", "BG-4", "text"),
    "BT-34": ("Seller electronic address", "BG-4", "identifier"),
    "BT-35": ("Seller address line 1", "BG-5", "text"),
    "BT-36": ("Seller address line 2", "BG-5", "text"),
    "BT-37": ("Seller city", "BG-5", "text"),
    "BT-38": ("Seller post code", "BG-5", "text"),
    "BT-39": ("Seller country subdivision", "BG-5", "text"),
    "BT-40": ("Seller country code", "BG-5", "code"),
    "BT-41": ("Seller contact point", "BG-6", "text"),
    "BT-42": ("Seller contact telephone number", "BG-6", "text"),
    "BT-43": ("Seller contact email address", "BG-6", "text"),
    "BT-44": ("Buyer name", "BG-7", "text"),
    "BT-45": ("Buyer trading name", "BG-7", "text"),
    "BT-46": ("Buyer identifier", "BG-7", "identifier"),
    "BT-47": ("Buyer legal registration identifier", "BG-7", "identifier"),
    "BT-48": ("Buyer VAT identifier", "BG-7", "identifier"),
    "BT-49": ("Buyer electronic address", "BG-7", "identifier"),
    "BT-50": ("Buyer address line 1", "BG-8", "text"),
    "BT-51": ("Buyer address line 2", "BG-8", "text"),
    "BT-52": ("Buyer city", "BG-8", "text"),
    "BT-53": ("Buyer post code", "BG-8", "text"),
    "BT-54": ("Buyer country subdivision", "BG-8", "text"),
    "BT-55": ("Buyer country code", "BG-8", "code"),
    "BT-56": ("Buyer contact point", "BG-9", "text"),
    "BT-57": ("Buyer contact telephone number", "BG-9", "text"),
    "BT-58": ("Buyer contact email address", "BG-9", "text"),
    "BT-59": ("Payee name", "BG-10", "text"),
    "BT-60": ("Payee identifier", "BG-10", "identifier"),
    "BT-61": ("Payee legal registration identifier", "BG-10", "identifier"),
    "BT-62": ("Seller tax representative name", "BG-11", "text"),
    "BT-63": ("Seller tax representative VAT identifier", "BG-11", "identifier"),
    "BT-64": ("Tax representative address line 1", "BG-12", "text"),
    "BT-65": ("Tax representative address line 2", "BG-12", "text"),
    "BT-66": ("Tax representative city", "BG-12", "text"),
    "BT-67": ("Tax representative post code", "BG-12", "text"),
    "BT-68": ("Tax representative country subdivision", "BG-12", "text"),
    "BT-69": ("Tax representative country code", "BG-12", "code"),
    "BT-70": ("Deliver to party name", "BG-13", "text"),
    "BT-71": ("Deliver to location identifier", "BG-13", "identifier"),
    "BT-72": ("Actual delivery date", "BG-13", "date"),
    "BT-73": ("Invoicing period start date", "BG-14", "date"),
    "BT-74": ("Invoicing period end date", "BG-14", "date"),
    "BT-75": ("Deliver to address line 1", "BG-15", "text"),
    "BT-76": ("Deliver to address line 2", "BG-15", "text"),
    "BT-77": ("Deliver to city", "BG-15", "text"),
    "BT-78": ("Deliver to post code", "BG-15", "text"),
    "BT-79": ("Deliver to country subdivision", "BG-15", "text"),
    "BT-80": ("Deliver to country code", "BG-15", "code"),
    "BT-81": ("Payment means type code", "BG-16", "code"),
    "BT-82": ("Payment means text", "BG-16", "text"),
    "BT-83": ("Remittance information", "BG-16", "text"),
    "BT-84": ("Payment account identifier", "BG-17", "identifier"),
    "BT-85": ("Payment account name", "BG-17", "text"),
    "BT-86": ("Payment service provider identifier", "BG-17", "identifier"),
    "BT-87": ("Payment card primary account number", "BG-18", "text"),
    "BT-88": ("Payment card holder name", "BG-18", "text"),
    "BT-89": ("Mandate reference identifier", "BG-19", "identifier"),
    "BT-90": ("Bank assigned creditor identifier", "BG-19", "identifier"),
    "BT-91": ("Debited account identifier", "BG-19", "identifier"),
    "BT-92": ("Document level allowance amount", "BG-20", "amount"),
    "BT-93": ("Document level allowance base amount", "BG-20", "amount"),
    "BT-94": ("Document level allowance percentage", "BG-20", "percentage"),
    "BT-95": ("Document level allowance VAT category code", "BG-20", "code"),
    "BT-96": ("Document level allowance VAT rate", "BG-20", "percentage"),
    "BT-97": ("Document level allowance reason", "BG-20", "text"),
    "BT-98": ("Document level allowance reason code", "BG-20", "code"),
    "BT-99": ("Document level charge amount", "BG-21", "amount"),
    "BT-100": ("Document level charge base amount", "BG-21", "amount"),
    "BT-101": ("Document level charge percentage", "BG-21", "percentage"),
    "BT-102": ("Document level charge VAT category code", "BG-21", "code"),
    "BT-103": ("Document level charge VAT rate", "BG-21", "percentage"),
    "BT-104": ("Document level charge reason", "BG-21", "text"),
    "BT-105": ("Document level charge reason code", "BG-21", "code"),
    "BT-106": ("Sum of Invoice line net amount", "BG-22", "amount"),
    "BT-107": ("Sum of allowances on document level", "BG-22", "amount"),
    "BT-108": ("Sum of charges on document level", "BG-22", "amount"),
    "BT-109": ("Invoice total amount without VAT", "BG-22", "amount"),
    "BT-110": ("Invoice total VAT amount", "BG-22", "amount"),
    "BT-111": ("Invoice total VAT amount in accounting currency", "BG-22", "amount"),
    "BT-112": ("Invoice total amount with VAT", "BG-22", "amount"),
    "BT-113": ("Paid amount", "BG-22", "amount"),
    "BT-114": ("Rounding amount", "BG-22", "amount"),
    "BT-115": ("Amount due for payment", "BG-22", "amount"),
    "BT-116": ("VAT category taxable amount", "BG-23", "amount"),
    "BT-117": ("VAT category tax amount", "BG-23", "amount"),
    "BT-118": ("VAT category code", "BG-23", "code"),
    "BT-119": ("VAT category rate", "BG-23", "percentage"),
    "BT-120": ("VAT exemption reason text", "BG-23", "text"),
    "BT-121": ("VAT exemption reason code", "BG-23", "code"),
    "BT-122": ("Supporting document reference", "BG-24", "identifier"),
    "BT-123": ("Supporting document description", "BG-24", "text"),
    "BT-124": ("External document location", "BG-24", "text"),
    "BT-125": ("Attached document", "BG-24", "binary"),
    "BT-126": ("Invoice line identifier", "BG-25", "identifier"),
    "BT-127": ("Invoice line note", "BG-25", "text"),
    "BT-128": ("Invoice line object identifier", "BG-25", "identifier"),
    "BT-129": ("Invoiced quantity", "BG-25", "quantity"),
    "BT-130": ("Invoiced quantity unit of measure code", "BG-25", "code"),
    "BT-131": ("Invoice line net amount", "BG-25", "amount"),
    "BT-132": ("Referenced purchase order line reference", "BG-25", "identifier"),
    "BT-133": ("Invoice line Buyer accounting reference", "BG-25", "text"),
    "BT-134": ("Invoice line period start date", "BG-26", "date"),
    "BT-135": ("Invoice line period end date", "BG-26", "date"),
    "BT-136": ("Invoice line allowance amount", "BG-27", "amount"),
    "BT-137": ("Invoice line allowance base amount", "BG-27", "amount"),
    "BT-138": ("Invoice line allowance percentage", "BG-27", "percentage"),
    "BT-139": ("Invoice line allowance reason", "BG-27", "text"),
    "BT-140": ("Invoice line allowance reason code", "BG-27", "code"),
    "BT-141": ("Invoice line charge amount", "BG-28", "amount"),
    "BT-142": ("Invoice line charge base amount", "BG-28", "amount"),
    "BT-143": ("Invoice line charge percentage", "BG-28", "percentage"),
    "BT-144": ("Invoice line charge reason", "BG-28", "text"),
    "BT-145": ("Invoice line charge reason code", "BG-28", "code"),
    "BT-146": ("Item net price", "BG-29", "price"),
    "BT-147": ("Item price discount", "BG-29", "price"),
    "BT-148": ("Item gross price", "BG-29", "price"),
    "BT-149": ("Item price base quantity", "BG-29", "quantity"),
    "BT-150": ("Item price base quantity unit of measure code", "BG-29", "code"),
    "BT-151": ("Invoiced item VAT category code", "BG-30", "code"),
    "BT-152": ("Invoiced item VAT rate", "BG-30", "percentage"),
    "BT-153": ("Item name", "BG-31", "text"),
    "BT-154": ("Item description", "BG-31", "text"),
    "BT-155": ("Item Seller's identifier", "BG-31", "identifier"),
    "BT-156": ("Item Buyer's identifier", "BG-31", "identifier"),
    "BT-157": ("Item standard identifier", "BG-31", "identifier"),
    "BT-158": ("Item classification identifier", "BG-31", "identifier"),
    "BT-159": ("Item country of origin", "BG-31", "code"),
    "BT-160": ("Item attribute name", "BG-32", "text"),
    "BT-161": ("Item attribute value", "BG-32", "text"),
    "BT-162": ("Seller address line 3", "BG-5", "text"),
    "BT-163": ("Buyer address line 3", "BG-8", "text"),
    "BT-164": ("Tax representative address line 3", "BG-12", "text"),
    "BT-165": ("Deliver to address line 3", "BG-15", "text"),
}
