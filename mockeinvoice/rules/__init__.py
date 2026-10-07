"""Holding a document to the published rules, by their published names.

A rule here is one function under the identifier its publisher gave it
(`BR-CO-10`). What a finding says is that identifier, the flag the publisher
gave the rule (`fatal` or `warning`), where in the document it failed, a
description in this project's own words, and a link to where the rule itself
is published. The publisher's wording is not reproduced.

Layers
------
A document names its specification, and that decides its layers: the EN 16931
core always, then Peppol's rules or XRechnung's. `published` lists every rule
of every layer at the versions this package is pinned to.

What is not built is said
-------------------------
Most rules are not built yet. A `Report` lists the rules that ran and, layer
by layer, the published rules that did not, and its verdict follows from
both: a document with no failing rule is `valid` only when every fatal rule
of its layers ran. Until then the most it can be is `not judged`. Passing a
document on rules that were not run is the one thing this must never do.

How a rule is written
---------------------
The published rules are Schematron: XPath over the UBL document. Each
function says what its rule's test says, against the model, down to the
rule's own arithmetic (`calculation.py` has XPath's rounding, which is not
Python's). Where the published test would stop with an XPath error - a number
that is not a number, an element twice where the test takes one - a real
validator gives no verdict on the rule; here that is a failure of the rule
that says it could not be computed, because a document that cannot be checked
has not passed.
"""
from __future__ import annotations

import decimal
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, Iterator, List, Sequence, Tuple

from ..model import Document, Finding
from . import published
from .calculation import Incomputable

LAYERS_OF = {"peppol": ("en16931", "peppol"), "xrechnung": ("en16931", "xrechnung")}
FAILING = ("fatal", "error")

# A failure a rule reports: where in the model, and what was found there.
Failure = Tuple[str, str]


@dataclass(frozen=True)
class Rule:
    id: str
    layer: str
    about: str                      # what the rule asks, in our words
    check: Callable[[Document], Iterable[Failure]]

    @property
    def flag(self) -> str:
        return published.LAYERS[self.layer][self.id]

    @property
    def link(self) -> str:
        return published.SOURCES[self.layer][1]


REGISTRY: Dict[str, Dict[str, Rule]] = {layer: {} for layer in published.LAYERS}


def rule(layer: str, identifier: str, about: str) -> Callable:
    """Register a function as a published rule. The identifier must be one
    its layer publishes, and no rule is written twice."""
    def register(check: Callable[[Document], Iterable[Failure]]) -> Callable:
        if identifier not in published.LAYERS[layer]:
            raise ValueError("%s is not a rule %s publishes" % (identifier, layer))
        if identifier in REGISTRY[layer]:
            raise ValueError("%s is written twice" % identifier)
        REGISTRY[layer][identifier] = Rule(identifier, layer, about, check)
        return check
    return register


@dataclass
class Report:
    """What became of a document: what was found, and what was not asked."""
    specification: str
    findings: List[Finding] = field(default_factory=list)
    ran: List[str] = field(default_factory=list)
    # The published rules of the document's layers that are not built, by
    # layer, each with its flag.
    not_built: Dict[str, Dict[str, str]] = field(default_factory=dict)

    @property
    def failures(self) -> List[Finding]:
        return [f for f in self.findings if f.level in FAILING]

    @property
    def unasked(self) -> int:
        """How many fatal rules of the document's layers were never run."""
        return sum(1 for rules in self.not_built.values()
                   for flag in rules.values() if flag == "fatal")

    @property
    def verdict(self) -> str:
        """`invalid`, `not judged` or `valid`.

        `not judged` is a document nothing was found wrong with, by a
        validator that has fatal rules left to build. It is not `valid`.
        """
        if self.failures:
            return "invalid"
        return "not judged" if self.unasked else "valid"


def check(document: Document, specification: str,
          reading: Sequence[Finding] = ()) -> Report:
    """Hold a document to the rules of its specification that are built.

    `reading` is what the reader had to say about the document; it goes at
    the head of the report and counts towards the verdict.
    """
    if specification not in LAYERS_OF:
        raise ValueError("a specification is one of %s, not %r"
                         % (", ".join(sorted(LAYERS_OF)), specification))
    report = Report(specification, list(reading))
    for layer in LAYERS_OF[specification]:
        report.findings.extend(run(document, layer))
        report.ran.extend(REGISTRY[layer])
        report.not_built[layer] = {identifier: flag
                                   for identifier, flag in published.LAYERS[layer].items()
                                   if identifier not in REGISTRY[layer]}
    return report


def run(document: Document, layer: str) -> Iterator[Finding]:
    """Every failure of one layer's built rules, in the order they are published."""
    # Sums of amounts are exact in decimal arithmetic given room for them.
    with decimal.localcontext() as context:
        context.prec = 60
        for identifier in published.LAYERS[layer]:
            found = REGISTRY[layer].get(identifier)
            if found is None:
                continue
            try:
                failures = list(found.check(document))
            except Incomputable as error:
                failures = [("", "could not be computed: %s" % error)]
            for path, detail in failures:
                yield Finding(found.flag, identifier, path or "/",
                              "%s: %s" % (found.about, detail), found.link)


from . import en16931 as _en16931  # noqa: E402,F401  (registers its rules)
