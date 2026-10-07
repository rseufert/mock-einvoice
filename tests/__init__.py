"""The tests, and the sample documents they read.

`tests/samples` holds documents written for this project. `tests/samples/external`
holds documents published by others, unmodified, each directory under the
licence its own README names.
"""
import os

SAMPLES = os.path.join(os.path.dirname(__file__), "samples")
EXTERNAL = os.path.join(SAMPLES, "external")


def sample(name: str) -> bytes:
    with open(os.path.join(SAMPLES, name), "rb") as handle:
        return handle.read()


def external(directory: str):
    """Every published example in one directory: (name, bytes) pairs."""
    folder = os.path.join(EXTERNAL, directory)
    for name in sorted(os.listdir(folder)):
        if name.endswith(".xml"):
            with open(os.path.join(folder, name), "rb") as handle:
                yield name, handle.read()
