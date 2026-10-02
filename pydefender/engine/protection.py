"""Integrity protection for the PyDefender engine.

Two complementary mechanisms are provided:

1. **Engine-side validation** (:func:`compute_checksum`): every run can
   return the SHA-256 checksum of the protected output, and the engine
   verifies written files byte-for-byte after writing.

2. **Runtime integrity guard** (:func:`build_integrity_block`): for
   level-3 outputs the loader stub can embed a checksum of its payload
   and verify it before executing. A modified payload raises a clear,
   named exception instead of running tampered code.

Design guarantees:

* The guard is **non-destructive** - it only raises; it never deletes
  or modifies files, registry entries, or anything else.
* The guard is **self-contained** - protected files never import
  PyDefender, so they keep working offline and inside PyInstaller,
  Nuitka, cx_Freeze and py2exe bundles.
* The guard detects *unexpected modification*. It is a tamper-evident
  seal, not cryptographic attestation: a sufficiently skilled attacker
  who controls the runtime environment can always patch a check. This
  is documented honestly rather than overstated.
"""

from __future__ import annotations

import hashlib
from typing import List, Optional

__all__ = ["compute_checksum", "build_integrity_block", "RUNTIME_GUARD_EXCEPTION_NAME"]

#: Name of the exception class embedded into protected files.
RUNTIME_GUARD_EXCEPTION_NAME = "PyDefenderIntegrityError"


def compute_checksum(text: str) -> str:
    """Return the SHA-256 hex digest of ``text`` (UTF-8 encoded)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_integrity_block(payload: str) -> str:
    """Build the runtime integrity check for a level-3 loader stub.

    Args:
        payload: The exact base85 payload string embedded in the stub.
            The checksum is computed over this string, so any edit to
            the embedded data - including edits that would still decode
            - is detected before the payload is decompressed.

    Returns:
        Python source code lines to insert into the loader stub.
    """
    expected = hashlib.sha256(payload.encode("ascii")).hexdigest()
    lines: List[str] = [
        "import hashlib as _pd_hashlib",
        "",
        f"class {RUNTIME_GUARD_EXCEPTION_NAME}(RuntimeError):",
        '    """Raised when the protected payload of this file was modified."""',
        "",
        "",
    ]
    lines.extend(
        [
            "def _pd_verify_integrity():",
            f'    _pd_expected = "{expected}"',
            '    _pd_actual = _pd_hashlib.sha256(_pd_payload.encode("ascii")).hexdigest()',
            "    if _pd_actual != _pd_expected:",
            "        raise PyDefenderIntegrityError(",
            '            "PyDefender integrity check failed: the protected payload "',
            '            "of this file was modified (expected sha256 " + _pd_expected[:16] ',
            '            + "..., got " + _pd_actual[:16] + "...). Refusing to execute."',
            "        )",
            "",
            "",
            "_pd_verify_integrity()",
            "",
        ]
    )
    return "\n".join(lines)


def verify_written_output(path, expected_content: str) -> Optional[str]:
    """Read back a written file and compare it with the generated content.

    Returns ``None`` on success or a human-readable problem description.
    Never modifies or deletes the file - verification is read-only.
    """
    try:
        actual = path.read_text(encoding="utf-8")
    except OSError as exc:
        return f"could not re-read written output: {exc}"
    if actual != expected_content:
        return "written output differs from generated content (disk or encoding issue)"
    return None
