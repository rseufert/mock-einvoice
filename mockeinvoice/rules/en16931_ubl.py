"""The EN 16931 core's rules about the UBL document itself.

Three families, asked of the document's elements and not of the model
(`tree.py`):

- `UBL-CR`: an element or attribute UBL has and the standard has no use for
  is not there. 676 warnings and two fatal rules, one to each such place.
- `UBL-DT`: what an element's data type allows: two decimals on an amount,
  an attachment's MIME type and file name, and 21 attributes that are not to
  be anywhere.
- `UBL-SR`: an element the standard has once is there at most once, and a
  few that must be there. 54 fatal rules.

Of the 756, all but 26 are one of two tests with a different path in each.
Those paths are in `ublsyntax.py`, which is generated from the published
rules and is under their licence, not this package's. The 26 are below.

What the published tests say that one might not expect
------------------------------------------------------
- **A payee with no name fails three rules** (`UBL-SR-19`, `-20`, `-21`).
  Each ends by comparing the payee's name with the seller's legal name, and
  a name that is not there is not different from anything. So does a seller
  with no legal name, whatever the payee is called.
- **Two payment instructions must say the same** (`UBL-SR-44`, `-47`): the
  rules count the different payment references and payment means codes in
  the document, and allow one of each.
- **An attachment needs a MIME type and a file name** (`UBL-DT-06`, `-07`),
  though the code list rule lets an attachment without a MIME type pass.
- **Any element whose name ends in `Amount`** is held to two decimals
  (`UBL-DT-01`), a price and a price's allowance excepted, whether or not the
  standard has a term for it.

Where this departs from the published tests
-------------------------------------------
- **A charge indicator that is neither true nor false.** Two rules pick
  allowances and charges by it, which is an XPath error on other text. Here
  those two rules are reported as not computable.
- **A tax scheme named twice in one registration.** Three rules upper-case
  the scheme's identifier, which is an XPath error if there are two. Here
  either may match.
"""
from __future__ import annotations

import functools
from typing import Iterator, List

from . import Failure, rule
from .tree import ROOT, At, contexts, elements, select, tag, texts
from .ublsyntax import ABSENT, AT_MOST_ONE

en16931 = functools.partial(rule, "en16931", over="tree")

AMOUNT, BINARY_OBJECT = "Amount", "BinaryObject"
PRICE, ALLOWANCE_CHARGE = tag("cac:Price"), tag("cac:AllowanceCharge")
REFERENCE = "cac:AdditionalDocumentReference"
SELLERS_NAME = "cac:AccountingSupplierParty/cac:Party/cac:PartyLegalEntity/cbc:RegistrationName"


# -- the two tests most of them are --------------------------------------------

def absent(identifier: str, path: str) -> None:
    last = path.rpartition("/")[2]
    what = "the attribute %s" % last[1:] if last.startswith("@") else "the element %s" % last
    place = path.rpartition("/")[0].lstrip("/")
    about = "%s is not used%s" % (what, (" %s %s" % (
        "on" if last.startswith("@") else "in", place) if place else
        " anywhere" if path.startswith("//") else " at the head of the document"))

    @en16931(identifier, about)
    def check(root: At) -> Iterator[Failure]:
        for where, _text in select(root, path):
            yield where, "it is there"


def at_most_one(identifier: str, context: str, path: str) -> None:
    about = "%s is there at most once%s" % (
        path, "" if context == ROOT else " in each %s" % context.partition("[")[0])

    @en16931(identifier, about)
    def check(root: At) -> Iterator[Failure]:
        for at in contexts(root, context):
            found = select(at, path)
            if len(found) > 1:
                # Where the second one is, which is where the reader says
                # an element is repeated.
                yield found[1][0], "it is there %d times" % len(found)


for _identifier, _path in ABSENT.items():
    absent(_identifier, _path)
for _identifier, (_context, _path) in AT_MOST_ONE.items():
    at_most_one(_identifier, _context, _path)


# -- UBL-CR: the rest ------------------------------------------------------------

@en16931("UBL-CR-002", "the UBL version, if it is given, is 2.1")
def ubl_cr_002(root: At) -> Iterator[Failure]:
    versions = elements(root, "cbc:UBLVersionID")
    if versions and "2.1" not in texts(versions):
        yield versions[0].path, "it is %r" % versions[0].text


@en16931("UBL-CR-412", "an invoice has no due date in its payment instructions; a credit "
                       "note has it there")
def ubl_cr_412(root: At) -> Iterator[Failure]:
    if root.node.tag == tag("cn:CreditNote"):
        return
    for date in elements(root, "cac:PaymentMeans/cbc:PaymentDueDate"):
        yield date.path, "it is there"


def typed(root: At, invoiced_object: bool) -> List[At]:
    """Every additional document reference whose type code is, or is not, 130.

    "Is not" is the published test's: some type code of its is another, or it
    has none.
    """
    found = []
    for at in root.everything():
        if at.node.tag != tag(REFERENCE):
            continue
        codes = texts(elements(at, "cbc:DocumentTypeCode"))
        if ("130" in codes) if invoiced_object else (not codes or any(c != "130" for c in codes)):
            found.append(at)
    return found


@en16931("UBL-CR-665", "the identifier of a supporting document has no scheme; only an "
                       "invoiced object's identifier has one")
def ubl_cr_665(root: At) -> Iterator[Failure]:
    for reference in typed(root, invoiced_object=False):
        for where, _scheme in select(reference, "cbc:ID/@schemeID"):
            yield where, "it is there"


def not_on_an_invoiced_object(identifier: str, name: str, what: str) -> None:
    @en16931(identifier, "a reference to an invoiced object has no %s" % what)
    def check(root: At) -> Iterator[Failure]:
        for reference in typed(root, invoiced_object=True):
            for found in elements(reference, name):
                yield found.path, "it is there"


not_on_an_invoiced_object("UBL-CR-666", "cac:Attachment", "attachment")
not_on_an_invoiced_object("UBL-CR-673", "cbc:DocumentDescription", "description")


# -- UBL-DT ----------------------------------------------------------------------

@en16931("UBL-DT-01", "an amount has at most two decimals, a price and a price's allowance "
                      "excepted")
def ubl_dt_01(root: At) -> Iterator[Failure]:
    for at in root.everything():
        name = at.node.tag.rpartition("}")[2]
        if not name.endswith(AMOUNT) or name.endswith("PriceAmount"):
            continue
        # Excepted: anything inside a price that has an allowance in it.
        if any(a.node.tag == PRICE and any(c.node.tag == ALLOWANCE_CHARGE for c in a.children)
               for a in at.ancestors()):
            continue
        if len(at.text.partition(".")[2]) > 2:
            yield at.path, "it is %s" % at.text


def on_an_attachment(identifier: str, attribute: str, what: str) -> None:
    @en16931(identifier, "an attached document says its %s" % what)
    def check(root: At) -> Iterator[Failure]:
        for at in root.everything():
            if at.node.tag.endswith(BINARY_OBJECT) and attribute not in at.node.attributes:
                yield at.path, "it does not"


on_an_attachment("UBL-DT-06", "mimeCode", "MIME type")
on_an_attachment("UBL-DT-07", "filename", "file name")


@en16931("UBL-DT-18", "the attribute name is on a payment means code and nowhere else")
def ubl_dt_18(root: At) -> Iterator[Failure]:
    for at in root.everything():
        if "name" in at.node.attributes and at.node.tag != tag("cbc:PaymentMeansCode"):
            yield "%s/@name" % at.path, "it is there"


# -- UBL-SR: the rest ------------------------------------------------------------

@en16931("UBL-SR-04", "the invoiced object has at most one identifier")
def ubl_sr_04(root: At) -> Iterator[Failure]:
    found = [identifier for reference in elements(root, REFERENCE)
             if "130" in texts(elements(reference, "cbc:DocumentTypeCode"))
             for identifier in elements(reference, "cbc:ID")]
    if len(found) > 1:
        yield found[1].path, "it has %d" % len(found)


@en16931("UBL-SR-07", "a preceding invoice reference has the invoice's number")
def ubl_sr_07(root: At) -> Iterator[Failure]:
    for reference in contexts(root, "cac:BillingReference"):
        if not elements(reference, "cac:InvoiceDocumentReference/cbc:ID"):
            yield reference.path, "it has none"


def registrations(party: At, vat: bool) -> List[At]:
    """A party's tax registration identifiers under the scheme VAT, or under
    another: compared upper-cased and not trimmed, as the tests have it."""
    found = []
    for scheme in elements(party, "cac:PartyTaxScheme"):
        said = [identifier.text.upper()
                for tax_scheme in elements(scheme, "cac:TaxScheme")
                for identifier in elements(tax_scheme, "cbc:ID")]
        # A tax scheme with no identifier is "not VAT": nothing is not `VAT`.
        other = any(not elements(tax_scheme, "cbc:ID")
                    for tax_scheme in elements(scheme, "cac:TaxScheme"))
        if ("VAT" in said) if vat else (other or any(s != "VAT" for s in said)):
            found += elements(scheme, "cbc:CompanyID")
    return found


def one_registration(identifier: str, party: str, name: str, vat: bool) -> None:
    @en16931(identifier, "the %s has at most one %s" % (
        name, "VAT identifier" if vat else "tax registration that is not for VAT"))
    def check(root: At) -> Iterator[Failure]:
        found = [identifier for at in elements(root, "%s/cac:Party" % party)
                 for identifier in registrations(at, vat)]
        if len(found) > 1:
            yield found[1].path, "it has %d" % len(found)


one_registration("UBL-SR-12", "cac:AccountingSupplierParty", "seller", True)
one_registration("UBL-SR-13", "cac:AccountingSupplierParty", "seller", False)
one_registration("UBL-SR-18", "cac:AccountingCustomerParty", "buyer", True)


def differs_from_the_seller(payee: At) -> bool:
    """`(payee name) != (seller's legal name)`: some name of the one is not
    some name of the other, which neither is if either is not there."""
    names = texts(elements(payee, "cac:PartyName/cbc:Name"))
    sellers = texts(elements(payee.parent, SELLERS_NAME)) if payee.parent else []
    return any(name != seller for name in names for seller in sellers)


def of_a_payee(identifier: str, what: str, counted) -> None:
    @en16931(identifier, "a payee has at most one %s, and a name that is not the seller's "
                         "legal name" % what)
    def check(root: At) -> Iterator[Failure]:
        for payee in contexts(root, "cac:PayeeParty"):
            found = counted(payee)
            if len(found) > 1:
                yield found[1].path, "it has %d" % len(found)
            elif not differs_from_the_seller(payee):
                yield payee.path, ("its name is not different from the seller's legal name, "
                                   "or one of the two is not there")


of_a_payee("UBL-SR-19", "name", lambda payee: elements(payee, "cac:PartyName/cbc:Name"))
of_a_payee("UBL-SR-20", "identifier besides its creditor identifier", lambda payee: [
    identifier for identifier in elements(payee, "cac:PartyIdentification/cbc:ID")
    if identifier.node.attributes.get("schemeID", "").upper() != "SEPA"])
of_a_payee("UBL-SR-21", "legal registration identifier",
           lambda payee: elements(payee, "cac:PartyLegalEntity/cbc:CompanyID"))


@en16931("UBL-SR-29", "the document has at most one bank assigned creditor identifier")
def ubl_sr_29(root: At) -> Iterator[Failure]:
    found = [identifier for at in root.everything()
             if at.node.tag == tag("cac:PartyIdentification")
             for identifier in elements(at, "cbc:ID")
             if identifier.node.attributes.get("schemeID", "").upper() == "SEPA"]
    if len(found) > 1:
        yield found[1].path, "it has %d" % len(found)


@en16931("UBL-SR-42", "the seller has at most two tax registrations")
def ubl_sr_42(root: At) -> Iterator[Failure]:
    for party in contexts(root, "cac:AccountingSupplierParty/cac:Party"):
        found = elements(party, "cac:PartyTaxScheme")
        if len(found) > 2:
            yield found[2].path, "it has %d" % len(found)


@en16931("UBL-SR-43", "an additional document reference has a scheme on its identifier or a "
                      "type code only if it is the invoiced object (type 130) or, on a credit "
                      "note, the project (type 50)")
def ubl_sr_43(root: At) -> Iterator[Failure]:
    credit_note = root.node.tag == tag("cn:CreditNote")
    for reference in contexts(root, REFERENCE):
        codes = texts(elements(reference, "cbc:DocumentTypeCode"))
        if "130" in codes or (credit_note and "50" in codes):
            continue
        if codes:
            yield reference.path, "its type code is %r" % codes[0]
        elif select(reference, "cbc:ID/@schemeID"):
            yield reference.path, "its identifier has a scheme and it has no type code"


def said_once(identifier: str, name: str, what: str) -> None:
    """`count(//X[not(preceding::X/. = .)]) <= 1`: the different values."""
    @en16931(identifier, "every payment instruction has the same %s" % what)
    def check(root: At) -> Iterator[Failure]:
        seen: List[str] = []
        for at in root.everything():
            if at.node.tag == tag(name) and at.text not in seen:
                seen.append(at.text)
                if len(seen) == 2:
                    yield at.path, "%r here and %r before it" % (at.text, seen[0])


said_once("UBL-SR-44", "cbc:PaymentID", "payment reference")
said_once("UBL-SR-47", "cbc:PaymentMeansCode", "payment means code")


@en16931("UBL-SR-46", "at most one payment means code in the document says what it means")
def ubl_sr_46(root: At) -> Iterator[Failure]:
    found = select(root, "cac:PaymentMeans/cbc:PaymentMeansCode/@name")
    if len(found) > 1:
        yield found[1][0], "%d do" % len(found)


@en16931("UBL-SR-48", "a line has exactly one VAT category")
def ubl_sr_48(root: At) -> Iterator[Failure]:
    for line in contexts(root, "cac:InvoiceLine | cac:CreditNoteLine"):
        found = elements(line, "cac:Item/cac:ClassifiedTaxCategory")
        if len(found) != 1:
            yield (found[1].path if found else line.path), "it has %d" % len(found)


@en16931("UBL-SR-51", "an address has at most one third line")
def ubl_sr_51(root: At) -> Iterator[Failure]:
    for address in contexts(root, "//cac:PostalAddress | //cac:Address"):
        found = elements(address, "cac:AddressLine")
        if len(found) > 1:
            yield found[1].path, "it has %d" % len(found)


@en16931("UBL-SR-53", "a tax registration has an identifier and names its tax scheme")
def ubl_sr_53(root: At) -> Iterator[Failure]:
    for registration in contexts(root, "cac:PartyTaxScheme"):
        missing = [name for name in ("cac:TaxScheme/cbc:ID", "cbc:CompanyID")
                   if not elements(registration, name)]
        if missing:
            yield registration.path, "it has no %s" % " and no ".join(missing)
