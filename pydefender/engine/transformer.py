"""AST transformation stages of the PyDefender engine.

Each class in this module is an independent, individually testable
transformation stage. All stages operate exclusively on the standard
library AST - there is no regex-based source rewriting anywhere, so
valid Python syntax is never corrupted.

Every transformation is *behavior-preserving by construction* and
conservative by design: when a transformation cannot be applied safely
to a construct, the construct is skipped rather than transformed.

Available stages
----------------

- :class:`MetadataReducer` - removes docstrings (module/class/function).
- :class:`NameProtector` - scope-safe renaming of function-local
  variables; parameters, imports, ``global``/``nonlocal`` names and all
  nested-scope references are never touched.
- :class:`ConstantProtector` - rewrites large integer literals into
  equivalent arithmetic expressions (exact integer math only).
- :class:`StringProtector` - rewrites long string literals into
  self-contained decode expressions that evaluate to the identical
  string. Short strings and f-string fragments are skipped.
- :class:`ControlFlowProtector` - inserts compile-time-false opaque
  predicates carrying decoy statements. CPython's peephole optimizer
  removes these branches at compile time, so runtime behavior and
  bytecode size are unaffected.
"""

from __future__ import annotations

import ast
from typing import Dict, Iterator, List, Optional, Set, Tuple

from pydefender.engine.exceptions import TransformationError
from pydefender.engine.parser import is_docstring

__all__ = [
    "TransformContext",
    "MetadataReducer",
    "NameProtector",
    "ConstantProtector",
    "StringProtector",
    "ControlFlowProtector",
]

#: Minimum absolute integer value considered for constant protection.
CONSTANT_THRESHOLD = 1000

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


class TransformContext:
    """Per-run context shared by transformation stages.

    Carries the deterministic RNG, a fresh-name counter and the warning
    collector. The RNG is seeded from the configuration, so identical
    input plus identical configuration produce identical output.
    """

    def __init__(self, rng, config, filename: str, warnings: List[str]) -> None:
        self.rng = rng
        self.config = config
        self.filename = filename
        self.warnings = warnings
        self._counter = 0

    def next_id(self) -> int:
        self._counter += 1
        return self._counter


def _string_binding_name(node: ast.AST) -> Optional[str]:
    """Return the identifier bound by a string-binding node, if any."""
    name = getattr(node, "name", None) or getattr(node, "rest", None)
    return name if isinstance(name, str) else None


def _own_scope_children(node: ast.AST):
    """Yield the direct children that belong to ``node``'s own scope.

    Decorators, base classes, keyword arguments, return annotations and
    parameter defaults are evaluated in the *enclosing* scope, so they
    are excluded here.
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


def _import_binding_name(import_node, alias: ast.alias) -> str:
    """Return the name an import statement binds into the current scope."""
    if isinstance(import_node, ast.Import):
        return alias.asname or alias.name.split(".")[0]
    return alias.asname or alias.name


def _collect_scope_data(node: ast.AST) -> Tuple[Set[str], Set[str], Set[str]]:
    """Collect ``(bindings, import_boundings, declared)`` for one scope."""
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

    Conservative by design: any name appearing in a nested function,
    lambda or class body excludes that name from renaming in the
    enclosing scope, which keeps closures, ``nonlocal``/``global``
    access and class bodies reading enclosing locals fully working.
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


def _param_names(node: ast.AST) -> Set[str]:
    """Collect the parameter names (and PEP 695 type parameters) of a
    function node. Parameters are never renamed, so their names must be
    excluded from rename targets even when they are reassigned in the
    function body (e.g. ``start -= 1`` creates a Store-context Name)."""
    names: Set[str] = set()
    arguments = getattr(node, "args", None)
    if arguments is not None:
        for arg in (
            list(getattr(arguments, "posonlyargs", []))
            + list(arguments.args)
            + list(getattr(arguments, "kwonlyargs", []))
        ):
            names.add(arg.arg)
        if arguments.vararg is not None:
            names.add(arguments.vararg.arg)
        if arguments.kwarg is not None:
            names.add(arguments.kwarg.arg)
    for type_param in getattr(node, "type_params", None) or []:
        type_param_name = getattr(type_param, "name", None)
        if isinstance(type_param_name, str):
            names.add(type_param_name)
    return names


def _rename_string_binding(current: ast.AST, new_name: str) -> None:
    """Rename the string attribute of a match/except binding node."""
    if getattr(current, "name", None) is not None:
        current.name = new_name
    elif getattr(current, "rest", None) is not None:
        current.rest = new_name


def _apply_renames(node: ast.AST, mapping: Dict[str, str]) -> None:
    """Rename ``Name`` nodes inside ``node``'s own scope only.

    Match-statement capture patterns (``case ... as name``), mapping
    rest patterns (``case {**rest}:``) and exception handlers
    (``except ... as error:``) bind through plain string attributes
    rather than ``Name`` nodes, so those attributes are renamed here as
    well - keeping bindings and references consistent.
    """
    for child in _own_scope_children(node):
        stack = [child]
        while stack:
            current = stack.pop()
            if isinstance(current, _SCOPE_NODES):
                continue
            if isinstance(current, ast.Name) and current.id in mapping:
                current.id = mapping[current.id]
            elif isinstance(current, _STRING_BINDING_NODES):
                bound = _string_binding_name(current)
                if bound in mapping:
                    _rename_string_binding(current, mapping[bound])
            stack.extend(ast.iter_child_nodes(current))


def _walk_with_parents(tree: ast.AST) -> Iterator[Tuple[ast.AST, ast.AST]]:
    """Yield ``(parent, node)`` pairs for every node in the tree."""
    stack: List[Tuple[ast.AST, ast.AST]] = [(tree, tree)]
    while stack:
        parent, node = stack.pop()
        yield parent, node
        for child in ast.iter_child_nodes(node):
            stack.append((node, child))


def _replace_child(parent: ast.AST, old: ast.AST, new: ast.AST) -> bool:
    """Replace the child node ``old`` of ``parent`` with ``new``."""
    for field_name, value in ast.iter_fields(parent):
        if value is old:
            setattr(parent, field_name, new)
            return True
        if isinstance(value, list):
            for index, item in enumerate(value):
                if item is old:
                    value[index] = new
                    return True
    return False


class MetadataReducer:
    """Metadata reduction: strip module, class and function docstrings."""

    name = "metadata-reduction"
    description = "remove docstrings and embedded metadata"

    def apply(self, tree: ast.Module, ctx: TransformContext) -> str:
        stripper = _DocstringStripper()
        stripper.visit(tree)
        return f"{stripper.removed} docstring(s) removed"


class _DocstringStripper(ast.NodeTransformer):
    """NodeTransformer that removes docstrings from an AST."""

    def __init__(self) -> None:
        self.removed = 0

    def _strip_docstring(self, node: ast.AST) -> ast.AST:
        body = getattr(node, "body", None)
        if body and is_docstring(body[0]):
            self.removed += 1
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


class NameProtector:
    """Name protection: conservative, scope-safe local-variable renaming.

    Safety rules (never violated):

    * parameters are never renamed (keyword call sites stay compatible)
    * names bound by ``import`` statements are never renamed
    * ``global``/``nonlocal`` declared names are never renamed
    * names referenced in nested scopes are never renamed
    * module-level and class-level names are never renamed
    * attribute names, dict keys and string values are never touched
    * dunder names are never renamed
    """

    name = "name-protection"
    description = "rename function-local variables"

    def apply(self, tree: ast.Module, ctx: TransformContext) -> str:
        renamer = _LocalRenamer()
        renamer.visit(tree)
        return f"{renamer.renamed} local variable(s) renamed"


class _LocalRenamer(ast.NodeTransformer):
    """NodeTransformer that renames function-local variables."""

    def __init__(self) -> None:
        self.renamed = 0

    def _fresh_name(self, counter: int) -> str:
        return f"_0x{counter:04x}"

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
        forbidden = imports | declared | _param_names(node)
        targets = bindings - forbidden - _nested_references(node)
        targets = {
            name
            for name in targets
            if not (name.startswith("__") and name.endswith("__"))
        }
        if not targets:
            return
        mapping = {
            name: self._fresh_name(self.renamed + offset + 1)
            for offset, name in enumerate(sorted(targets))
        }
        self.renamed += len(mapping)
        _apply_renames(node, mapping)


class ConstantProtector:
    """Constant protection: rewrite large integer literals.

    An integer literal ``n`` (``abs(n) >= CONSTANT_THRESHOLD``) becomes
    an equivalent addition of two deterministically chosen terms, e.g.
    ``1000000`` -> ``(654321 + 345679)``. Only exact integer arithmetic
    is used, so the evaluated value is bit-for-bit identical. Small
    integers, booleans, floats and complex numbers are never touched.
    """

    name = "constant-protection"
    description = "transform large integer literals"

    def apply(self, tree: ast.Module, ctx: TransformContext) -> str:
        count = 0
        for parent, node in list(_walk_with_parents(tree)):
            if not isinstance(node, ast.Constant) or type(node.value) is not int:
                continue
            if abs(node.value) < CONSTANT_THRESHOLD:
                continue
            replacement = self._build_expression(node.value, ctx)
            if replacement is None:
                continue
            if not _replace_child(parent, node, replacement):
                continue
            ast.copy_location(replacement, node)
            count += 1
        return f"{count} constant(s) protected"

    def _build_expression(self, value: int, ctx: TransformContext) -> Optional[ast.AST]:
        try:
            magnitude = abs(value)
            low = magnitude // 4 + 1
            high = max(low + 1, (3 * magnitude) // 4)
            first = ctx.rng.randrange(low, high)
            second = magnitude - first
            expression: ast.AST = ast.BinOp(
                left=ast.Constant(value=first),
                op=ast.Add(),
                right=ast.Constant(value=second),
            )
            if value < 0:
                expression = ast.UnaryOp(op=ast.USub(), operand=expression)
            return expression
        except Exception as exc:  # pragma: no cover - defensive
            ctx.warnings.append(f"constant protection skipped for {value}: {exc}")
            return None


class StringProtector:
    """String protection: rewrite long string literals.

    A string literal of at least ``min_string_length`` characters becomes
    a self-contained decode expression::

        bytes((_pdb ^ 0x1f for _pdb in b"...")).decode("utf-8")

    The expression evaluates to the byte-identical original string at
    runtime, requires no imports and has its own generator scope, so it
    cannot collide with program names. Skipped for safety: short strings,
    f-string fragments, and empty strings.
    """

    name = "string-protection"
    description = "encode long string literals"

    def apply(self, tree: ast.Module, ctx: TransformContext) -> str:
        count = 0
        skip_parents = (ast.JoinedStr, ast.FormattedValue)
        for parent, node in list(_walk_with_parents(tree)):
            if isinstance(parent, skip_parents):
                continue
            if not isinstance(node, ast.Constant) or type(node.value) is not str:
                continue
            if len(node.value) < ctx.config.min_string_length:
                continue
            replacement = self._build_expression(node.value, ctx)
            if replacement is None:
                continue
            if not _replace_child(parent, node, replacement):
                continue
            ast.copy_location(replacement, node)
            count += 1
        return f"{count} string(s) protected"

    def _build_expression(self, value: str, ctx: TransformContext) -> Optional[ast.AST]:
        try:
            key = ctx.rng.randrange(1, 256)
            payload = bytes(byte ^ key for byte in value.encode("utf-8"))
            expression_source = (
                f'bytes((_pdb ^ {key} for _pdb in {payload!r})).decode("utf-8")'
            )
            return ast.parse(expression_source, mode="eval").body
        except Exception as exc:  # pragma: no cover - defensive
            ctx.warnings.append(f"string protection skipped ({len(value)} chars): {exc}")
            return None


class ControlFlowProtector:
    """Control-flow protection: compile-time-false opaque predicates.

    Inserts decoy branches guarded by constant arithmetic predicates that
    evaluate to ``0`` (false), e.g. ``if (37 * 53 - 1961):``. CPython's
    peephole optimizer folds these at compile time, so the protected
    program's bytecode and runtime behavior are unchanged, while the
    source gains misleading structure.

    Guards applied for safety:

    * only function/async-function bodies are seeded (never module level,
      which would risk moving ``__future__`` imports out of position)
    * insertion happens after a docstring if one is present, so
      ``__doc__`` semantics are preserved when metadata reduction is off
    * decoy statements only assign fresh internal names
    """

    name = "control-flow-protection"
    description = "insert opaque dead branches"

    def __init__(self, density: float = 0.4) -> None:
        self.density = density

    def apply(self, tree: ast.Module, ctx: TransformContext) -> str:
        count = 0
        targets = [
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        for function_node in targets:
            body = function_node.body
            offset = 1 if body and is_docstring(body[0]) else 0
            if len(body) - offset < 2:
                continue
            if ctx.rng.random() >= self.density:
                continue
            dead_branch = self._build_dead_branch(ctx)
            ast.copy_location(dead_branch, body[offset])
            ast.fix_missing_locations(dead_branch)
            function_node.body = body[:offset] + [dead_branch] + body[offset:]
            count += 1
        return f"{count} opaque branch(es) inserted"

    def _build_dead_branch(self, ctx: TransformContext) -> ast.If:
        factor_a = ctx.rng.randrange(17, 96)
        factor_b = ctx.rng.randrange(17, 96)
        product = factor_a * factor_b
        test = ast.BinOp(
            left=ast.BinOp(
                left=ast.Constant(value=factor_a),
                op=ast.Mult(),
                right=ast.Constant(value=factor_b),
            ),
            op=ast.Sub(),
            right=ast.Constant(value=product),
        )
        decoy_statements: List[ast.stmt] = []
        for _ in range(ctx.rng.randrange(1, 4)):
            ghost_name = f"_pd{ctx.next_id():03d}"
            decoy_statements.append(
                ast.Assign(
                    targets=[ast.Name(id=ghost_name, ctx=ast.Store())],
                    value=ast.BinOp(
                        left=ast.Constant(value=ctx.rng.randrange(16, 4096)),
                        op=ast.Add(),
                        right=ast.Constant(value=ctx.rng.randrange(16, 4096)),
                    ),
                )
            )
        return ast.If(test=test, body=decoy_statements, orelse=[])


def guarded_stage(stage, tree: ast.Module, ctx: TransformContext) -> str:
    """Run one transformation stage, converting unexpected failures into
    a :class:`TransformationError` with full context.

    The engine fails safely: the original AST/source is left untouched
    (the caller keeps the pristine source) and nothing is written.
    """
    try:
        return stage.apply(tree, ctx)  # type: ignore[arg-type]
    except TransformationError:
        raise
    except Exception as exc:
        raise TransformationError(
            f"transformation stage {stage.name!r} failed",
            file=ctx.filename,
            stage=stage.name,
            reason=f"{type(exc).__name__}: {exc}",
        ) from exc
