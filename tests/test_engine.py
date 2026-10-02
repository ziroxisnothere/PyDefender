"""Tests for the standalone engine public API.

Covers ObfuscationEngine, ObfuscationConfig and ObfuscationResult:
deterministic configuration, dry-run mode, reproducibility, integrity
protection, stage enablement, error handling, dependency detection,
directory mode, environment detection and engine/CLI equivalence.
"""

from __future__ import annotations

import logging
import sys

import pytest

from pydefender import ObfuscationConfig, ObfuscationEngine, ObfuscationResult
from pydefender.engine.exceptions import (
    ConfigurationError,
    IntegrityError,
    OutputError,
    ParsingError,
    PyDefenderError,
    ValidationError,
)

SIMPLE = "def compute(value):\n    factor = 3\n    return value * factor\n"


def run_code(source: str) -> dict:
    namespace: dict = {}
    exec(compile(source, "<protected>", "exec"), namespace)
    return namespace


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def test_default_config_is_level_3_and_reproducible():
    config = ObfuscationConfig()
    assert config.level == 3
    assert config.reproducible is True
    assert config.seed == 0
    assert config.dry_run is False
    assert "metadata" in config.enabled_stages()
    assert "rename" in config.enabled_stages()


def test_config_rejects_invalid_level():
    with pytest.raises(ConfigurationError):
        ObfuscationConfig(level=9)


def test_config_rejects_bad_seed():
    with pytest.raises(ConfigurationError):
        ObfuscationConfig(seed=-3)


def test_config_rejects_unknown_keys():
    with pytest.raises(ConfigurationError):
        ObfuscationConfig.from_dict({"nonsense": True})


def test_config_from_dict():
    config = ObfuscationConfig.from_dict({"level": 2, "integrity": True})
    assert config.level == 2
    assert config.integrity is True


def test_stage_flags_override_level_baseline():
    light_plus_rename = ObfuscationConfig(level=1, rename=True)
    assert "rename" in light_plus_rename.enabled_stages()
    assert "strings" not in light_plus_rename.enabled_stages()

    heavy_minus_strings = ObfuscationConfig(level=3, strings=False)
    assert "strings" not in heavy_minus_strings.enabled_stages()
    assert "rename" in heavy_minus_strings.enabled_stages()


def test_target_python_normalization():
    assert ObfuscationConfig(target_python="3.9").target_python == (3, 9)
    assert ObfuscationConfig(target_python=(3, 11)).target_python == (3, 11)
    with pytest.raises(ConfigurationError):
        ObfuscationConfig(target_python="three.nine")


def test_target_python_rejects_newer_syntax():
    match_source = 'def pick(value):\n    match value:\n        case 1:\n            return "one"\n        case _:\n            return "other"\n'
    engine = ObfuscationEngine(ObfuscationConfig(target_python="3.9"))
    if sys.version_info >= (3, 10):
        with pytest.raises(ParsingError):
            engine.obfuscate_source(match_source)
    else:
        # On 3.9 the parser itself rejects match statements regardless.
        with pytest.raises(PyDefenderError):
            engine.obfuscate_source(match_source)


# ---------------------------------------------------------------------------
# Core engine API
# ---------------------------------------------------------------------------


def test_obfuscate_source_returns_result_with_code():
    engine = ObfuscationEngine()
    result = engine.obfuscate_source(SIMPLE)
    assert isinstance(result, ObfuscationResult)
    assert result.success is True
    assert "def compute" not in result.code  # level 3 wraps everything
    assert run_code(result.code)["compute"](6) == 18
    assert result.output_path is None
    assert result.stages, "stage reports must be present"
    assert result.duration_ms >= 0


def test_engine_accepts_default_config():
    engine = ObfuscationEngine()
    assert isinstance(engine.config, ObfuscationConfig)


def test_engine_rejects_foreign_config():
    with pytest.raises(ConfigurationError):
        ObfuscationEngine(config="level 3 please")


def test_obfuscate_file(tmp_path):
    source_file = tmp_path / "app.py"
    source_file.write_text(SIMPLE, encoding="utf-8")
    engine = ObfuscationEngine(ObfuscationConfig(level=2))
    result = engine.obfuscate(source_file)
    assert result.output_path == source_file.with_name("app_protected.py")
    assert result.output_path.is_file()
    assert run_code(result.output_path.read_text(encoding="utf-8"))["compute"](5) == 15


def test_dry_run_writes_nothing(tmp_path):
    source_file = tmp_path / "app.py"
    source_file.write_text(SIMPLE, encoding="utf-8")
    engine = ObfuscationEngine(ObfuscationConfig(level=3, dry_run=True))
    result = engine.obfuscate(source_file)
    assert result.dry_run is True
    assert result.output_path is not None  # would-be destination is reported
    assert result.code  # protected code is still produced in memory
    assert not list(tmp_path.glob("*_protected.py"))


def test_output_overwrite_protection(tmp_path):
    source_file = tmp_path / "app.py"
    source_file.write_text(SIMPLE, encoding="utf-8")
    output = tmp_path / "out.py"
    output.write_text("original = True\n", encoding="utf-8")
    engine = ObfuscationEngine(ObfuscationConfig(level=1))
    with pytest.raises(OutputError):
        engine.obfuscate(source_file, output)
    assert output.read_text(encoding="utf-8") == "original = True\n"
    engine.obfuscate(source_file, output, overwrite=True)
    assert "original = True" not in output.read_text(encoding="utf-8")


def test_missing_input_raises_output_error(tmp_path):
    engine = ObfuscationEngine()
    with pytest.raises(OutputError):
        engine.obfuscate(tmp_path / "missing.py")


def test_directory_requires_output(tmp_path):
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "a.py").write_text(SIMPLE, encoding="utf-8")
    engine = ObfuscationEngine(ObfuscationConfig(level=1))
    with pytest.raises(OutputError):
        engine.obfuscate(source_dir)


def test_directory_mode_mirrors_tree(tmp_path):
    source_dir = tmp_path / "src"
    (source_dir / "pkg").mkdir(parents=True)
    (source_dir / "__pycache__").mkdir()
    (source_dir / "a.py").write_text("def a():\n    local = 2\n    return local\n", encoding="utf-8")
    (source_dir / "pkg" / "b.py").write_text("def b():\n    inner = 3\n    return inner\n", encoding="utf-8")
    (source_dir / "__pycache__" / "junk.py").write_text("junk = 1\n", encoding="utf-8")
    output_dir = tmp_path / "dist"
    engine = ObfuscationEngine(ObfuscationConfig(level=2))
    result = engine.obfuscate(source_dir, output_dir)
    assert len(result.files) == 2
    assert (output_dir / "a.py").is_file()
    assert (output_dir / "pkg" / "b.py").is_file()
    assert not (output_dir / "__pycache__" / "junk.py").exists()
    assert run_code((output_dir / "pkg" / "b.py").read_text(encoding="utf-8"))["b"]() == 3


def test_dependencies_are_detected():
    source = (
        "import json\n"
        "import os.path\n"
        "from collections import OrderedDict\n"
        "from . import sibling\n"
        "from ..shared import tool\n"
    )
    engine = ObfuscationEngine(ObfuscationConfig(level=1))
    result = engine.obfuscate_source(source)
    assert "json" in result.dependencies
    assert "os" in result.dependencies
    assert "collections" in result.dependencies
    # Relative imports are reported as a single deduplicated marker.
    assert "<relative>" in result.dependencies


# ---------------------------------------------------------------------------
# Reproducibility
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("level", [1, 2, 3])
def test_identical_input_and_config_is_byte_identical(level):
    source = SIMPLE + "\ndef helper(item):\n    payload = item * 4\n    return payload\n"
    first = ObfuscationEngine(ObfuscationConfig(level=level, seed=5)).obfuscate_source(source).code
    second = ObfuscationEngine(ObfuscationConfig(level=level, seed=5)).obfuscate_source(source).code
    assert first == second


def test_different_seeds_can_change_output():
    source = (
        "def noisy(item):\n"
        "    large = 987654\n"
        "    text = 'a rather long string used for protection testing'\n"
        "    return large, text\n"
    )
    first = ObfuscationEngine(ObfuscationConfig(level=2, seed=1)).obfuscate_source(source).code
    second = ObfuscationEngine(ObfuscationConfig(level=2, seed=2)).obfuscate_source(source).code
    assert first != second  # different seeds may differ (and both stay valid)
    assert run_code(first)["noisy"](1) == run_code(second)["noisy"](1)


def test_output_is_independent_of_file_path(tmp_path):
    source = SIMPLE
    first = tmp_path / "one.py"
    second = tmp_path / "nested" / "two.py"
    first.write_text(source, encoding="utf-8")
    second.parent.mkdir()
    second.write_text(source, encoding="utf-8")
    engine_a = ObfuscationEngine(ObfuscationConfig(level=2, seed=7))
    engine_b = ObfuscationEngine(ObfuscationConfig(level=2, seed=7))
    code_a = engine_a.obfuscate(first).code
    code_b = engine_b.obfuscate(second).code
    # Content-based seeding: identical content anywhere -> identical output.
    assert code_a == code_b


# ---------------------------------------------------------------------------
# Integrity protection
# ---------------------------------------------------------------------------


def test_integrity_checksum_in_result():
    engine = ObfuscationEngine(ObfuscationConfig(level=3, integrity=True))
    result = engine.obfuscate_source(SIMPLE)
    assert result.integrity_checksum
    assert len(result.integrity_checksum) == 64


def test_no_checksum_without_integrity():
    engine = ObfuscationEngine(ObfuscationConfig(level=3))
    result = engine.obfuscate_source(SIMPLE)
    assert result.integrity_checksum is None


def test_integrity_warning_below_level_3():
    engine = ObfuscationEngine(ObfuscationConfig(level=2, integrity=True))
    result = engine.obfuscate_source(SIMPLE)
    assert any("level 3" in warning for warning in result.warnings)


def test_tampered_payload_raises_integrity_error(tmp_path, run_python):
    engine = ObfuscationEngine(ObfuscationConfig(level=3, integrity=True))
    source_file = tmp_path / "app.py"
    source_file.write_text("print('should never appear')\n", encoding="utf-8")
    result = engine.obfuscate(source_file)
    protected = result.output_path.read_text(encoding="utf-8")
    # Flip one character inside the embedded base85 payload.
    marker = '    "'
    start = protected.index(marker) + len(marker)
    original_char = protected[start]
    replacement = "A" if original_char != "A" else "B"
    tampered = protected[:start] + replacement + protected[start + 1 :]
    assert tampered != protected
    tampered_file = tmp_path / "tampered.py"
    tampered_file.write_text(tampered, encoding="utf-8")
    proc = run_python(tampered_file)
    assert proc.returncode != 0
    assert "PyDefenderIntegrityError" in proc.stderr
    assert "should never appear" not in proc.stdout


def test_engine_never_deletes_user_files(tmp_path):
    source_file = tmp_path / "app.py"
    source_file.write_text(SIMPLE, encoding="utf-8")
    engine = ObfuscationEngine(ObfuscationConfig(level=2, dry_run=True))
    engine.obfuscate(source_file)
    assert source_file.is_file()  # original untouched
    assert source_file.read_text(encoding="utf-8") == SIMPLE


# ---------------------------------------------------------------------------
# Error handling and reporting
# ---------------------------------------------------------------------------


def test_parsing_error_carries_file_and_stage():
    engine = ObfuscationEngine(ObfuscationConfig(level=2))
    with pytest.raises(ParsingError) as excinfo:
        engine.obfuscate_source("def broken(:\n", filename="project/module.py")
    assert excinfo.value.file == "project/module.py"
    assert excinfo.value.stage == "parsing"
    assert "could not parse" in str(excinfo.value)


def test_validation_error_for_non_string():
    engine = ObfuscationEngine(ObfuscationConfig(level=2))
    with pytest.raises(ValidationError):
        engine.obfuscate_source(12345)  # type: ignore[arg-type]


def test_result_str_is_informative():
    engine = ObfuscationEngine(ObfuscationConfig(level=3, integrity=True))
    result = engine.obfuscate_source(SIMPLE)
    text = str(result)
    for expected in ("PyDefender obfuscation result", "level", "stages", "sha256"):
        assert expected in text


# ---------------------------------------------------------------------------
# Stage enablement through the engine
# ---------------------------------------------------------------------------


def test_disabling_rename_keeps_original_locals():
    engine = ObfuscationEngine(ObfuscationConfig(level=2, rename=False, strings=False, constants=False))
    result = engine.obfuscate_source(SIMPLE)
    assert "factor" in result.code
    assert run_code(result.code)["compute"](4) == 12


def test_disabling_metadata_keeps_docstrings():
    source = 'def documented():\n    """Keep me."""\n    return 1\n'
    engine = ObfuscationEngine(ObfuscationConfig(level=2, metadata=False, strings=False, constants=False))
    result = engine.obfuscate_source(source)
    assert "Keep me." in result.code
    assert run_code(result.code)["documented"].__doc__ == "Keep me."


# ---------------------------------------------------------------------------
# Environment detection and logging
# ---------------------------------------------------------------------------


def test_detect_environment():
    engine = ObfuscationEngine()
    info = engine.detect_environment()
    assert info.python_version
    assert info.engine_version
    assert isinstance(info.pyinstaller_available, bool)
    assert "PyDefender runtime environment" in str(info)


def test_engine_logging(caplog):
    engine = ObfuscationEngine(ObfuscationConfig(level=2))
    with caplog.at_level(logging.DEBUG, logger="pydefender"):
        engine.obfuscate_source(SIMPLE)
    assert any("stage" in record.message for record in caplog.records)


def test_engine_cache_reuse(tmp_path):
    source_file = tmp_path / "app.py"
    source_file.write_text(SIMPLE, encoding="utf-8")
    engine = ObfuscationEngine(ObfuscationConfig(level=1))
    first = engine.analyze(source_file)
    second = engine.analyze(source_file)
    assert first == second
    engine.clear_cache()
    assert engine._cache == {}


# ---------------------------------------------------------------------------
# Isolation guarantees
# ---------------------------------------------------------------------------


def test_protected_output_never_imports_pydefender():
    for level in (1, 2, 3):
        engine = ObfuscationEngine(ObfuscationConfig(level=level, integrity=True))
        result = engine.obfuscate_source(SIMPLE)
        assert "import pydefender" not in result.code
        assert "from pydefender" not in result.code
