"""ObfuscationEngine - the public facade of the PyDefender engine.

The engine is completely standalone: it depends only on the Python
standard library, works fully offline, never sends source code anywhere
and never stores or requires credentials of any kind. It is designed to
be embedded by the CLI, GUIs, build scripts and packaging pipelines.

Example::

    from pydefender.engine import ObfuscationEngine, ObfuscationConfig

    config = ObfuscationConfig(level=3, integrity=True)
    engine = ObfuscationEngine(config)

    result = engine.obfuscate("main.py", "dist/main.py")
    print(result)

    result = engine.obfuscate_source(source_code)
    protected_text = result.code
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from pydefender.engine import parser, protection
from pydefender.engine.config import ObfuscationConfig
from pydefender.engine.exceptions import ConfigurationError, OutputError
from pydefender.engine.models import ObfuscationResult, RuntimeInfo, StageReport
from pydefender.engine.pipeline import Pipeline

__all__ = ["ObfuscationEngine"]

#: Directory names skipped during directory obfuscation.
_SKIPPED_DIRS = {
    "__pycache__",
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "env",
    "build",
    "dist",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    "htmlcov",
    "node_modules",
    ".idea",
    ".vscode",
    ".eggs",
}

#: Maximum number of cached source reads per engine instance.
_CACHE_LIMIT = 64


def _engine_version() -> str:
    try:
        from pydefender import __version__

        return __version__
    except Exception:  # pragma: no cover - defensive
        return "0.1.0"


def _detect_pyinstaller() -> Tuple[bool, Optional[str]]:
    """Detect a local PyInstaller installation (offline, best effort)."""
    try:
        from importlib.util import find_spec

        if find_spec("PyInstaller") is None:
            return False, None
    except Exception:  # pragma: no cover - defensive
        return False, None
    try:
        from importlib.metadata import version as dist_version

        return True, dist_version("pyinstaller")
    except Exception:  # pragma: no cover - defensive
        return True, None


class ObfuscationEngine:
    """Standalone, reusable protection engine.

    The engine owns configuration, caching, logging and reporting. The
    CLI and any GUI are thin wrappers around this class - there is no
    second implementation of the protection logic anywhere.

    Args:
        config: An :class:`ObfuscationConfig` (a default one is created
            when omitted).
        logger: A standard library logger. Defaults to the
            ``pydefender`` logger.
    """

    def __init__(
        self,
        config: Optional[ObfuscationConfig] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        if config is None:
            config = ObfuscationConfig()
        elif not isinstance(config, ObfuscationConfig):
            raise ConfigurationError(
                "config must be an ObfuscationConfig instance (or None)",
                stage="configuration",
                reason=f"got {type(config).__name__}",
            )
        self.config = config
        self.logger = logger or logging.getLogger("pydefender")
        self._cache: Dict[Tuple, Dict] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def obfuscate(
        self,
        input_path: Union[str, Path],
        output_path: Union[str, Path, None] = None,
        *,
        overwrite: bool = False,
    ) -> ObfuscationResult:
        """Obfuscate a Python file or a directory tree of ``.py`` files.

        Args:
            input_path: Path of a ``.py`` file or a directory.
            output_path: Destination file (for file input) or directory
                (for directory input). Defaults to
                ``<input_stem>_protected.py`` next to the input; required
                for directory input.
            overwrite: Allow replacing existing output files.

        Returns:
            An :class:`ObfuscationResult`.

        Raises:
            OutputError: Missing input, invalid destination or an
                existing output without ``overwrite=True``.
            PyDefenderError: Any pipeline failure. Nothing is written
                when the pipeline fails, and user files are never
                deleted.
        """
        started = time.perf_counter()
        input_path = Path(input_path)
        if not input_path.exists():
            raise OutputError(f"input path does not exist: {input_path}", file=str(input_path))
        if input_path.is_dir():
            result = self._obfuscate_directory(input_path, output_path, overwrite)
        else:
            result = self._obfuscate_file(input_path, output_path, overwrite)
        result.duration_ms = (time.perf_counter() - started) * 1000.0
        return result

    def obfuscate_source(
        self,
        source: str,
        filename: str = "<source>",
    ) -> ObfuscationResult:
        """Obfuscate an in-memory source string.

        Returns:
            An :class:`ObfuscationResult` whose ``code`` attribute holds
            the protected source. No files are read or written.
        """
        started = time.perf_counter()
        pipeline = self._build_pipeline()
        outcome = pipeline.run(source, filename=filename)
        result = ObfuscationResult(
            code=outcome.code,
            level=self.config.level,
            original_size=len(source.encode("utf-8")) if isinstance(source, str) else 0,
            protected_size=len(outcome.code.encode("utf-8")),
            stages=outcome.reports,
            dependencies=outcome.dependencies,
            warnings=list(outcome.warnings),
            integrity_checksum=protection.compute_checksum(outcome.code)
            if self.config.integrity
            else None,
        )
        result.duration_ms = (time.perf_counter() - started) * 1000.0
        self.logger.info(
            "obfuscated %s in %.1f ms (level %d)",
            filename,
            result.duration_ms,
            self.config.level,
        )
        return result

    def analyze(self, input_path: Union[str, Path]) -> Dict:
        """Analyze a Python source file and return its protection report."""
        return self._analysis_cached(Path(input_path))

    def detect_environment(self) -> RuntimeInfo:
        """Detect the local runtime environment (fully offline)."""
        pyinstaller_available, pyinstaller_version = _detect_pyinstaller()
        return RuntimeInfo(
            engine_version=_engine_version(),
            pyinstaller_available=pyinstaller_available,
            pyinstaller_version=pyinstaller_version,
        )

    def clear_cache(self) -> None:
        """Drop all cached file reads and analyses."""
        self._cache.clear()

    # ------------------------------------------------------------------
    # Single-file runs
    # ------------------------------------------------------------------

    def _obfuscate_file(
        self,
        input_path: Path,
        output_path: Union[str, Path, None],
        overwrite: bool,
    ) -> ObfuscationResult:
        source = self._read_cached(input_path)
        pipeline = self._build_pipeline()
        outcome = pipeline.run(source, filename=str(input_path))

        destination = self._resolve_destination(input_path, output_path)
        result = ObfuscationResult(
            code=outcome.code,
            input_path=input_path,
            output_path=destination if not self.config.dry_run else destination,
            dry_run=self.config.dry_run,
            level=self.config.level,
            original_size=len(source.encode("utf-8")),
            protected_size=len(outcome.code.encode("utf-8")),
            stages=outcome.reports,
            dependencies=outcome.dependencies,
            warnings=list(outcome.warnings),
            integrity_checksum=protection.compute_checksum(outcome.code)
            if self.config.integrity
            else None,
        )

        if self.config.dry_run:
            self.logger.info("dry run complete for %s (nothing written)", input_path)
            return result

        self._write_output(input_path, destination, outcome.code, overwrite)
        result.output_path = destination
        self.logger.info(
            "protected %s -> %s (level %d)",
            input_path,
            destination,
            self.config.level,
        )
        return result

    def _resolve_destination(
        self,
        input_path: Path,
        output_path: Union[str, Path, None],
    ) -> Path:
        if output_path is None:
            return input_path.with_name(f"{input_path.stem}_protected.py")
        destination = Path(output_path)
        if destination.is_dir():
            return destination / f"{input_path.stem}_protected.py"
        return destination

    def _write_output(
        self,
        input_path: Path,
        destination: Path,
        content: str,
        overwrite: bool,
    ) -> None:
        same_file = destination.exists() and destination.resolve() == input_path.resolve()
        if destination.exists() and not same_file and not overwrite:
            raise OutputError(
                f"output already exists (enable overwrite to replace it): {destination}",
                file=str(destination),
                stage="output",
            )
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(content, encoding="utf-8")
        except OSError as exc:
            raise OutputError(
                f"could not write protected output",
                file=str(destination),
                stage="output",
                reason=str(exc),
            ) from exc
        problem = protection.verify_written_output(destination, content)
        if problem:
            raise OutputError(
                problem,
                file=str(destination),
                stage="output",
            )

    # ------------------------------------------------------------------
    # Directory runs
    # ------------------------------------------------------------------

    def _obfuscate_directory(
        self,
        input_dir: Path,
        output_path: Union[str, Path, None],
        overwrite: bool,
    ) -> ObfuscationResult:
        if output_path is None:
            raise OutputError(
                "obfuscating a directory requires an output directory",
                file=str(input_dir),
                stage="output",
            )
        output_dir = Path(output_path)
        files = self._collect_python_files(input_dir)
        if not files:
            raise OutputError(
                f"no Python files found under: {input_dir}",
                file=str(input_dir),
                stage="output",
            )

        result = ObfuscationResult(
            input_path=input_dir,
            output_path=output_dir,
            dry_run=self.config.dry_run,
            level=self.config.level,
            dependencies=[],
            warnings=[],
        )
        merged_stages: Dict[str, StageReport] = {}
        for source_file in files:
            relative = source_file.relative_to(input_dir)
            destination = output_dir / relative
            file_result = self._obfuscate_file(source_file, destination, overwrite)
            result.files.append((source_file, destination))
            result.original_size += file_result.original_size
            result.protected_size += file_result.protected_size
            result.warnings.extend(
                f"{source_file}: {warning}" for warning in file_result.warnings
            )
            for dependency in file_result.dependencies:
                if dependency not in result.dependencies:
                    result.dependencies.append(dependency)
            for report in file_result.stages:
                merged = merged_stages.get(report.name)
                if merged is None:
                    merged_stages[report.name] = StageReport(
                        name=report.name,
                        description=report.description,
                        status=report.status,
                        duration_ms=report.duration_ms,
                        details=report.details,
                    )
                else:
                    merged.duration_ms += report.duration_ms
                    if report.status != "ok":
                        merged.status = report.status
            if file_result.integrity_checksum:
                result.integrity_checksum = file_result.integrity_checksum
        result.stages = [merged_stages[name] for name in sorted(merged_stages)]
        if not self.config.dry_run:
            self.logger.info(
                "protected %d file(s) under %s -> %s",
                len(result.files),
                input_dir,
                output_dir,
            )
        return result

    def _collect_python_files(self, input_dir: Path) -> List[Path]:
        """Recursively collect ``*.py`` files, skipping junk directories."""

        def should_skip(directory: Path) -> bool:
            return directory.name in _SKIPPED_DIRS or directory.name.startswith(".")

        files = []
        for path in sorted(input_dir.rglob("*.py")):
            if any(should_skip(parent) for parent in path.relative_to(input_dir).parents):
                continue
            files.append(path)
        return files

    # ------------------------------------------------------------------
    # Caching and helpers
    # ------------------------------------------------------------------

    def _build_pipeline(self) -> Pipeline:
        return Pipeline(self.config, self.logger, version=_engine_version())

    def _cache_key(self, path: Path) -> Tuple:
        stat = path.stat()
        return (str(path.resolve()), stat.st_mtime_ns, stat.st_size)

    def _read_cached(self, path: Path) -> str:
        key = self._cache_key(path)
        entry = self._cache.get(key)
        if entry is not None and "source" in entry:
            self.logger.debug("cache hit (source): %s", path)
            return entry["source"]
        source = parser.read_source(path)
        if len(self._cache) >= _CACHE_LIMIT:
            self._cache.pop(next(iter(self._cache)))
        self._cache[key] = {"source": source}
        return source

    def _analysis_cached(self, path: Path) -> Dict:
        key = self._cache_key(path)
        entry = self._cache.get(key)
        if entry is not None and "report" in entry:
            self.logger.debug("cache hit (analysis): %s", path)
            return entry["report"]
        source = self._read_cached(path)
        report = parser.analyze_source(source)
        report["path"] = str(path)
        entry = self._cache.setdefault(key, {})
        entry["report"] = report
        return report
