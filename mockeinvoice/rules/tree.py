"""Walking the document as XML, for the rules that are about the XML.

Most rules are asked of the model. The rules about the UBL document itself
(`en16931_ubl.py`) cannot be: they say an element UBL has and the standard
does not is not to be there, and the model holds only what the standard has.
So they are asked of the document's elements, and this is the little of XPath
they need: a path of names from an element, `//` for anywhere, `(a|b)` for
either of two names, and `@name` for an attribute at the end.
"""
from __future__ import annotations

import re
from typing import Dict, Iterator, List, Optional, Sequence, Tuple

from ..ubl import CAC_NS, CBC_NS, CREDIT_NOTE_NS, INVOICE_NS, Node, paths
from .calculation import Incomputable, normalize_space

NAMESPACES = {
    "cac": CAC_NS, "cbc": CBC_NS, "ubl": INVOICE_NS, "cn": CREDIT_NOTE_NS,
    "ext": "urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2",
}
ROOT = "/ubl:Invoice | /cn:CreditNote"
PREDICATE = re.compile(r"(\w+:\w+)\[cbc:ChargeIndicator = (true|false)\(\)\]")


class At:
    """An element, where it is, and what it is in."""
    __slots__ = ("node", "path", "parent", "_children", "_all")

    def __init__(self, node: Node, path: str, parent: Optional["At"] = None):
        self.node, self.path, self.parent = node, path, parent
        self._children: Optional[List["At"]] = None
        self._all: Optional[List["At"]] = None

    @property
    def children(self) -> List["At"]:
        if self._children is None:
            self._children = [At(child, where, self) for child, where in
                              zip(self.node.children, paths(self.node, self.path))]
        return self._children

    @property
    def text(self) -> str:
        return self.node.text

    def everything(self) -> List["At"]:
        """This element and every one under it, in the document's order.
        Walked once: a few hundred rules ask it of the root."""
        if self._all is None:
            self._all = [self]
            for child in self.children:
                self._all += child.everything()
        return self._all

    def ancestors(self) -> Iterator["At"]:
        at = self.parent
        while at is not None:
            yield at
            at = at.parent


def top(root: Node) -> At:
    local = root.tag.rpartition("}")[2]
    return At(root, "/" + local)


def tag(name: str) -> str:
    prefix, _, local = name.partition(":")
    return "{%s}%s" % (NAMESPACES[prefix], local)


Step = Tuple[str, Tuple[str, ...]]      # ("child", tags) or ("attribute", (name,))


def compiled(path: str) -> Tuple[bool, List[Step]]:
    """A path as (whether it starts anywhere, its steps)."""
    anywhere = path.startswith("//")
    steps: List[Step] = []
    for step in path.lstrip("/").split("/"):
        if step.startswith("@"):
            steps.append(("attribute", (step[1:],)))
        else:
            steps.append(("child", tuple(tag(name) for name in step.strip("()").split("|"))))
    return anywhere, steps


_COMPILED: Dict[str, Tuple[bool, List[Step]]] = {}


def select(start: At, path: str) -> List[Tuple[str, str]]:
    """What a path finds from an element: each as (where, its text).

    A path that ends in an attribute finds the attribute, and its text is the
    attribute's value.
    """
    if path not in _COMPILED:
        _COMPILED[path] = compiled(path)
    anywhere, steps = _COMPILED[path]
    # `//a` is every `a` in the document, the root too if that is its name;
    # `//@a` is the attribute on any element.
    found: List[At] = [start]
    if anywhere:
        root = start
        while root.parent is not None:
            root = root.parent
        everything = root.everything()
        kind, names = steps[0]
        if kind == "attribute":
            return [("%s/@%s" % (at.path, names[0]), at.node.attributes[names[0]])
                    for at in everything if names[0] in at.node.attributes]
        found, steps = [at for at in everything if at.node.tag in names], steps[1:]
    for kind, names in steps:
        if kind == "attribute":
            return [("%s/@%s" % (at.path, names[0]), at.node.attributes[names[0]])
                    for at in found if names[0] in at.node.attributes]
        found = [child for at in found for child in at.children if child.node.tag in names]
    return [(at.path, at.text) for at in found]


def elements(start: At, path: str) -> List[At]:
    """The elements a path of names finds from an element."""
    found = [start]
    for name in path.split("/"):
        wanted = tag(name)
        found = [child for at in found for child in at.children if child.node.tag == wanted]
    return found


def boolean(text: str) -> bool:
    """`cbc:ChargeIndicator = true()`: the text as an `xs:boolean`, which is
    an XPath error if it is not one."""
    trimmed = normalize_space(text)
    if trimmed not in ("true", "false", "1", "0"):
        raise Incomputable("a charge indicator is %r, which is neither true nor false" % text)
    return trimmed in ("true", "1")


def contexts(root: At, context: str) -> List[At]:
    """The elements a rule is asked of.

    A context is the root, or names: an element wherever it is, or one in
    another (`cac:Party` in `cac:AccountingSupplierParty`), with `|` between
    alternatives, and for allowances and charges which of the two it is.
    """
    if context == ROOT:
        return [root]
    found: List[At] = []
    everything = root.everything()
    for alternative in context.split(" | "):
        alternative = alternative.lstrip("/")
        indicator: Optional[bool] = None
        match = PREDICATE.fullmatch(alternative)
        if match:
            alternative, indicator = match.group(1), match.group(2) == "true"
        names = [tag(name) for name in alternative.split("/")]
        for at in everything:
            if at.node.tag != names[-1]:
                continue
            ancestors = [a.node.tag for a in at.ancestors()][:len(names) - 1]
            if ancestors != names[-2::-1]:
                continue
            if indicator is not None and not any(
                    boolean(i.text) == indicator for i in elements(at, "cbc:ChargeIndicator")):
                continue
            found.append(at)
    return found


def texts(found: Sequence[At]) -> List[str]:
    return [at.text for at in found]
