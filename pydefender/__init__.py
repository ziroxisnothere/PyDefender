"""PyDefender - Python source-code obfuscator and protection tool.

PyDefender turns readable Python source into functionally identical,
hard-to-read code. The standalone engine (``pydefender.engine``) is the
core; the CLI (``pydefender``) is a thin wrapper around it.

Standalone engine::

    from pydefender.engine import ObfuscationEngine, ObfuscationConfig

    config = ObfuscationConfig(level=3, integrity=True)
    engine = ObfuscationEngine(config)
    result = engine.obfuscate("main.py", "dist/main.py")
    print(result)

Convenience API (backward compatible)::

    from pydefender import obfuscate_source, obfuscate_file

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
    "ConfigurationError",
    "IntegrityError",
    "ObfuscationConfig",
    "ObfuscationEngine",
    "ObfuscationResult",
    "OutputError",
    "ParsingError",
    "PyDefenderError",
    "RuntimeInfo",
    "StageReport",
    "TransformationError",
    "ValidationError",
    "__version__",
    "analyze_file",
    "analyze_source",
    "main",
    "obfuscate_file",
    "obfuscate_source",
]

from pydefender.engine import (
    LEVELS,
    ConfigurationError,
    IntegrityError,
    ObfuscationConfig,
    ObfuscationEngine,
    ObfuscationResult,
    OutputError,
    ParsingError,
    PyDefenderError,
    RuntimeInfo,
    StageReport,
    TransformationError,
    ValidationError,
)
from pydefender.engine.legacy import analyze_file, analyze_source, obfuscate_file, obfuscate_source
from pydefender.cli import main
