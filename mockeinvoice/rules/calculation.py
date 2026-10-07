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
"""
from __future__ import annotations

from decimal import ROUND_FLOOR, Decimal
from typing import Iterable, List, Optional

from ..model import Group

HALF = Decimal("0.5")


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
