# mock-einvoice

A mock e-invoicing partner: EN 16931 invoices in and out, with the responses that follow. Zero dependencies.

A sibling of [mock-sap](https://github.com/rseufert/mock-sap), [mock-edi](https://github.com/rseufert/mock-edi) and [mock-bank](https://github.com/rseufert/mock-bank), and of [mock-acme](https://github.com/rseufert/mock-acme), the integration between them.

```
python3 -m pip install mock-einvoice
mock-einvoice --port 8100
```

It reads and writes UBL invoices and credit notes, and the Peppol Invoice Response that answers one, and holds them to their published rules: invoices to all 979 rules of the EN 16931 core, to all 165 of Peppol's (its own 63, the 31 it has for Germany and the 71 for seven other countries), and to the 34 of a standard XRechnung document; responses to all 82 of theirs. Over HTTP it is a buyer that takes invoices in and answers the Peppol ones, and a supplier that sends them, writes the invoice for an order it is told of, and takes the answers.

**What 0.2.0 is not:**

- **It writes no invoices of its own.** The supplier sends the documents it is given. (Since 0.2.0, and not yet released: it writes the invoice for an order it is told of. See [An order, and the invoice for it](#an-order-and-the-invoice-for-it).)
- **It knows nothing of the other mocks.** Writing an invoice from one of mock-sap's billing documents, and saying "paid" when SAP has cleared it, is integration, and belongs in [mock-acme](https://github.com/rseufert/mock-acme) with the rest of it. It is not built there yet.
- **Peppol's ten rules for a seller in Iceland are held to this project's tests only.** Peppol publishes unit tests for its rules for Denmark, Greece, Italy, the Netherlands, Norway and Sweden, and every case agrees here; for Iceland it publishes none. Those ten were written from the same reading of the rule file as the tests that hold them, so a misreading would be in both.
- **No CII, no XRechnung Extension, no ZUGFeRD**, and no transport: see [What it refuses](#what-it-refuses) and [Known to be wrong, or not real](#known-to-be-wrong-or-not-real).

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

- **Terms by number.** `BT-1` is the invoice number in an invoice and in a credit note, whatever UBL calls the element. `mockeinvoice.model.TERMS` names all of them, and the server gives the same table to a client that cannot import it: `GET /_mock/terms`.
- **Decimals.** Every amount, quantity, price and percentage is a `decimal.Decimal` made from the text as written. `10.50` stays `10.50`. There is no float anywhere, and making a value from one is a `TypeError`.
- **Groups that repeat are groups**: lines (`BG-25`), the VAT breakdown (`BG-23`), allowances and charges, notes, payment instructions, supporting documents. A group that occurs once (the seller, the totals) has its terms on the document or the line itself.
- **Findings.** What the reader has to say about a document, each with a level, a code and the path it is about.
- **One term, two places.** The bank assigned creditor identifier (`BT-90`) may be on the seller or the payee. It is one term here, each value noting if it was the payee's, and it is written back where it was read.

## The rules

```python
from mockeinvoice import validate

document, report = validate(xml)

report.verdict                      # "invalid", "not judged", or "valid"
for finding in report.failures:
    finding.code                    # "BR-CO-10": the rule's published identifier
    finding.level                   # "fatal": the flag its publisher gave it
    finding.path                    # "BT-106": where, in the model; or, for a rule about
                                    # the XML itself, "/Invoice/cbc:UUID"
    finding.text                    # what the rule asks and what was found, in our words
    finding.link                    # where the rule itself is published
report.ran                          # the rules that were run
report.not_built                    # by layer, the published rules that were not
report.not_applicable               # and those not built that could not apply to it
```

A rule is one function under the identifier its publisher gave it. A finding gives that identifier and a link to the published rule; the description is this project's own, and the publisher's wording is not reproduced.

A document names its specification, and that decides its layers:

| Layer | Pinned to | Published rules | Built |
| --- | --- | --- | --- |
| EN 16931 core | [validation artefacts 1.3.16](https://github.com/ConnectingEurope/eInvoicing-EN16931/tree/validation-1.3.16) | 979 (281 fatal) | all 979: what a document must have in it (`BR-01` to `BR-65`), the calculation rules (`BR-CO-*`), the decimals rules (`BR-DEC-*`), the ten families of VAT category rules, the code lists (`BR-CL-*`), and the 756 rules about the UBL document itself (`UBL-CR-*`, `UBL-DT-*`, `UBL-SR-*`) |
| Peppol BIS Billing 3.0 | 3.0.21, at commit [`806866b`](https://github.com/OpenPEPPOL/peppol-bis-invoice-3/commit/806866bd2bd91d7e9623b68f08164e8fbe9e67a0) (it has no tag) | 165 (139 fatal) | all 165: Peppol's own 63 (`PEPPOL-EN16931-*`, `PEPPOL-COMMON-*`), Germany's 31 (`DE-R-*`), and the 71 for a seller in Denmark, Greece, Iceland, Italy, the Netherlands, Norway or Sweden (`DK-R`, `GR-R`, `GR-S`, `IS-R`, `IT-R`, `NL-R`, `NO-R`, `SE-R`) |
| XRechnung 3.0 | [Schematron 2.6.0](https://github.com/itplr-kosit/xrechnung-schematron/tree/v2.6.0) | 56 (46 fatal) | 34: every rule of a standard XRechnung document (`BR-DE-*`, `BR-TMP-2`, `BR-TMP-6`). Not the 22 of XRechnung Extension and CVD (`BR-DEX-*`, `BR-DE-CVD-*`), whose documents are refused by name |

**Not built is said, never assumed.** `mockeinvoice/rules/published.py` lists every published rule of every layer by identifier and flag, and a report lists the ones that did not run. A document nothing was found wrong with is `not judged`, not `valid`, for as long as a fatal rule that could apply to it is unbuilt. Every rule that can apply to a document this package takes is built, so no document is `not judged` today; the verdict is kept for the day a specification publishes a rule before this package has it.

**A rule that could not apply is not waited on.** The rules of XRechnung Extension and CVD say nothing of a standard XRechnung document. A report lists them apart, as `not_applicable`, and they do not hold back its verdict.

**Where a seller is, is not one question.** Peppol's rules for a seller's country do not agree on what makes a document one of theirs. Norway, Italy and Greece go by the first two letters of the seller's VAT identifier, then its tax representative's, and only then by the country of its address. Denmark, Iceland and Sweden go by the address, written exactly (`dk` is not Denmark). The Netherlands goes by the address however it is written. Each rule here goes by what its published test goes by, and `mockeinvoice/rules/peppol_national.py` says which.

**Two things a rule is asked of.** Most rules are asked of the model. The 756 about the UBL document itself are asked of its elements, because they are about elements the standard has no term for and the model does not hold: `validate(xml)` asks them of the document as it was sent. `check(document, specification)`, given a model and no XML, asks them of the document that model would be written as. Where one of them reports an element, the reader's own finding about that element (`UNHELD`, `REPEATED`) is left out, so an element is reported once, under the published rule's name where there is one.

**The arithmetic is the rules' own.** The published rules are XPath, and XPath rounds a tie towards positive infinity (`-2.5` is `-2`), which is neither Python's `round` nor half-up. A total that is absent is equal to nothing, so its rule fails. `mockeinvoice/rules/calculation.py` has both.

**A rule that cannot be computed has failed.** Where the published test would stop with an XPath error (a number that is not a number, an amount twice where the test takes one), the finding says the rule could not be computed, and the document is invalid.

## The Invoice Response

What a buyer answers an invoice with on the Peppol route: acknowledged, in process, under query, conditionally accepted, rejected, accepted or paid, and why.

```python
from mockeinvoice import read_response, write_response, validate_response

response, findings = read_response(xml)
response.code                       # "UQ": under query
response.statuses[0].reason_code    # "REF", from the list named in .list_id
response.statuses[0].conditions     # [("BT-132", "20")]: what in the invoice it is about
response.document.id                # "GLX-4711": the invoice it answers
xml = write_response(response)

response, report = validate_response(xml)
```

It is Peppol's transaction T111, a UBL `ApplicationResponse`, pinned to release 3.0.17 at commit [`ad6828c`](https://github.com/OpenPEPPOL/poacc-upgrade-3/commit/ad6828c94f8090bdfd620df4e48b213977afa2cb) of `OpenPEPPOL/poacc-upgrade-3` (it has no tag; the newest tag is 3.0.15). All 82 of its published rules are built. Fifty-four of them are generated when Peppol builds its rule file and are in no file of its repository, so their identifiers are taken from the file Peppol publishes.

A response with nothing found wrong is `valid`.

XRechnung has no such message: an XRechnung invoice gets a verdict and nothing after it.

## The server

```
python -m mockeinvoice --port 8100
```

`8100` is the default (mock-sap is on `8000`, mock-edi on `8080`, mock-bank on `8090`). Installed, the command is `mock-einvoice`. The one process is both a **buyer**, which invoices are sent to, and a **supplier**, which sends them. Two of it can be pointed at each other.

### The buyer

```
$ python -m mockeinvoice --clock 2026-10-07T09:00 &
$ curl -s --data-binary @tests/samples/peppol-invoice.xml http://127.0.0.1:8100/invoices
{
  "id": "1",
  "kind": "Invoice",
  "number": "GLX-4711",
  ...
  "verdict": "valid",
  "status": "",
  "findings": [],
  "responses": [],
  "document": "/_mock/invoices/1/document"
}
$ curl -s -d '{"code": "UQ", "reasons": [{"code": "REF", "text": "No purchase order."}], "actions": ["PIN"]}' \
    http://127.0.0.1:8100/_mock/invoices/1/responses
{
  "id": "1",
  "invoice": "1",
  "code": "UQ",
  ...
  "document": "/_mock/responses/1"
}
$ curl -s http://127.0.0.1:8100/_mock/responses/1      # the Invoice Response, as XML
```

**What a selling system uses**, as it would use the network:

| | |
| --- | --- |
| `POST /invoices` | A UBL `Invoice` or `CreditNote`. `201` if it is `valid`, and it is held. `422` with the findings if it is `invalid`. `422` naming the rules that were not run if it is `not judged`: the mock does not take in what it could not judge. `400` with the refusal's code for what is not taken at all ([What it refuses](#what-it-refuses)). |

**What a test uses**, under `/_mock`:

| | |
| --- | --- |
| `GET /_mock/invoices`, `/_mock/invoices/<id>`, `/_mock/invoices/<id>/document` | what is held; one, with its findings and its responses; and as it was sent |
| `POST /_mock/invoices/<id>/responses` | the buyer says something of it: `{"code", "reasons", "actions", "note", "force"}`. A reason or an action is a code, or `{"code", "text", "conditions"}` with conditions as pairs of a business term and a value |
| `GET /_mock/responses/<id>` | an Invoice Response, as XML |
| `GET`, `PATCH /_mock/buyer` | how the buyer behaves: `{"answers": ...}` |

**Responses go to the seller.** Peppol's guide has the Invoice Response pushed from buyer to seller, and a seller cannot ask for one. `--seller-url URL` is where each is `POST`ed, and what became of that is on the response (`"delivery"`). Without it, responses are written and kept.

**When the buyer speaks unasked** (`--answers`, or `PATCH /_mock/buyer`):

- `required`, the default. An invoice sent under Peppol's Billing with Response (billing's profile `02`), where Peppol makes the response "a required step", is acknowledged (`AB`) on receipt. Under profile `01` nothing is said until it is asked for.
- `always`: every Peppol document is acknowledged.
- `never`: the buyer who owes a response and sends none.

Nothing else happens by itself. Each later status is asked for with `POST /_mock/invoices/<id>/responses`.

**The order responses come in.** Peppol's guide to the Invoice Response has [process rules](https://docs.peppol.eu/poacc/upgrade-3/profiles/63-invoiceresponse/#invoice-response-process-rules) that are in none of its Schematron files, so no validator checks them. The buyer keeps to them, and a response that would break one is `409` with the rule's identifier:

| Rule | In our words |
| --- | --- |
| `OP-BR111-R012` | A status does not go back in the order `AB`, `IP`, `UQ`, `CA`, `RE`, `AP`, `PD`. Any may be first and any left out. Only under query and a part payment (`PD` with the reason `PPD`) come twice. |
| `OP-BR111-R004` | Nothing follows a rejection or a payment in full. |
| `OP-BR111-R005` | Only paid follows accepted. |
| `OP-BR111-R014` | The type code is the answered document's own. The mock writes it so; there is nothing to ask for. |

`"force": true` sends a response out of order all the same, and marks it `"forced"`: a seller's system has to cope with a buyer who does. Every response is held to the 82 published rules before it goes, and one that fails (a rejection with no reason) is `422` with the finding, forced or not. Its warnings go with it.

An **XRechnung** document gets its verdict and no response. Asking for one is `409`.

### The supplier

```
$ python -m mockeinvoice --port 8101 --buyer-url http://127.0.0.1:8100/invoices &
$ curl -s --data-binary @tests/samples/peppol-invoice.xml http://127.0.0.1:8101/_mock/sent
{
  "id": "1",
  ...
  "verdict": "valid",
  "forced": false,
  "delivery": {
    "to": "http://127.0.0.1:8100/invoices",
    "status": 201
  },
  "status": "",
  ...
}
```

**What a test uses**, under `/_mock`:

| | |
| --- | --- |
| `POST /_mock/sent` | Send this UBL `Invoice` or `CreditNote` to the buyer: a `POST` of it to `--buyer-url`, and what became of that is its `"delivery"`. Without `--buyer-url` it is recorded and goes nowhere. It is held to its rules first, as a real sender's access point does, and one that is not `valid` is not sent (`422` with the findings). `?force=true` sends it anyway. What is not an invoice at all is `400`, forced or not. |
| `GET /_mock/sent`, `/_mock/sent/<id>`, `/_mock/sent/<id>/document` | what was sent; one, with its delivery, the responses it has had and its status; and as it was sent |
| `GET /_mock/answers/<id>` | an Invoice Response, as it was received |

**What a buyer's system uses**, as it would use the network:

| | |
| --- | --- |
| `POST /responses` | A Peppol Invoice Response. `201` if it passes its 82 rules and is about a document that was sent, which is found by its number and type code. `422` with the findings if it fails a rule, `422` `NO-SUCH-INVOICE` if no such document was sent, `400` if it is not an Invoice Response. |

A document's `"status"` is the last thing its buyer said. **A response out of order is taken and ignored.** Peppol's guide says of a response that follows a rejection or a payment in full, or follows an acceptance with anything but paid, that the seller may ignore it. So the supplier does: the response is `201` and kept, marked `"ignored"` with the rule it broke, and the status does not move. The same for one that goes back in the order.

#### An order, and the invoice for it

The supplier can be told of an order, and writes and sends the invoice for it itself.

```
$ curl -s -d '{"number": "4500000017",
    "buyer": {"name": "ACME Corporation", "endpoint": "0088:4098765000003",
              "city": "Berlin", "postal_code": "10115", "country": "DE"},
    "lines": [{"line": "10", "name": "Widget", "quantity": 40, "unit": "C62", "price": "20.00"}]}' \
    http://127.0.0.1:8101/_mock/orders
{
  "id": "1",
  "number": "4500000017",
  ...
  "status": "open",
  ...
}
$ curl -s -X POST http://127.0.0.1:8101/_mock/orders/1/invoices
{
  "id": "1",
  "kind": "Invoice",
  "number": "GLX-0001",
  ...
  "verdict": "valid",
  "delivery": {
    "to": "http://127.0.0.1:8100/invoices",
    "status": 201
  },
  "order": "/_mock/orders/1",
  ...
}
```

| | |
| --- | --- |
| `POST /_mock/orders` | Tell the supplier of an order: `{"number", "reference", "buyer", "currency", "lines"}`. The buyer is `{"name", "endpoint", "vat", "legal_id", "street", "city", "postal_code", "country"}` and needs its name, its country, and its endpoint written `scheme:identifier`. A line is `{"line", "name", "seller_item", "buyer_item", "quantity", "unit", "price"}` and needs its name, a quantity above nought, a unit (a code of UN/ECE Recommendation 20: `C62` is "one") and a price for one unit, without VAT. A line with no number has its place in the order for one. `201` and it is held; nothing is billed. `400` for what it lacks or does not know. `422` `UNBILLABLE` with the findings where the invoice it would be billed with is not `valid`: the invoice is written and held to its rules when the order comes, and thrown away. |
| `GET /_mock/orders`, `/_mock/orders/<id>` | the orders; one, with what is billed and what is open of each line, and the invoices sent for it |
| `POST /_mock/orders/<id>/invoices` | Write the invoice for all that is not yet billed, and send it as `POST /_mock/sent` would: the answer is the same, and the document is at `/_mock/sent/<id>` with the rest. `{"lines": [{"line": "10", "quantity": 15}]}` bills that much of those lines and no more. `409` `OVER-BILLED` for more than is open of a line, `409` `BILLED` when nothing is. `422` `NOT-VALID` with the findings if the invoice is not `valid`, which can only be because the supplier was changed since the order came; it is not sent, nothing is counted as billed, and there is no forcing it. |
| `GET`, `PATCH /_mock/supplier` | who the supplier is, and changing it: any of the fields below. `POST /_mock/reset` forgets the orders and starts the invoice numbers again, and leaves this alone. |

**An order is JSON here, and not a document of any standard.** Peppol has one, the UBL `Order` of its ordering profiles, with rules of its own. None of them is built, and taking the document in without holding it to them would be half of it. So the order is on a `/_mock` path, where the test's own controls are, and says no more than an invoice needs.

**A number is never a float.** A quantity or a price is taken as text or as a JSON number, and a JSON number is read as the decimal it was written as.

**Nothing is billed until it is asked for**, as nothing else here happens by itself.

**What the supplier makes up, and from what.** An order does not say who is selling, where to pay, or what the invoice is called. The invoice is a Peppol BIS Billing 3.0 invoice (type `380`, billing's profile `01`), and what is in it comes from:

| In the invoice | From |
| --- | --- |
| The seller: name (BT-27), electronic address (BT-34), VAT identifier (BT-31), legal registration (BT-30), address (BT-35, 37, 38, 40), contact (BT-41, 42, 43) | the supplier: `name`, `endpoint`, `vat`, `legal_id`, `street`, `city`, `postal_code`, `country`, `contact`, `telephone`, `email`. Until it is changed it is Globex GmbH of Hamburg, the seller of this project's sample invoice. |
| The invoice number (BT-1) | the supplier's `number_prefix` and a count of the invoices it has written: `GLX-0001`. A document sent with `POST /_mock/sent` is not counted. |
| The issue date (BT-2) and the due date (BT-9) | the clock, and the clock plus the supplier's `payment_days` (30) |
| The currency (BT-5) | the order's, or the supplier's `currency` (`EUR`) |
| The order (BT-13) and each line's order line (BT-132) | the order's number and its lines' numbers |
| The buyer reference (BT-10) | the order's `reference`; **where it has none, the order's number again.** Peppol's rules for Germany want a buyer reference on every invoice between two German parties, and an order number is what a supplier with nothing else has. |
| The buyer (BT-44, 47, 48, 49, 50, 52, 53, 55) | the order's buyer |
| How to pay (BG-16): a credit transfer (code `30`) to the account (BT-84, 85, 86), quoting the invoice number (BT-83) | the supplier's `iban`, `name` and `bic` |
| Each line: quantity, unit, item name, the seller's and the buyer's item number, price | the order's line. The line's net amount (BT-131) is quantity times price, rounded to the cent with a half going up. |
| VAT: category `S` on every line at one rate (BT-151, 152), and one breakdown (BG-23) | the supplier's `vat_rate` (19). The tax is the rate on the sum of the lines, rounded once. |
| The totals (BT-106, 109, 110, 112, 115) | the sums of the above. Nothing is prepaid, and there are no allowances or charges. |

**What it does not write:** a line at any VAT category but `S` (exempt, nought, reverse charge, an intra-community supply), allowances and charges, a delivery date, notes, payment terms as text, a credit note, an XRechnung. A rate of nought is refused for that reason. An invoice that needs one of these is written by whoever drives the mock and sent with `POST /_mock/sent`, as before.

### Both

| | |
| --- | --- |
| `GET /_mock/health` | that it is up, its version, and how many documents it holds and has sent |
| `GET /_mock/turned-away` | what was not taken in, on which side, and why |
| `POST /_mock/validate` | an invoice, a credit note or an Invoice Response held to its rules, and not kept |
| `GET /_mock/terms` | the business terms and groups this package knows, by number: `{"terms": [{"id", "name", "group", "kind"}], "groups": [{"id", "name", "repeats", "inside", "terms"}]}`, 164 terms and 32 groups, in the standard's order |
| `GET /_mock/terms/BT-13`, `/_mock/terms/BG-25` | one term or one group, as in the list. `404` `NO-SUCH-TERM` for anything else, written any other way (`bt-13`) |
| `POST /_mock/reset` | forget every document and response, on both sides |

**The terms are the package's own table, served.** `GET /_mock/terms` is made from `mockeinvoice.model.TERMS` and `GROUPS` when it is asked, so what a client reads is what the reader, the writer and the rules go by.

- A term's `kind` is one of `amount`, `binary`, `code`, `date`, `identifier`, `percentage`, `price`, `quantity`, `text`. Its `group` is `null` where the standard puts it on the document itself.
- A group's `repeats` says how this package holds it and not how often the standard allows it: `true` where it is kept as a group of its own (the lines, the VAT breakdown), `false` where its terms are held by the document or the line. `inside` is the group it is written within, if any.
- Three terms are written as an attribute of another's element (`BT-130`, the unit, is `BT-129`'s `unitCode`) and say so in `attribute_of`. Sixteen more, the scheme identifiers and their like (`BT-29-1`), have a number and no entry of their own here: each is listed under `attributes` on the term that holds it, and asked for by itself is `404` saying where it is.
- A finding still gives a term by its number alone. Its path is not always a term (a rule about the XML gives an XPath), and a client that wants the name has this to look it up in.

To see the two sides talk, run two: a buyer with `--seller-url http://127.0.0.1:8101/responses`, and a supplier with `--buyer-url http://127.0.0.1:8100/invoices`.

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

- **No transport.** A real Peppol invoice goes by AS4, signed and encrypted, between access points that find each other by SMP lookup. Here it is a `POST`, and the other party is a URL. The paths and status codes are this mock's own; nothing published defines an HTTP interface for any of it.
- **An invalid document is turned away at the door and gets no Invoice Response.** On the real network the sender's access point validates before it sends, and Peppol's guide puts the status of a transmission outside what an Invoice Response is for. That this is how a failed validation should look from the seller's side is this project's reading and not a published rule.
- **Nothing happens with time.** A real buyer moves an invoice to in process, accepted and paid over days, and Peppol asks for a first response within three working days. Here each status after the first is asked for.
- **A duplicate is taken like the first.** A second document with a seller and a number already held is held too. A real buyer's system would likely reject it; with which status and reason is not known here, and is not guessed.
- **Any buyer an invoice names is this mock**, and no document is turned away because its buyer is unknown. Nor does the supplier compare who a response is from with who its invoice was for: a response is matched by the invoice's number and type code alone, and of two documents sent with one number it is taken to be about the later.
- **A response about a document that was never sent is turned away**, and so is one that names a type code other than its document's (`OP-BR111-R014`). The guide says the code must be the document's own and not what a seller does when it is not; and on the real network a response would be delivered whatever it was about. Both are this project's choices.
- **How a real supplier bills an order is not known here, and the supplier's way is this project's own.** That it bills when asked and not on shipping, numbers its invoices by counting, takes a second order with a number it already holds, counts an invoice as billed though the buyer's system could not be reached or turned it away, and gives the order number as the buyer reference where it was given none: none of it is from a published source. An order's prices are also taken as they are; there is no price list to hold them to.
- **Nothing is kept on disk.** Documents and responses are gone when the server stops.
- **No XML Schema validation.** The published validators check the UBL schema before any rule. The standard library cannot, so this reads what it understands and reports what it did not. A document that is not schema-valid is not refused for that.
- **The writer does not promise the same bytes.** Reading what was written gives an equal document. The order among repeats of different kinds (allowances and charges, say), the namespace prefixes, white space, comments and anything `UNHELD` are not kept.
- **The writer does not supply what UBL requires and the model lacks.** A credit note with a due date and no payment instruction is written with a `PaymentMeans` that holds only the date, because that is where the binding puts the date. The UBL schema does not allow it, and read back, the document has an empty payment instruction it did not have before.
- **A tax category's scheme is taken to be VAT.** Several published rules look at a tax category only if its `TaxScheme/ID` is `VAT`. The reader reports any other value (`FIXED`) and holds the category all the same, so such a document is judged here as if it had said VAT.
- **A tax category that names no scheme counts as VAT.** `BR-32`, `BR-37`, `BR-47` and `BR-48` look for a category whose scheme is VAT, and one with no `TaxScheme` at all is not that. The model does not hold whether a scheme was named, so here it passes where a real validator fails it. UBL's schema requires the element.
- **An element the standard has once, sent twice, is one here.** Two seller addresses are held as one address with what was in both, and the reader says so (`REPEATED`). A published rule runs once for each; here it runs once, and where it takes one value and finds two it is reported as not computable.
- **A date outside the years 0001 to 9999** cannot be compared here, and a rule that compares it (`BR-29`, `BR-30`) is reported as not computable. XPath can compare it. A date that names no time zone is compared as UTC, which XPath leaves to the implementation.
- **A tax category on a line's allowance or charge is not seen.** The standard has none there and the reader does not hold one (`UNHELD`), so the VAT category rules that look at every `AllowanceCharge` see the document's and not a line's.
- **A tax category with nothing in it but its scheme is not known to be there.** The rules for category O (`BR-O-11` to `BR-O-14`) count the categories that are not O, and one with no code is not O. Here a category is known by its code, its rate or its exemption reason, and on a line by its element; one with none of those is not counted.
- **The VAT category rules differ between families in ways that look like accidents**, and are built as published. `BR-AF-01`, `BR-AG-01`, `BR-AF-04` and both `BR-B` rules compare a category code as written where their siblings trim it. `BR-G` and `BR-IC` want the seller's VAT identifier where the others take any tax registration. `BR-S-08` can be met by the allowances and charges alone, without the lines. `rules/en16931_vat.py` names each where it is made.
- **One unit of leeway on a taxable amount is measured as a double.** `BR-S-08`, `BR-AF-08` and `BR-AG-08` are published as `xs:decimal(cbc:TaxableAmount - 1)`, which subtracts in binary floating point: 100.10 less one is a hair under 99.10. At exactly one unit of difference the rule passes or fails by that, here as there. It is the one place a float is used; no amount is held as one.
- **A code list rule is asked of the places the standard has for the code.** The published tests are on an element wherever it occurs: any `Country`, any `TaxCategory`. One in an element that is not held is not asked, and the reader has reported the element.
- **Of the 756 rules about the UBL document, 747 have no unit test from their publisher.** They are held instead to a second reading of their paths by the standard library's own path language, which shares no code with this package's, over a document made for each path; and none of them fires on any of the 66 valid documents from the three publishers.
- **A payee with no name fails three more rules than one would think** (`UBL-SR-19`, `-20`, `-21`): each compares the payee's name with the seller's legal name, and a name that is not there is not different from anything. Two payment instructions that name different payment means, or different payment references, fail `UBL-SR-47` and `UBL-SR-44`. Both are the published tests, built as published.
- **Peppol takes `true` and `false` for a charge indicator, and not `1` and `0`**, which the core takes. An allowance marked `0` fails `PEPPOL-EN16931-R043` and is left out of its line's net amount by `PEPPOL-EN16931-R120`. Built as published.
- **A price divided by its base quantity** (`PEPPOL-EN16931-R120`) is computed to 60 significant digits here; XPath leaves the precision to the implementation. The rule allows two cents either way.
- **XRechnung publishes no unit tests of its rules** in the form EN 16931 and Peppol do. Thirty-one of its 34 standard rules are the same tests as Peppol's rules for Germany, which Peppol does publish unit tests for, and are one piece of code here under two names; the other three rest on this project's tests. The documents of its test suite that this project carries are valid ones, and are all valid here; none of them shows a rule failing.
- **XRechnung's rules are asked of every XRechnung document**, whatever its parties' countries; Peppol's for Germany only where both are in Germany. `BR-TMP-6` asks that a date looks like `YYYY-MM-DD` and no more, so the thirtieth of February passes it.
- **Peppol's rules for Germany are asked only where seller and buyer are both in Germany.** A German seller invoicing a buyer abroad is asked none of them. Its IBAN checks (`DE-R-019`, `DE-R-020`) are warnings, asked of SEPA transfers and direct debits only, and read a small letter in an IBAN as another number than its capital. A cash discount line in the payment terms has to end in a line break (`DE-R-018`). All as published.
- **A response to an invoice of type 817, 875, 876 or 877 fails a rule.** `PEPPOL-T111-B04201` holds the type code of the document answered to UNTDID 1001 as it was in 2017 (edition D.17A), which has not those four codes; Peppol's billing rules allow all four. The same list has one entry that is no code, `1999`, a year out of the description of code 423, so a type code of `1999` passes. Both are Peppol's list as published, and are built as published.
- **`PEPPOL-T111-R005` cannot fail.** It is meant to say that the reason "partially paid" goes only with the response "paid". Its published test asks whether a comparison exists, and one always does. Built as published, it finds nothing.
- **An element with no place in an Invoice Response is fatal**, where in an invoice it is a warning; but a second note is not, because the response's rules say what may be there and not how often. The reader reports the repeat.
- **Four rules are published twice.** `BR-CO-21` to `BR-CO-24` have the same test as `BR-33`, `BR-38`, `BR-42` and `BR-44`, so an allowance or charge with no reason fails two rules, as it does in a real validator.
- **Six published rules cannot fail, here or anywhere.** `BR-CO-05` to `BR-CO-08` are published with the test `true()`. `BR-DEC-13` and `BR-DEC-15` compare a tax amount's currency with an element a tax amount does not have, so they select nothing and pass. They are built as published.
- **A VAT rate under half a percent** rounds to nought in `BR-CO-17`, which then wants the tax to round to nought too. That is the published test, and it is built as published.
- **A note's subject code** (`BT-21`) is read from `#CODE#` at the start of a note's text. That convention is from memory of the standard's UBL binding and was not checked against a published source.

## Held to what others published

The rules, the reader and the writer are tested against files this project did not write.

| Source, at the pinned version | What | How it comes out today |
| --- | --- | --- |
| EN 16931 unit tests | 1,137 cases, each a small document and what one rule should make of it | 1,126 agree, none disagree. One is in a document UBL's schema does not allow (a credit note with an invoice's line), where the reader does not hold the element the rule is about; it is counted apart. 12 name `BR-CO-25`, which the pinned rule file does not have. Only 9 of the 756 rules about the UBL document have a published case. |
| EN 16931 examples | 17 documents | read, written back, and compared element for element by a reader that is not this one |
| XRechnung test suite | 39 valid XRechnung 3.0 documents | read with nothing to say, written back element for element, and every one is `valid`: no rule of the core's 979 or XRechnung's 34 fails or warns. Seventeen are told, as information, that they do not say when they were delivered (`BR-DE-TMP-32`) |
| XRechnung test suite | 5 Extension and 1 CVD document | refused by name |
| Peppol unit tests | 673 cases, with 678 things said of a rule | all 678 agree: 331 for Peppol's own rules, 65 for Germany's and 282 for the other six countries that have any. 4 cases are about a UBL Order. Iceland's ten rules have none |
| Peppol Invoice Response | 14 examples and 13 unit test cases | every example is read with nothing to say, written back element for element, and no rule has anything to say of it; all 13 cases agree. The structure and the code lists here are compared with the ones Peppol describes |
| Peppol examples | 10 documents | read with nothing to say, written back element for element, and no rule has anything to say of them. All ten are `valid` |
| Peppol national examples | 3 documents, kept by Peppol's national authorities | two are `valid` with a warning each; the third, a Greek invoice through a tax representative, is `invalid` by the core's `BR-06`, because its seller has no legal name |

- **A case for a rule that is not built is never counted as agreeing.** The counts are written out in `tests/test_upstream.py`, so building a rule moves a number there on purpose.
- **A disagreement is a failure here** until the published rule shows the case to be wrong; then it is listed in `tests/upstream.py` by name, with the reason. None is.
- **To read the counts:** `python -m tests.upstream`. CI prints them on every run.

Peppol's files are not in this repository (see Licences). `python tools/fetch_peppol.py` fetches the 167 listed in `tools/peppol-files.tsv` (billing's examples and national examples, its unit tests, and the rule file itself, which a test reads Peppol's code lists from) and the 28 in `tools/peppol-response-files.tsv` (the Invoice Response's examples, unit tests, hand-written rules, code lists and the description of its structure) from the pinned commit, checks each against the git hash listed for it, and puts them where the tests look. Without them those two tests are skipped and say so. CI fetches them on two of its jobs.

Two things were checked while building and are not tests, because their sources are not here:

- The table of where each term sits agrees, term for term, with the syntax description Peppol publishes for BIS Billing 3.0.21, for both documents.
- Its order agrees with the UBL 2.1 schemas from OASIS, for both documents and every aggregate under them.

## Licences

The code values of UNTDID 1001, the United Nations' list of kinds of document, are in `mockeinvoice/rules/untdid.py`: 727 numbers from edition D.17A as UNECE publishes it, and none of the names or descriptions, which are the United Nations'. The directory's pages say "Copyright United Nations, all rights reserved"; the numbers are taken to be facts and not text.

The names of the 164 business terms and 32 business groups in `mockeinvoice/model.py` are, by that file's own account, the standard's names for them, typed in by hand ("Invoice number", "Seller postal address"). None of the standard's descriptions or usage notes is there. They have been in the package since 0.1.0, and the server now gives them out as well (`GET /_mock/terms`).

Nothing of Peppol's is in the package. Its rules are written here by hand from reading the tests, each under its published identifier and in this project's words. Where a Peppol rule holds a value to a code list, the list is the EN 16931 one already in the package, with the differences named: one currency code, twenty-one electronic address schemes, and two short lists of document type codes. A test compares the result with Peppol's own lists whenever its files have been fetched.

The package is MIT, with two files that are not. `mockeinvoice/rules/codelists.py` holds the code lists of the EN 16931 code list rules (currencies, countries, units of measure and the rest), generated from the published rules by `tools/code_lists.py` and kept exactly as published. `mockeinvoice/rules/ublsyntax.py` holds the paths of the rules about the UBL document itself, generated by `tools/ubl_syntax.py`. Both are from the EN 16931 validation artefacts and are under the EUPL 1.2, whose text is beside them and goes into the wheel with them. One list more is in `rules/en16931.py`, the country prefixes `BR-CO-09` searches, and is from the same source. The wheel holds the package and nothing else.

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

The tests start the server on a port the operating system chooses, and a stand-in seller beside it.

`tools/published_rules.py` regenerates `mockeinvoice/rules/published.py` from the three Schematron files when a pin moves. It takes each rule's identifier and flag and nothing else. The repository's settings are described in [docs/GITHUB.md](docs/GITHUB.md).
