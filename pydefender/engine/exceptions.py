"""Exception hierarchy for the PyDefender engine.

Every exception raised by the engine derives from :class:`PyDefenderError`
and, whenever possible, carries three context fields:

* ``file``   - the affected source file (or ``"<source>"`` for in-memory input)
* ``stage``  - the pipeline stage that failed (e.g. ``"identifier-renaming"``)
* ``reason`` - a human-readable explanation

``str(exception)`` renders all available context in a stable, greppable
format so failures are easy to diagnose and to log::

    PyDefenderError: could not parse source code
    File: project/module.py
    Stage: parsing
    Reason: invalid syntax (module.py, line 4)
"""

from __future__ import annotations

from typing import Optional

__all__ = [
    "PyDefenderError",
    "ConfigurationError",
    "ParsingError",
    "TransformationError",
    "ValidationError",
    "OutputError",
    "IntegrityError",
]


class PyDefenderError(Exception):
    """Base class for every error raised by the PyDefender engine."""

    def __init__(
        self,
        message: str,
        *,
        file: Optional[str] = None,
        stage: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.file = file
        self.stage = stage
        self.reason = reason or message

    def __str__(self) -> str:
        lines = [self.message]
        if self.file:
            lines.append(f"File: {self.file}")
        if self.stage:
            lines.append(f"Stage: {self.stage}")
        if self.reason and self.reason != self.message:
            lines.append(f"Reason: {self.reason}")
        return "\n".join(lines)


class ConfigurationError(PyDefenderError):
    """Raised when an :class:`~pydefender.engine.ObfuscationConfig` is invalid."""


class ParsingError(PyDefenderError):
    """Raised when source code cannot be parsed into a valid AST."""

    def __init__(self, message: str, **kwargs) -> None:
        kwargs.setdefault("stage", "parsing")
        super().__init__(message, **kwargs)


class TransformationError(PyDefenderError):
    """Raised when an AST transformation stage fails.

    The engine fails safely: the original source is never modified and
    no partially transformed output is produced.
    """


class ValidationError(PyDefenderError):
    """Raised when pre- or post-obfuscation validation fails."""


class OutputError(PyDefenderError):
    """Raised when the protected output cannot be written safely
    (missing input, existing output without overwrite permission, ...)."""


class IntegrityError(PyDefenderError):
    """Raised when integrity validation detects an unexpected modification.

    Integrity failures are always non-destructive: the engine (and the
    runtime integrity guard embedded in protected files) only reports the
    problem. User files are never deleted or altered by PyDefender.
    """
