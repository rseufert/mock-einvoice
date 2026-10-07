# mock-einvoice

A mock e-invoicing partner: EN 16931 invoices in and out, with the responses that follow. Zero dependencies.

A sibling of [mock-sap](https://github.com/rseufert/mock-sap), [mock-edi](https://github.com/rseufert/mock-edi) and [mock-bank](https://github.com/rseufert/mock-bank), and of [mock-acme](https://github.com/rseufert/mock-acme), the integration between them.

**It is not a mock yet.** What is built reads and writes invoices. It does not hold one to any rule, it has no server, and it answers nothing. [#1](https://github.com/rseufert/mock-einvoice/issues/1) says what the first release is to be; nothing is on PyPI until then.

## What is built

UBL 2.1 `Invoice` and `CreditNote`, into one model named by the business terms of EN 16931, and back.

```python
from mockeinvoice import read, write

document, specification, findings = read(xml)     # bytes or str

document.kind                       # "Invoice" or "CreditNote"
specification                       # "peppol" or "xrechnung"
document.text("BT-1")               # the invoice number
document.term("BT-115").number      # the amount due, a Decimal
for line in document.all("BG-25"):  # the lines
    line.text("BT-153"), line.term("BT-131").number

xml = write(document)               # UBL again, in the schema's order
```

- **Terms by number.** `BT-1` is the invoice number in an invoice and in a credit note, whatever UBL calls the element. `mockeinvoice.model.TERMS` names all of them.
- **Decimals.** Every amount, quantity, price and percentage is a `decimal.Decimal` made from the text as written. `10.50` stays `10.50`. There is no float anywhere, and making a value from one is a `TypeError`.
- **Groups that repeat are groups**: lines (`BG-25`), the VAT breakdown (`BG-23`), allowances and charges, notes, payment instructions, supporting documents. A group that occurs once (the seller, the totals) has its terms on the document or the line itself.
- **Findings.** What the reader has to say about a document, each with a level, a code and the path it is about.

## What it refuses

`read` raises `Refused`, with a `code` and a sentence naming what was sent, for:

| Code | What |
| --- | --- |
| `NOT-XML` | anything that is not well-formed XML |
| `DTD` | a document with a `DOCTYPE`. Nothing in it is expanded or fetched. |
| `CII` | a UN/CEFACT Cross Industry Invoice. Not built. |
| `NOT-AN-INVOICE`, `NOT-UBL` | any other UBL document, and anything else |
| `NO-SPECIFICATION` | no `CustomizationID` (BT-24) |
| `XRECHNUNG-EXTENSION`, `XRECHNUNG-CVD` | those two kinds of XRechnung. Not built. |
| `SPECIFICATION` | any other identifier, plain EN 16931 among them |

The two identifiers taken are Peppol BIS Billing 3.0 and XRechnung 3.0. An identifier this package does not know is refused, not quietly held to the core alone.

## What the reader does not hold

UBL has thousands of elements and EN 16931 has a place for about a hundred and sixty. The rest is not held, and is never dropped without saying so:

| Finding | Level | What |
| --- | --- | --- |
| `UNHELD` | warning | an element with no business term (it is not written back), or an attribute with none (it is kept with its value) |
| `REPEATED` | error | an element that occurs twice where the standard has one. Every value is still held, in order. |
| `NOT-DECIMAL` | error | a number that is not what XML Schema calls a decimal: `1,190.00`, `1e3` |
| `FIXED` | warning | an element the binding gives one value, written another way: `ChargeIndicator` as `0` |
| `TEXT`, `STRUCTURE`, `EMPTY` | | text among elements, elements where text belongs, a group with nothing in it |

These are the reader's own findings, not published rules. The published rules, by their published identifiers, are the next step ([#3](https://github.com/rseufert/mock-einvoice/issues/3)).

## Known to be wrong, or not real

- **No XML Schema validation.** The published validators check the UBL schema before any rule. The standard library cannot, so this reads what it understands and reports what it did not. A document that is not schema-valid is not refused for that.
- **The writer does not promise the same bytes.** Reading what was written gives an equal document. The order among repeats of different kinds (allowances and charges, say), the namespace prefixes, white space, comments and anything `UNHELD` are not kept.
- **The writer does not supply what UBL requires and the model lacks.** A credit note with a due date and no payment means is written with a `PaymentMeans` that holds only the date, which the UBL schema does not allow; that is where the binding puts the date.
- **The creditor identifier has two places and one term.** `BT-90` is a party identifier with scheme `SEPA`, on the payee or the seller. It is read from either and written to the payee if there is one. A document with one on each comes back with both on one party.
- **A note's subject code** (`BT-21`) is read from `#CODE#` at the start of a note's text. That convention is from memory of the standard's UBL binding and was not checked against a published source.

## How it was checked

- The table of where each term sits agrees, term for term, with the syntax description Peppol publishes for BIS Billing 3.0.21, for both documents.
- Its order agrees with the UBL 2.1 schemas from OASIS, for both documents and every aggregate under them.
- The seventeen UBL examples published with the EN 16931 validation artefacts are read, written and compared element for element by a reader that is not this one. They are in `tests/samples/external/en16931`, unmodified, under their own licence.

The first two were checked while building and are not tests here: neither source is in this repository.

## Licences

The package is MIT. The examples under `tests/samples/external/` are not: each directory has a README naming where its files came from and the licence they are under. They are in the source distribution and not in the wheel.

## Development

```
python -m unittest
```

Python 3.8 or later, and nothing to install. The repository's settings are described in [docs/GITHUB.md](docs/GITHUB.md).
