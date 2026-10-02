"""The PyDefender protection pipeline.

Orchestrates independently testable stages::

    Input
     v
    validation            (input sanity, shebang extraction)
     v
    parsing               (AST parse, dependency detection)
     v
    metadata-reduction    (docstring removal)
     v
    name-protection       (scope-safe identifier renaming)
     v
    constant-protection   (integer literal transforms)
     v
    string-protection     (string literal encoding)
     v
    control-flow-protection (opaque dead branches)
     v
    code-generation       (unparse + compile smoke test)
     v
    packaging             (banner / heavy loader wrapper)
     v
    integrity-validation  (final compile check)
     v
    Output

Every stage is independently callable and testable (see
``tests/test_stages.py``). Stages can be enabled/disabled through
:class:`~pydefender.engine.ObfuscationConfig`.

Stage order note: metadata reduction runs *before* control-flow
protection so that dead branches are never inserted ahead of a
docstring (which would change ``__doc__`` semantics when metadata
reduction is disabled), and constant/string protection run before
packaging so generated payload data is never re-transformed.
"""

from __future__ import annotations

import ast
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

from pydefender.engine import compiler, parser, protection
from pydefender.engine.config import ObfuscationConfig
from pydefender.engine.exceptions import PyDefenderError, ValidationError
from pydefender.engine.models import StageReport
from pydefender.engine.transformer import (
    ConstantProtector,
    ControlFlowProtector,
    MetadataReducer,
    NameProtector,
    StringProtector,
    TransformContext,
    guarded_stage,
)

__all__ = ["Pipeline", "PipelineOutcome"]


@dataclass
class PipelineOutcome:
    """Raw output of one pipeline run (single file or in-memory source)."""

    code: str = ""
    dependencies: List[str] = field(default_factory=list)
    reports: List[StageReport] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


class Pipeline:
    """Configurable, observable protection pipeline."""

    def __init__(self, config: ObfuscationConfig, logger: Optional[logging.Logger] = None, version: str = "") -> None:
        self.config = config
        self.logger = logger or logging.getLogger("pydefender")
        self.version = version

    # -- stage definitions ------------------------------------------------

    def _transform_stage_specs(self) -> List[Tuple[str, str, Tuple[str, ...], Callable]]:
        """Return ``(report_name, description, config_flags, factory)`` tuples."""
        return [
            ("metadata-reduction", "remove docstrings and embedded metadata", ("metadata",), MetadataReducer),
            ("name-protection", "rename function-local variables", ("rename",), NameProtector),
            ("constant-protection", "transform large integer literals", ("constants",), ConstantProtector),
            ("string-protection", "encode long string literals", ("strings",), StringProtector),
            ("control-flow-protection", "insert opaque dead branches", ("control_flow", "dead_code"), ControlFlowProtector),
        ]

    # -- execution ---------------------------------------------------------

    def run(self, source: str, filename: str = "<source>") -> PipelineOutcome:
        """Run the full pipeline for one source text.

        Raises:
            PyDefenderError: On any validation, parsing, transformation,
                generation or integrity failure. The original source is
                never modified; nothing is written by the pipeline.
        """
        started = time.perf_counter()
        warnings: List[str] = []
        reports: List[StageReport] = []

        # ---- validation -------------------------------------------------
        # (runs first, before any RNG construction, so non-string input
        # fails cleanly with a ValidationError)
        with self._stage("validation", "validate input", reports) as stage:
            if not isinstance(source, str):
                raise ValidationError(
                    "source must be a string containing Python code",
                    file=filename,
                    reason=f"got {type(source).__name__}",
                )
            if not source.strip():
                stage.details = "empty source"
            size_bytes = len(source.encode("utf-8"))
            if size_bytes > parser.MAX_INPUT_BYTES:
                raise ValidationError(
                    "source exceeds the maximum supported size",
                    file=filename,
                    reason=f"{size_bytes} bytes (limit {parser.MAX_INPUT_BYTES})",
                )

        ctx = TransformContext(
            rng=self._build_rng(source, filename),
            config=self.config,
            filename=filename,
            warnings=warnings,
        )

        # ---- parsing ----------------------------------------------------
        tree: Optional[ast.Module] = None
        with self._stage("parsing", "parse source into AST", reports) as stage:
            tree = parser.parse_source(source, filename=filename, target_python=self.config.target_python)
            dependencies = parser.extract_dependencies(tree)
            stage.details = f"{len(dependencies)} module(s) imported"

        assert tree is not None  # for type checkers; parse either returned or raised

        # ---- transformation stages ---------------------------------------
        for stage_name, description, flags, stage_factory in self._transform_stage_specs():
            if not self._stage_enabled(flags):
                reports.append(
                    StageReport(name=stage_name, description=description, status="skipped")
                )
                continue
            stage_instance = stage_factory()
            with self._stage(stage_name, description, reports) as report:
                details = guarded_stage(stage_instance, tree, ctx)
                report.details = details
            ast.fix_missing_locations(tree)

        # ---- code generation ----------------------------------------------
        protected_code = ""
        with self._stage("code-generation", "generate protected source", reports) as report:
            protected_code = compiler.tree_to_source(tree, filename)
            if self.config.validate_syntax:
                compiler.compile_check(protected_code, filename, stage="code-generation")
            report.details = f"{len(protected_code)} chars generated"

        # ---- packaging ------------------------------------------------------
        final_code = ""
        with self._stage("packaging", "package protected output", reports) as report:
            level_name = {1: "light", 2: "standard", 3: "heavy"}[self.config.level]
            final_code = compiler.finalize_output(
                protected_code,
                source,
                self.config,
                level_name,
                self.version or "0.1.0",
            )
            if self.config.compression_active:
                report.details = "heavy loader wrapper applied"
            else:
                if self.config.integrity:
                    warnings.append(
                        "runtime integrity enforcement requires the heavy loader "
                        "(level 3); integrity=True has no runtime effect below "
                        "level 3 - the checksum is still returned in the result"
                    )
                report.details = "plain protected source"

        # ---- integrity validation ---------------------------------------------
        with self._stage("integrity-validation", "verify protected output", reports) as report:
            if self.config.validate_syntax:
                compiler.compile_check(final_code, filename, stage="integrity-validation")
            report.details = f"sha256:{protection.compute_checksum(final_code)[:16]}..."

        duration_ms = (time.perf_counter() - started) * 1000.0
        self.logger.debug(
            "pipeline finished for %s in %.1f ms (%d warnings)",
            filename,
            duration_ms,
            len(warnings),
        )
        _ = duration_ms  # total duration is reported by the engine layer
        return PipelineOutcome(
            code=final_code,
            dependencies=dependencies,
            reports=reports,
            warnings=warnings,
        )

    # -- helpers -----------------------------------------------------------

    def _build_rng(self, source: str, filename: str) -> random.Random:
        """Build the per-run RNG.

        The seed is derived from the configured seed and a content hash,
        never from wall-clock time or file location, so identical input
        plus identical configuration yields identical output.
        """
        if not self.config.reproducible:
            return random.Random()
        content_tag = protection.compute_checksum(source)[:16]
        return random.Random(f"pydefender:{self.config.seed}:{content_tag}")

    def _stage_enabled(self, flags: Tuple[str, ...]) -> bool:
        """A transform stage runs when any of its config flags is enabled."""
        enabled = self.config.enabled_stages()
        return any(flag in enabled for flag in flags)

    def _stage(self, name: str, description: str, reports: List[StageReport]):
        """Context manager that runs one stage with timing and error capture."""
        return _StageRunner(self, name, description, reports)


class _StageRunner:
    """Context manager implementing per-stage timing and error wrapping."""

    def __init__(self, pipeline: Pipeline, name: str, description: str, reports: List[StageReport]) -> None:
        self.pipeline = pipeline
        self.name = name
        self.description = description
        self.reports = reports
        self.report: Optional[StageReport] = None
        self._start = 0.0

    def __enter__(self) -> StageReport:
        self._start = time.perf_counter()
        self.report = StageReport(name=self.name, description=self.description)
        self.pipeline.logger.debug("stage %s: started", self.name)
        return self.report

    def __exit__(self, exc_type, exc, tb) -> bool:
        assert self.report is not None
        self.report.duration_ms = (time.perf_counter() - self._start) * 1000.0
        if exc_type is None:
            self.report.status = "ok"
            self.pipeline.logger.debug("stage %s: ok (%.1f ms)", self.name, self.report.duration_ms)
            self.reports.append(self.report)
            return False
        if isinstance(exc, PyDefenderError):
            if not exc.stage:
                exc.stage = self.name
            raise
        # Unexpected internal error: wrap with stage context, preserve traceback.
        raise PyDefenderError(
            f"pipeline stage {self.name!r} failed unexpectedly",
            stage=self.name,
            reason=f"{type(exc).__name__}: {exc}",
        ) from exc
