"""Core obfuscation engine for PyDefender.

PyDefender transforms readable Python source code into functionally
equivalent, hard-to-read code using the standard library ``ast`` module.
Three protection levels are provided:

    1 (light)     strip docstrings and comments
    2 (standard)  level 1 + safe renaming of function-local variables
    3 (heavy)     level 1 + 2 + full source compression into a
                  base85/zlib loader stub

All transformations are semantic-preserving: the protected code executes
exactly like the original. Only the Python standard library is used.
"""

from __future__ import annotations

import ast
import base64
import os
import textwrap
import tokenize
import zlib
from io import StringIO
from pathlib import Path
from typing import Dict, Optional, Set, Tuple, Union

__all__ = [
    "PyDefenderError",
    "LEVELS",
    "GITHUB_URL",
    "obfuscate_source",
    "obfuscate_file",
    "analyze_source",
    "analyze_file",
]

#: Available protection levels and their human-readable names.
LEVELS: Dict[int, str] = {1: "light", 2: "standard", 3: "heavy"}

#: Project homepage.
GITHUB_URL = "https://github.com/ziroxisnothere/PyDefender"


class PyDefenderError(Exception):
    """Raised when PyDefender cannot obfuscate or analyze the given source."""


def _package_version() -> str:
    """Return the installed PyDefender version (best effort)."""
    try:
        from importlib.metadata import version as _dist_version

        return _dist_version("PyDefender")
    except Exception:
        try:
            from pydefender import __version__

            return __version__
        except Exception:
            return "0.1.0"


# ---------------------------------------------------------------------------
# Docstring removal (part of every protection level)
# ---------------------------------------------------------------------------


class _DocstringStripper(ast.NodeTransformer):
    """Remove module, class and function docstrings from an AST."""

    def _strip_docstring(self, node: ast.AST) -> ast.AST:
        body = getattr(node, "body", None)
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            if len(body) == 1:
                node.body = [ast.Pass()]  # type: ignore[attr-defined]
            else:
                node.body = body[1:]  # type: ignore[attr-defined]
        return node

    def visit_Module(self, node: ast.Module) -> ast.Module:
        self.generic_visit(node)
        return self._strip_docstring(node)  # type: ignore[return-value]

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.FunctionDef:
        self.generic_visit(node)
        return self._strip_docstring(node)  # type: ignore[return-value]

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AsyncFunctionDef:
        self.generic_visit(node)
        return self._strip_docstring(node)  # type: ignore[return-value]

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.ClassDef:
        self.generic_visit(node)
        return self._strip_docstring(node)  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Scope-safe renaming of function-local variables (level 2+)
# ---------------------------------------------------------------------------

#: AST node types that open a new lexical scope.
_SCOPE_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)

#: AST node types (across supported Python versions) that bind a name held
#: in a plain ``str`` attribute rather than in a ``Name`` node.
_STRING_BINDING_NODES = tuple(
    node_type
    for node_type in (
        getattr(ast, "ExceptHandler", None),
        getattr(ast, "MatchAs", None),
        getattr(ast, "MatchStar", None),
        getattr(ast, "MatchMapping", None),
        getattr(ast, "TypeVar", None),
        getattr(ast, "ParamSpec", None),
        getattr(ast, "TypeVarTuple", None),
    )
    if node_type is not None
)


def _string_binding_name(node: ast.AST) -> Optional[str]:
    """Return the identifier bound by a string-binding node, if any."""
    name = getattr(node, "name", None) or getattr(node, "rest", None)
    return name if isinstance(name, str) else None


def _own_scope_children(node: ast.AST):
    """Yield the direct children that belong to ``node``'s own scope.

    Decorators, base classes, keyword arguments, return annotations and
    parameter defaults are evaluated in the *enclosing* scope, so they are
    excluded here.
    """
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        excluded = {id(node.args)}
        if node.returns is not None:
            excluded.add(id(node.returns))
        excluded.update(id(deco) for deco in node.decorator_list)
        for child in ast.iter_child_nodes(node):
            if id(child) not in excluded:
                yield child
    elif isinstance(node, ast.ClassDef):
        excluded = {id(base) for base in node.bases}
        excluded.update(id(keyword.value) for keyword in node.keywords)
        excluded.update(id(deco) for deco in node.decorator_list)
        for child in ast.iter_child_nodes(node):
            if id(child) not in excluded:
                yield child
    else:
        yield from ast.iter_child_nodes(node)


def _walk_own_scope(node: ast.AST):
    """Yield every descendant inside ``node``'s immediate lexical scope.

    Does not descend into nested scopes (functions, lambdas, classes).
    """
    stack = list(_own_scope_children(node))
    while stack:
        current = stack.pop()
        yield current
        if not isinstance(current, _SCOPE_NODES):
            stack.extend(ast.iter_child_nodes(current))


def _import_binding_name(import_node: Union[ast.Import, ast.ImportFrom], alias: ast.alias) -> str:
    """Return the name an import statement binds into the current scope."""
    if isinstance(import_node, ast.Import):
        return alias.asname or alias.name.split(".")[0]
    return alias.asname or alias.name


def _collect_scope_data(node: ast.AST) -> Tuple[Set[str], Set[str], Set[str]]:
    """Collect ``(bindings, import_boundings, declared)`` for one scope.

    ``bindings``         every name bound in the scope (assignments, loop
                         targets, with/except targets, imports, walrus, ...)
    ``import_boundings`` subset of bindings introduced by import statements
                         (never renamed, keeps the module API stable)
    ``declared``         names declared ``global``/``nonlocal`` in this scope
    """
    bindings: Set[str] = set()
    import_boundings: Set[str] = set()
    declared: Set[str] = set()
    for child in _own_scope_children(node):
        stack = [child]
        while stack:
            current = stack.pop()
            if isinstance(current, _SCOPE_NODES):
                continue
            if isinstance(current, (ast.Import, ast.ImportFrom)):
                for alias in current.names:
                    if alias.name == "*":
                        continue
                    bound = _import_binding_name(current, alias)
                    bindings.add(bound)
                    import_boundings.add(bound)
                continue
            if isinstance(current, (ast.Global, ast.Nonlocal)):
                declared.update(current.names)
                continue
            if isinstance(current, ast.Name) and isinstance(current.ctx, (ast.Store, ast.Del)):
                bindings.add(current.id)
            elif isinstance(current, _STRING_BINDING_NODES):
                name = _string_binding_name(current)
                if name:
                    bindings.add(name)
            stack.extend(ast.iter_child_nodes(current))
    return bindings, import_boundings, declared


def _nested_references(node: ast.AST) -> Set[str]:
    """Collect every identifier referenced or bound inside nested scopes.

    Any name appearing in a nested function, lambda or class body is
    excluded from renaming in the enclosing scope. This is deliberately
    conservative: it guarantees closures, ``nonlocal``/``global`` access
    and class bodies that read enclosing locals keep working.
    """
    refs: Set[str] = set()
    for child in _own_scope_children(node):
        stack = [child]
        while stack:
            current = stack.pop()
            if isinstance(current, _SCOPE_NODES):
                for inner in ast.walk(current):
                    if isinstance(inner, ast.Name):
                        refs.add(inner.id)
                    elif isinstance(inner, ast.arg):
                        refs.add(inner.arg)
                    elif isinstance(inner, _STRING_BINDING_NODES):
                        name = _string_binding_name(inner)
                        if name:
                            refs.add(name)
                    elif isinstance(inner, (ast.Global, ast.Nonlocal)):
                        refs.update(inner.names)
                    elif isinstance(inner, (ast.Import, ast.ImportFrom)):
                        for alias in inner.names:
                            if alias.name != "*":
                                refs.add(_import_binding_name(inner, alias))
            else:
                stack.extend(ast.iter_child_nodes(current))
    return refs


def _apply_renames(node: ast.AST, mapping: Dict[str, str]) -> None:
    """Rename ``Name`` nodes inside ``node``'s own scope only.

    Nested scope subtrees are skipped: they were already processed with
    their own rename maps and may legitimately shadow outer names.
    """
    for child in _own_scope_children(node):
        stack = [child]
        while stack:
            current = stack.pop()
            if isinstance(current, _SCOPE_NODES):
                continue
            if isinstance(current, ast.Name) and current.id in mapping:
                current.id = mapping[current.id]
            stack.extend(ast.iter_child_nodes(current))


class _LocalRenamer(ast.NodeTransformer):
    """Rename function-local variables using conservative, scope-safe rules.

    Safety rules (never violated):

    * parameters are never renamed (keyword arguments stay compatible)
    * names bound by ``import`` statements are never renamed
    * ``global``/``nonlocal`` declared names are never renamed
    * names referenced in nested scopes are never renamed
    * module-level and class-level names are never renamed
    * attribute names, dict keys and string values are never touched
    * dunder names are never renamed
    """

    def __init__(self, prefix: str = "_0x") -> None:
        self._prefix = prefix
        self._counter = 0

    def _fresh_name(self) -> str:
        self._counter += 1
        return f"{self._prefix}{self._counter:04x}"

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.FunctionDef:
        self.generic_visit(node)
        self._rename_own_scope(node)
        return node

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AsyncFunctionDef:
        self.generic_visit(node)
        self._rename_own_scope(node)
        return node

    def _rename_own_scope(self, node: ast.AST) -> None:
        bindings, imports, declared = _collect_scope_data(node)
        forbidden = imports | declared
        targets = bindings - forbidden - _nested_references(node)
        targets = {
            name
            for name in targets
            if not (name.startswith("__") and name.endswith("__"))
        }
        if not targets:
            return
        mapping = {name: self._fresh_name() for name in sorted(targets)}
        _apply_renames(node, mapping)


# ---------------------------------------------------------------------------
# Heavy wrapping (level 3)
# ---------------------------------------------------------------------------


def _wrap_heavy(code: str) -> str:
    """Compress ``code`` into a self-contained base85/zlib loader stub."""
    version = _package_version()
    payload = base64.b85encode(zlib.compress(code.encode("utf-8"), 9)).decode("ascii")
    chunks = textwrap.wrap(payload, 72) or [""]
    payload_lines = "\n".join(f'    "{chunk}"' for chunk in chunks)
    return (
        f"# Protected by PyDefender v{version} (level 3: heavy)\n"
        f"# {GITHUB_URL}\n"
        "# This file contains protected source code. Do not edit manually.\n"
        "import base64 as _pd_b85, zlib as _pd_zlib\n"
        "\n"
        "_pd_payload = (\n"
        f"{payload_lines}\n"
        ")\n"
        "exec(compile(_pd_zlib.decompress(_pd_b85.b85decode(_pd_payload)), "
        "'<pydefender>', 'exec'))\n"
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def obfuscate_source(source: str, level: int = 2) -> str:
    """Obfuscate Python source code and return the protected source.

    Args:
        source: Python source code as a string.
        level: Protection level, ``1`` (light), ``2`` (standard) or
            ``3`` (heavy). Defaults to ``2``.

    Returns:
        The protected Python source code, functionally equivalent
        to the input.

    Raises:
        PyDefenderError: If the source cannot be parsed or the level
            is invalid.
    """
    if not isinstance(source, str):
        raise PyDefenderError("source must be a string containing Python code")
    if level not in LEVELS:
        valid = ", ".join(str(value) for value in sorted(LEVELS))
        raise PyDefenderError(
            f"invalid protection level {level!r} (choose from: {valid})"
        )
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError) as exc:
        raise PyDefenderError(f"could not parse source code: {exc}") from exc

    tree = _DocstringStripper().visit(tree)
    ast.fix_missing_locations(tree)

    if level >= 2:
        tree = _LocalRenamer().visit(tree)
        ast.fix_missing_locations(tree)

    code = ast.unparse(tree)

    if level == 3:
        return _wrap_heavy(code)

    version = _package_version()
    banner = (
        f"# Protected by PyDefender v{version} (level {level}: {LEVELS[level]})\n"
        f"# {GITHUB_URL}\n\n"
    )
    return banner + code + "\n"


def obfuscate_file(
    input_path: Union[str, os.PathLike],
    output_path: Optional[Union[str, os.PathLike]] = None,
    level: int = 2,
    in_place: bool = False,
) -> Path:
    """Obfuscate a Python source file and write the protected copy.

    Args:
        input_path: Path of the ``.py`` file to protect.
        output_path: Destination path. Defaults to
            ``<input_stem>_protected.py`` next to the input. If the path
            is an existing directory, the default file name is used
            inside it.
        level: Protection level (see :func:`obfuscate_source`).
        in_place: If ``True``, overwrite ``input_path`` instead of
            writing a copy (``output_path`` is ignored).

    Returns:
        The path of the protected file that was written.

    Raises:
        PyDefenderError: If the input is missing, unreadable or invalid.
    """
    input_path = Path(input_path)
    if not input_path.is_file():
        raise PyDefenderError(f"input file not found: {input_path}")
    try:
        source = input_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise PyDefenderError(f"could not read {input_path}: {exc}") from exc

    protected = obfuscate_source(source, level=level)

    shebang = ""
    if source.startswith("#!"):
        shebang = source.split("\n", 1)[0] + "\n"

    if in_place:
        destination = input_path
    elif output_path is None:
        destination = input_path.with_name(f"{input_path.stem}_protected.py")
    else:
        destination = Path(output_path)
        if destination.is_dir():
            destination = destination / f"{input_path.stem}_protected.py"

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(shebang + protected, encoding="utf-8")
    return destination


def _docstring_of(node: ast.AST) -> Optional[str]:
    """Return the docstring of a module/class/function node, if present."""
    body = getattr(node, "body", None)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        return body[0].value.value
    return None


def analyze_source(source: str) -> Dict[str, int]:
    """Analyze Python source and return a protection report.

    Raises:
        PyDefenderError: If the source cannot be parsed.
    """
    if not isinstance(source, str):
        raise PyDefenderError("source must be a string containing Python code")
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError) as exc:
        raise PyDefenderError(f"could not parse source code: {exc}") from exc

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
            if _docstring_of(node) is not None:
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
    """Analyze a Python source file and return a protection report.

    Raises:
        PyDefenderError: If the file is missing, unreadable or invalid.
    """
    file_path = Path(path)
    if not file_path.is_file():
        raise PyDefenderError(f"input file not found: {file_path}")
    try:
        source = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise PyDefenderError(f"could not read {file_path}: {exc}") from exc
    return analyze_source(source)
