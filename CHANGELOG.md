# Changelog

Every release of [mock-einvoice](https://pypi.org/project/mock-einvoice/). The
format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the
versions follow [semantic versioning](https://semver.org/spec/v2.0.0.html) -
while the major version is 0, a minor bump may change behaviour, and each entry
says so where it does.

## [Unreleased]

Nothing is released yet. What is here reads and writes invoices and holds them
to the first of the published rules.

### Added

- **A rule engine, and the first 44 rules of the EN 16931 core** ([#3]): the
  calculation rules (`BR-CO-*`) and the rules on how many decimals an amount
  carries (`BR-DEC-*`). A rule is one function under its published identifier.
  A finding gives that identifier, the publisher's flag, where in the model
  it failed, a description in this project's words, and a link to the
  published rule; the publisher's wording is not reproduced. The arithmetic
  is XPath's, as the published tests have it: a tie rounds towards positive
  infinity, and a total that is absent equals nothing.
- **Every published rule listed, built or not** ([#3]): 979 for EN 16931, 166
  for Peppol BIS Billing 3.0.21 and 55 for XRechnung 3.0, by identifier and
  flag. A report says which ran and which did not, and a document's verdict
  is `invalid` or `not judged`. It is not `valid` while a fatal rule of its
  specification is unbuilt.
- **A group with nothing in it is still there** ([#3]). An empty VAT breakdown
  is a VAT breakdown, an invoicing period with no dates is an invoicing
  period: the published rules ask whether they exist, so the model can say.

- **A model of the invoice as EN 16931 describes it** ([#2]): every business
  term under its own number (`BT-1` to `BT-165`), the groups that repeat as
  groups, and one model for an invoice and a credit note. Every amount,
  quantity, price and percentage is a `Decimal` made from the text as written,
  with the digits after the point kept as sent. There is no float.
- **A reader and a writer for UBL 2.1 `Invoice` and `CreditNote`** ([#2]),
  from one table of where each term sits. Read then written, a document is the
  same document: held to the seventeen UBL examples published with the EN
  16931 validation artefacts, element for element.
- **Nothing dropped in silence** ([#2]). An element or attribute the standard
  has no term for, an element that repeats where the standard has one, text
  among elements, and a number that is not a decimal are each a finding that
  names the place.
- **Refusals by name** ([#2]): what is not XML, anything with a DTD, a Cross
  Industry Invoice, any other UBL document, and any specification identifier
  other than Peppol BIS Billing 3.0 and XRechnung 3.0, with the XRechnung
  Extension and CVD identifiers named as such.

[#2]: https://github.com/rseufert/mock-einvoice/issues/2
[#3]: https://github.com/rseufert/mock-einvoice/issues/3
