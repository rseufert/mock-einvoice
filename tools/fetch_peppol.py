"""Fetch Peppol's test files, which this repository does not carry.

    python tools/fetch_peppol.py

Peppol BIS Billing and Peppol's Invoice Response are published with examples
and with unit tests for their rules, and with a statement that they may not
be redistributed without OpenPeppol's consent. So they are not in this
repository or in its source distribution. This puts them where the tests look
for them,

    tests/samples/fetched/peppol/               billing
    tests/samples/fetched/peppol-response/      the Invoice Response

which git ignores. The tests that need them are skipped without them.

What is fetched is exactly the files listed in `tools/peppol-files.tsv` and
`tools/peppol-response-files.tsv`, from the commits this package is pinned
to. Each is checked against the git blob
hash the list gives for it, so what arrives is what was listed or nothing is
kept. A file already there and right is not fetched again.
"""
import hashlib
import os
import sys
import time
import urllib.error
import urllib.request

COMMIT = "806866bd2bd91d7e9623b68f08164e8fbe9e67a0"     # Peppol BIS Billing 3.0.21
RESPONSE_COMMIT = "ad6828c94f8090bdfd620df4e48b213977afa2cb"    # Invoice Response 3.0.17
HERE = os.path.dirname(os.path.abspath(__file__))
FETCHED = os.path.join(os.path.dirname(HERE), "tests", "samples", "fetched")
# What is fetched: its name, the repository and commit, the list, and where to.
SETS = (
    ("Peppol BIS Billing 3.0.21", "OpenPEPPOL/peppol-bis-invoice-3", COMMIT,
     os.path.join(HERE, "peppol-files.tsv"), os.path.join(FETCHED, "peppol")),
    ("Peppol Invoice Response 3.0.17", "OpenPEPPOL/poacc-upgrade-3", RESPONSE_COMMIT,
     os.path.join(HERE, "peppol-response-files.tsv"), os.path.join(FETCHED, "peppol-response")),
)
SOURCE = "https://raw.githubusercontent.com/%s/%s/%s"
LIST, TARGET = SETS[0][3], SETS[0][4]


def listed(path: str = LIST):
    """(git blob hash, size, path) for each file to fetch."""
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                blob, size, path = line.rstrip("\n").split("\t")
                yield blob, int(size), path


def blob_hash(data: bytes) -> str:
    """The hash git gives these bytes as a blob."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def fetch(path: str, repository: str = SETS[0][1], commit: str = COMMIT, tries: int = 3) -> bytes:
    url = SOURCE % (repository, commit, urllib.request.quote(path))
    for attempt in range(1, tries + 1):
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                return response.read()
        except (urllib.error.URLError, OSError) as error:
            if attempt == tries:
                raise SystemExit("could not fetch %s: %s" % (url, error))
            time.sleep(2 * attempt)
    raise AssertionError("unreachable")


def main() -> None:
    for name, repository, commit, files, target in SETS:
        fetched = kept = 0
        for blob, size, path in listed(files):
            there = os.path.join(target, *path.split("/"))
            if os.path.exists(there):
                with open(there, "rb") as handle:
                    if blob_hash(handle.read()) == blob:
                        kept += 1
                        continue
            data = fetch(path, repository, commit)
            if len(data) != size or blob_hash(data) != blob:
                raise SystemExit("%s is not the file that was listed: %d bytes, hash %s, and "
                                 "the list has %d bytes, hash %s"
                                 % (path, len(data), blob_hash(data), size, blob))
            os.makedirs(os.path.dirname(there), exist_ok=True)
            with open(there, "wb") as handle:
                handle.write(data)
            fetched += 1
        with open(os.path.join(target, "FETCHED.txt"), "w", encoding="utf-8") as handle:
            handle.write("%s, %s at commit %s.\nNot part of this repository: see "
                         "tools/fetch_peppol.py.\n" % (name, repository, commit))
        print("%s: test files at %s: %d fetched, %d already there"
              % (name, target, fetched, kept))


if __name__ == "__main__":
    main()
