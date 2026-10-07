# mock-einvoice

A mock e-invoicing partner: EN 16931 invoices in and out, with the responses that follow. Zero dependencies.

A sibling of [mock-sap](https://github.com/rseufert/mock-sap), [mock-edi](https://github.com/rseufert/mock-edi) and [mock-bank](https://github.com/rseufert/mock-bank), and of [mock-acme](https://github.com/rseufert/mock-acme), the integration between them.

**It is not a mock yet.** What is built reads and writes invoices and holds them to the first 44 of the published rules. It has no server and answers nothing, and no document's verdict is "valid" until every fatal rule of its specification is built. [#1](https://github.com/rseufert/mock-einvoice/issues/1) says what the first release is to be; nothing is on PyPI until then.

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

## The rules

```python
from mockeinvoice import validate

document, report = validate(xml)

report.verdict                      # "invalid", or "not judged"
for finding in report.failures:
    finding.code                    # "BR-CO-10": the rule's published identifier
    finding.level                   # "fatal": the flag its publisher gave it
    finding.path                    # "BT-106": where, in the model
    finding.text                    # what the rule asks and what was found, in our words
    finding.link                    # where the rule itself is published
report.ran                          # the rules that were run
report.not_built                    # by layer, the published rules that were not
```

A rule is one function under the identifier its publisher gave it. A finding gives that identifier and a link to the published rule; the description is this project's own, and the publisher's wording is not reproduced.

A document names its specification, and that decides its layers:

| Layer | Pinned to | Published rules | Built |
| --- | --- | --- | --- |
| EN 16931 core | [validation artefacts 1.3.16](https://github.com/ConnectingEurope/eInvoicing-EN16931/tree/validation-1.3.16) | 979 (281 fatal) | 44: the calculation rules (`BR-CO-*`) and the decimals rules (`BR-DEC-*`) |
| Peppol BIS Billing 3.0 | 3.0.21, at commit [`806866b`](https://github.com/OpenPEPPOL/peppol-bis-invoice-3/commit/806866bd2bd91d7e9623b68f08164e8fbe9e67a0) (it has no tag) | 166 (139 fatal) | none |
| XRechnung 3.0 | [Schematron 2.6.0](https://github.com/itplr-kosit/xrechnung-schematron/tree/v2.6.0) | 55 (46 fatal) | none |

**Not built is said, never assumed.** `mockeinvoice/rules/published.py` lists every published rule of every layer by identifier and flag, and a report lists the ones that did not run. A document nothing was found wrong with is `not judged`, not `valid`, for as long as a fatal rule of its layers is unbuilt. That is every document today.

**The arithmetic is the rules' own.** The published rules are XPath, and XPath rounds a tie towards positive infinity (`-2.5` is `-2`), which is neither Python's `round` nor half-up. A total that is absent is equal to nothing, so its rule fails. `mockeinvoice/rules/calculation.py` has both.

**A rule that cannot be computed has failed.** Where the published test would stop with an XPath error (a number that is not a number, an amount twice where the test takes one), the finding says the rule could not be computed, and the document is invalid.

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
| `TEXT`, `STRUCTURE` | warning, error | text among elements, and elements where text belongs |

These are the reader's own findings, not published rules. An error among them makes a document invalid as a failing rule does.

A group with nothing in it is still there: an empty `TaxSubtotal` is a VAT breakdown, as it is to the published rules, which ask only that one exists.

## Known to be wrong, or not real

- **No XML Schema validation.** The published validators check the UBL schema before any rule. The standard library cannot, so this reads what it understands and reports what it did not. A document that is not schema-valid is not refused for that.
- **The writer does not promise the same bytes.** Reading what was written gives an equal document. The order among repeats of different kinds (allowances and charges, say), the namespace prefixes, white space, comments and anything `UNHELD` are not kept.
- **The writer does not supply what UBL requires and the model lacks.** A credit note with a due date and no payment instruction is written with a `PaymentMeans` that holds only the date, because that is where the binding puts the date. The UBL schema does not allow it, and read back, the document has an empty payment instruction it did not have before.
- **A tax category's scheme is taken to be VAT.** Several published rules look at a tax category only if its `TaxScheme/ID` is `VAT`. The reader reports any other value (`FIXED`) and holds the category all the same, so such a document is judged here as if it had said VAT.
- **Six published rules cannot fail, here or anywhere.** `BR-CO-05` to `BR-CO-08` are published with the test `true()`. `BR-DEC-13` and `BR-DEC-15` compare a tax amount's currency with an element a tax amount does not have, so they select nothing and pass. They are built as published.
- **A VAT rate under half a percent** rounds to nought in `BR-CO-17`, which then wants the tax to round to nought too. That is the published test, and it is built as published.
- **The creditor identifier has two places and one term.** `BT-90` is a party identifier with scheme `SEPA`, on the payee or the seller. It is read from either and written to the payee if there is one. A document with one on each comes back with both on one party.
- **A note's subject code** (`BT-21`) is read from `#CODE#` at the start of a note's text. That convention is from memory of the standard's UBL binding and was not checked against a published source.

## How it was checked

- The table of where each term sits agrees, term for term, with the syntax description Peppol publishes for BIS Billing 3.0.21, for both documents.
- Its order agrees with the UBL 2.1 schemas from OASIS, for both documents and every aggregate under them.
- The seventeen UBL examples published with the EN 16931 validation artefacts are read, written and compared element for element by a reader that is not this one. They are in `tests/samples/external/en16931`, unmodified, under their own licence.

- The 44 rules agree with all 148 cases in the unit tests the EN 16931 artefacts publish for them (`test/Invoice-unit-UBL` and `test/CreditNote-unit-UBL`, `BR-CO-*`; there are none for `BR-DEC-*`). The first run disagreed on two, both about an empty VAT breakdown, and the reader was changed.

The third is a test here. The others were checked while building and are not: those sources are not in this repository yet ([#4](https://github.com/rseufert/mock-einvoice/issues/4) brings in the unit tests).

## Licences

The package is MIT. The examples under `tests/samples/external/` are not: each directory has a README naming where its files came from and the licence they are under. They are in the source distribution and not in the wheel.

## Development

```
python -m unittest
```

Python 3.8 or later, and nothing to install.

`tools/published_rules.py` regenerates `mockeinvoice/rules/published.py` from the three Schematron files when a pin moves. It takes each rule's identifier and flag and nothing else. The repository's settings are described in [docs/GITHUB.md](docs/GITHUB.md).
