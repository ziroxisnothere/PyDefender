"""PyDefender - Python source-code obfuscator and protection tool.

PyDefender turns readable Python source into functionally identical,
hard-to-read code. It ships a CLI (``pydefender``) and a small, stable
Python API built on top of the standard library ``ast`` module.

Quick start::

    from pydefender import obfuscate_source

    protected = obfuscate_source(source_code, level=3)

Command line::

    pydefender obfuscate app.py --level 3
    pydefender --help
"""

from __future__ import annotations

__version__ = "0.1.0"
__author__ = "Zirox"
__all__ = [
    "LEVELS",
    "PyDefenderError",
    "__version__",
    "analyze_file",
    "analyze_source",
    "main",
    "obfuscate_file",
    "obfuscate_source",
]

from pydefender.obfuscator import (
    LEVELS,
    PyDefenderError,
    analyze_file,
    analyze_source,
    obfuscate_file,
    obfuscate_source,
)
from pydefender.cli import main
