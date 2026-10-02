"""Basic usage of the PyDefender standalone engine.

Run:
    python examples/basic_usage.py
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from pydefender.engine import ObfuscationConfig, ObfuscationEngine

SAMPLE = '''\
"""Internal pricing logic - do not distribute readable."""

DISCOUNT_TABLE = {
    "bronze": 5,
    "silver": 10,
    "gold": 20,
}


def final_price(base_price, tier):
    discount_percent = DISCOUNT_TABLE.get(tier, 0)
    adjusted = base_price * (100 - discount_percent) / 100
    return round(adjusted, 2)


if __name__ == "__main__":
    for tier in ("bronze", "silver", "gold"):
        print(tier, final_price(200, tier))
'''


def main() -> None:
    # 1. In-memory protection: source string -> protected source string.
    engine = ObfuscationEngine(
        ObfuscationConfig(level=3, integrity=True, reproducible=True, seed=0)
    )
    result = engine.obfuscate_source(SAMPLE, filename="pricing.py")
    print(result)
    print()

    # The protected code runs identically to the original.
    namespace: dict = {}
    exec(compile(result.code, "<protected>", "exec"), namespace)
    print("protected output:", namespace["final_price"](200, "gold"))
    print()

    # 2. File protection: input path -> output path (same engine API).
    with tempfile.TemporaryDirectory() as tmp:
        source_file = Path(tmp) / "pricing.py"
        source_file.write_text(SAMPLE, encoding="utf-8")
        file_result = engine.obfuscate(
            source_file,
            Path(tmp) / "dist" / "pricing.py",
        )
        print(f"written: {file_result.output_path}")
        print(f"checksum: sha256:{file_result.integrity_checksum[:24]}...")

        # 3. Dry run: full pipeline, nothing written.
        dry = engine.obfuscate(source_file, Path(tmp) / "dist2" / "x.py")
        print("dry run would write:", dry.output_path)


if __name__ == "__main__":
    main()
