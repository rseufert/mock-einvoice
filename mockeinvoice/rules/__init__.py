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
Some rules are not built yet. A `Report` lists the rules that ran and, layer
by layer, the published rules that did not, and its verdict follows from
both: a document with no failing rule is `valid` only when every fatal rule
of its layers that could apply to it ran. Until then the most it can be is `not judged`. Passing a
document on rules that were not run is the one thing this must never do.

A rule that could not apply is not waited on: the rules Peppol has for a
seller in one country say nothing of a document from another, and are listed
apart as not applicable (`SCOPES`).

Two things a rule can be asked of
---------------------------------
Most rules are asked of the model. The rules about the UBL document itself
(`UBL-CR`, `UBL-DT`, `UBL-SR`) are asked of its elements, because they are
about elements the model does not hold. `validate` gives them the document
as it was sent. `check`, given only a model, asks them of the document that
model would be written as, since that is the only XML there is.

Where one of those rules reports an element, what the reader said of the
same element is left out of the report: "not held" and "repeated" are the
reader's words for what the published rule says under its own name.

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
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

from ..model import Document, Finding
from . import published
from .calculation import Incomputable

LAYERS_OF = {"peppol": ("en16931", "peppol"), "xrechnung": ("en16931", "xrechnung")}
# A response to an invoice is held to one layer, and has no model the rules
# are asked of: every one of them is about its elements.
RESPONSE = "peppol-response"
FAILING = ("fatal", "error")

# A failure a rule reports: where in the model, and what was found there.
Failure = Tuple[str, str]


@dataclass(frozen=True)
class Rule:
    id: str
    layer: str
    about: str                      # what the rule asks, in our words
    check: Callable[[Any], Iterable[Failure]]
    # What it is asked of: the "model", or the "tree" of the document's
    # elements (`tree.At`, the root).
    over: str = "model"

    @property
    def flag(self) -> str:
        return published.LAYERS[self.layer][self.id]

    @property
    def link(self) -> str:
        return published.SOURCES[self.layer][1]


REGISTRY: Dict[str, Dict[str, Rule]] = {layer: {} for layer in published.LAYERS}


def rule(layer: str, identifier: str, about: str, over: str = "model") -> Callable:
    """Register a function as a published rule. The identifier must be one
    its layer publishes, and no rule is written twice."""
    def register(check: Callable[[Any], Iterable[Failure]]) -> Callable:
        if identifier not in published.LAYERS[layer]:
            raise ValueError("%s is not a rule %s publishes" % (identifier, layer))
        if identifier in REGISTRY[layer]:
            raise ValueError("%s is written twice" % identifier)
        REGISTRY[layer][identifier] = Rule(identifier, layer, about, check, over)
        return check
    return register


@dataclass
class Report:
    """What became of a document: what was found, and what was not asked."""
    specification: str
    findings: List[Finding] = field(default_factory=list)
    ran: List[str] = field(default_factory=list)
    # The published rules of the document's layers that are not built and
    # could apply to it, by layer, each with its flag.
    not_built: Dict[str, Dict[str, str]] = field(default_factory=dict)
    # And those that are not built and cannot apply to it: the rules for a
    # seller's country, of a document from another. They are not waited on.
    not_applicable: Dict[str, Dict[str, str]] = field(default_factory=dict)

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
          reading: Sequence[Finding] = (), sent=None) -> Report:
    """Hold a document to the rules of its specification that are built.

    `reading` is what the reader had to say about the document; it goes at
    the head of the report and counts towards the verdict. `sent` is the
    document's elements as they were sent (`ubl.parse_tree`); without it the
    rules about the XML are asked of the model as it would be written.
    """
    if specification not in LAYERS_OF:
        raise ValueError("a specification is one of %s, not %r"
                         % (", ".join(sorted(LAYERS_OF)), specification))
    from .. import ubl
    from . import tree
    if sent is None:
        sent = ubl.tree(ubl.write(document))
    root = tree.top(sent)
    report = Report(specification)
    for layer in LAYERS_OF[specification]:
        report.findings.extend(run(document, layer, sent))
        report.ran.extend(REGISTRY[layer])
        report.not_built[layer], report.not_applicable[layer] = {}, {}
        for identifier, flag in published.LAYERS[layer].items():
            if identifier not in REGISTRY[layer]:
                could = could_apply(layer, identifier, root)
                (report.not_built if could else report.not_applicable)[layer][identifier] = flag
    report.findings[:0] = unsaid(reading, report.findings)
    return report


def check_response(sent, reading: Sequence[Finding] = ()) -> Report:
    """Hold an Invoice Response to its rules: `sent` is its elements
    (`response.parse_tree`), and `reading` what the reader said of it."""
    report = Report(RESPONSE)
    report.findings.extend(run(None, RESPONSE, sent))
    report.ran.extend(REGISTRY[RESPONSE])
    report.not_built[RESPONSE] = {identifier: flag
                                  for identifier, flag in published.LAYERS[RESPONSE].items()
                                  if identifier not in REGISTRY[RESPONSE]}
    report.not_applicable[RESPONSE] = {}
    report.findings[:0] = unsaid(reading, report.findings)
    return report


# By layer, the rule sets that are for some documents only: the start of
# their rules' names, and whether a document is one of theirs. Filled by the
# layer's module. A set is listed only where every one of its published rules
# asks the same question of the document before anything else.
SCOPES: Dict[str, Dict[str, Callable[[Any], bool]]] = {layer: {} for layer in published.LAYERS}


def could_apply(layer: str, identifier: str, root: Any) -> bool:
    """Whether an unbuilt rule could have anything to say of this document.
    Every rule could, but one of a set the document is outside of."""
    for prefix, within in SCOPES[layer].items():
        if identifier.startswith(prefix):
            return within(root)
    return True


def unsaid(reading: Sequence[Finding], found: Sequence[Finding]) -> List[Finding]:
    """What the reader said that no rule about the XML has said.

    The reader reports an element it does not hold, and one repeated where
    the standard has one. Where a published rule reports that element, or
    something in it, under its own name, the reader's finding is dropped.
    """
    # A rule asked of the document's elements says where as a path from its root.
    places = [finding.path for finding in found if finding.path.startswith("/")]
    return [finding for finding in reading
            if finding.code not in ("UNHELD", "REPEATED")
            or not any(place == finding.path or place.startswith(finding.path + "/")
                       or place.startswith(finding.path + "[")
                       for place in places)]


def run(document: Document, layer: str, sent=None) -> Iterator[Finding]:
    """Every failure of one layer's built rules, in the order they are published."""
    root = None
    # Sums of amounts are exact in decimal arithmetic given room for them.
    with decimal.localcontext() as context:
        context.prec = 60
        for identifier in published.LAYERS[layer]:
            found = REGISTRY[layer].get(identifier)
            if found is None:
                continue
            if found.over == "tree" and root is None:
                from .. import ubl
                from . import tree
                root = tree.top(sent if sent is not None else ubl.tree(ubl.write(document)))
            try:
                failures = list(found.check(root if found.over == "tree" else document))
            except Incomputable as error:
                failures = [("", "could not be computed: %s" % error)]
            for path, detail in failures:
                yield Finding(found.flag, identifier, path or "/",
                              "%s: %s" % (found.about, detail), found.link)


from . import en16931 as _en16931  # noqa: E402,F401  (registers its rules)
from . import en16931_codes as _en16931_codes  # noqa: E402,F401
from . import en16931_ubl as _en16931_ubl  # noqa: E402,F401
from . import en16931_vat as _en16931_vat  # noqa: E402,F401
from . import peppol as _peppol  # noqa: E402,F401
from . import peppol_de as _peppol_de  # noqa: E402,F401

from . import xrechnung as _xrechnung  # noqa: E402,F401
from . import peppol_response as _peppol_response  # noqa: E402,F401

SCOPES["peppol"].update(_peppol.SCOPES)
SCOPES["xrechnung"].update(_xrechnung.SCOPES)
