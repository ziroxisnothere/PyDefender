"""PyDefender Standalone Engine.

A clean, dependency-free, offline protection engine for Python source
code. This package has no dependency on the CLI, GUI, PyPI tooling or
any external service, and can be embedded directly::

    from pydefender.engine import ObfuscationEngine, ObfuscationConfig

    config = ObfuscationConfig(level=3, integrity=True)
    engine = ObfuscationEngine(config)

    result = engine.obfuscate("main.py", "dist/main.py")
    print(result)

Public surface:

- :class:`ObfuscationEngine` - the facade (``obfuscate``,
  ``obfuscate_source``, ``analyze``, ``detect_environment``)
- :class:`ObfuscationConfig` - deterministic, validated configuration
- :class:`ObfuscationResult`, :class:`StageReport`,
  :class:`RuntimeInfo` - result models
- :class:`PyDefenderError` and subclasses - the exception hierarchy

The submodules (``parser``, ``transformer``, ``compiler``,
``protection``, ``pipeline``) are implementation details; import them
only when extending the engine.
"""

from __future__ import annotations

from pydefender.engine.config import GITHUB_URL, LEVELS, ObfuscationConfig
from pydefender.engine.core import ObfuscationEngine
from pydefender.engine.exceptions import (
    ConfigurationError,
    IntegrityError,
    OutputError,
    ParsingError,
    PyDefenderError,
    TransformationError,
    ValidationError,
)
from pydefender.engine.models import ObfuscationResult, RuntimeInfo, StageReport

__all__ = [
    "GITHUB_URL",
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
]
