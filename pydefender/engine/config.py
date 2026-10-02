"""ObfuscationConfig - deterministic, validated engine configuration.

The configuration is the single source of truth for every pipeline run.
It is a plain, hashable-by-value dataclass with strict validation, so the
same configuration object always yields the same behavior.

Stage enablement follows two simple rules:

1. The protection ``level`` (1-3) defines the *baseline* set of stages.
2. Explicit stage flags override the baseline: ``True`` adds a stage that
   is not part of the level preset, ``False`` removes one that is.

This makes configurations easy to reason about and fully testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Sequence, Set, Tuple, Union

from pydefender.engine.exceptions import ConfigurationError

__all__ = ["LEVELS", "GITHUB_URL", "LEVEL_STAGES", "STAGE_FLAGS", "ObfuscationConfig"]

#: Available protection levels and their human-readable names.
LEVELS: Dict[int, str] = {1: "light", 2: "standard", 3: "heavy"}

#: Project homepage (used in generated banners).
GITHUB_URL = "https://github.com/ziroxisnothere/PyDefender"

#: Pipeline stages included in each protection level by default.
LEVEL_STAGES: Dict[int, Set[str]] = {
    1: {"metadata"},
    2: {"metadata", "rename", "constants", "strings"},
    3: {"metadata", "rename", "constants", "strings", "control_flow", "dead_code"},
}

#: Mapping of pipeline stage name -> matching :class:`ObfuscationConfig` flag.
STAGE_FLAGS: Dict[str, str] = {
    "metadata": "metadata",
    "rename": "rename",
    "constants": "constants",
    "strings": "strings",
    "control_flow": "control_flow",
    "dead_code": "dead_code",
}

#: Stages that always run regardless of configuration.
_ALWAYS_ON_STAGES = ("validation", "parsing", "code-generation", "packaging", "integrity-validation")


@dataclass
class ObfuscationConfig:
    """Deterministic configuration for :class:`ObfuscationEngine`.

    Attributes:
        level: Protection preset, ``1`` (light), ``2`` (standard),
            ``3`` (heavy). Level 3 additionally compresses the whole
            program into a self-contained loader stub.
        rename: Enable/disable identifier renaming (default: follow level).
        strings: Enable/disable string-literal protection (default: follow level).
        constants: Enable/disable numeric-constant protection (default: follow level).
        control_flow: Enable/disable safe control-flow transforms (default: follow level).
        dead_code: Enable/disable dead-code insertion (default: follow level).
        metadata: Enable/disable metadata reduction - docstring removal
            (default: follow level).
        compress: Force the heavy loader wrapper on/off. ``None`` follows
            the level (level 3 compresses).
        integrity: Embed a runtime integrity check (level 3) and compute
            the SHA-256 checksum returned in the result. Default ``False``.
        reproducible: When ``True`` (default), identical input plus
            identical configuration produce byte-identical output.
        seed: Seed for transformations that use randomness. Only
            meaningful together with ``reproducible=True``.
        dry_run: Run the full pipeline but never write any file.
        validate_syntax: Compile-check every generated output (recommended).
        target_python: Optional minimum Python version the output must
            support (e.g. ``"3.9"`` or ``(3, 9)``). The parser then
            rejects syntax the target version cannot handle.
        min_string_length: Minimum length of a string literal to be
            protected by the string stage.
        keep_shebang: Preserve a leading ``#!`` line from the input file.
    """

    level: int = 3
    rename: Optional[bool] = None
    strings: Optional[bool] = None
    constants: Optional[bool] = None
    control_flow: Optional[bool] = None
    dead_code: Optional[bool] = None
    metadata: Optional[bool] = None
    compress: Optional[bool] = None
    integrity: bool = False
    reproducible: bool = True
    seed: int = 0
    dry_run: bool = False
    validate_syntax: bool = True
    target_python: Optional[Union[str, Sequence[int]]] = None
    min_string_length: int = 16
    keep_shebang: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.level, int) or isinstance(self.level, bool) or self.level not in LEVELS:
            valid = ", ".join(str(value) for value in sorted(LEVELS))
            raise ConfigurationError(
                f"invalid protection level {self.level!r} (choose from: {valid})",
                stage="configuration",
                reason=f"level must be one of {sorted(LEVELS)}",
            )
        for flag_name in (
            "rename",
            "strings",
            "constants",
            "control_flow",
            "dead_code",
            "metadata",
            "compress",
        ):
            value = getattr(self, flag_name)
            if value is not None and not isinstance(value, bool):
                object.__setattr__(self, flag_name, bool(value))
        self.integrity = bool(self.integrity)
        self.reproducible = bool(self.reproducible)
        self.dry_run = bool(self.dry_run)
        self.validate_syntax = bool(self.validate_syntax)
        self.keep_shebang = bool(self.keep_shebang)
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise ConfigurationError(
                "seed must be a non-negative integer",
                stage="configuration",
                reason=f"got seed={self.seed!r}",
            )
        if self.seed < 0:
            raise ConfigurationError(
                "seed must be a non-negative integer",
                stage="configuration",
                reason=f"got seed={self.seed}",
            )
        if isinstance(self.min_string_length, bool) or not isinstance(self.min_string_length, int):
            raise ConfigurationError(
                "min_string_length must be a positive integer",
                stage="configuration",
                reason=f"got min_string_length={self.min_string_length!r}",
            )
        if self.min_string_length < 1:
            raise ConfigurationError(
                "min_string_length must be a positive integer",
                stage="configuration",
                reason=f"got min_string_length={self.min_string_length}",
            )
        self.target_python = self._normalize_target(self.target_python)

    @staticmethod
    def _normalize_target(value) -> Optional[Tuple[int, int]]:
        if value is None:
            return None
        if isinstance(value, str):
            parts = value.split(".")
            if len(parts) >= 2 and all(part.isdigit() for part in parts[:2]):
                return (int(parts[0]), int(parts[1]))
            raise ConfigurationError(
                f"invalid target_python {value!r} (use e.g. \"3.9\" or (3, 9))",
                stage="configuration",
            )
        try:
            major, minor = int(value[0]), int(value[1])
        except (TypeError, ValueError, IndexError):
            raise ConfigurationError(
                f"invalid target_python {value!r} (use e.g. \"3.9\" or (3, 9))",
                stage="configuration",
            ) from None
        return (major, minor)

    @property
    def compression_active(self) -> bool:
        """Whether the heavy loader wrapper is applied at output time."""
        if self.compress is None:
            return self.level >= 3
        return bool(self.compress)

    def enabled_stages(self) -> Set[str]:
        """Return the set of transformation stages enabled by this config.

        The result combines the level baseline with explicit flag
        overrides (``True`` adds, ``False`` removes).
        """
        baseline = set(LEVEL_STAGES[self.level])
        enabled: Set[str] = set()
        for stage_name, flag_name in STAGE_FLAGS.items():
            explicit = getattr(self, flag_name)
            if explicit is True:
                enabled.add(stage_name)
            elif explicit is None and stage_name in baseline:
                enabled.add(stage_name)
        return enabled

    def stage_enabled(self, stage_name: str) -> bool:
        """Return ``True`` if the named transformation stage will run."""
        if stage_name in _ALWAYS_ON_STAGES:
            return True
        if stage_name in STAGE_FLAGS:
            return stage_name in self.enabled_stages()
        raise ConfigurationError(
            f"unknown pipeline stage {stage_name!r}",
            stage="configuration",
        )

    @classmethod
    def from_dict(cls, data: Dict) -> "ObfuscationConfig":
        """Build a config from a plain mapping, rejecting unknown keys."""
        if not isinstance(data, dict):
            raise ConfigurationError(
                "ObfuscationConfig.from_dict expects a mapping",
                stage="configuration",
            )
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        unknown = sorted(set(data) - valid_fields)
        if unknown:
            raise ConfigurationError(
                f"unknown configuration keys: {', '.join(unknown)}",
                stage="configuration",
                reason=f"valid keys are: {', '.join(sorted(valid_fields))}",
            )
        return cls(**data)
