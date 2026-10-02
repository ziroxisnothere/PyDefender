"""Public result and report models of the PyDefender engine.

These dataclasses are part of the stable public API. They are returned
by :meth:`ObfuscationEngine.obfuscate` and
:meth:`ObfuscationEngine.obfuscate_source` and are safe to serialize,
compare and log.
"""

from __future__ import annotations

import platform
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

__all__ = ["StageReport", "ObfuscationResult", "RuntimeInfo"]


@dataclass
class StageReport:
    """Outcome of a single pipeline stage.

    Attributes:
        name: Stage identifier (e.g. ``"name-protection"``).
        description: Short human-readable description.
        status: ``"ok"`` or ``"skipped"`` (failed stages raise instead).
        duration_ms: Wall time spent in the stage.
        details: Optional stage-specific information (counts, sizes...).
    """

    name: str
    description: str
    status: str = "ok"
    duration_ms: float = 0.0
    details: str = ""

    def __str__(self) -> str:
        suffix = f" - {self.details}" if self.details else ""
        return f"[{self.status:>7}] {self.name} ({self.duration_ms:.1f} ms){suffix}"


@dataclass
class ObfuscationResult:
    """Result of an engine run.

    Attributes:
        code: The protected source code. Always populated for
            single-file and in-memory runs; empty for directory runs.
        input_path: Original input path (``None`` for in-memory input).
        output_path: Path the protected file was written to
            (``None`` for in-memory or dry-run input).
        success: ``True`` when the run completed (failures raise instead).
        dry_run: ``True`` when the run stopped before writing output.
        level: Protection level that was used.
        original_size: Size of the input source in bytes.
        protected_size: Size of the protected source in bytes.
        files: ``(input, output)`` pairs for directory runs.
        stages: Per-stage reports, in execution order.
        dependencies: Top-level modules detected in the imports of the
            input. Useful as PyInstaller ``--hidden-import`` candidates.
        integrity_checksum: SHA-256 hex digest of the protected source
            (only when ``integrity=True``).
        warnings: Non-fatal messages collected during the run.
        python_version: Version of the interpreter that ran the engine.
        duration_ms: Total wall time of the run.
    """

    code: str = ""
    input_path: Optional[Path] = None
    output_path: Optional[Path] = None
    success: bool = True
    dry_run: bool = False
    level: int = 0
    original_size: int = 0
    protected_size: int = 0
    files: List[Tuple[Path, Path]] = field(default_factory=list)
    stages: List[StageReport] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    integrity_checksum: Optional[str] = None
    warnings: List[str] = field(default_factory=list)
    python_version: str = field(default_factory=platform.python_version)
    duration_ms: float = 0.0

    @property
    def stages_ok(self) -> int:
        return sum(1 for stage in self.stages if stage.status == "ok")

    @property
    def stages_skipped(self) -> int:
        return sum(1 for stage in self.stages if stage.status == "skipped")

    def __str__(self) -> str:
        lines = ["PyDefender obfuscation result"]
        lines.append(f"  status        : {'success' if self.success else 'failed'}"
                     f"{' (dry run - nothing written)' if self.dry_run else ''}")
        lines.append(f"  level         : {self.level}")
        if self.input_path is not None:
            lines.append(f"  input         : {self.input_path}")
        if self.output_path is not None:
            lines.append(f"  output        : {self.output_path}")
        if self.files:
            lines.append(f"  files         : {len(self.files)} protected")
        lines.append(f"  size          : {self.original_size} -> {self.protected_size} bytes")
        lines.append(
            f"  stages        : {self.stages_ok} ok, {self.stages_skipped} skipped"
            f" ({len(self.stages)} total)"
        )
        lines.append(f"  dependencies  : {len(self.dependencies)} detected")
        if self.integrity_checksum:
            lines.append(f"  integrity     : sha256:{self.integrity_checksum[:16]}...")
        if self.warnings:
            lines.append(f"  warnings      : {len(self.warnings)}")
        lines.append(f"  duration      : {self.duration_ms:.1f} ms")
        return "\n".join(lines)


@dataclass
class RuntimeInfo:
    """Environment information detected by the engine.

    Everything is detected locally - the engine never touches the network.
    """

    engine_version: str = ""
    python_version: str = field(default_factory=platform.python_version)
    python_implementation: str = field(default_factory=platform.python_implementation)
    platform: str = field(default_factory=lambda: platform.platform(terse=True))
    executable: str = field(default_factory=lambda: str(sys.executable))
    frozen: bool = field(default_factory=lambda: bool(getattr(sys, "frozen", False)))
    pyinstaller_available: bool = False
    pyinstaller_version: Optional[str] = None

    def __str__(self) -> str:
        lines = [
            "PyDefender runtime environment",
            f"  engine          : {self.engine_version}",
            f"  python          : {self.python_version} ({self.python_implementation})",
            f"  platform        : {self.platform}",
            f"  executable      : {self.executable}",
            f"  frozen          : {'yes' if self.frozen else 'no'}",
            f"  pyinstaller     : {self.pyinstaller_version or 'not installed'}",
        ]
        return "\n".join(lines)
