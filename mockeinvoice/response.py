"""The Peppol Invoice Response: what a buyer answers an invoice with.

A UBL `ApplicationResponse` (Peppol's transaction T111) that says what has
become of an invoice or credit note: acknowledged, in process, under query,
conditionally accepted, rejected, accepted or paid, and why.

    from mockeinvoice import read_response, write_response, validate_response

    response, findings = read_response(xml)
    response.code                       # "RE"
    response.statuses[0].reason_code    # "REF", from the list in .list_id
    response.document.id                # the invoice number it answers
    xml = write_response(response)

    response, report = validate_response(xml)
    report.verdict

`STRUCTURE` is the whole of what a response may hold, and the reader, the
writer and the rules about its structure (`rules/peppol_response.py`) all go
by it. What a document has besides is reported and not held, as with an
invoice.

XRechnung has no such message. An XRechnung invoice gets a verdict and
nothing after it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Union

from .model import Finding, Refused, Value
from .ubl import CAC_NS, CBC_NS, Node, cac, cbc, paths, qname, serialise, tree

NAMESPACE = "urn:oasis:names:specification:ubl:schema:xsd:ApplicationResponse-2"
ROOT = "{%s}ApplicationResponse" % NAMESPACE
SPECIFICATION = "urn:fdc:peppol.eu:poacc:trns:invoice_response:3"
PROFILE = "urn:fdc:peppol.eu:poacc:bis:invoice_response:3"
# The profile a response has when it answers an invoice sent under billing's
# profile 02, where a response is a required step.
BILLING_WITH_RESPONSE = "urn:peppol:bis:billing_with_response"

# The seven things a response can say, with UN/ECE's names for them.
CODES = {
    "AB": "message acknowledgement", "IP": "in process", "UQ": "under query",
    "CA": "conditionally accepted", "RE": "rejected", "AP": "accepted", "PD": "paid",
}
# Why, where a reason is given: what is wrong, and what the seller is to do.
REASONS = {
    "NON": "no issue", "REF": "references incorrect", "LEG": "legal information incorrect",
    "REC": "receiver unknown", "QUA": "item quality insufficient", "DEL": "delivery issues",
    "PRI": "prices incorrect", "QTY": "quantity incorrect", "ITM": "items incorrect",
    "PAY": "payment terms incorrect", "UNR": "not recognized", "FIN": "finance incorrect",
    "PPD": "partially paid", "OTH": "other",
}
ACTIONS = {
    "NOA": "no action required", "PIN": "provide information", "NIN": "issue new invoice",
    "CNF": "credit fully", "CNP": "credit partially", "CNA": "credit the amount", "OTH": "other",
}
REASON_LIST, ACTION_LIST = "OPStatusReason", "OPStatusAction"

# What a response may hold: each element's children, in the order UBL has
# them, and None for one that holds text. `MANY` are the two that repeat.
LEAF = None
PARTY_IDENTIFICATION = {"cac:PartyIdentification": {"cbc:ID": LEAF}}
LEGAL_NAME = {"cac:PartyLegalEntity": {"cbc:RegistrationName": LEAF}}
NAMED = dict(PARTY_IDENTIFICATION, **{"cac:PartyName": {"cbc:Name": LEAF}})
STRUCTURE: Dict[str, object] = {
    "cbc:CustomizationID": LEAF, "cbc:ProfileID": LEAF, "cbc:ID": LEAF, "cbc:IssueDate": LEAF,
    "cbc:IssueTime": LEAF, "cbc:Note": LEAF,
    "cac:SenderParty": dict({"cbc:EndpointID": LEAF}, **PARTY_IDENTIFICATION, **LEGAL_NAME, **{
        "cac:Contact": {"cbc:Name": LEAF, "cbc:Telephone": LEAF, "cbc:ElectronicMail": LEAF}}),
    "cac:ReceiverParty": dict({"cbc:EndpointID": LEAF}, **PARTY_IDENTIFICATION, **LEGAL_NAME),
    "cac:DocumentResponse": {
        "cac:Response": {
            "cbc:ResponseCode": LEAF, "cbc:EffectiveDate": LEAF,
            "cac:Status": {
                "cbc:StatusReasonCode": LEAF, "cbc:StatusReason": LEAF,
                "cac:Condition": {"cbc:AttributeID": LEAF, "cbc:Description": LEAF}}},
        "cac:DocumentReference": {"cbc:ID": LEAF, "cbc:IssueDate": LEAF,
                                  "cbc:DocumentTypeCode": LEAF},
        "cac:IssuerParty": NAMED, "cac:RecipientParty": NAMED},
}
MANY = ("cac:Status", "cac:Condition")
ATTRIBUTES = {"cbc:EndpointID": ("schemeID",), "cbc:ID": ("schemeID",),
              "cbc:StatusReasonCode": ("listID",), "cbc:ResponseCode": ("listID",)}


@dataclass
class Party:
    """The buyer who sends a response, or the seller who receives it."""
    endpoint: Optional[Value] = None        # its electronic address, with `schemeID`
    identifier: Optional[Value] = None
    name: str = ""                          # its legal name
    contact_name: str = ""                  # a sender's contact only
    telephone: str = ""
    email: str = ""


@dataclass
class Named:
    """Who issued the invoice being answered, or who it was for, where the
    response says so."""
    identifier: Optional[Value] = None
    name: str = ""


@dataclass
class Status:
    """One clarification: a reason or an action by its code, a text, and the
    places in the invoice it is about."""
    reason_code: str = ""
    list_id: str = ""                       # `OPStatusReason` or `OPStatusAction`
    reason: str = ""
    conditions: List[Tuple[str, str]] = field(default_factory=list)     # (BT-48, value)


@dataclass
class Answered:
    """The invoice or credit note the response is about."""
    id: str = ""
    issue_date: str = ""
    type_code: str = ""                     # 380 for an invoice, 381 for a credit note


@dataclass
class Response:
    """An Invoice Response. Text is as written; nothing is trimmed or parsed."""
    specification: str = SPECIFICATION
    profile: str = PROFILE
    id: str = ""
    issue_date: str = ""
    issue_time: str = ""
    note: str = ""
    sender: Party = field(default_factory=Party)
    receiver: Party = field(default_factory=Party)
    code: str = ""
    code_list: str = ""                     # `listID` on the code, where it had one
    effective_date: str = ""
    statuses: List[Status] = field(default_factory=list)
    document: Answered = field(default_factory=Answered)
    issuer: Optional[Named] = None
    recipient: Optional[Named] = None


# -- reading ------------------------------------------------------------------------

def name(short: str) -> str:
    prefix, _, local = short.partition(":")
    return (cac if prefix == "cac" else cbc)(local)


def parse_tree(data: Union[bytes, str]) -> Tuple[Response, List[Finding], Node]:
    """Read a response, with what the reader has to say of it and its
    elements as they were sent. Refuses what is not an Invoice Response."""
    root = tree(data)
    if root.tag != ROOT:
        local = root.tag.rpartition("}")[2]
        raise Refused("NOT-A-RESPONSE", "the document is a %s and not a UBL "
                      "ApplicationResponse" % local)
    stated = [child.text for child in root.children if child.tag == cbc("CustomizationID")]
    if not any(text.strip().startswith(SPECIFICATION) for text in stated):
        raise Refused("NOT-AN-INVOICE-RESPONSE", "the response's specification identifier is "
                      "%r, and what is taken is Peppol's Invoice Response (%r)"
                      % (stated[0] if stated else "", SPECIFICATION))
    findings: List[Finding] = []
    survey(root, STRUCTURE, "/ApplicationResponse", findings)
    return held(root), findings, root


def read(data: Union[bytes, str]) -> Tuple[Response, List[Finding]]:
    response, findings, _root = parse_tree(data)
    return response, findings


def survey(node: Node, allowed: Dict[str, object], path: str, findings: List[Finding]) -> None:
    """Say what is in a document that a response has no place for, and what
    is there twice where a response has one."""
    by_tag = {name(short): (short, inside) for short, inside in allowed.items()}
    seen: Dict[str, int] = {}
    for child, where in zip(node.children, paths(node, path)):
        if child.tag not in by_tag:
            findings.append(Finding("warning", "UNHELD", where, "%s has no place here in an "
                                    "Invoice Response, so it is not held and would not be "
                                    "written back" % qname(child.tag)))
            continue
        short, inside = by_tag[child.tag]
        seen[short] = seen.get(short, 0) + 1
        if seen[short] == 2 and short not in MANY:
            findings.append(Finding("error", "REPEATED", where, "%s occurs more than once here, "
                                    "and a response has one; the first is held" % short))
        for attribute in child.attributes:
            if attribute not in ATTRIBUTES.get(short, ()):
                findings.append(Finding("warning", "UNHELD", "%s/@%s" % (where, attribute),
                                        "the attribute %s on %s has no place in an Invoice "
                                        "Response, so it is not held" % (attribute, short)))
        if isinstance(inside, dict):
            survey(child, inside, where, findings)


def first(node: Optional[Node], *shorts: str) -> Optional[Node]:
    for short in shorts:
        node = next((c for c in node.children if c.tag == name(short)), None) if node else None
    return node


def text(node: Optional[Node], *shorts: str) -> str:
    found = first(node, *shorts)
    return found.text if found is not None else ""


def value(node: Optional[Node], *shorts: str) -> Optional[Value]:
    found = first(node, *shorts)
    if found is None:
        return None
    return Value(found.text, {key: found.attributes[key] for key in ("schemeID",)
                              if key in found.attributes})


def held(root: Node) -> Response:
    def party(short: str) -> Party:
        at = first(root, short)
        return Party(value(at, "cbc:EndpointID"), value(at, "cac:PartyIdentification", "cbc:ID"),
                     text(at, "cac:PartyLegalEntity", "cbc:RegistrationName"),
                     text(at, "cac:Contact", "cbc:Name"), text(at, "cac:Contact", "cbc:Telephone"),
                     text(at, "cac:Contact", "cbc:ElectronicMail"))

    def named(short: str) -> Optional[Named]:
        at = first(root, "cac:DocumentResponse", short)
        if at is None:
            return None
        return Named(value(at, "cac:PartyIdentification", "cbc:ID"),
                     text(at, "cac:PartyName", "cbc:Name"))

    answer = first(root, "cac:DocumentResponse", "cac:Response")
    code = first(answer, "cbc:ResponseCode")
    statuses = []
    for status in (answer.children if answer is not None else ()):
        if status.tag != name("cac:Status"):
            continue
        reason = first(status, "cbc:StatusReasonCode")
        statuses.append(Status(
            reason.text if reason is not None else "",
            reason.attributes.get("listID", "") if reason is not None else "",
            text(status, "cbc:StatusReason"),
            [(text(c, "cbc:AttributeID"), text(c, "cbc:Description"))
             for c in status.children if c.tag == name("cac:Condition")]))
    reference = first(root, "cac:DocumentResponse", "cac:DocumentReference")
    return Response(
        text(root, "cbc:CustomizationID"), text(root, "cbc:ProfileID"), text(root, "cbc:ID"),
        text(root, "cbc:IssueDate"), text(root, "cbc:IssueTime"), text(root, "cbc:Note"),
        party("cac:SenderParty"), party("cac:ReceiverParty"),
        code.text if code is not None else "",
        code.attributes.get("listID", "") if code is not None else "",
        text(answer, "cbc:EffectiveDate"), statuses,
        Answered(text(reference, "cbc:ID"), text(reference, "cbc:IssueDate"),
                 text(reference, "cbc:DocumentTypeCode")),
        named("cac:IssuerParty"), named("cac:RecipientParty"))


# -- writing --------------------------------------------------------------------------

def leaf(short: str, written: str, **attributes: str) -> Optional[Node]:
    """An element with text, or nothing where there is no text to write:
    an empty element is a fault in a response."""
    if not written:
        return None
    return Node(name(short), {k: v for k, v in attributes.items() if v}, written)


def of(value_: Optional[Value], short: str) -> Optional[Node]:
    if value_ is None:
        return None
    return leaf(short, value_.text, schemeID=value_.attributes.get("schemeID", ""))


def within(short: str, *children: Optional[Node]) -> Optional[Node]:
    """A wrapper with what there is to put in it, or nothing if nothing is."""
    kept = [child for child in children if child is not None]
    if not kept:
        return None
    node = Node(name(short))
    node.children = kept
    return node


def node_of(response: Response) -> Node:
    def party(short: str, who: Party, contact: bool) -> Optional[Node]:
        return within(
            short, of(who.endpoint, "cbc:EndpointID"),
            within("cac:PartyIdentification", of(who.identifier, "cbc:ID")),
            within("cac:PartyLegalEntity", leaf("cbc:RegistrationName", who.name)),
            within("cac:Contact", leaf("cbc:Name", who.contact_name),
                   leaf("cbc:Telephone", who.telephone),
                   leaf("cbc:ElectronicMail", who.email)) if contact else None)

    def named(short: str, who: Optional[Named]) -> Optional[Node]:
        if who is None:
            return None
        return within(short, within("cac:PartyIdentification", of(who.identifier, "cbc:ID")),
                      within("cac:PartyName", leaf("cbc:Name", who.name)))

    statuses = [within("cac:Status",
                       leaf("cbc:StatusReasonCode", status.reason_code, listID=status.list_id),
                       leaf("cbc:StatusReason", status.reason),
                       *[within("cac:Condition", leaf("cbc:AttributeID", attribute),
                                leaf("cbc:Description", description))
                         for attribute, description in status.conditions])
                for status in response.statuses]
    root = Node(ROOT)
    root.children = [node for node in (
        leaf("cbc:CustomizationID", response.specification),
        leaf("cbc:ProfileID", response.profile), leaf("cbc:ID", response.id),
        leaf("cbc:IssueDate", response.issue_date), leaf("cbc:IssueTime", response.issue_time),
        leaf("cbc:Note", response.note),
        party("cac:SenderParty", response.sender, True),
        party("cac:ReceiverParty", response.receiver, False),
        within("cac:DocumentResponse",
               within("cac:Response",
                      leaf("cbc:ResponseCode", response.code, listID=response.code_list),
                      leaf("cbc:EffectiveDate", response.effective_date), *statuses),
               within("cac:DocumentReference", leaf("cbc:ID", response.document.id),
                      leaf("cbc:IssueDate", response.document.issue_date),
                      leaf("cbc:DocumentTypeCode", response.document.type_code)),
               named("cac:IssuerParty", response.issuer),
               named("cac:RecipientParty", response.recipient)),
    ) if node is not None]
    return root


def write(response: Response) -> bytes:
    """Write a response as a UBL 2.1 `ApplicationResponse`, UTF-8."""
    lines = ['<?xml version="1.0" encoding="UTF-8"?>']
    serialise(node_of(response), NAMESPACE, 0, lines, declare=True)
    return ("\n".join(lines) + "\n").encode("utf-8")


assert CAC_NS and CBC_NS        # the two namespaces `serialise` declares
