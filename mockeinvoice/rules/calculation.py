"""The arithmetic of the published rules, which is XPath's and not Python's.

Two things differ from what a Python programmer would write.

Rounding. XPath's `round` takes a tie towards positive infinity: 2.5 is 3 and
-2.5 is -2. Python's `round` takes it to the even neighbour and `ROUND_HALF_UP`
takes it away from zero; on a credit, where amounts can be negative, all three
disagree. The rules round to cents as `round(x * 100) div 100`.

Nothing. In XPath a missing element is an empty sequence, and comparing
anything with an empty sequence is false: a total that is not there is not
equal to anything. So a rule about an amount that is absent fails, where
code that skipped `None` would pass it.

The same goes for what is not arithmetic. `normalize-space` knows four
characters of white space and no more; a comparison of an element with a
number reads the element as a double, and is an error if it is not one; a
date may carry a time zone.
"""
from __future__ import annotations

import datetime
import re
from decimal import ROUND_FLOOR, Decimal
from typing import Iterable, List, Optional

from ..model import DECIMAL, Group

HALF = Decimal("0.5")
SMALLEST_DOUBLE = Decimal("2.5e-324")     # below this a double rounds to zero
XML_SPACE = re.compile(r"[ \t\r\n]+")
DOUBLE = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?|-?INF|NaN")
XS_DATE = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})(Z|[+-][0-9]{2}:[0-9]{2})?")


class Incomputable(Exception):
    """The published test would end in an XPath error here, and why."""


def xpath_round(number: Decimal) -> Decimal:
    """To the nearest whole number, a tie going towards positive infinity."""
    return (number + HALF).to_integral_value(rounding=ROUND_FLOOR)


def cents(number: Optional[Decimal]) -> Optional[Decimal]:
    """`round(x * 10 * 10) div 100`, or nothing of nothing."""
    return None if number is None else xpath_round(number * 100) / 100


def one(group: Group, term: str) -> Optional[Decimal]:
    """A term's value as a number: `xs:decimal(cbc:X)` in a rule's test.

    None if the term is not there. If it is there twice, or is not a decimal,
    the cast is an XPath error and the rule cannot be computed.
    """
    values = group.values(term)
    if not values:
        return None
    if len(values) > 1:
        raise Incomputable("%s occurs %d times where the rule takes one" % (term, len(values)))
    number = values[0].number
    if number is None:
        raise Incomputable("%s is %r, which is not a decimal number" % (term, values[0].text))
    return number


def total(groups: Iterable[Group], term: str) -> Decimal:
    """The sum of a term over groups: `sum(X/xs:decimal(cbc:Y))`. A group
    without the term adds nothing, and the sum of none is zero."""
    return sum((n for n in (one(group, term) for group in groups) if n is not None),
               Decimal(0))


def plus(*numbers: Optional[Decimal]) -> Optional[Decimal]:
    """A sum, or nothing if any part of it is nothing."""
    return None if any(n is None for n in numbers) else sum(numbers, Decimal(0))


def minus(left: Optional[Decimal], right: Optional[Decimal]) -> Optional[Decimal]:
    return None if left is None or right is None else left - right


def equal(left: Optional[Decimal], right: Optional[Decimal]) -> bool:
    """Numerically equal. Nothing is equal to nothing, itself included."""
    return left is not None and right is not None and left == right


def shown(number: Optional[Decimal]) -> str:
    return "nothing" if number is None else format(number, "f")


def decimals_after_point(text: str) -> int:
    """`string-length(substring-after(text, '.'))`: on the text as written,
    so a space after the last digit counts, as it does in the rule."""
    return len(text.partition(".")[2])


def numbered(groups: List[Group], name: str):
    """Each group with its place in the model: ("BG-25[2]", line)."""
    for number, group in enumerate(groups, start=1):
        yield "%s[%d]" % (name, number) if len(groups) > 1 else name, group


def normalize_space(text: str) -> str:
    """XPath's `normalize-space`: space, tab, carriage return and line feed
    are white space, and a no-break space is a character like any other."""
    return XML_SPACE.sub(" ", text).strip(" ")


def said(group: Group, term: str) -> str:
    """`normalize-space(cbc:X)` in a rule's test: "" if the term is not there.

    If it is there twice the function is handed two things where it takes
    one, which is an XPath error.
    """
    values = group.values(term)
    if len(values) > 1:
        raise Incomputable("%s occurs %d times where the rule takes one" % (term, len(values)))
    return normalize_space(values[0].text) if values else ""


def doubles_of(texts: Iterable[str], what: str = "it") -> List[Optional[Decimal]]:
    """Texts as `cbc:X >= 0` reads them: each as an `xs:double`.

    That is wider than a decimal: `1e3` is one, and `INF`, and `NaN`, which
    is not greater than, less than or equal to anything and is None here.
    Text that is not a double is an XPath error. The numbers are held as
    decimals, as everything here is, with the one thing a double does that
    matters to a comparison with zero: what is too small for it is zero.
    """
    numbers: List[Optional[Decimal]] = []
    for written in texts:
        text = normalize_space(written)
        if not DOUBLE.fullmatch(text):
            raise Incomputable("%s is %r, which is not a number" % (what, written))
        if text == "NaN":
            numbers.append(None)
            continue
        number = Decimal(text.replace("INF", "Infinity"))
        numbers.append(Decimal(0) if abs(number) < SMALLEST_DOUBLE else number)
    return numbers


def doubles(group: Group, term: str) -> List[Optional[Decimal]]:
    """A term's values, each as an `xs:double`: see `doubles_of`."""
    return doubles_of((value.text for value in group.values(term)), term)


def date_of(text: str, what: str = "it") -> int:
    """`xs:date('...')`, as something to compare: the minute its day starts.

    A date may name a time zone, and one that names none is taken as UTC
    here; XPath leaves that to the implementation. Text that is not a date is
    an XPath error. So, here, is a year outside 0001 to 9999, which XPath can
    compute with and this cannot.
    """
    match = XS_DATE.fullmatch(normalize_space(text))
    try:
        if not match:
            raise ValueError
        day = datetime.date(*(int(part) for part in match.groups()[:3]))
        zone = match.group(4) or "Z"
        hours, minutes = (0, 0) if zone == "Z" else (int(zone[1:3]), int(zone[4:6]))
        if minutes > 59 or hours * 60 + minutes > 14 * 60:
            raise ValueError
    except ValueError:
        raise Incomputable("%s is %r, which is not a date" % (what, text))
    offset = hours * 60 + minutes
    return day.toordinal() * 1440 - (-offset if zone[0] == "-" else offset)


def xs_date(group: Group, term: str) -> Optional[int]:
    """`xs:date(cbc:X)` of a term: None if it is not there; twice, or not a
    date, is an XPath error."""
    values = group.values(term)
    if not values:
        return None
    if len(values) > 1:
        raise Incomputable("%s occurs %d times where the rule takes one" % (term, len(values)))
    return date_of(values[0].text, term)


def decimal_of(text: str, what: str = "it") -> Decimal:
    """`xs:decimal('...')`: an XPath error if the text is not a decimal."""
    trimmed = normalize_space(text)
    if not DECIMAL.fullmatch(trimmed):
        raise Incomputable("%s is %r, which is not a decimal number" % (what, text))
    return Decimal(trimmed)


def double_sum(text: str, by: str) -> Decimal:
    """`xs:decimal(element + 0.02)` in a published test: the sum as a double,
    made a decimal. An element in arithmetic is read as a double, so the sum
    is a double's, and exactly that double is what is compared. This is the
    one place a binary float is used, because the published tests use one.
    """
    trimmed = normalize_space(text)
    if not DOUBLE.fullmatch(trimmed) or "INF" in trimmed or trimmed == "NaN":
        raise Incomputable("%r is not a number a decimal can be made of" % text)
    return Decimal(float(trimmed) + float(by))


def nudged(group: Group, term: str, by: int) -> Optional[Decimal]:
    """`xs:decimal(cbc:X + 1)` in a rule's test, which is not the amount plus
    one: see `double_sum`. 100.10 less one is a hair under 99.10 that way, so
    at exactly one unit of leeway a rule passes or fails by the double.

    None if the term is not there; twice, or not a number, is an XPath error.
    """
    values = group.values(term)
    if not values:
        return None
    if len(values) > 1:
        raise Incomputable("%s occurs %d times where the rule takes one" % (term, len(values)))
    return double_sum(values[0].text, str(by))
