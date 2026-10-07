# XRechnung test documents

The UBL documents of the XRechnung test suite, copied unmodified, names and
directories included:

- from <https://github.com/itplr-kosit/xrechnung-testsuite>, directory `src/test`
- at tag `v2026-08-31`, "compatible with XRechnung 3.0"

| Directory | Files | What they are |
| --- | --- | --- |
| `business-cases/standard` | 33 | XRechnung 3.0 invoices and credit notes, valid |
| `technical-cases/cius` | 6 | XRechnung 3.0 documents built to exercise the format, valid |
| `business-cases/extension` | 5 | XRechnung Extension invoices |
| `technical-cases/cvd` | 1 | an XRechnung CVD invoice |

The suite's CII documents are not here: CII is not built.

They are **not** under this repository's MIT licence. They are licensed under the
Apache License 2.0, whose text is beside them in `LICENSE-Apache-2.0.txt`. The
repository they come from has no `NOTICE` file.

The first two directories are documents this package must read without
complaint and find nothing wrong with. The last two it must refuse by name.

Nothing in `mockeinvoice/` is derived from them.
