"""Test suite for PyDefender.

Covers the obfuscation engine (all three protection levels), the
scope-safety guarantees of the local-variable renamer, the file API,
the ``analyze`` reports and the full CLI surface.
"""

from __future__ import annotations

import math
import subprocess
import sys

import pytest

import pydefender
from pydefender import PyDefenderError, main, obfuscate_source
from pydefender.obfuscator import LEVELS, analyze_source, obfuscate_file


def run_code(source: str) -> dict:
    """Execute ``source`` in a fresh namespace and return the namespace."""
    namespace: dict = {}
    exec(compile(source, "<protected>", "exec"), namespace)
    return namespace


SAMPLE = '''\
"""Module docstring."""

import math


def circle_area(radius):
    """Return the area of a circle."""
    result = math.pi * radius ** 2
    return result


class Greeter:
    """A friendly greeter."""

    def greet(self, name):
        message = f"Hello, {name}!"
        return message
'''


# ---------------------------------------------------------------------------
# Package metadata
# ---------------------------------------------------------------------------


def test_package_version():
    assert pydefender.__version__ == "0.1.0"


def test_levels_defined():
    assert set(LEVELS) == {1, 2, 3}
    assert set(LEVELS.values()) == {"light", "standard", "heavy"}


def test_main_is_exposed_for_entry_point():
    # pyproject.toml declares `pydefender = "pydefender:main"`.
    assert callable(pydefender.main)


# ---------------------------------------------------------------------------
# Level 1 - light
# ---------------------------------------------------------------------------


def test_level1_strips_docstrings_and_comments():
    source = SAMPLE + "\n# a trailing comment\n"
    protected = obfuscate_source(source, level=1)
    assert "Module docstring." not in protected
    assert "Return the area of a circle." not in protected
    assert "a friendly greeter" not in protected
    assert "# a trailing comment" not in protected
    assert "Protected by PyDefender" in protected  # provenance banner


def test_level1_preserves_behavior():
    protected = obfuscate_source(SAMPLE, level=1)
    namespace = run_code(protected)
    assert namespace["circle_area"](2) == pytest.approx(math.pi * 4)
    assert namespace["Greeter"]().greet("Bob") == "Hello, Bob!"


# ---------------------------------------------------------------------------
# Level 2 - standard (local variable renaming)
# ---------------------------------------------------------------------------


def test_level2_renames_function_locals():
    protected = obfuscate_source(SAMPLE, level=2)
    assert "result" not in protected
    assert "message" not in protected
    # Module-level API surface and parameters stay intact.
    assert "circle_area" in protected
    assert "Greeter" in protected
    assert "radius" in protected
    assert "math" in protected
    namespace = run_code(protected)
    assert namespace["circle_area"](2) == pytest.approx(math.pi * 4)
    assert namespace["Greeter"]().greet("Bob") == "Hello, Bob!"


def test_level2_preserves_parameters_for_keyword_calls():
    source = (
        "def scale(value, factor=2):\n"
        "    doubled = value * factor\n"
        "    return doubled\n"
    )
    protected = obfuscate_source(source, level=2)
    assert "factor" in protected  # parameter untouched
    namespace = run_code(protected)
    assert namespace["scale"](3) == 6
    assert namespace["scale"](3, factor=10) == 30


def test_level2_keeps_closures_and_nonlocal_working():
    source = (
        "def make_accumulator(start=0):\n"
        "    total = start\n"
        "    history = []\n"
        "\n"
        "    def add(amount):\n"
        "        nonlocal total\n"
        "        total += amount\n"
        "        history.append(total)\n"
        "        return total\n"
        "\n"
        "    def reset():\n"
        "        nonlocal total\n"
        "        snapshot = list(history)\n"
        "        history.clear()\n"
        "        total = start\n"
        "        return snapshot\n"
        "\n"
        "    return add, reset\n"
    )
    protected = obfuscate_source(source, level=2)
    add, reset = run_code(protected)["make_accumulator"](5)
    assert add(3) == 8
    assert add(2) == 10
    assert reset() == [8, 10]
    assert add(1) == 6  # total was reset to start=5


def test_level2_keeps_global_variables_working():
    source = (
        "counter = 0\n"
        "\n"
        "def bump():\n"
        "    global counter\n"
        "    step = 1\n"
        "    counter += step\n"
        "    return counter\n"
    )
    protected = obfuscate_source(source, level=2)
    assert "counter" in protected  # global name untouched
    assert "step" not in protected  # local renamed
    namespace = run_code(protected)
    assert namespace["bump"]() == 1
    assert namespace["bump"]() == 2


def test_level2_keeps_import_bindings_working():
    source = (
        "import json as _json\n"
        "from os import path\n"
        "\n"
        "def dumps(obj):\n"
        "    payload = _json.dumps(obj)\n"
        "    return payload\n"
        "\n"
        "def exists(target):\n"
        "    present = path.exists(target)\n"
        "    return present\n"
    )
    protected = obfuscate_source(source, level=2)
    assert "_json" in protected
    assert "path" in protected
    namespace = run_code(protected)
    assert namespace["dumps"]({"a": 1}) == '{"a": 1}'
    assert namespace["exists"]("/") in (True, False)


def test_level2_keeps_class_bodies_reading_enclosing_locals():
    source = (
        "def factory(multiplier):\n"
        "    factor = multiplier\n"
        "\n"
        "    class Widget:\n"
        "        size = factor * 2\n"
        "\n"
        "        def scale(self, value):\n"
        "            adjusted = value * Widget.size\n"
        "            return adjusted\n"
        "\n"
        "    return Widget\n"
    )
    protected = obfuscate_source(source, level=2)
    namespace = run_code(protected)
    assert namespace["factory"](3)().scale(2) == 12


def test_level2_handles_comprehension_shadowing():
    source = (
        "def summarize(numbers):\n"
        "    total = 0\n"
        "    for value in numbers:\n"
        "        total += value\n"
        "    squares = [value * value for value in numbers]\n"
        "    return total, squares\n"
    )
    protected = obfuscate_source(source, level=2)
    namespace = run_code(protected)
    assert namespace["summarize"]([1, 2, 3]) == (6, [1, 4, 9])


def test_level2_output_is_deterministic():
    first = obfuscate_source(SAMPLE, level=2)
    second = obfuscate_source(SAMPLE, level=2)
    assert first == second


# ---------------------------------------------------------------------------
# Level 3 - heavy (base85/zlob wrapper)
# ---------------------------------------------------------------------------


def test_level3_roundtrip_preserves_behavior():
    protected = obfuscate_source(SAMPLE, level=3)
    assert "def circle_area" not in protected
    assert "PyDefender" in protected
    namespace = run_code(protected)
    assert namespace["circle_area"](2) == pytest.approx(math.pi * 4)
    assert namespace["Greeter"]().greet("Bob") == "Hello, Bob!"


def test_level3_protected_file_runs_as_script(tmp_path):
    source = (
        "def main():\n"
        "    print('protected-run-ok')\n"
        "    return 0\n"
        "\n"
        "if __name__ == '__main__':\n"
        "    main()\n"
    )
    protected = obfuscate_source(source, level=3)
    script = tmp_path / "protected_script.py"
    script.write_text(protected, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "protected-run-ok" in result.stdout


def test_level3_preserves_shebang(tmp_path):
    source = "#!/usr/bin/env python3\nvalue = 41 + 1\n"
    script = tmp_path / "with_shebang.py"
    script.write_text(source, encoding="utf-8")
    output = obfuscate_file(script, level=3)
    assert output.read_text(encoding="utf-8").startswith("#!/usr/bin/env python3\n")


# ---------------------------------------------------------------------------
# File API
# ---------------------------------------------------------------------------


def test_obfuscate_file_default_output_name(tmp_path):
    source = tmp_path / "app.py"
    source.write_text(SAMPLE, encoding="utf-8")
    output = obfuscate_file(source, level=2)
    assert output == source.with_name("app_protected.py")
    assert output.is_file()
    namespace = run_code(output.read_text(encoding="utf-8"))
    assert namespace["circle_area"](2) == pytest.approx(math.pi * 4)


def test_obfuscate_file_explicit_output_and_levels(tmp_path):
    source = tmp_path / "app.py"
    source.write_text(SAMPLE, encoding="utf-8")
    target_dir = tmp_path / "dist"
    target_dir.mkdir()
    output = obfuscate_file(source, target_dir, level=3)
    assert output == target_dir / "app_protected.py"
    assert "def circle_area" not in output.read_text(encoding="utf-8")


def test_obfuscate_file_missing_input_raises(tmp_path):
    with pytest.raises(PyDefenderError):
        obfuscate_file(tmp_path / "missing.py")


# ---------------------------------------------------------------------------
# Analysis reports
# ---------------------------------------------------------------------------


def test_analyze_source_report():
    report = analyze_source(SAMPLE)
    assert report["functions"] == 2  # circle_area + greet
    assert report["classes"] == 1
    assert report["imports"] == 1
    assert report["docstrings"] == 3  # module + circle_area + Greeter (greet has none)
    assert report["comments"] == 0
    assert report["recommended_level"] == 3


def test_analyze_source_counts_comments():
    report = analyze_source("# one\n# two\nx = 1\n")
    assert report["comments"] == 2


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def test_invalid_level_raises():
    with pytest.raises(PyDefenderError):
        obfuscate_source("x = 1\n", level=4)


def test_non_string_source_raises():
    with pytest.raises(PyDefenderError):
        obfuscate_source(123)  # type: ignore[arg-type]


def test_syntax_error_raises():
    with pytest.raises(PyDefenderError):
        obfuscate_source("def broken(:\n", level=2)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_help():
    with pytest.raises(SystemExit) as excinfo:
        main(["--help"])
    assert excinfo.value.code == 0
    # argparse prints help to stdout; presence of commands is asserted via SystemExit code


def test_cli_version_flag(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
    assert "0.1.0" in capsys.readouterr().out


def test_cli_version_subcommand(capsys):
    assert main(["version"]) == 0
    captured = capsys.readouterr()
    assert "PyDefender" in captured.out
    assert "0.1.0" in captured.out


def test_cli_bare_invocation_is_usage_error():
    with pytest.raises(SystemExit) as excinfo:
        main([])
    assert excinfo.value.code == 2


def test_cli_obfuscate_file(tmp_path):
    source = tmp_path / "app.py"
    source.write_text("def f():\n    local_value = 1\n    return local_value\n", encoding="utf-8")
    output = tmp_path / "out.py"
    code = main(["obfuscate", str(source), "-o", str(output), "--level", "2", "--force"])
    assert code == 0
    namespace = run_code(output.read_text(encoding="utf-8"))
    assert namespace["f"]() == 1


def test_cli_obfuscate_refuses_overwrite_without_force(tmp_path):
    source = tmp_path / "app.py"
    source.write_text("x = 1\n", encoding="utf-8")
    output = tmp_path / "out.py"
    output.write_text("old = 1\n", encoding="utf-8")
    code = main(["obfuscate", str(source), "-o", str(output), "--level", "1"])
    assert code == 1
    assert output.read_text(encoding="utf-8") == "old = 1\n"


def test_cli_obfuscate_directory(tmp_path, capsys):
    source_dir = tmp_path / "src"
    (source_dir / "pkg").mkdir(parents=True)
    (source_dir / "a.py").write_text("def a():\n    local = 2\n    return local\n", encoding="utf-8")
    (source_dir / "pkg" / "b.py").write_text("def b():\n    inner = 3\n    return inner\n", encoding="utf-8")
    (source_dir / "__pycache__" / "junk.py").parent.mkdir()
    (source_dir / "__pycache__" / "junk.py").write_text("junk = 1\n", encoding="utf-8")
    output_dir = tmp_path / "dist"

    code = main(["obfuscate", str(source_dir), "-o", str(output_dir), "--level", "2", "--force"])
    assert code == 0
    assert (output_dir / "a.py").is_file()
    assert (output_dir / "pkg" / "b.py").is_file()
    assert not (output_dir / "__pycache__" / "junk.py").exists()
    namespace = run_code((output_dir / "pkg" / "b.py").read_text(encoding="utf-8"))
    assert namespace["b"]() == 3
    assert "protected" in capsys.readouterr().out


def test_cli_check(tmp_path, capsys):
    source = tmp_path / "app.py"
    source.write_text(SAMPLE, encoding="utf-8")
    assert main(["check", str(source)]) == 0
    captured = capsys.readouterr()
    assert "functions" in captured.out
    assert "recommended" in captured.out


def test_cli_check_missing_file_returns_error(capsys):
    assert main(["check", "definitely_missing_file.py"]) == 1
    assert "error" in capsys.readouterr().err


def test_cli_obfuscate_missing_input_returns_error(capsys):
    assert main(["obfuscate", "definitely_missing_dir/", "--force"]) == 1
    assert "error" in capsys.readouterr().err


def test_python_dash_m_invocation(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "pydefender", "--version"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0
    assert "0.1.0" in result.stdout
