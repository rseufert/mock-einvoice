# EN 16931 examples and unit tests

Everything here but this file is published with the EN 16931 validation
artefacts and copied unmodified, names included:

- from <https://github.com/ConnectingEurope/eInvoicing-EN16931>
- at tag `validation-1.3.16`

| Here | There | Files |
| --- | --- | --- |
| the seventeen `.xml` files in this directory | `ubl/examples` | 17 |
| `unit/Invoice-unit-UBL` | `test/Invoice-unit-UBL` | 207 |
| `unit/CreditNote-unit-UBL` | `test/CreditNote-unit-UBL` | 71 |

They are **not** under this repository's MIT licence. They are licensed under the
European Union Public Licence 1.2, whose text is beside them in
`LICENSE-EUPL-1.2.txt`, as it is in the repository they come from.

The examples hold the reader and writer to documents this project did not
write. The unit tests hold each rule to what its publisher expects of it: each
file is a set of small documents, each marked with a rule and whether that rule
should pass or fail on it. `tests/upstream.py` reads them.

Nothing in `mockeinvoice/` is derived from them.
