"""UNTDID 1001, document name code: which numbers are codes.

The United Nations Trade Data Interchange Directory's list of kinds of
document, edition D.17A, which is the edition Peppol's Invoice Response holds
the type code of an answered document to (`PEPPOL-T111-B04201`).

Only the code values are here: 727 numbers, written as the runs they come
in. Their names and descriptions are the United Nations' and are not copied.
Read from the directory as UNECE publishes it,
https://service.unece.org/trade/untdid/d17a/tred/tred1001.htm
"""
from __future__ import annotations

RUNS_1001_D17A = (
    (1, 470), (481, 491), (493, 499), (520, 539), (550, 554), (575, 589), (610, 610),
    (621, 659), (700, 751), (760, 761), (763, 766), (770, 770), (775, 775), (780, 799),
    (810, 812), (820, 825), (830, 830), (833, 833), (840, 841), (850, 853), (855, 856),
    (860, 865), (870, 870), (890, 890), (895, 896), (901, 901), (910, 911), (913, 917),
    (925, 927), (929, 938), (940, 941), (950, 955), (960, 966), (970, 972), (974, 979),
    (990, 991), (995, 996), (998, 998),
)
DOCUMENT_NAME_CODES = frozenset(str(code) for first, last in RUNS_1001_D17A
                                for code in range(first, last + 1))
