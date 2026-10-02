"""Code generation and output packaging for the PyDefender engine.

The compiler turns a transformed AST back into source and packages it
into its final, self-contained form. Protected files never import
PyDefender at runtime - they run on a plain Python interpreter with no
engine installed.
"""

from __future__ import annotations

import ast
import base64
import textwrap
import zlib
from typing import Optional

from pydefender.engine.config import GITHUB_URL, ObfuscationConfig
from pydefender.engine.exceptions import ValidationError
from pydefender.engine.parser import extract_shebang
from pydefender.engine.protection import build_integrity_block

__all__ = [
    "tree_to_source",
    "compile_check",
    "build_heavy_wrapper",
    "apply_banner",
    "finalize_output",
]

_B85_CHUNK = 72


def tree_to_source(tree: ast.Module, filename: str = "<source>") -> str:
    """Unparse an AST back into Python source code."""
    try:
        return ast.unparse(tree)
    except Exception as exc:
        raise ValidationError(
            "could not generate source code from transformed AST",
            file=filename,
            stage="code-generation",
            reason=f"{type(exc).__name__}: {exc}",
        ) from exc


def compile_check(source: str, filename: str = "<source>", stage: str = "integrity-validation") -> None:
    """Compile ``source`` to bytecode without executing it.

    This is the engine's main safety net: if any transformation ever
    produced invalid code, the run fails here - before anything is
    written to disk - and the original file remains untouched.

    Raises:
        ValidationError: If the source does not compile.
    """
    try:
        compile(source, filename, "exec")
    except (SyntaxError, ValueError, TypeError) as exc:
        raise ValidationError(
            "generated protected code failed the compile check",
            file=filename,
            stage=stage,
            reason=str(exc),
        ) from exc


def build_heavy_wrapper(code: str, version: str, integrity: bool = False) -> str:
    """Wrap ``code`` into a self-contained base85/zlib loader stub.

    The stub imports only standard library modules (``base64``, ``zlib``
    and optionally ``hashlib``), defines everything locally with
    ``_pd_``-prefixed names and therefore stays compatible with frozen
    environments such as PyInstaller, Nuitka, cx_Freeze and py2exe.

    When ``integrity`` is ``True`` the stub embeds a checksum of its own
    payload and refuses to execute modified payloads (non-destructively).
    """
    payload = base64.b85encode(zlib.compress(code.encode("utf-8"), 9)).decode("ascii")
    chunks = textwrap.wrap(payload, _B85_CHUNK) or [""]
    payload_lines = "\n".join(f'    "{chunk}"' for chunk in chunks)
    integrity_block = build_integrity_block(payload) if integrity else None
    parts = [
        f"# Protected by PyDefender v{version} (level 3: heavy)",
        f"# {GITHUB_URL}",
        "# This file contains protected source code. Do not edit manually.",
        "import base64 as _pd_b85, zlib as _pd_zlib",
        "",
        "_pd_payload = (",
        payload_lines,
        ")",
    ]
    if integrity_block:
        parts.append(integrity_block)
    parts.append(
        "exec(compile(_pd_zlib.decompress(_pd_b85.b85decode(_pd_payload)), "
        "'<pydefender>', 'exec'))"
    )
    return "\n".join(parts) + "\n"


def apply_banner(code: str, level: int, level_name: str, version: str) -> str:
    """Prepend the provenance banner to light/standard protected code."""
    banner = (
        f"# Protected by PyDefender v{version} (level {level}: {level_name})\n"
        f"# {GITHUB_URL}\n\n"
    )
    return banner + code + "\n"


def finalize_output(
    protected_code: str,
    original_source: str,
    config: ObfuscationConfig,
    level_name: str,
    version: str,
) -> str:
    """Assemble the final file content for all levels.

    Handles the heavy wrapper (when compression is active), the
    provenance banner (levels 1-2) and optional shebang preservation.
    """
    if config.compression_active:
        output = build_heavy_wrapper(protected_code, version, integrity=config.integrity)
    else:
        output = apply_banner(protected_code, config.level, level_name, version)
    if config.keep_shebang:
        output = extract_shebang(original_source) + output
    return output
