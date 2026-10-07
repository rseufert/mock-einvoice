"""mock-einvoice: EN 16931 invoices, read, held to their rules, and answered.

So far: UBL 2.1 invoices and credit notes in and out.

    from mockeinvoice import read, write

    document, specification, findings = read(xml)
    document.text("BT-1")                       # the invoice number
    for line in document.all("BG-25"):
        line.term("BT-131").number              # a Decimal, never a float
    xml = write(document)

`read` refuses, with `Refused`, what is not built: anything that is not a UBL
`Invoice` or `CreditNote`, and any specification other than Peppol BIS Billing
3.0 and XRechnung 3.0. It does not yet hold a document to any rule.
"""
from __future__ import annotations

from typing import List, Tuple, Union

from . import specification as _specification
from .model import Document, Finding, Group, Refused, Value
from .ubl import parse, write

__version__ = "0.1.0.dev0"

__all__ = ["Document", "Finding", "Group", "Refused", "Value", "read", "write", "__version__"]


def read(data: Union[bytes, str]) -> Tuple[Document, str, List[Finding]]:
    """Read an invoice or credit note: the document, which specification it
    says it follows (`"peppol"` or `"xrechnung"`), and what the reader has to
    say about it. Raises `Refused` for what is not taken."""
    document, findings = parse(data)
    return document, _specification.identify(document), findings
