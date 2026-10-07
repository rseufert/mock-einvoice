# mock-einvoice

A mock e-invoicing partner: EN 16931 invoices in and out, with the responses that follow. Zero dependencies.

A sibling of [mock-sap](https://github.com/rseufert/mock-sap), [mock-edi](https://github.com/rseufert/mock-edi) and [mock-bank](https://github.com/rseufert/mock-bank), and of [mock-acme](https://github.com/rseufert/mock-acme), the integration between them.

**It is not a mock yet.** What is built reads and writes invoices and holds them to the first 102 of the published rules. It has no server and answers nothing, and no document's verdict is "valid" until every fatal rule of its specification is built. [#1](https://github.com/rseufert/mock-einvoice/issues/1) says what the first release is to be; nothing is on PyPI until then.

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
- **One term, two places.** The bank assigned creditor identifier (`BT-90`) may be on the seller or the payee. It is one term here, each value noting if it was the payee's, and it is written back where it was read.

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
| EN 16931 core | [validation artefacts 1.3.16](https://github.com/ConnectingEurope/eInvoicing-EN16931/tree/validation-1.3.16) | 979 (281 fatal) | 102: what a document must have in it (`BR-01` to `BR-65`), the calculation rules (`BR-CO-*`) and the decimals rules (`BR-DEC-*`) |
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
- **A tax category that names no scheme counts as VAT.** `BR-32`, `BR-37`, `BR-47` and `BR-48` look for a category whose scheme is VAT, and one with no `TaxScheme` at all is not that. The model does not hold whether a scheme was named, so here it passes where a real validator fails it. UBL's schema requires the element.
- **An element the standard has once, sent twice, is one here.** Two seller addresses are held as one address with what was in both, and the reader says so (`REPEATED`). A published rule runs once for each; here it runs once, and where it takes one value and finds two it is reported as not computable.
- **A date outside the years 0001 to 9999** cannot be compared here, and a rule that compares it (`BR-29`, `BR-30`) is reported as not computable. XPath can compare it. A date that names no time zone is compared as UTC, which XPath leaves to the implementation.
- **Four rules are published twice.** `BR-CO-21` to `BR-CO-24` have the same test as `BR-33`, `BR-38`, `BR-42` and `BR-44`, so an allowance or charge with no reason fails two rules, as it does in a real validator.
- **Six published rules cannot fail, here or anywhere.** `BR-CO-05` to `BR-CO-08` are published with the test `true()`. `BR-DEC-13` and `BR-DEC-15` compare a tax amount's currency with an element a tax amount does not have, so they select nothing and pass. They are built as published.
- **A VAT rate under half a percent** rounds to nought in `BR-CO-17`, which then wants the tax to round to nought too. That is the published test, and it is built as published.
- **A note's subject code** (`BT-21`) is read from `#CODE#` at the start of a note's text. That convention is from memory of the standard's UBL binding and was not checked against a published source.

## Held to what others published

The rules, the reader and the writer are tested against files this project did not write.

| Source, at the pinned version | What | How it comes out today |
| --- | --- | --- |
| EN 16931 unit tests | 1,137 cases, each a small document and what one rule should make of it | 460 agree, none disagree. 667 are for the 123 rules with cases that are not built yet, and are compared with nothing. 12 name `BR-CO-25`, which the pinned rule file does not have. |
| EN 16931 examples | 17 documents | read, written back, and compared element for element by a reader that is not this one |
| XRechnung test suite | 39 valid XRechnung 3.0 documents | read with nothing to say, written back element for element, and no built rule fails |
| XRechnung test suite | 5 Extension and 1 CVD document | refused by name |
| Peppol unit tests | 400 cases | none of Peppol's rules is built: 396 are compared with nothing, and 4 are about a UBL Order |
| Peppol examples | 10 documents | as XRechnung's valid ones |

- **A case for a rule that is not built is never counted as agreeing.** The counts are written out in `tests/test_upstream.py`, so building a rule moves a number there on purpose.
- **A disagreement is a failure here** until the published rule shows the case to be wrong; then it is listed in `tests/upstream.py` by name, with the reason. None is.
- **To read the counts:** `python -m tests.upstream`. CI prints them on every run.

Peppol's files are not in this repository (see Licences). `python tools/fetch_peppol.py` fetches the 100 listed in `tools/peppol-files.tsv` from the pinned commit, checks each against the git hash listed for it, and puts them where the tests look. Without them those two tests are skipped and say so. CI fetches them on two of its jobs.

Two things were checked while building and are not tests, because their sources are not here:

- The table of where each term sits agrees, term for term, with the syntax description Peppol publishes for BIS Billing 3.0.21, for both documents.
- Its order agrees with the UBL 2.1 schemas from OASIS, for both documents and every aggregate under them.

## Licences

The package is MIT, and the wheel holds the package and nothing else.

The files under `tests/samples/external/` are other people's, copied unmodified, each directory with the licence its files are under and a README saying where they came from. They are in the repository and the source distribution, which is about 5 MB because of them.

| Directory | From | Licence |
| --- | --- | --- |
| `en16931/` | the EN 16931 validation artefacts, `validation-1.3.16` | EUPL 1.2 |
| `xrechnung/` | the XRechnung test suite, `v2026-08-31` | Apache 2.0 |

Peppol's examples and unit tests are **not** here. Peppol BIS Billing is published with a statement that it may not be redistributed without OpenPeppol's consent, so they are fetched for the tests and are in nothing this project ships. CI checks the source distribution for them.

This is a reading of the licence texts by the people who wrote the code, not legal advice.

## Development

```
python -m unittest
```

Python 3.8 or later, and nothing to install.

`tools/published_rules.py` regenerates `mockeinvoice/rules/published.py` from the three Schematron files when a pin moves. It takes each rule's identifier and flag and nothing else. The repository's settings are described in [docs/GITHUB.md](docs/GITHUB.md).
