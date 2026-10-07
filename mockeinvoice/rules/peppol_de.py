"""Peppol BIS Billing 3.0: the rules for a seller and a buyer both in Germany.

`DE-R-001` to `DE-R-031` and `DE-R-T02`: 31 rules, 24 fatal. Every one is
asked only where the seller's address and the buyer's address both name
Germany, however `DE` is written: a German seller invoicing a buyer abroad is
asked none of these.

They are Peppol's rendering of XRechnung's rules, and the tests are the same
tests: `german.py` has them, and says what is in them.
"""
from __future__ import annotations

import functools
from typing import Iterator

from . import Failure, german, rule
from .peppol import both_german
from .tree import At

peppol = functools.partial(rule, "peppol", over="tree")


def in_germany(check):
    """Asked only of a document whose seller and buyer are both in Germany."""
    @functools.wraps(check)
    def gated(root: At) -> Iterator[Failure]:
        if both_german(root):
            yield from check(root)
    return gated


german.build(lambda key, about: lambda check: peppol("DE-R-" + key, about)(in_germany(check)))
