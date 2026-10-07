# Changelog

Every release of [mock-einvoice](https://pypi.org/project/mock-einvoice/). The
format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the
versions follow [semantic versioning](https://semver.org/spec/v2.0.0.html) -
while the major version is 0, a minor bump may change behaviour, and each entry
says so where it does.

## [Unreleased]

Nothing is released yet. What is here reads and writes invoices; it does not
yet hold one to any rule.

### Added

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
