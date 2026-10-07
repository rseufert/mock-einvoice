"""The tests, and the sample documents they read.

`tests/samples` holds documents written for this project. `tests/samples/external`
holds documents published by others, unmodified, each directory under the
licence its own README names.
"""
import contextlib
import os

SAMPLES = os.path.join(os.path.dirname(__file__), "samples")
EXTERNAL = os.path.join(SAMPLES, "external")


def sample(name: str) -> bytes:
    with open(os.path.join(SAMPLES, name), "rb") as handle:
        return handle.read()


@contextlib.contextmanager
def unbuilt(layer: str, *starts: str):
    """The package as it would be with some of a layer's rules not built:
    every rule whose identifier starts with one of these."""
    from mockeinvoice.rules import REGISTRY
    built = dict(REGISTRY[layer])
    for identifier in built:
        if identifier.startswith(starts):
            del REGISTRY[layer][identifier]
    try:
        yield
    finally:
        REGISTRY[layer].clear()
        REGISTRY[layer].update(built)


def external(directory: str):
    """Every published example in one directory: (name, bytes) pairs."""
    folder = os.path.join(EXTERNAL, directory)
    for name in sorted(os.listdir(folder)):
        if name.endswith(".xml"):
            with open(os.path.join(folder, name), "rb") as handle:
                yield name, handle.read()
