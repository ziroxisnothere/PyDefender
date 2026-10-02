"""Command-line interface for PyDefender.

The CLI is a **thin wrapper** around :class:`pydefender.engine.ObfuscationEngine`.
It contains no protection logic of its own: every obfuscation request is
delegated to the same public engine API that Python applications use.

Exit codes:

* ``0``   success
* ``1``   runtime error (unreadable input, invalid source, ...)
* ``2``   usage error (handled by argparse)
* ``130`` interrupted by the user (Ctrl+C)
"""

from __future__ import annotations

import sys
from typing import Optional, Sequence

from pydefender.cli.app import build_parser, main

__all__ = ["build_parser", "main"]
