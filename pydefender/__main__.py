"""Allow running PyDefender as a module: ``python -m pydefender``."""

from __future__ import annotations

import sys

from pydefender.cli import main

if __name__ == "__main__":
    sys.exit(main())
