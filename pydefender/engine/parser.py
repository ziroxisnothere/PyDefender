"""Parsing and static analysis stage of the PyDefender engine.

All source understanding happens here, on top of the standard library
``ast`` and ``tokenize`` modules. No regex-based source rewriting is
used anywhere in the engine: every transformation operates on a real
AST so valid Python syntax can never be corrupted by pattern matching.
"""

from __future__ import annotations

import ast
import os
import tokenize
from io import StringIO
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from pydefender.engine.exceptions import OutputError, ParsingError

__all__ = [
    "read_source",
    "parse_source",
    "extract_dependencies",
    "extract_shebang",
    "is_docstring",
    "analyze_source",
    "analyze_file",
]

#: Maximum input size the engine accepts (guards against accidents).
MAX_INPUT_BYTES = 64 * 1024 * 1024


def read_source(path: Union[str, os.PathLike]) -> str:
    """Read a Python source file as UTF-8 text.

    Raises:
        OutputError: If the file is missing, not a file, unreadable,
            too large or not valid UTF-8.
    """
    file_path = Path(path)
    if not file_path.exists():
        raise OutputError(f"input path does not exist: {file_path}", file=str(file_path))
    if not file_path.is_file():
        raise OutputError(f"input path is not a file: {file_path}", file=str(file_path))
    try:
        size = file_path.stat().st_size
        if size > MAX_INPUT_BYTES:
            raise OutputError(
                f"input file too large ({size} bytes, limit is {MAX_INPUT_BYTES})",
                file=str(file_path),
            )
        return file_path.read_text(encoding="utf-8")
    except OutputError:
        raise
    except UnicodeDecodeError as exc:
        raise OutputError(
            f"could not read {file_path}: source must be UTF-8 text",
            file=str(file_path),
            reason=str(exc),
        ) from exc
    except OSError as exc:
        raise OutputError(
            f"could not read {file_path}",
            file=str(file_path),
            reason=str(exc),
        ) from exc


def parse_source(
    source: str,
    filename: str = "<source>",
    target_python: Optional[Tuple[int, int]] = None,
) -> ast.Module:
    """Parse ``source`` into an AST.

    Args:
        source: Python source code.
        filename: Name used in error messages and compile records.
        target_python: Optional ``(major, minor)`` pair. When given, the
            parser rejects syntax that the target version cannot handle.

    Raises:
        ParsingError: If the source is not valid Python (or uses syntax
            newer than ``target_python``).
    """
    if not isinstance(source, str):
        raise ParsingError(
            "source must be a string containing Python code",
            file=filename,
            reason=f"got {type(source).__name__}",
        )
    feature_version: Optional[Tuple[int, int]] = None
    if target_python is not None:
        feature_version = (int(target_python[0]), int(target_python[1]))
    try:
        return ast.parse(source, filename=filename, feature_version=feature_version)
    except (SyntaxError, ValueError) as exc:
        raise ParsingError(
            "could not parse source code",
            file=filename,
            reason=str(exc),
        ) from exc


def extract_dependencies(tree: ast.Module) -> List[str]:
    """Extract the top-level modules imported by a parsed module.

    Relative imports are reported as ``"<relative>"``. Statically
    detectable dynamic imports - ``importlib.import_module("name")``,
    ``import_module("name")`` and ``__import__("name")`` calls with a
    literal string argument - are included as well, which makes the
    result directly useful as a packaging tool's hidden-import list
    (e.g. PyInstaller). The result is sorted and de-duplicated.
    """
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                found.add("<relative>")
            elif node.module:
                found.add(node.module.split(".")[0])
        elif isinstance(node, ast.Call):
            found.update(_dynamic_import_target(node))
    return sorted(found)


def _dynamic_import_target(call_node: ast.Call) -> Set[str]:
    """Return the module name for constant-name dynamic import calls."""
    func = call_node.func
    is_dynamic = False
    if isinstance(func, ast.Name) and func.id in ("import_module", "__import__"):
        is_dynamic = True
    elif (
        isinstance(func, ast.Attribute)
        and func.attr == "import_module"
        and isinstance(func.value, ast.Name)
        and func.value.id == "importlib"
    ):
        is_dynamic = True
    if not is_dynamic or not call_node.args:
        return set()
    first = call_node.args[0]
    if isinstance(first, ast.Constant) and type(first.value) is str and first.value:
        return {first.value.split(".")[0]}
    return set()


def extract_shebang(source: str) -> str:
    """Return the ``#!`` line of the source (with newline), or ``""``."""
    if source.startswith("#!"):
        first_line = source.split("\n", 1)[0]
        return first_line + "\n"
    return ""


def is_docstring(node: ast.AST) -> bool:
    """Return ``True`` if ``node`` is an expression statement holding
    only a plain string constant (i.e. a docstring position)."""
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )


def analyze_source(source: str) -> Dict[str, int]:
    """Analyze Python source and return a protection report.

    The report contains line/function/class/import/comment/docstring
    counts plus a recommended protection level. This stage is fully
    offline and independent from the transformation pipeline.
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError) as exc:
        raise ParsingError("could not parse source code", reason=str(exc)) from exc

    functions = 0
    classes = 0
    imports = 0
    scopes = 0
    documented = 0
    scope_types = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions += 1
        elif isinstance(node, ast.ClassDef):
            classes += 1
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            imports += 1
        if isinstance(node, scope_types):
            scopes += 1
            if getattr(node, "body", None) and is_docstring(node.body[0]):
                documented += 1

    comments = 0
    try:
        for token in tokenize.generate_tokens(StringIO(source).readline):
            if token.type == tokenize.COMMENT:
                comments += 1
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass  # keep whatever was counted before the error

    recommended = 3 if (comments > 0 or documented > 0) else 2
    return {
        "lines": len(source.splitlines()),
        "functions": functions,
        "classes": classes,
        "imports": imports,
        "comments": comments,
        "docstrings": documented,
        "scopes": scopes,
        "recommended_level": recommended,
    }


def analyze_file(path: Union[str, os.PathLike]) -> Dict[str, int]:
    """Analyze a Python source file and return a protection report."""
    source = read_source(path)
    report = analyze_source(source)
    report["path"] = str(path)  # type: ignore[assignment]
    return report
