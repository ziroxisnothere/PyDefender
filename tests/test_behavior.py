"""Behavior-preservation matrix: original vs protected program output.

For every fixture program and every protection level the test:

1. runs the original program and captures its output,
2. obfuscates it through the standalone engine,
3. runs the protected program,
4. asserts identical behavior (stdout, exit code).

This is the engine's primary contract::

    Original Python program -> PyDefender -> protected program
    -> same intended runtime behavior
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import FIXTURES_DIR, SCRIPTS_FIXTURES_DIR

from pydefender import ObfuscationConfig, ObfuscationEngine

SINGLE_FILE_FIXTURES = [
    "basic.py",
    "imports.py",
    "classes.py",
    "async.py",
    "decorators.py",
    "generators.py",
    "dataclasses.py",
    "match_case.py",
    "multiprocessing.py",
]

LEVELS = [1, 2, 3]


def _obfuscate_fixture(fixture_path: Path, tmp_path: Path, level: int) -> Path:
    engine = ObfuscationEngine(ObfuscationConfig(level=level, integrity=True))
    output_dir = tmp_path / f"protected_l{level}"
    result = engine.obfuscate(fixture_path, output_dir / fixture_path.name)
    assert result.success
    return result.output_path


@pytest.mark.parametrize("level", LEVELS)
@pytest.mark.parametrize("fixture_name", SINGLE_FILE_FIXTURES)
def test_single_file_fixtures_preserve_behavior(
    fixture_name,
    level,
    tmp_path,
    run_python,
):
    if fixture_name == "match_case.py" and sys.version_info < (3, 10):
        pytest.skip("match/case requires Python 3.10+")
    if fixture_name == "multiprocessing.py" and sys.version_info >= (3, 14):
        pytest.skip("fork/spawn defaults changed after 3.13; not part of the support matrix")

    original = SCRIPTS_FIXTURES_DIR / fixture_name
    baseline = run_python(original)
    assert baseline.returncode == 0, baseline.stderr

    protected_path = _obfuscate_fixture(original, tmp_path, level)
    assert protected_path != original
    assert original.is_file()  # original is never modified or deleted

    protected = run_python(protected_path)
    assert protected.returncode == 0, protected.stderr
    assert protected.stdout == baseline.stdout, (
        f"{fixture_name} (level {level}) behavior changed:\n"
        f"--- original ---\n{baseline.stdout}\n--- protected ---\n{protected.stdout}"
    )


@pytest.mark.parametrize("level", LEVELS)
def test_relative_imports_package_preserves_behavior(level, tmp_path, run_module):
    package_dir = FIXTURES_DIR / "relative_imports"
    baseline = run_module("relative_imports.main", FIXTURES_DIR)
    assert baseline.returncode == 0, baseline.stderr

    output_dir = tmp_path / f"dist_l{level}"
    engine = ObfuscationEngine(ObfuscationConfig(level=level))
    result = engine.obfuscate(package_dir, output_dir / "relative_imports")
    assert result.success
    assert len(result.files) == 4  # __init__, core, main, util

    protected = run_module("relative_imports.main", output_dir)
    assert protected.returncode == 0, protected.stderr
    assert protected.stdout == baseline.stdout


@pytest.mark.parametrize("level", LEVELS)
def test_package_project_preserves_behavior(level, tmp_path, run_module):
    package_dir = FIXTURES_DIR / "package_project"
    baseline = run_module("package_project", FIXTURES_DIR)
    assert baseline.returncode == 0, baseline.stderr

    output_dir = tmp_path / f"dist_l{level}"
    engine = ObfuscationEngine(ObfuscationConfig(level=level))
    result = engine.obfuscate(package_dir, output_dir / "package_project")
    assert result.success

    protected = run_module("package_project", output_dir)
    assert protected.returncode == 0, protected.stderr
    assert protected.stdout == baseline.stdout


def test_pyinstaller_project_preserves_behavior(tmp_path, run_python_normal):
    project_dir = FIXTURES_DIR / "pyinstaller_project"
    baseline = run_python_normal(project_dir / "main.py")
    assert baseline.returncode == 0, baseline.stderr

    output_dir = tmp_path / "dist"
    engine = ObfuscationEngine(ObfuscationConfig(level=2))
    result = engine.obfuscate(project_dir / "main.py", output_dir / "main.py")
    # helper_ops stays next to the protected file so the static local
    # import keeps working (the recommended PyInstaller workflow).
    shutil.copy(project_dir / "helper_ops.py", output_dir / "helper_ops.py")
    assert result.success

    protected = run_python_normal(output_dir / "main.py")
    assert protected.returncode == 0, protected.stderr
    assert protected.stdout == baseline.stdout


def test_unsupported_transformation_fails_safely(tmp_path):
    """A file with syntax the target cannot parse fails without side effects."""
    source_file = tmp_path / "newer_syntax.py"
    source_file.write_text("value: int = 1\nprint(value)\n", encoding="utf-8")
    engine = ObfuscationEngine(ObfuscationConfig(level=1))
    result = engine.obfuscate(source_file)
    assert result.success  # valid on this interpreter
    # Now the same file but a target that cannot parse it: safe failure.
    breaking = tmp_path / "breaking.py"
    breaking.write_text("value = 1\n", encoding="utf-8")
    strict = ObfuscationEngine(
        ObfuscationConfig(level=1, target_python=(99, 0))
    )
    with pytest.raises(Exception) as excinfo:
        strict.obfuscate(breaking)
    assert "parse" in str(excinfo.value)
    assert breaking.is_file()  # nothing deleted
    assert not (tmp_path / "breaking_protected.py").exists()  # nothing written


def test_fail_fast_leaves_original_untouched(tmp_path):
    source_file = tmp_path / "app.py"
    source_file.write_text("def broken(:\n", encoding="utf-8")
    engine = ObfuscationEngine(ObfuscationConfig(level=3))
    with pytest.raises(Exception):
        engine.obfuscate(source_file)
    assert source_file.read_text(encoding="utf-8") == "def broken(:\n"
    assert not list(tmp_path.glob("*_protected.py"))


# ---------------------------------------------------------------------------
# Optional real PyInstaller build (skipped when PyInstaller is absent)
# ---------------------------------------------------------------------------

pyinstaller_available = shutil.which("pyinstaller") is not None


@pytest.mark.skipif(not pyinstaller_available, reason="PyInstaller is not installed")
def test_pyinstaller_onefile_frozen_build(tmp_path, run_python_normal):
    """Full frozen-build workflow: protect -> pyinstaller --onefile -> run.

    Dynamic imports need --hidden-import (true for the original file as
    well); the engine's result.dependencies output provides the list.
    """
    import json as json_module

    project_dir = FIXTURES_DIR / "pyinstaller_project"
    baseline = run_python_normal(project_dir / "main.py")
    assert baseline.returncode == 0, baseline.stderr

    dist_dir = tmp_path / "protected"
    engine = ObfuscationEngine(ObfuscationConfig(level=2))
    result = engine.obfuscate(project_dir / "main.py", dist_dir / "main.py")
    shutil.copy(project_dir / "helper_ops.py", dist_dir / "helper_ops.py")

    # Use the engine's dependency detection for the hidden-import list.
    hidden = [dependency for dependency in result.dependencies if dependency not in ("<relative>", "helper_ops")]
    assert "json" in hidden

    work_dir = tmp_path / "build"
    build = subprocess.run(
        [
            "pyinstaller",
            "--onefile",
            str(dist_dir / "main.py"),
            *[f"--hidden-import={module}" for module in hidden],
            "--distpath", str(tmp_path / "frozen"),
            "--workpath", str(work_dir),
            "--specpath", str(work_dir),
            "--noconfirm",
        ],
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert build.returncode == 0, build.stderr

    frozen_binary = tmp_path / "frozen" / "main"
    assert frozen_binary.is_file()
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    frozen = subprocess.run(
        [str(frozen_binary)],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    assert frozen.returncode == 0, frozen.stderr
    json_module.loads(frozen.stdout.splitlines()[0])  # payload is valid JSON
    assert frozen.stdout == baseline.stdout
