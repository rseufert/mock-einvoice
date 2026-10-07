"""UBL 2.1 in and out: an `Invoice` or a `CreditNote`, to and from the model.

    bytes  ──parse──▶  Document, findings
    Document  ──write──▶  bytes

One table says where each business term sits in UBL (`binding`), and both
directions are read off it, so what is read is what is written. The table is
in the order the UBL schemas give their elements, because the writer writes in
the table's order and UBL is strict about it.

What the reader does with what it does not hold
-----------------------------------------------
UBL has thousands of elements and EN 16931 has a place for about a hundred and
sixty. An element with no business term is not held, and is not dropped in
silence either: each is a finding, `UNHELD`, naming it. So is an element that
repeats where the standard has one (`REPEATED`), text where only elements
belong (`TEXT`), and a number that is not a decimal (`NOT-DECIMAL`). These are
the reader's own findings, not published rules.

What the writer does not promise
--------------------------------
The same bytes back. Reading what was written gives an equal `Document`; the
element order among repeats of different kinds, the namespace prefixes, the
white space and anything `UNHELD` are the writer's own or gone. Nor does it
supply what UBL requires and the model does not hold: a document the model can
describe and UBL cannot write validly is written as it stands.

Not XML Schema validation. The standard library has none; this reads what it
understands and says what it did not.
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional, Sequence, Tuple, Union
from xml.parsers import expat
from xml.sax.saxutils import escape, quoteattr

from .model import (INVOICED_OBJECT_REFERENCE, NUMERIC, PARTY_ROLE, PROJECT_REFERENCE, TERMS,
                    Document, Finding, Group, Refused, Value)

INVOICE_NS = "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
CREDIT_NOTE_NS = "urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2"
CBC_NS = "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
CAC_NS = "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
CII_NS = "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"
ROOTS = {"Invoice": INVOICE_NS, "CreditNote": CREDIT_NOTE_NS}
PREFIXES = {CBC_NS: "cbc", CAC_NS: "cac",
            "urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2": "ext"}

# What a kind of value may carry as an attribute without it being a finding.
KIND_ATTRIBUTES = {"amount": ("currencyID",), "price": ("currencyID",),
                   "quantity": ("unitCode",)}
TRUE, FALSE = ("true", "1"), ("false", "0")


# -- a small tree of our own ------------------------------------------------
#
# Not `xml.etree`: the parser is expat directly so that a DTD can be refused
# before anything in it is acted on, and the writer wants its own prefixes.

class Node:
    __slots__ = ("tag", "attributes", "text", "children", "mixed")

    def __init__(self, tag: str, attributes: Optional[Dict[str, str]] = None, text: str = ""):
        self.tag = tag                      # "{namespace}local"
        self.attributes = attributes or {}
        self.text = text                    # the text before the first child
        self.children: List["Node"] = []
        self.mixed = False                  # text after a child, other than space

    def find(self, *tags: str) -> Optional["Node"]:
        node: Optional[Node] = self
        for tag in tags:
            node = next((c for c in node.children if c.tag == tag), None) if node else None
        return node

    def find_text(self, *tags: str) -> str:
        found = self.find(*tags)
        return found.text if found else ""


def cbc(name: str) -> str:
    return "{%s}%s" % (CBC_NS, name)


def cac(name: str) -> str:
    return "{%s}%s" % (CAC_NS, name)


def qname(tag: str) -> str:
    """A tag as people write it: `cbc:ID`, or the bare name at the root."""
    namespace, _, local = tag[1:].partition("}") if tag.startswith("{") else ("", "", tag)
    prefix = PREFIXES.get(namespace)
    return "%s:%s" % (prefix, local) if prefix else local


def tree(data: Union[bytes, str]) -> Node:
    """Parse XML into nodes, refusing what is not XML and anything with a DTD."""
    parser = expat.ParserCreate(namespace_separator="}")
    parser.buffer_text = True
    stack: List[Node] = []
    roots: List[Node] = []

    def name(raw: str) -> str:
        return "{" + raw if "}" in raw else raw

    def start(raw: str, attributes: Dict[str, str]) -> None:
        node = Node(name(raw), {name(k): v for k, v in attributes.items()})
        (stack[-1].children if stack else roots).append(node)
        stack.append(node)

    def end(_raw: str) -> None:
        stack.pop()

    def text(data: str) -> None:
        if not stack:
            return
        node = stack[-1]
        if node.children:
            node.mixed = node.mixed or bool(data.strip())
        else:
            node.text += data

    def doctype(*_args) -> None:
        # A DTD can declare entities that expand without end or reach for
        # files and addresses. No invoice needs one, so none is acted on.
        raise Refused("DTD", "the document has a DOCTYPE declaration, which is refused "
                             "and not read: an invoice needs no DTD and no entities")

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = text
    parser.StartDoctypeDeclHandler = doctype
    try:
        parser.Parse(data, True)
    except expat.ExpatError as error:
        raise Refused("NOT-XML", "the document is not well-formed XML: %s" % error) from None
    return roots[0]


# -- the binding ------------------------------------------------------------

class Leaf:
    """An element whose text is a business term's value.

    A term starting `ubl:` is not a business term. It is something UBL
    requires that the standard has no term for, carried so the document can be
    written. `root` puts the value on the document whatever group the element
    is in: a credit note's due date is inside `PaymentMeans`.
    """

    def __init__(self, tag: str, term: str, attributes: Sequence[str] = (), root: bool = False,
                 noting: Optional[Tuple[str, str]] = None):
        self.tag, self.term, self.root = tag, term, root
        self.noting = noting    # kept beside each value read here: which place it was
        self.kind = TERMS[term][2] if term in TERMS else "text"
        self.attributes = tuple(attributes) + KIND_ATTRIBUTES.get(self.kind, ())


class Fixed:
    """An element the binding gives one value: `ChargeIndicator` on a charge."""

    def __init__(self, tag: str, text: str, accept: Sequence[str] = ()):
        self.tag, self.text = tag, text
        self.accept = tuple(accept) or (text,)


class Wrap:
    """An element that only holds others, and is no group of its own.

    `when` picks this entry among several with one tag; they are tried in the
    table's order and the first that fits has the element, so the entry with
    no `when` comes last and takes what is left. `per` names the term
    the element is written once for each value of: one `PartyIdentification`
    to an identifier, and `where` picks which of the term's values are
    written here, for a term UBL has two places for. `marks` names the group of the
    standard that this element is, where that group occurs once: its terms go
    to the group around it, and if it held nothing, that it was there at all
    is noted on that group, so it can be asked and is written back. The two
    references told by a type code are marked the same way, under names of
    their own (`model.INVOICED_OBJECT_REFERENCE`), and are written back with
    the type code that told them.
    """

    def __init__(self, tag: str, children: list, when: Optional[Callable] = None,
                 per: str = "", where: Optional[Callable[[Value], bool]] = None,
                 marks: str = ""):
        self.tag, self.children, self.when, self.per, self.where = tag, children, when, per, where
        self.marks = marks      # the once-only thing this element is: "BG-4"


class Many:
    """An element that is one of a repeating group: a `Group` to each."""

    def __init__(self, tag: str, group: str, children: list, when: Optional[Callable] = None):
        self.tag, self.group, self.children, self.when = tag, group, children, when


class Note:
    """`cbc:Note` at the head of the document: one `BG-1` to each.

    The standard has a subject code for a note (`BT-21`) and UBL has no
    element for it, so the binding writes it at the front of the text between
    two `#`: `#AAI#the note`.
    """
    tag = cbc("Note")


class TaxRegistration:
    """`cac:PartyTaxScheme`: a VAT identifier, or another tax registration.

    Which it is, UBL says in `TaxScheme/ID`: `VAT`, compared as the published
    rules compare it, without regard to case or surrounding space. Anything
    else is the other registration, where the party has one, and is kept
    beside the value because the document cannot be written without it.
    """
    tag = cac("PartyTaxScheme")

    def __init__(self, vat: str, other: str = ""):
        self.vat, self.other = vat, other


Entry = Union[Leaf, Fixed, Wrap, Many, Note, TaxRegistration]


def indicator(values: Sequence[str]) -> Callable:
    return lambda node, _context: node.find_text(cbc("ChargeIndicator")).strip() in values


def document_type(*codes: str) -> Callable:
    return lambda node, _context: node.find_text(cbc("DocumentTypeCode")).strip() in codes


def sepa(node: Node, _context) -> bool:
    identifier = node.find(cbc("ID"))
    return identifier is not None and identifier.attributes.get("schemeID", "").upper() == "SEPA"


def in_accounting_currency(node: Node, context) -> bool:
    """The second `TaxTotal`: the VAT total in the accounting currency (BT-111).

    It is told from the first by its currency being the one `TaxCurrencyCode`
    names, where that differs from the document's, and by having no breakdown.
    """
    amount = node.find(cbc("TaxAmount"))
    currency = amount.attributes.get("currencyID", "") if amount else ""
    return bool(context.tax_currency and currency == context.tax_currency
                and currency != context.currency and node.find(cac("TaxSubtotal")) is None)


def in_document_currency(node: Node, context) -> bool:
    return not in_accounting_currency(node, context)


VAT_SCHEME = Wrap(cac("TaxScheme"), [Fixed(cbc("ID"), "VAT")])
PAYEES = PARTY_ROLE, "payee"


def address(tag: str, group: str, line1: str, line2: str, city: str, post_code: str,
            subdivision: str, line3: str, country: str) -> Wrap:
    return Wrap(cac(tag), marks=group, children=[
        Leaf(cbc("StreetName"), line1), Leaf(cbc("AdditionalStreetName"), line2),
        Leaf(cbc("CityName"), city), Leaf(cbc("PostalZone"), post_code),
        Leaf(cbc("CountrySubentity"), subdivision),
        Wrap(cac("AddressLine"), [Leaf(cbc("Line"), line3)]),
        Wrap(cac("Country"), [Leaf(cbc("IdentificationCode"), country)])])


def identification(term: str) -> Wrap:
    return Wrap(cac("PartyIdentification"), [Leaf(cbc("ID"), term, ["schemeID"])], per=term)


def creditor_identifier(payee: bool) -> Wrap:
    """The bank assigned creditor identifier (BT-90): a party identifier whose
    scheme is `SEPA`, on the seller or on the payee.

    One term with two places, and a document may use either whether or not it
    has a payee, so which it was is kept beside the value (`PAYEES`) and it is
    written back where it was read. A value with nothing beside it is the
    seller's.
    """
    return Wrap(cac("PartyIdentification"),
                [Leaf(cbc("ID"), "BT-90", ["schemeID"], noting=PAYEES if payee else None)],
                when=sepa, per="BT-90",
                where=lambda value: (value.attributes.get(PAYEES[0]) == PAYEES[1]) == payee)


def allowance_or_charge(group: str, charge: bool, reason_code: str, reason: str,
                        percentage: str, amount: str, base: str,
                        category: str = "", rate: str = "") -> Many:
    children: List[Entry] = [
        Fixed(cbc("ChargeIndicator"), "true" if charge else "false", TRUE if charge else FALSE),
        Leaf(cbc("AllowanceChargeReasonCode"), reason_code),
        Leaf(cbc("AllowanceChargeReason"), reason),
        Leaf(cbc("MultiplierFactorNumeric"), percentage),
        Leaf(cbc("Amount"), amount), Leaf(cbc("BaseAmount"), base)]
    if category:
        children.append(Wrap(cac("TaxCategory"), [
            Leaf(cbc("ID"), category), Leaf(cbc("Percent"), rate), VAT_SCHEME]))
    return Many(cac("AllowanceCharge"), group, children,
                when=indicator(TRUE if charge else FALSE))


def binding(kind: str) -> List[Entry]:
    """Where each business term is in a UBL `Invoice` or `CreditNote`.

    The two differ in five places: the type code's element, the line's and its
    quantity's, where the due date is, where the project reference is, and the
    order the schema puts some of the rest in.
    """
    invoice = kind == "Invoice"
    head: List[Entry] = [
        Leaf(cbc("CustomizationID"), "BT-24"), Leaf(cbc("ProfileID"), "BT-23"),
        Leaf(cbc("ID"), "BT-1"), Leaf(cbc("IssueDate"), "BT-2")]
    if invoice:
        head += [Leaf(cbc("DueDate"), "BT-9"), Leaf(cbc("InvoiceTypeCode"), "BT-3"),
                 Note(), Leaf(cbc("TaxPointDate"), "BT-7")]
    else:
        head += [Leaf(cbc("TaxPointDate"), "BT-7"), Leaf(cbc("CreditNoteTypeCode"), "BT-3"),
                 Note()]
    head += [
        Leaf(cbc("DocumentCurrencyCode"), "BT-5"), Leaf(cbc("TaxCurrencyCode"), "BT-6"),
        Leaf(cbc("AccountingCost"), "BT-19"), Leaf(cbc("BuyerReference"), "BT-10"),
        Wrap(cac("InvoicePeriod"), marks="BG-14", children=[
            Leaf(cbc("StartDate"), "BT-73"), Leaf(cbc("EndDate"), "BT-74"),
            Leaf(cbc("DescriptionCode"), "BT-8")]),
        Wrap(cac("OrderReference"), [
            Leaf(cbc("ID"), "BT-13"), Leaf(cbc("SalesOrderID"), "BT-14")]),
        Many(cac("BillingReference"), "BG-3", [
            Wrap(cac("InvoiceDocumentReference"), [
                Leaf(cbc("ID"), "BT-25"), Leaf(cbc("IssueDate"), "BT-26")])]),
        Wrap(cac("DespatchDocumentReference"), [Leaf(cbc("ID"), "BT-16")]),
        Wrap(cac("ReceiptDocumentReference"), [Leaf(cbc("ID"), "BT-15")])]

    originator = Wrap(cac("OriginatorDocumentReference"), [Leaf(cbc("ID"), "BT-17")])
    contract = Wrap(cac("ContractDocumentReference"), [Leaf(cbc("ID"), "BT-12")])
    invoiced_object = Wrap(cac("AdditionalDocumentReference"), [
        Leaf(cbc("ID"), "BT-18", ["schemeID"]), Fixed(cbc("DocumentTypeCode"), "130")],
        when=document_type("130"), marks=INVOICED_OBJECT_REFERENCE)
    supporting = [
        Leaf(cbc("ID"), "BT-122"), Leaf(cbc("DocumentDescription"), "BT-123"),
        Wrap(cac("Attachment"), [
            Leaf(cbc("EmbeddedDocumentBinaryObject"), "BT-125", ["mimeCode", "filename"]),
            Wrap(cac("ExternalReference"), [Leaf(cbc("URI"), "BT-124")])])]
    if invoice:
        references: List[Entry] = [
            originator, contract, invoiced_object,
            Many(cac("AdditionalDocumentReference"), "BG-24", supporting),
            Wrap(cac("ProjectReference"), [Leaf(cbc("ID"), "BT-11")])]
    else:
        # A credit note has no ProjectReference: the project is an additional
        # document reference of type 50.
        references = [
            contract, invoiced_object,
            Wrap(cac("AdditionalDocumentReference"), [
                Leaf(cbc("ID"), "BT-11"), Fixed(cbc("DocumentTypeCode"), "50")],
                when=document_type("50"), marks=PROJECT_REFERENCE),
            Many(cac("AdditionalDocumentReference"), "BG-24", supporting),
            originator]

    parties: List[Entry] = [
        Wrap(cac("AccountingSupplierParty"), marks="BG-4", children=[Wrap(cac("Party"), [
            Leaf(cbc("EndpointID"), "BT-34", ["schemeID"]),
            creditor_identifier(payee=False),
            identification("BT-29"),
            Wrap(cac("PartyName"), [Leaf(cbc("Name"), "BT-28")]),
            address("PostalAddress", "BG-5", "BT-35", "BT-36", "BT-37", "BT-38", "BT-39",
                    "BT-162", "BT-40"),
            TaxRegistration("BT-31", "BT-32"),
            Wrap(cac("PartyLegalEntity"), [
                Leaf(cbc("RegistrationName"), "BT-27"),
                Leaf(cbc("CompanyID"), "BT-30", ["schemeID"]),
                Leaf(cbc("CompanyLegalForm"), "BT-33")]),
            Wrap(cac("Contact"), marks="BG-6", children=[
                Leaf(cbc("Name"), "BT-41"), Leaf(cbc("Telephone"), "BT-42"),
                Leaf(cbc("ElectronicMail"), "BT-43")])])]),
        Wrap(cac("AccountingCustomerParty"), marks="BG-7", children=[Wrap(cac("Party"), [
            Leaf(cbc("EndpointID"), "BT-49", ["schemeID"]),
            identification("BT-46"),
            Wrap(cac("PartyName"), [Leaf(cbc("Name"), "BT-45")]),
            address("PostalAddress", "BG-8", "BT-50", "BT-51", "BT-52", "BT-53", "BT-54",
                    "BT-163", "BT-55"),
            TaxRegistration("BT-48"),
            Wrap(cac("PartyLegalEntity"), [
                Leaf(cbc("RegistrationName"), "BT-44"),
                Leaf(cbc("CompanyID"), "BT-47", ["schemeID"])]),
            Wrap(cac("Contact"), marks="BG-9", children=[
                Leaf(cbc("Name"), "BT-56"), Leaf(cbc("Telephone"), "BT-57"),
                Leaf(cbc("ElectronicMail"), "BT-58")])])]),
        Wrap(cac("PayeeParty"), marks="BG-10", children=[
            creditor_identifier(payee=True),
            identification("BT-60"),
            Wrap(cac("PartyName"), [Leaf(cbc("Name"), "BT-59")]),
            Wrap(cac("PartyLegalEntity"), [Leaf(cbc("CompanyID"), "BT-61", ["schemeID"])])]),
        Wrap(cac("TaxRepresentativeParty"), marks="BG-11", children=[
            Wrap(cac("PartyName"), [Leaf(cbc("Name"), "BT-62")]),
            address("PostalAddress", "BG-12", "BT-64", "BT-65", "BT-66", "BT-67", "BT-68",
                    "BT-164", "BT-69"),
            TaxRegistration("BT-63")]),
        Wrap(cac("Delivery"), marks="BG-13", children=[
            Leaf(cbc("ActualDeliveryDate"), "BT-72"),
            Wrap(cac("DeliveryLocation"), [
                Leaf(cbc("ID"), "BT-71", ["schemeID"]),
                address("Address", "BG-15", "BT-75", "BT-76", "BT-77", "BT-78", "BT-79",
                        "BT-165", "BT-80")]),
            Wrap(cac("DeliveryParty"), [Wrap(cac("PartyName"), [Leaf(cbc("Name"), "BT-70")])])])]

    payment: List[Entry] = [Leaf(cbc("PaymentMeansCode"), "BT-81", ["name"])]
    if not invoice:
        payment.append(Leaf(cbc("PaymentDueDate"), "BT-9", root=True))
    payment += [
        Leaf(cbc("PaymentID"), "BT-83"),
        Wrap(cac("CardAccount"), marks="BG-18", children=[
            Leaf(cbc("PrimaryAccountNumberID"), "BT-87"),
            Leaf(cbc("NetworkID"), "ubl:NetworkID"),
            Leaf(cbc("HolderName"), "BT-88")]),
        Wrap(cac("PayeeFinancialAccount"), marks="BG-17", children=[
            Leaf(cbc("ID"), "BT-84"), Leaf(cbc("Name"), "BT-85"),
            Wrap(cac("FinancialInstitutionBranch"), [Leaf(cbc("ID"), "BT-86")])]),
        Wrap(cac("PaymentMandate"), marks="BG-19", children=[
            Leaf(cbc("ID"), "BT-89"),
            Wrap(cac("PayerFinancialAccount"), [Leaf(cbc("ID"), "BT-91")])])]

    line: List[Entry] = [
        Leaf(cbc("ID"), "BT-126"), Leaf(cbc("Note"), "BT-127"),
        Leaf(cbc("InvoicedQuantity" if invoice else "CreditedQuantity"), "BT-129"),
        Leaf(cbc("LineExtensionAmount"), "BT-131"), Leaf(cbc("AccountingCost"), "BT-133"),
        Wrap(cac("InvoicePeriod"), marks="BG-26", children=[
            Leaf(cbc("StartDate"), "BT-134"), Leaf(cbc("EndDate"), "BT-135")]),
        Wrap(cac("OrderLineReference"), [Leaf(cbc("LineID"), "BT-132")]),
        Wrap(cac("DocumentReference"), [
            Leaf(cbc("ID"), "BT-128", ["schemeID"]), Fixed(cbc("DocumentTypeCode"), "130")],
            when=document_type("130")),
        allowance_or_charge("BG-27", False, "BT-140", "BT-139", "BT-138", "BT-136", "BT-137"),
        allowance_or_charge("BG-28", True, "BT-145", "BT-144", "BT-143", "BT-141", "BT-142"),
        Wrap(cac("Item"), marks="BG-31", children=[
            Leaf(cbc("Description"), "BT-154"), Leaf(cbc("Name"), "BT-153"),
            Wrap(cac("BuyersItemIdentification"), [Leaf(cbc("ID"), "BT-156")]),
            Wrap(cac("SellersItemIdentification"), [Leaf(cbc("ID"), "BT-155")]),
            Wrap(cac("StandardItemIdentification"), [Leaf(cbc("ID"), "BT-157", ["schemeID"])]),
            Wrap(cac("OriginCountry"), [Leaf(cbc("IdentificationCode"), "BT-159")]),
            Wrap(cac("CommodityClassification"), [
                Leaf(cbc("ItemClassificationCode"), "BT-158", ["listID", "listVersionID"])],
                per="BT-158"),
            Wrap(cac("ClassifiedTaxCategory"), marks="BG-30", children=[
                Leaf(cbc("ID"), "BT-151"), Leaf(cbc("Percent"), "BT-152"), VAT_SCHEME]),
            Many(cac("AdditionalItemProperty"), "BG-32", [
                Leaf(cbc("Name"), "BT-160"), Leaf(cbc("Value"), "BT-161")])]),
        Wrap(cac("Price"), marks="BG-29", children=[
            Leaf(cbc("PriceAmount"), "BT-146"), Leaf(cbc("BaseQuantity"), "BT-149"),
            Wrap(cac("AllowanceCharge"), [
                Fixed(cbc("ChargeIndicator"), "false", FALSE),
                Leaf(cbc("Amount"), "BT-147"), Leaf(cbc("BaseAmount"), "BT-148")])])]

    tail: List[Entry] = [
        Many(cac("PaymentMeans"), "BG-16", payment),
        Wrap(cac("PaymentTerms"), [Leaf(cbc("Note"), "BT-20")]),
        allowance_or_charge("BG-20", False, "BT-98", "BT-97", "BT-94", "BT-92", "BT-93",
                            "BT-95", "BT-96"),
        allowance_or_charge("BG-21", True, "BT-105", "BT-104", "BT-101", "BT-99", "BT-100",
                            "BT-102", "BT-103"),
        Wrap(cac("TaxTotal"), [
            Leaf(cbc("TaxAmount"), "BT-110"),
            Many(cac("TaxSubtotal"), "BG-23", [
                Leaf(cbc("TaxableAmount"), "BT-116"), Leaf(cbc("TaxAmount"), "BT-117"),
                Wrap(cac("TaxCategory"), [
                    Leaf(cbc("ID"), "BT-118"), Leaf(cbc("Percent"), "BT-119"),
                    Leaf(cbc("TaxExemptionReasonCode"), "BT-121"),
                    Leaf(cbc("TaxExemptionReason"), "BT-120"), VAT_SCHEME])])],
            when=in_document_currency),
        Wrap(cac("TaxTotal"), [Leaf(cbc("TaxAmount"), "BT-111")], when=in_accounting_currency),
        Wrap(cac("LegalMonetaryTotal"), marks="BG-22", children=[
            Leaf(cbc("LineExtensionAmount"), "BT-106"),
            Leaf(cbc("TaxExclusiveAmount"), "BT-109"),
            Leaf(cbc("TaxInclusiveAmount"), "BT-112"),
            Leaf(cbc("AllowanceTotalAmount"), "BT-107"),
            Leaf(cbc("ChargeTotalAmount"), "BT-108"),
            Leaf(cbc("PrepaidAmount"), "BT-113"),
            Leaf(cbc("PayableRoundingAmount"), "BT-114"),
            Leaf(cbc("PayableAmount"), "BT-115")]),
        Many(cac("InvoiceLine" if invoice else "CreditNoteLine"), "BG-25", line)]
    return head + references + parties + tail


BINDINGS = {kind: binding(kind) for kind in ROOTS}


# -- reading ----------------------------------------------------------------

class Reading:
    """One document being read: where the values go and what is said of it."""

    def __init__(self, document: Document, root: Node):
        self.document = document
        self.findings: List[Finding] = []
        self.currency = root.find_text(cbc("DocumentCurrencyCode")).strip()
        self.tax_currency = root.find_text(cbc("TaxCurrencyCode")).strip()

    def say(self, level: str, code: str, path: str, text: str) -> None:
        self.findings.append(Finding(level, code, path, text))


def parse(data: Union[bytes, str]) -> Tuple[Document, List[Finding]]:
    """Read a UBL invoice or credit note. Refuses anything else, by name.

    This is the syntax alone: it does not ask which specification the
    document claims. `mockeinvoice.read` does, and is what a caller wants.
    """
    document, findings, _root = parse_tree(data)
    return document, findings


def parse_tree(data: Union[bytes, str]) -> Tuple[Document, List[Finding], Node]:
    """`parse`, and the document's elements as they were sent: the rules
    about the XML itself are asked of those."""
    root = tree(data)
    kind = next((k for k, namespace in ROOTS.items()
                 if root.tag == "{%s}%s" % (namespace, k)), None)
    if kind is None:
        raise Refused(*not_ubl(root))
    document = Document(kind=kind)
    reading = Reading(document, root)
    read_children(root, BINDINGS[kind], document, "/" + kind, reading)
    return document, reading.findings, root


def not_ubl(root: Node) -> Tuple[str, str]:
    namespace, _, local = root.tag[1:].partition("}") if root.tag.startswith("{") else ("", "", root.tag)
    if namespace == CII_NS:
        return "CII", ("the document is a UN/CEFACT Cross Industry Invoice (%s), which is not "
                       "built: UBL Invoice and CreditNote are what is read" % local)
    if namespace.startswith("urn:oasis:names:specification:ubl:schema:xsd:"):
        return "NOT-AN-INVOICE", ("the document is a UBL %s, not an Invoice or a CreditNote"
                                  % local)
    return "NOT-UBL", ("the document's root is %s in namespace %r, not a UBL Invoice or "
                       "CreditNote" % (local, namespace))


def paths(parent: Node, path: str) -> List[str]:
    """Each child's path, numbered where a tag occurs more than once."""
    total: Dict[str, int] = {}
    for child in parent.children:
        total[child.tag] = total.get(child.tag, 0) + 1
    seen: Dict[str, int] = {}
    out = []
    for child in parent.children:
        seen[child.tag] = seen.get(child.tag, 0) + 1
        number = "[%d]" % seen[child.tag] if total[child.tag] > 1 else ""
        out.append("%s/%s%s" % (path, qname(child.tag), number))
    return out


def read_children(parent: Node, entries: List[Entry], group: Group, path: str,
                  reading: Reading) -> None:
    if parent.text.strip() or parent.mixed:
        reading.say("warning", "TEXT", path, "text among the elements of %s, which holds "
                    "only elements; it is not held" % qname(parent.tag))
    used: Dict[int, int] = {}
    for child, where in zip(parent.children, paths(parent, path)):
        entry = next((e for e in entries if e.tag == child.tag
                      and (getattr(e, "when", None) is None or e.when(child, reading))), None)
        if entry is None:
            reading.say("warning", "UNHELD", where, "%s has no business term here in "
                        "EN 16931, so it is not held and would not be written back"
                        % qname(child.tag))
            continue
        used[id(entry)] = used.get(id(entry), 0) + 1
        repeats = isinstance(entry, (Many, Note, TaxRegistration)) or getattr(entry, "per", "")
        if used[id(entry)] == 2 and not repeats:
            reading.say("error", "REPEATED", where, "%s occurs more than once here, and "
                        "the standard has one; every value is held, in the order written"
                        % qname(child.tag))
        read_entry(child, entry, group, where, reading)


def read_entry(node: Node, entry: Entry, group: Group, path: str, reading: Reading) -> None:
    if isinstance(entry, Leaf):
        target = reading.document if entry.root else group
        value = read_value(node, entry.kind, entry.attributes, path, reading)
        if entry.noting:
            value.attributes[entry.noting[0]] = entry.noting[1]
        target.add(entry.term, value)
    elif isinstance(entry, Fixed):
        read_value(node, "code", (), path, reading)
        if node.text != entry.text:
            reading.say("warning", "FIXED", path, "%s is %r here; it is read as %r and "
                        "would be written back as that" % (qname(node.tag), node.text, entry.text))
    elif isinstance(entry, Wrap):
        read_children(node, entry.children, group, path, reading)
        if entry.marks and not group.has(entry.marks):
            group.present.add(entry.marks)      # there, with nothing held in it
    elif isinstance(entry, Many):
        # Kept even if nothing in it could be held: that it is there is
        # something a rule can ask ("there is at least one VAT breakdown").
        made = group.new(entry.group)
        read_children(node, entry.children, made, path, reading)
    elif isinstance(entry, Note):
        made = group.new("BG-1")
        value = read_value(node, "text", (), path, reading)
        subject, text = split_note(value.text)
        if subject:
            made.add("BT-21", Value(subject))
        made.add("BT-22", Value(text, value.attributes))
    else:
        read_tax_registration(node, entry, group, path, reading)


def split_note(text: str) -> Tuple[str, str]:
    """`#AAI#the note` is subject code AAI and text `the note`."""
    if text.startswith("#"):
        subject, mark, rest = text[1:].partition("#")
        if mark and subject and not any(c.isspace() for c in subject):
            return subject, rest
    return "", text


def read_tax_registration(node: Node, entry: TaxRegistration, group: Group, path: str,
                          reading: Reading) -> None:
    scheme = node.find(cac("TaxScheme"), cbc("ID"))
    said = scheme.text if scheme is not None else ""
    is_vat = said.strip().upper() == "VAT"
    term = entry.vat if is_vat or not entry.other else entry.other
    if not is_vat and not entry.other:
        reading.say("warning", "UNHELD", path, "a tax registration under scheme %r has no "
                    "business term for this party in EN 16931; it is held as the VAT "
                    "identifier (%s), with the scheme beside it" % (said, entry.vat))
    for child, where in zip(node.children, paths(node, path)):
        if child.tag == cbc("CompanyID"):
            value = read_value(child, "identifier", (), where, reading)
            if said != "VAT":
                value.attributes["TaxScheme/ID"] = said
            group.add(term, value)
        elif child.tag == cac("TaxScheme"):
            for inner, inner_path in zip(child.children, paths(child, where)):
                if inner.tag != cbc("ID"):
                    reading.say("warning", "UNHELD", inner_path, "%s has no business term "
                                "here in EN 16931, so it is not held and would not be "
                                "written back" % qname(inner.tag))
        else:
            reading.say("warning", "UNHELD", where, "%s has no business term here in "
                        "EN 16931, so it is not held and would not be written back"
                        % qname(child.tag))


def read_value(node: Node, kind: str, allowed: Sequence[str], path: str,
               reading: Reading) -> Value:
    if node.children:
        reading.say("error", "STRUCTURE", path, "%s holds elements where it should hold "
                    "text; only its text is read" % qname(node.tag))
    value = Value(node.text)
    for name, text in node.attributes.items():
        if name.startswith("{"):
            # An attribute from another vocabulary: xsi:type, say.
            reading.say("warning", "UNHELD", "%s/@%s" % (path, name),
                        "the attribute %s on %s is not UBL's, so it is not held and would "
                        "not be written back" % (name, qname(node.tag)))
            continue
        value.attributes[name] = text
        if name not in allowed:
            reading.say("warning", "UNHELD", "%s/@%s" % (path, name),
                        "the attribute %s on %s has no place in EN 16931; it is kept with "
                        "the value" % (name, qname(node.tag)))
    if kind in NUMERIC and value.number is None:
        reading.say("error", "NOT-DECIMAL", path, "%r is not a decimal number, so %s has no "
                    "value a rule could compute with" % (node.text, qname(node.tag)))
    return value


# -- writing ----------------------------------------------------------------

def write(document: Document) -> bytes:
    """Write a document as UBL 2.1, UTF-8, in the order the schema wants."""
    if document.kind not in ROOTS:
        raise ValueError("a document is an Invoice or a CreditNote, not %r" % document.kind)
    namespace = ROOTS[document.kind]
    root = Node("{%s}%s" % (namespace, document.kind))
    root.children = [node for node, _fixed in build(BINDINGS[document.kind], document, document)]
    lines = ['<?xml version="1.0" encoding="UTF-8"?>']
    serialise(root, namespace, 0, lines, declare=True)
    return ("\n".join(lines) + "\n").encode("utf-8")


def build(entries: List[Entry], group: Group, document: Document,
          only: Optional[Tuple[str, Value]] = None, first: bool = True) -> List[Tuple[Node, bool]]:
    """The elements these entries make of a group, each with whether it is
    there only because the binding fixes it (and so says nothing by itself)."""
    made: List[Tuple[Node, bool]] = []
    for entry in entries:
        if isinstance(entry, Leaf):
            if entry.root:
                values = document.terms.get(entry.term, []) if first else []
            elif only and only[0] == entry.term:
                values = [only[1]]
            else:
                values = group.terms.get(entry.term, [])
            made += [(leaf(entry.tag, value), False) for value in values]
        elif isinstance(entry, Fixed):
            made.append((Node(entry.tag, text=entry.text), True))
        elif isinstance(entry, Wrap):
            if entry.per:
                for value in group.terms.get(entry.per, []):
                    if entry.where and not entry.where(value):
                        continue
                    made += wrapped(entry, build(entry.children, group, document,
                                                 (entry.per, value), first), group)
            else:
                made += wrapped(entry, build(entry.children, group, document, only, first),
                                group)
        elif isinstance(entry, Many):
            instances = group.groups.get(entry.group, [])
            if not instances and any(isinstance(e, Leaf) and e.root and document.terms.get(e.term)
                                     for e in entry.children):
                # Something the document holds has its only place in here.
                instances = [Group(entry.group)]
            for number, instance in enumerate(instances):
                node = Node(entry.tag)
                node.children = kept(build(entry.children, instance, document,
                                           first=number == 0), force=True)
                made.append((node, False))
        elif isinstance(entry, Note):
            for note in group.groups.get("BG-1", []):
                text = note.terms.get("BT-22", [Value("")])[0]
                subject = note.terms.get("BT-21", [])
                joined = "#%s#%s" % (subject[0].text, text.text) if subject else text.text
                made.append((leaf(entry.tag, Value(joined, text.attributes)), False))
        else:
            for term in (entry.vat, entry.other):
                for value in group.terms.get(term, []) if term else []:
                    node = Node(entry.tag)
                    scheme = Node(cac("TaxScheme"))
                    scheme.children = [Node(cbc("ID"), text=value.attributes.get(
                        "TaxScheme/ID", "VAT"))]
                    node.children = [leaf(cbc("CompanyID"), value), scheme]
                    made.append((node, False))
    return made


def wrapped(entry: Wrap, inside: List[Tuple[Node, bool]], group: Group) -> List[Tuple[Node, bool]]:
    """A wrapper, if it has anything to hold. One that holds only what the
    binding fixes is itself only fixed: `TaxScheme` with its `VAT`. One that
    is a group of the standard's is written if that group was there, though
    it held nothing."""
    node = Node(entry.tag)
    if all(fixed for _node, fixed in inside):
        if entry.marks and entry.marks in group.present:
            if entry.when:
                # What it was chosen by is fixed in it, and without that it
                # would be read back as something else.
                node.children = [child for child, _fixed in inside]
            return [(node, False)]
        if not inside or not always(entry):
            return []           # it has places for values, and there were none
        node.children = [child for child, _fixed in inside]
        return [(node, True)]
    node.children = kept(inside)
    return [(node, False)]


def always(entry: Entry) -> bool:
    """Whether an entry is nothing but what the binding fixes, all the way down."""
    if isinstance(entry, Fixed):
        return True
    return isinstance(entry, Wrap) and all(always(child) for child in entry.children)


def kept(inside: List[Tuple[Node, bool]], force: bool = False) -> List[Node]:
    """What a parent writes: everything, if any of it says something."""
    if force or any(not fixed for _node, fixed in inside):
        return [node for node, _fixed in inside]
    return []


def leaf(tag: str, value: Value) -> Node:
    return Node(tag, {name: text for name, text in value.attributes.items() if "/" not in name},
                value.text)


def serialise(node: Node, default: str, depth: int, lines: List[str], declare: bool = False) -> None:
    namespace, _, local = node.tag[1:].partition("}")
    name = local if namespace == default else "%s:%s" % (PREFIXES[namespace], local)
    attributes = ""
    if declare:
        attributes = ' xmlns="%s" xmlns:cac="%s" xmlns:cbc="%s"' % (default, CAC_NS, CBC_NS)
    for key in sorted(node.attributes):
        attributes += " %s=%s" % (key, quoteattr(node.attributes[key]))
    pad = "  " * depth
    if node.children:
        lines.append("%s<%s%s>" % (pad, name, attributes))
        for child in node.children:
            serialise(child, default, depth + 1, lines)
        lines.append("%s</%s>" % (pad, name))
    else:
        lines.append("%s<%s%s>%s</%s>" % (pad, name, attributes, escape(node.text), name))
