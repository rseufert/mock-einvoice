"""Peppol's Invoice Response (T111), release 3.0.17: its rules.

Eighty-two are published, in three kinds.

- `PEPPOL-T111-B*` (54), about the structure: what must be there, what may
  not be, and which code a coded value is. Peppol generates these from a
  description of the message; here they are generated the same way, from
  `response.STRUCTURE` and the table below, under the published identifiers.
- `PEPPOL-T111-R001` to `R008` (8), about what a response says: a reason is
  owed where an invoice is queried, conditionally accepted or rejected.
- `PEPPOL-COMMON-*` (20): no empty elements, dates, and the checksums of
  identifiers by their scheme, which are the tests Peppol has for an invoice
  and are the same code (`peppol.py`).

Written by hand from reading the tests; nothing is copied from Peppol's rule
file. The three short code lists are in `response.py` with their meanings,
and the long one, UNTDID 1001, is in `untdid.py` from the United Nations'
own directory.

What the published tests say that one might not expect
------------------------------------------------------
- **`PEPPOL-T111-R005` cannot fail.** It is meant to say that the reason
  `PPD`, partially paid, goes only with the response `PD`, paid. Its test
  asks whether a comparison exists, and a comparison always does, true or
  false. It is registered and runs, and finds nothing, here as anywhere.
- **A reason is owed by its response code's text among others**
  (`R001`): the test looks for the code, with a space either side, in
  ` CA UQ RE `, so a code of `CA UQ` is one of them too.
- **An element with no place in a response is fatal** (the `B` rules that
  say "no other element here"), where in an invoice it is a warning. But a
  second `cbc:Note` is not: the rules name what may be there, not how often.
- **The type code of the document answered is held to an old edition of
  the list, with a year in it** (`B04201`). Peppol's list is UNTDID 1001 as
  of 2017, which has not the codes 817, 875, 876 and 877 that Peppol's own
  billing rules allow an invoice: a response to such an invoice fails this
  rule. And
  it has one entry that is no code, `1999`, a year from the description of
  code 423, which therefore passes. Both are built as published.
- **`schemaLocation` on the root is asked twice**, as a warning
  (`PEPPOL-COMMON-R003`) and as fatal (`PEPPOL-T111-B00108`).
"""
from __future__ import annotations

import functools
from typing import Dict, Iterator, List, Optional, Tuple

from .. import response
from . import Failure, rule
from .calculation import Incomputable, date_of, normalize_space
from .codelists import LISTS
from .peppol import ADDRESS_SCHEMES, OTHERS, SCHEMES, by_scheme, codes, named
from .tree import At, elements, texts
from .untdid import DOCUMENT_NAME_CODES

t111 = functools.partial(rule, "peppol-response", over="tree")

ICD = codes("BR-CL-11")         # ISO 6523: the same list the core has
LIST_IDS = (response.ACTION_LIST, response.REASON_LIST)
assert LISTS


# -- the structure ------------------------------------------------------------------

def at_path(root: At, path: str) -> List[At]:
    """The elements at a path of names from the root: "" is the root."""
    return elements(root, path) if path else [root]


def required(identifier: str, path: str, child: str) -> None:
    what = "the attribute %s" % child[1:] if child.startswith("@") else child

    @t111(identifier, "%s has %s" % (path.rpartition("/")[2] or "a response", what))
    def check(root: At) -> Iterator[Failure]:
        for at in at_path(root, path):
            there = (child[1:] in at.node.attributes if child.startswith("@")
                     else bool(elements(at, child)))
            if not there:
                yield at.path, "it has none"


def nothing_else(identifier: str, path: str) -> None:
    """No element here but those a response has a place for."""
    allowed: object = response.STRUCTURE
    for step in path.split("/") if path else ():
        allowed = allowed[step]         # type: ignore[index]
    tags = {response.name(short) for short in allowed}      # type: ignore[union-attr]

    @t111(identifier, "%s holds no element a response has no place for"
          % (path.rpartition("/")[2] or "a response"))
    def check(root: At) -> Iterator[Failure]:
        for at in at_path(root, path):
            for child in at.children:
                if child.node.tag not in tags:
                    yield child.path, "it is there"


def coded(identifier: str, path: str, attribute: str, allowed, what: str) -> None:
    @t111(identifier, "%s is %s" % (
        "the %s of %s" % (attribute, path.rpartition("/")[2]) if attribute
        else path.rpartition("/")[2], what))
    def check(root: At) -> Iterator[Failure]:
        for at in at_path(root, path):
            if attribute:
                # Asked only where the attribute is; that it is there is another rule's.
                if attribute in at.node.attributes and at.node.attributes[attribute] not in allowed:
                    yield at.path, "it is %r" % at.node.attributes[attribute]
            elif normalize_space(at.text) not in allowed:
                yield at.path, "it is %r" % at.text


SENDER, RECEIVER, ANSWER = "cac:SenderParty", "cac:ReceiverParty", "cac:DocumentResponse"
RESPONSE, STATUS = ANSWER + "/cac:Response", ANSWER + "/cac:Response/cac:Status"
REFERENCE = ANSWER + "/cac:DocumentReference"
ISSUER, RECIPIENT = ANSWER + "/cac:IssuerParty", ANSWER + "/cac:RecipientParty"

# Each published rule about the structure: its number, where it is asked,
# and what of. A name is a child that must be there, `@name` an attribute,
# `*` that nothing else is, and a pair is a code list for an attribute (or,
# with no attribute, for the text).
EAS = (ADDRESS_SCHEMES, "an electronic address scheme Peppol has")
ISO6523 = (ICD, "an ISO 6523 ICD code")
BASIC: Tuple[Tuple[str, str, object], ...] = (
    ("00101", "", "cbc:CustomizationID"), ("00102", "", "cbc:ProfileID"), ("00103", "", "cbc:ID"),
    ("00104", "", "cbc:IssueDate"), ("00105", "", SENDER), ("00106", "", RECEIVER),
    ("00107", "", ANSWER), ("00109", "", "*"),
    ("00801", SENDER, "cbc:EndpointID"), ("00802", SENDER, "cac:PartyLegalEntity"),
    ("00803", SENDER, "*"),
    ("00901", SENDER + "/cbc:EndpointID", "@schemeID"),
    ("00902", SENDER + "/cbc:EndpointID", ("schemeID",) + EAS),
    ("01101", SENDER + "/cac:PartyIdentification", "cbc:ID"),
    ("01201", SENDER + "/cac:PartyIdentification/cbc:ID", ("schemeID",) + ISO6523),
    ("01401", SENDER + "/cac:PartyLegalEntity", "cbc:RegistrationName"),
    ("01402", SENDER + "/cac:PartyLegalEntity", "*"),
    ("01601", SENDER + "/cac:Contact", "*"),
    ("02001", RECEIVER, "cbc:EndpointID"), ("02002", RECEIVER, "cac:PartyLegalEntity"),
    ("02003", RECEIVER, "*"),
    ("02101", RECEIVER + "/cbc:EndpointID", "@schemeID"),
    ("02102", RECEIVER + "/cbc:EndpointID", ("schemeID",) + EAS),
    ("02301", RECEIVER + "/cac:PartyIdentification", "cbc:ID"),
    ("02401", RECEIVER + "/cac:PartyIdentification/cbc:ID", ("schemeID",) + ISO6523),
    ("02601", RECEIVER + "/cac:PartyLegalEntity", "cbc:RegistrationName"),
    ("02602", RECEIVER + "/cac:PartyLegalEntity", "*"),
    ("02801", ANSWER, "cac:Response"), ("02802", ANSWER, "cac:DocumentReference"),
    ("02803", ANSWER, "*"),
    ("02901", RESPONSE, "cbc:ResponseCode"), ("02902", RESPONSE, "*"),
    ("03001", RESPONSE + "/cbc:ResponseCode", ("", frozenset(response.CODES),
                                               "one of the seven response codes")),
    ("03201", STATUS, "*"),
    ("03301", STATUS + "/cbc:StatusReasonCode", (
        "", frozenset(response.REASONS) | frozenset(response.ACTIONS),
        "a reason or an action Peppol has a code for")),
    ("03302", STATUS + "/cbc:StatusReasonCode", "@listID"),
    ("03303", STATUS + "/cbc:StatusReasonCode", ("listID", LIST_IDS,
                                                 "OPStatusReason or OPStatusAction")),
    ("03601", STATUS + "/cac:Condition", "cbc:AttributeID"),
    ("03602", STATUS + "/cac:Condition", "*"),
    ("03901", REFERENCE, "cbc:ID"), ("03902", REFERENCE, "cbc:DocumentTypeCode"),
    ("03903", REFERENCE, "*"),
    # UNTDID 1001 as Peppol has it: edition D.17A, and `1999`, which is in
    # Peppol's list and is no code of the United Nations'.
    ("04201", REFERENCE + "/cbc:DocumentTypeCode", (
        "", DOCUMENT_NAME_CODES | {"1999"}, "a UNTDID 1001 document name code")),
    ("04301", ISSUER, "cac:PartyName"), ("04302", ISSUER, "*"),
    ("04401", ISSUER + "/cac:PartyIdentification", "cbc:ID"),
    ("04501", ISSUER + "/cac:PartyIdentification/cbc:ID", ("schemeID",) + ISO6523),
    ("04701", ISSUER + "/cac:PartyName", "cbc:Name"),
    ("04901", RECIPIENT, "cac:PartyName"), ("04902", RECIPIENT, "*"),
    ("05001", RECIPIENT + "/cac:PartyIdentification", "cbc:ID"),
    ("05101", RECIPIENT + "/cac:PartyIdentification/cbc:ID", ("schemeID",) + ISO6523),
    ("05301", RECIPIENT + "/cac:PartyName", "cbc:Name"),
)

for _number, _path, _what in BASIC:
    _identifier = "PEPPOL-T111-B" + _number
    if _what == "*":
        nothing_else(_identifier, _path)
    elif isinstance(_what, tuple):
        coded(_identifier, _path, *_what)
    else:
        required(_identifier, _path, _what)     # type: ignore[arg-type]


def located(root: At) -> List[str]:
    """`@*:schemaLocation`: the attribute by that name in any namespace."""
    return [key for key in root.node.attributes if key.rpartition("}")[2] == "schemaLocation"]


def no_schema_location(identifier: str) -> None:
    @t111(identifier, "the document does not say where its schema is")
    def check(root: At) -> Iterator[Failure]:
        for key in located(root):
            yield "%s/@schemaLocation" % root.path, "it does"


no_schema_location("PEPPOL-T111-B00108")
no_schema_location("PEPPOL-COMMON-R003")


# -- what a response says ---------------------------------------------------------------

def said(at: At, name: str) -> str:
    found = elements(at, name)
    if len(found) > 1:
        raise Incomputable("%s occurs %d times where the rule takes one" % (name, len(found)))
    return normalize_space(found[0].text) if found else ""


def statuses(root: At, code: str) -> List[At]:
    """Every status with this reason code, as written."""
    return [at for at in named(root, "cac:Status")
            if code in texts(elements(at, "cbc:StatusReasonCode"))]


@t111("PEPPOL-T111-R001", "a response of under query (UQ), conditionally accepted (CA) or "
                          "rejected (RE) gives a reason code")
def r001(root: At) -> Iterator[Failure]:
    for answer in named(root, "cac:Response"):
        # The code is looked for in the text ` CA UQ RE ` with a space either
        # side, which finds `CA UQ` too.
        if (" %s " % said(answer, "cbc:ResponseCode") in " CA UQ RE "
                and not elements(answer, "cac:Status/cbc:StatusReasonCode")):
            yield answer.path, "it gives none"


@t111("PEPPOL-T111-R002", "the reason `OTH`, other, comes with a text that says what")
def r002(root: At) -> Iterator[Failure]:
    for status in statuses(root, "OTH"):
        if not elements(status, "cbc:StatusReason"):
            yield status.path, "it has none"


@t111("PEPPOL-T111-R003", "the specification identifier is the Invoice Response's")
def r003(root: At) -> Iterator[Failure]:
    for at in named(root, "cbc:CustomizationID"):
        if not normalize_space(at.text).startswith(response.SPECIFICATION):
            yield at.path, "it is %r" % at.text


@t111("PEPPOL-T111-R004", "the reason `PPD`, partially paid, comes with a text")
def r004(root: At) -> Iterator[Failure]:
    for status in statuses(root, "PPD"):
        # A status that is also `OTH` was asked the rule about that, which
        # is earlier in the pattern, and is asked no other.
        if status in statuses(root, "OTH"):
            continue
        if not elements(status, "cbc:StatusReason"):
            yield status.path, "it has none"


@t111("PEPPOL-T111-R005", "the reason `PPD`, partially paid, goes only with the response "
                          "`PD`, paid (published with a test that cannot fail)")
def r005(_root: At) -> Iterator[Failure]:
    return iter(())


def reason_in_its_list(identifier: str, list_id: str, allowed: Dict[str, str],
                       earlier: Optional[str] = None) -> None:
    @t111(identifier, "a reason code that names the list %s is one of that list's" % list_id)
    def check(root: At) -> Iterator[Failure]:
        for status in named(root, "cac:Status"):
            lists = [code.node.attributes.get("listID")
                     for code in elements(status, "cbc:StatusReasonCode")]
            if list_id not in lists or (earlier and earlier in lists):
                continue
            if said(status, "cbc:StatusReasonCode") not in allowed:
                yield status.path, "it is %r" % said(status, "cbc:StatusReasonCode")


reason_in_its_list("PEPPOL-T111-R006", response.ACTION_LIST, response.ACTIONS)
reason_in_its_list("PEPPOL-T111-R007", response.REASON_LIST, response.REASONS,
                   earlier=response.ACTION_LIST)


@t111("PEPPOL-T111-R008", "the profile is the Invoice Response's, or billing with response")
def r008(root: At) -> Iterator[Failure]:
    for at in named(root, "cbc:ProfileID"):
        if normalize_space(at.text) not in (response.PROFILE, response.BILLING_WITH_RESPONSE):
            yield at.path, "it is %r" % at.text


# -- what Peppol asks of every document -----------------------------------------------------

@t111("PEPPOL-COMMON-R001", "no element is empty")
def common_r001(root: At) -> Iterator[Failure]:
    for at in root.everything():
        if not at.children and not normalize_space(at.text):
            yield at.path, "it is"


DATES = ("cbc:IssueDate", "cbc:DueDate", "cbc:TaxPointDate", "cbc:StartDate", "cbc:EndDate",
         "cbc:ActualDeliveryDate")


@t111("PEPPOL-COMMON-R030", "a date is ten characters, `YYYY-MM-DD`")
def common_r030(root: At) -> Iterator[Failure]:
    for at in named(root, *DATES):
        try:
            well_formed = len(at.text) == 10 and date_of(at.text) is not None
        except Incomputable:
            well_formed = False
        if not well_formed:
            yield at.path, "it is %r" % at.text


for _scheme in SCHEMES:
    by_scheme(*_scheme, register=t111)
for _identifier, _about, _check in OTHERS:
    t111(_identifier, _about)(_check)
