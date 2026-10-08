"""An order the supplier was told of, and the invoice it writes for one.

    from mockeinvoice.order import WHO, invoice, read_order

    order = read_order({"number": "4500000017", "buyer": {...}, "lines": [...]})
    document = invoice(order, WHO, "GLX-0001", datetime.date(2026, 10, 7))

An order here is a description in JSON and not a document of any standard.
Peppol has one, the UBL `Order` of its ordering profiles, with rules of its
own; none of them is built, so it is not taken. What is taken says no more
than an invoice needs: who is buying, the order's number, and the lines.

The rest of an invoice is the supplier's own (`WHO`): who it is, where it is
paid, the one rate of VAT it charges, when payment falls due, and the number
it gives the invoice. Every line is VAT category S at that rate. A supplier
that sells exempt, at nought, or across a border under reverse charge is not
built.

The invoice is a Peppol BIS Billing 3.0 invoice under billing's profile 01.
"""
from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Dict, List, Optional

from . import specification as _specification
from .model import DECIMAL, Document, Value

PROFILE = "urn:fdc:peppol.eu:2017:poacc:billing:01:1.0"
CENT = Decimal("0.01")
ENDPOINT = re.compile(r"([0-9A-Za-z]+):(\S.*)")

# Who the supplier is until it is told otherwise: the seller of this project's
# own sample invoice, with nothing an invoice needs left out.
WHO = {
    "name": "Globex GmbH",
    "endpoint": "0088:4012345000009",
    "vat": "DE123456789",
    "legal_id": "",
    "street": "Industriestrasse 1",
    "city": "Hamburg",
    "postal_code": "20095",
    "country": "DE",
    "contact": "Accounts receivable",
    "telephone": "+49 40 000000",
    "email": "ar@globex.example",
    "iban": "DE02120300000000202051",
    "bic": "BYLADEM1001",
    "currency": "EUR",
    "vat_rate": "19",
    "payment_days": 30,
    "number_prefix": "GLX-",
}
BUYER = ("name", "endpoint", "vat", "legal_id", "street", "city", "postal_code", "country")
LINE = ("line", "name", "seller_item", "buyer_item", "quantity", "unit", "price")
ORDER = ("number", "reference", "buyer", "currency", "lines")


class NotTaken(Exception):
    """An order, or a description of the supplier, that was not taken: what
    it lacks or has too much of. Where it is an order whose invoice would not
    be valid, `report` is what was found in that invoice."""

    def __init__(self, reason: str, report=None):
        super().__init__(reason)
        self.reason, self.report = reason, report


@dataclass
class OrderLine:
    line: str                               # the buyer's number for it (BT-132)
    name: str
    quantity: Decimal
    unit: str                               # a code of UN/ECE Recommendation 20
    price: Decimal                          # for one unit, without VAT
    seller_item: str = ""
    buyer_item: str = ""
    billed: Decimal = Decimal(0)

    @property
    def open(self) -> Decimal:
        return self.quantity - self.billed


@dataclass
class Order:
    number: str
    buyer: Dict[str, str]
    lines: List[OrderLine]
    reference: str = ""                     # the buyer's reference (BT-10), if it gave one
    currency: str = ""                      # or the supplier's own
    id: str = ""
    received: str = ""
    invoices: List[str] = field(default_factory=list)   # the ids of the documents sent for it

    @property
    def status(self) -> str:
        if all(line.open == 0 for line in self.lines):
            return "billed"
        return "billed in part" if any(line.billed for line in self.lines) else "open"

    def line(self, number: str) -> Optional[OrderLine]:
        return next((line for line in self.lines if line.line == number), None)


def only(said: object, what: str, allowed) -> dict:
    if not isinstance(said, dict):
        raise NotTaken("%s is a JSON object, not %s" % (what, type(said).__name__))
    unknown = sorted(set(said) - set(allowed))
    if unknown:
        raise NotTaken("%s has %s, and what is taken is %s"
                       % (what, ", ".join(unknown), ", ".join(allowed)))
    return said


def texts(said: dict, what: str, required=()) -> Dict[str, str]:
    for name, value in said.items():
        if not isinstance(value, str):
            raise NotTaken("%s's %s is text, not %r" % (what, name, value))
    missing = [name for name in required if not said.get(name, "").strip()]
    if missing:
        raise NotTaken("%s has no %s" % (what, " and no ".join(missing)))
    return {name: value.strip() for name, value in said.items()}


def number(value: object, what: str) -> Decimal:
    """A number as JSON has it or as text, and never through a float: the
    server reads a JSON number as the decimal it was written as."""
    if isinstance(value, bool) or isinstance(value, float):
        raise NotTaken("%s is a number written as text, or a whole number, not %r"
                       % (what, value))
    if isinstance(value, (int, Decimal)):
        value = str(value)
    if not isinstance(value, str) or not DECIMAL.fullmatch(value.strip()):
        raise NotTaken("%s is a number, not %r" % (what, value))
    return Decimal(value.strip())


def endpoint(said: str, whose: str) -> Value:
    """An electronic address written `scheme:identifier`, as `0088:4012345000009`."""
    match = ENDPOINT.fullmatch(said)
    if not match:
        raise NotTaken("%s endpoint is written scheme:identifier, as 0088:4012345000009, "
                       "not %r" % (whose, said))
    return Value(match.group(2), {"schemeID": match.group(1)})


def read_order(said: object) -> Order:
    """An order from what was said of it, or `NotTaken`."""
    said = only(said, "the order", ORDER)
    for name in ("number", "reference", "currency"):
        if not isinstance(said.get(name, ""), str):
            raise NotTaken("the order's %s is text, not %r" % (name, said[name]))
    if not said.get("number", "").strip():
        raise NotTaken("the order has no number")
    buyer = texts(only(said.get("buyer"), "the buyer", BUYER), "the buyer",
                  ("name", "endpoint", "country"))
    endpoint(buyer["endpoint"], "the buyer's")
    given = said.get("lines")
    if not isinstance(given, list) or not given:
        raise NotTaken("the order has no lines")
    lines: List[OrderLine] = []
    for position, one in enumerate(given, 1):
        what = "line %d" % position
        one = only(one, what, LINE)
        said_of = texts({name: value for name, value in one.items()
                         if name not in ("quantity", "price")}, what, ("name", "unit"))
        for name in ("quantity", "price"):
            if name not in one:
                raise NotTaken("%s has no %s" % (what, name))
        quantity = number(one["quantity"], "%s's quantity" % what)
        price = number(one["price"], "%s's price" % what)
        if quantity <= 0:
            raise NotTaken("%s orders %s, and an order is for more than nothing"
                           % (what, quantity))
        if price < 0:
            raise NotTaken("%s's price is %s, and a price is not negative" % (what, price))
        line = said_of.get("line") or str(position)
        if any(earlier.line == line for earlier in lines):
            raise NotTaken("two lines are numbered %s" % line)
        lines.append(OrderLine(line, said_of["name"], quantity, said_of["unit"], price,
                               said_of.get("seller_item", ""), said_of.get("buyer_item", "")))
    return Order(said["number"].strip(), buyer, lines, said.get("reference", "").strip(),
                 said.get("currency", "").strip())


def described(who: dict, changes: object) -> dict:
    """The supplier as it would be with these changes, or `NotTaken`."""
    changes = only(changes, "the supplier", tuple(WHO))
    now = dict(who)
    for name, value in changes.items():
        if name == "payment_days":
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise NotTaken("payment_days is a whole number of days, not %r" % (value,))
        elif name == "vat_rate":
            rate = number(value, "vat_rate")
            if rate <= 0:
                raise NotTaken("vat_rate is %s, and every line is VAT category S, whose rate "
                               "is more than nought: no other category is built" % rate)
            value = str(rate)
        elif not isinstance(value, str):
            raise NotTaken("the supplier's %s is text, not %r" % (name, value))
        elif name == "endpoint":
            endpoint(value, "the supplier's")
        now[name] = value
    return now


def amount(value: Decimal, currency: str) -> Value:
    return Value(str(value.quantize(CENT, rounding=ROUND_HALF_UP)), {"currencyID": currency})


def plain(value: Decimal) -> str:
    """A number as an invoice writes it: as it was given, and with no exponent."""
    return format(value, "f")


def invoice(order: Order, who: dict, numbered: str, day: datetime.date,
            quantities: Optional[Dict[str, Decimal]] = None) -> Document:
    """The invoice for an order, or for these quantities of its lines (by the
    order's line numbers); without any, for all that is not yet billed. A line
    with nothing to bill is left out.

    A line's net amount is its quantity times its price, rounded to the cent
    with a half going up. The VAT is the rate on the sum of the lines, rounded
    the same way, once.
    """
    if quantities is None:
        quantities = {line.line: line.open for line in order.lines}
    currency = order.currency or who["currency"]
    rate = Decimal(who["vat_rate"])
    document = Document(kind="Invoice")
    for term, value in (
            ("BT-24", _specification.PEPPOL), ("BT-23", PROFILE), ("BT-1", numbered),
            ("BT-2", day.isoformat()),
            ("BT-9", (day + datetime.timedelta(days=who["payment_days"])).isoformat()),
            ("BT-3", "380"), ("BT-5", currency),
            # A buyer that gave no reference of its own gets its order number
            # back as one: Peppol's rules for Germany want a buyer reference
            # on every invoice.
            ("BT-10", order.reference or order.number), ("BT-13", order.number),
            ("BT-34", endpoint(who["endpoint"], "the supplier's")), ("BT-27", who["name"]),
            ("BT-31", who["vat"]), ("BT-35", who["street"]), ("BT-37", who["city"]),
            ("BT-38", who["postal_code"]), ("BT-40", who["country"]),
            ("BT-41", who["contact"]), ("BT-42", who["telephone"]), ("BT-43", who["email"]),
            ("BT-49", endpoint(order.buyer["endpoint"], "the buyer's")),
            ("BT-44", order.buyer["name"]), ("BT-48", order.buyer.get("vat", "")),
            ("BT-47", order.buyer.get("legal_id", "")),
            ("BT-50", order.buyer.get("street", "")), ("BT-52", order.buyer.get("city", "")),
            ("BT-53", order.buyer.get("postal_code", "")), ("BT-55", order.buyer["country"]),
            ("BT-30", who["legal_id"])):
        if isinstance(value, Value) or value:
            document.add(term, value)
    payment = document.new("BG-16")
    payment.add("BT-81", Value("30", {"name": "Credit transfer"}))
    payment.add("BT-83", numbered)
    for term, value in (("BT-84", who["iban"]), ("BT-85", who["name"]), ("BT-86", who["bic"])):
        if value:
            payment.add(term, value)
    total = Decimal(0)
    for line in order.lines:
        quantity = quantities.get(line.line, Decimal(0))
        if not quantity:
            continue
        net = (quantity * line.price).quantize(CENT, rounding=ROUND_HALF_UP)
        total += net
        written = document.new("BG-25")
        written.add("BT-126", str(len(document.all("BG-25"))))
        written.add("BT-129", Value(plain(quantity), {"unitCode": line.unit}))
        written.add("BT-131", amount(net, currency))
        written.add("BT-132", line.line)
        written.add("BT-153", line.name)
        for term, value in (("BT-155", line.seller_item), ("BT-156", line.buyer_item)):
            if value:
                written.add(term, value)
        written.add("BT-151", "S")
        written.add("BT-152", plain(rate))
        written.add("BT-146", Value(plain(line.price), {"currencyID": currency}))
    tax = (total * rate / 100).quantize(CENT, rounding=ROUND_HALF_UP)
    breakdown = document.new("BG-23")
    breakdown.add("BT-116", amount(total, currency))
    breakdown.add("BT-117", amount(tax, currency))
    breakdown.add("BT-118", "S")
    breakdown.add("BT-119", plain(rate))
    for term, value in (("BT-106", total), ("BT-109", total), ("BT-110", tax),
                        ("BT-112", total + tax), ("BT-115", total + tax)):
        document.add(term, amount(value, currency))
    return document
