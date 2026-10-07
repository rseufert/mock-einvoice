"""Fetch Peppol's test files, which this repository does not carry.

    python tools/fetch_peppol.py

Peppol BIS Billing is published with examples and with unit tests for its
rules, and with a statement that it may not be redistributed without
OpenPeppol's consent. So they are not in this repository or in its source
distribution. This puts them where the tests look for them,

    tests/samples/fetched/peppol/

which git ignores. The tests that need them are skipped without them.

What is fetched is exactly the files listed in `tools/peppol-files.tsv`, from
the commit this package is pinned to. Each is checked against the git blob
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
SOURCE = "https://raw.githubusercontent.com/OpenPEPPOL/peppol-bis-invoice-3/%s/%s"
HERE = os.path.dirname(os.path.abspath(__file__))
LIST = os.path.join(HERE, "peppol-files.tsv")
TARGET = os.path.join(os.path.dirname(HERE), "tests", "samples", "fetched", "peppol")


def listed():
    """(git blob hash, size, path) for each file to fetch."""
    with open(LIST, encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                blob, size, path = line.rstrip("\n").split("\t")
                yield blob, int(size), path


def blob_hash(data: bytes) -> str:
    """The hash git gives these bytes as a blob."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def fetch(path: str, tries: int = 3) -> bytes:
    url = SOURCE % (COMMIT, urllib.request.quote(path))
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
    fetched = kept = 0
    for blob, size, path in listed():
        target = os.path.join(TARGET, *path.split("/"))
        if os.path.exists(target):
            with open(target, "rb") as handle:
                if blob_hash(handle.read()) == blob:
                    kept += 1
                    continue
        data = fetch(path)
        if len(data) != size or blob_hash(data) != blob:
            raise SystemExit("%s is not the file that was listed: %d bytes, hash %s, and the "
                             "list has %d bytes, hash %s"
                             % (path, len(data), blob_hash(data), size, blob))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as handle:
            handle.write(data)
        fetched += 1
    with open(os.path.join(TARGET, "FETCHED.txt"), "w", encoding="utf-8") as handle:
        handle.write("Peppol BIS Billing 3.0.21, commit %s.\nNot part of this repository: "
                     "see tools/fetch_peppol.py.\n" % COMMIT)
    print("Peppol test files at %s: %d fetched, %d already there" % (TARGET, fetched, kept))


if __name__ == "__main__":
    main()
