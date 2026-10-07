"""mock-einvoice: EN 16931 invoices, read, held to their rules, and answered.

So far: UBL 2.1 invoices and credit notes in and out, the rules of the
EN 16931 core, all of Peppol's, and XRechnung's; the
Peppol Invoice Response; and over HTTP a buyer that takes invoices in and
answers them, and a supplier that sends them and takes the answers
(`mockeinvoice.buyer`, `mockeinvoice.supplier`, `mockeinvoice.server`).

    from mockeinvoice import read, validate, write

    document, specification, findings = read(xml)
    document.text("BT-1")                       # the invoice number
    for line in document.all("BG-25"):
        line.term("BT-131").number              # a Decimal, never a float
    xml = write(document)

    document, report = validate(xml)
    report.verdict                              # "invalid", "not judged" or "valid"
    for finding in report.failures:
        finding.code, finding.path, finding.text    # "BR-CO-10", "BT-106", ...

`read` refuses, with `Refused`, what is not built: anything that is not a UBL
`Invoice` or `CreditNote`, and any specification other than Peppol BIS Billing
3.0 and XRechnung 3.0. `validate` holds a document to the rules that are
built, and says which were not: a document's verdict is "valid" only when
every fatal rule that could apply to it ran and found nothing.
"""
from __future__ import annotations

from typing import List, Tuple, Union

from . import response as _response
from . import specification as _specification
from .model import Document, Finding, Group, Refused, Value
from .response import Response
from .rules import Report, check, check_response
from .ubl import parse, parse_tree, write

__version__ = "0.1.0"

__all__ = ["Document", "Finding", "Group", "Refused", "Report", "Response", "Value", "check",
           "read", "read_response", "validate", "validate_response", "write", "write_response",
           "__version__"]


def read(data: Union[bytes, str]) -> Tuple[Document, str, List[Finding]]:
    """Read an invoice or credit note: the document, which specification it
    says it follows (`"peppol"` or `"xrechnung"`), and what the reader has to
    say about it. Raises `Refused` for what is not taken."""
    document, findings = parse(data)
    return document, _specification.identify(document), findings


def validate(data: Union[bytes, str]) -> Tuple[Document, Report]:
    """Read a document and hold it to the rules of its specification that are
    built. The report has what the reader said first, then what the rules
    found, the rules that ran, and the published rules that did not."""
    document, findings, sent = parse_tree(data)
    specification = _specification.identify(document)
    return document, check(document, specification, findings, sent)


def read_response(data: Union[bytes, str]) -> Tuple[Response, List[Finding]]:
    """Read a Peppol Invoice Response, and what the reader has to say of it.
    Raises `Refused` for what is not one."""
    return _response.read(data)


def write_response(response: Response) -> bytes:
    """Write an Invoice Response as a UBL `ApplicationResponse`."""
    return _response.write(response)


def validate_response(data: Union[bytes, str]) -> Tuple[Response, Report]:
    """Read an Invoice Response and hold it to its rules."""
    response, findings, sent = _response.parse_tree(data)
    return response, check_response(sent, findings)
