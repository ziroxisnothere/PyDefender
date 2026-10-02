"""Per-stage tests: every pipeline stage tested in isolation.

These tests exercise the stage classes directly, independent of the
full pipeline, as required by the modular-pipeline design.
"""

from __future__ import annotations

import ast
import random

import pytest

from pydefender.engine.config import ObfuscationConfig
from pydefender.engine.parser import analyze_source, extract_dependencies, parse_source
from pydefender.engine.pipeline import Pipeline, PipelineOutcome
from pydefender.engine.protection import compute_checksum
from pydefender.engine.transformer import (
    ConstantProtector,
    ControlFlowProtector,
    MetadataReducer,
    NameProtector,
    StringProtector,
    TransformContext,
)


def make_ctx(config: ObfuscationConfig | None = None, filename: str = "<stage-test>") -> TransformContext:
    config = config or ObfuscationConfig()
    return TransformContext(
        rng=random.Random(f"pydefender:{config.seed}:{filename}"),
        config=config,
        filename=filename,
        warnings=[],
    )


def run_code(source: str) -> dict:
    namespace: dict = {}
    exec(compile(source, "<stage>", "exec"), namespace)
    return namespace


# ---------------------------------------------------------------------------
# Parser stage
# ---------------------------------------------------------------------------


def test_parse_source_rejects_syntax_errors():
    with pytest.raises(Exception) as excinfo:
        parse_source("def broken(:\n")
    assert "parse" in str(excinfo.value)


def test_extract_dependencies():
    tree = parse_source("import json\nimport os.path\nfrom collections import deque\nfrom . import x\n")
    deps = extract_dependencies(tree)
    assert deps == ["<relative>", "collections", "json", "os"]


def test_analyze_source_counts():
    report = analyze_source("import math\n\ndef area(r):\n    '''doc'''\n    return math.pi * r\n")
    assert report["functions"] == 1
    assert report["imports"] == 1
    assert report["docstrings"] == 1


# ---------------------------------------------------------------------------
# MetadataReducer
# ---------------------------------------------------------------------------


def test_metadata_reducer_strips_all_docstrings():
    source = (
        '"""Module doc."""\n'
        "class C:\n"
        '    """Class doc."""\n'
        "    def m(self):\n"
        '        """Method doc."""\n'
        "        return 1\n"
    )
    tree = parse_source(source)
    details = MetadataReducer().apply(tree, make_ctx())
    assert "3" in details
    output = ast.unparse(tree)
    assert "doc" not in output
    assert run_code(output)["C"]().m() == 1


# ---------------------------------------------------------------------------
# NameProtector
# ---------------------------------------------------------------------------


def test_name_protector_renames_locals_only():
    source = (
        "module_level = 5\n"
        "\n"
        "def func(param):\n"
        "    local_value = param + module_level\n"
        "    return local_value\n"
    )
    tree = parse_source(source)
    NameProtector().apply(tree, make_ctx())
    output = ast.unparse(tree)
    assert "local_value" not in output
    assert "param" in output      # parameters are never renamed
    assert "module_level" in output  # module-level names are never renamed
    assert run_code(output)["func"](2) == 7


def test_name_protector_skips_nested_scope_references():
    source = (
        "def outer(start):\n"
        "    total = start\n"
        "    def inner(step):\n"
        "        nonlocal total\n"
        "        total += step\n"
        "        return total\n"
        "    return inner\n"
    )
    tree = parse_source(source)
    NameProtector().apply(tree, make_ctx())
    output = ast.unparse(tree)
    inner = run_code(output)["outer"](10)
    assert inner(5) == 15
    assert inner(5) == 20


# ---------------------------------------------------------------------------
# ConstantProtector
# ---------------------------------------------------------------------------


def test_constant_protector_preserves_values():
    source = "def values():\n    big = 123456\n    small = 42\n    return big, small\n"
    config = ObfuscationConfig(level=2)
    tree = parse_source(source)
    ConstantProtector().apply(tree, make_ctx(config))
    output = ast.unparse(tree)
    assert "123456" not in output
    assert "42" in output  # small ints untouched
    assert run_code(output)["values"]() == (123456, 42)


def test_constant_protector_handles_negatives_and_bools():
    source = (
        "def mixed(flag):\n"
        "    negative = -250000\n"
        "    flag_value = True\n"
        "    return negative, flag_value, flag\n"
    )
    tree = parse_source(source)
    ConstantProtector().apply(tree, make_ctx())
    output = ast.unparse(tree)
    assert "250000" not in output
    namespace = run_code(output)
    assert namespace["mixed"](True) == (-250000, True, True)


def test_constant_protector_is_exact_for_large_values():
    huge = 987654321987
    source = f"def huge_value():\n    number = {huge}\n    return number\n"
    tree = parse_source(source)
    ConstantProtector().apply(tree, make_ctx())
    assert run_code(ast.unparse(tree))["huge_value"]() == huge


# ---------------------------------------------------------------------------
# StringProtector
# ---------------------------------------------------------------------------


def test_string_protector_roundtrips_long_strings():
    secret = "this-string-is-long-enough-to-be-protected!"
    source = f"def read_secret():\n    payload = {secret!r}\n    return payload\n"
    config = ObfuscationConfig(level=2)
    tree = parse_source(source)
    StringProtector().apply(tree, make_ctx(config))
    output = ast.unparse(tree)
    assert secret not in output
    assert run_code(output)["read_secret"]() == secret


def test_string_protector_skips_short_strings():
    source = "def short():\n    keep = 'kept'\n    return keep\n"
    tree = parse_source(source)
    StringProtector().apply(tree, make_ctx())
    output = ast.unparse(tree)
    assert "'kept'" in output


def test_string_protector_skips_f_strings():
    source = (
        "def formatted(name, count):\n"
        "    message = f'hello {name}, you have {count} long enough items here'\n"
        "    return message\n"
    )
    tree = parse_source(source)
    StringProtector().apply(tree, make_ctx())
    assert run_code(ast.unparse(tree))["formatted"]("ada", 3) == "hello ada, you have 3 long enough items here"


def test_string_protector_handles_unicode():
    secret = "çok özel veri içeren uzun bir dize — sensitive ✓"
    source = f"def unicode_secret():\n    payload = {secret!r}\n    return payload\n"
    tree = parse_source(source)
    StringProtector().apply(tree, make_ctx())
    assert run_code(ast.unparse(tree))["unicode_secret"]() == secret


# ---------------------------------------------------------------------------
# ControlFlowProtector
# ---------------------------------------------------------------------------


def test_control_flow_protector_inserts_never_taken_branches():
    source = (
        "def branchy(value):\n"
        "    first = value * 2\n"
        "    second = first + 1\n"
        "    return second\n"
    )
    config = ObfuscationConfig(level=3)
    tree = parse_source(source)
    details = ControlFlowProtector(density=1.0).apply(tree, make_ctx(config))
    assert "1" in details  # one branch inserted
    output = ast.unparse(tree)
    assert "if" in output
    assert run_code(output)["branchy"](10) == 21


def test_control_flow_protector_preserves_docstring_position():
    source = (
        "def documented(value):\n"
        "    '''Important docstring stays first when metadata is off.'''\n"
        "    doubled = value * 2\n"
        "    return doubled\n"
    )
    config = ObfuscationConfig(level=3, metadata=False)
    tree = parse_source(source)
    ControlFlowProtector().apply(tree, make_ctx(config))
    output = ast.unparse(tree)
    namespace = run_code(output)
    func = namespace["documented"]
    assert func.__doc__ == "Important docstring stays first when metadata is off."
    assert func(8) == 16


def test_control_flow_never_touches_module_level():
    source = "from __future__ import annotations\n\nanswer = 42\n"
    tree = parse_source(source)
    details = ControlFlowProtector().apply(tree, make_ctx())
    assert "0" in details  # nothing inserted at module level
    assert ast.unparse(tree).index("from __future__") == 0


# ---------------------------------------------------------------------------
# Protection helpers
# ---------------------------------------------------------------------------


def test_compute_checksum_is_stable():
    assert compute_checksum("abc") == compute_checksum("abc")
    assert compute_checksum("abc") != compute_checksum("abd")
    assert len(compute_checksum("abc")) == 64


# ---------------------------------------------------------------------------
# Pipeline composition
# ---------------------------------------------------------------------------


def test_pipeline_reports_skipped_stages():
    config = ObfuscationConfig(level=1)
    outcome = Pipeline(config).run("value = 1\n")
    statuses = {report.name: report.status for report in outcome.reports}
    assert statuses["metadata-reduction"] == "ok"
    assert statuses["name-protection"] == "skipped"
    assert statuses["control-flow-protection"] == "skipped"


def test_pipeline_outcome_type():
    outcome = Pipeline(ObfuscationConfig(level=2)).run(SIMPLE_SRC := "def f():\n    x = 1\n    return x\n")
    assert isinstance(outcome, PipelineOutcome)
    assert outcome.code
    assert "parsing" in {report.name for report in outcome.reports}


# ---------------------------------------------------------------------------
# Regression tests (found by the behavior matrix)
# ---------------------------------------------------------------------------


def test_name_protector_keeps_reassigned_parameters_working():
    """A parameter reassigned in the body must stay linked to the argument."""
    source = (
        "def countdown(start):\n"
        "    steps = 0\n"
        "    while start > 0:\n"
        "        yield start\n"
        "        start -= 1\n"
        "        steps += 1\n"
        "    return steps\n"
    )
    tree = parse_source(source)
    NameProtector().apply(tree, make_ctx())
    output = ast.unparse(tree)
    generator = run_code(output)["countdown"](3)
    assert list(generator) == [3, 2, 1]


def test_name_protector_keeps_except_as_bindings_working():
    source = (
        "def risky(values):\n"
        "    results = []\n"
        "    for value in values:\n"
        "        try:\n"
        "            results.append(10 // value)\n"
        "        except ZeroDivisionError as error:\n"
        "            results.append(str(type(error).__name__))\n"
        "    return results\n"
    )
    tree = parse_source(source)
    NameProtector().apply(tree, make_ctx())
    output = ast.unparse(tree)
    assert "error" not in output
    assert run_code(output)["risky"]([2, 0, 5]) == [5, "ZeroDivisionError", 2]


def test_name_protector_keeps_match_captures_working():
    source = (
        "def classify(command):\n"
        "    match command:\n"
        "        case {'op': 'add', 'value': amount}:\n"
        "            return f'adding {amount}'\n"
        "        case ['pair', label]:\n"
        "            return f'pair of {label}'\n"
        "        case {'rest': 1, **remainder}:\n"
        "            return f'rest {sorted(remainder)}'\n"
        "        case _:\n"
        "            return 'unknown'\n"
    )
    tree = parse_source(source)
    NameProtector().apply(tree, make_ctx())
    output = ast.unparse(tree)
    classify = run_code(output)["classify"]
    assert classify({"op": "add", "value": 41}) == "adding 41"
    assert classify(["pair", "socks"]) == "pair of socks"
    assert classify({"rest": 1, "b": 2}) == "rest ['b']"
    assert classify("nope") == "unknown"
