"""Backward-compatibility module for the pre-engine PyDefender layout.

Historically the whole engine lived in this module. It now delegates to
the standalone engine package (``pydefender.engine``), which is where
all protection logic lives. New code should import from
``pydefender.engine`` (or the ``pydefender`` top level) directly.
"""

from __future__ import annotations

from pydefender.engine.config import GITHUB_URL, LEVELS
from pydefender.engine.exceptions import PyDefenderError
from pydefender.engine.legacy import analyze_file, analyze_source, obfuscate_file, obfuscate_source

__all__ = [
    "GITHUB_URL",
    "LEVELS",
    "PyDefenderError",
    "analyze_file",
    "analyze_source",
    "obfuscate_file",
    "obfuscate_source",
]
