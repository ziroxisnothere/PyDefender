"""Backward-compatible convenience API.

These functions preserve the pre-1.0 ``pydefender`` top-level API on
top of the new engine. New code should prefer
:class:`~pydefender.engine.ObfuscationEngine` directly, which exposes
the full configuration, reporting and logging surface.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Optional, Union

from pydefender.engine.config import ObfuscationConfig
from pydefender.engine.core import ObfuscationEngine
from pydefender.engine.parser import analyze_file, analyze_source  # noqa: F401 (re-export)

__all__ = ["obfuscate_source", "obfuscate_file", "analyze_source", "analyze_file"]


def obfuscate_source(source: str, level: int = 2) -> str:
    """Obfuscate Python source code and return the protected source.

    Convenience wrapper around :class:`ObfuscationEngine` preserving the
    historical signature. See :meth:`ObfuscationEngine.obfuscate_source`
    for the full-featured API (result object, warnings, stage reports).

    Args:
        source: Python source code as a string.
        level: Protection level, ``1`` (light), ``2`` (standard) or
            ``3`` (heavy). Defaults to ``2``.

    Returns:
        The protected Python source code, functionally equivalent to
        the input.

    Raises:
        PyDefenderError: If the source cannot be parsed or the level
            is invalid.
    """
    config = ObfuscationConfig(level=level)
    engine = ObfuscationEngine(config)
    return engine.obfuscate_source(source).code


def obfuscate_file(
    input_path: Union[str, os.PathLike],
    output_path: Optional[Union[str, os.PathLike]] = None,
    level: int = 2,
    in_place: bool = False,
) -> Path:
    """Obfuscate a Python source file and write the protected copy.

    Convenience wrapper around :class:`ObfuscationEngine` preserving the
    historical signature.

    Args:
        input_path: Path of the ``.py`` file to protect.
        output_path: Destination path. Defaults to
            ``<input_stem>_protected.py`` next to the input. If the path
            is an existing directory, the default file name is used
            inside it.
        level: Protection level (see :func:`obfuscate_source`).
        in_place: If ``True``, overwrite ``input_path`` instead of
            writing a copy (``output_path`` is ignored).

    Returns:
        The path of the protected file that was written.

    Raises:
        PyDefenderError: If the input is missing, unreadable or invalid.
    """
    config = ObfuscationConfig(level=level)
    engine = ObfuscationEngine(config)
    destination = input_path if in_place else output_path
    result = engine.obfuscate(input_path, destination, overwrite=True)
    return Path(result.output_path)
