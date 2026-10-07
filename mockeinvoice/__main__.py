"""`python -m mockeinvoice`: the server, as `mock-einvoice` runs it."""
import sys

from .server import main

sys.exit(main())
