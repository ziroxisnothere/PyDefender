"""Shared test helpers for the PyDefender test suite."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).parent
FIXTURES_DIR = TESTS_DIR / "fixtures"
SCRIPTS_FIXTURES_DIR = FIXTURES_DIR / "scripts"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def run_python():
    """Run a Python script in isolated mode (-I) and return the result.

    Isolated mode keeps fixture script directories off ``sys.path``, so
    fixture file names cannot shadow standard library modules.
    """

    def _run(path: Path, timeout: int = 120) -> subprocess.CompletedProcess:
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        return subprocess.run(
            [sys.executable, "-I", str(path)],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )

    return _run


@pytest.fixture
def run_python_normal():
    """Run a Python script normally (script dir on sys.path).

    Used for multi-file projects whose modules import each other by
    script-directory layout, exactly like a real user would run them.
    """

    def _run(path: Path, cwd: Path | None = None, timeout: int = 120) -> subprocess.CompletedProcess:
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        return subprocess.run(
            [sys.executable, str(path)],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(cwd) if cwd else None,
            env=env,
        )

    return _run


@pytest.fixture
def run_module():
    """Run an installed-package style module by name from a directory.

    Uses ``runpy`` with the package parent directory injected into
    ``sys.path``; the caller controls the working directory.
    """

    def _run(module: str, package_dir: Path, timeout: int = 120) -> subprocess.CompletedProcess:
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        code = (
            "import runpy, sys\n"
            f"sys.path.insert(0, r'{package_dir}')\n"
            f"runpy.run_module({module!r}, run_name='__main__')\n"
        )
        return subprocess.run(
            [sys.executable, "-I", "-c", code],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )

    return _run
