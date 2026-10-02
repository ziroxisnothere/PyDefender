"""Fixture: PyInstaller-friendly program.

Design notes (mirrors the engine's PyInstaller guidance):
- static local import (helper_ops) so PyInstaller's analysis bundles it
- dynamic importlib usage of the standard library ("json") - dynamic
  imports are invisible to static analysis even in the ORIGINAL file,
  so frozen builds need `--hidden-import json`; the engine's
  result.dependencies output tells you exactly which modules to pass
- no reliance on __file__, cwd or external resources
"""

import importlib
from helper_ops import transform_batch


def main():
    serializer = importlib.import_module("json")
    records = [
        {"id": index, "square": index * index}
        for index in range(1, 6)
    ]
    transformed = transform_batch(records)
    print(serializer.dumps(transformed, sort_keys=True))
    print("done")


if __name__ == "__main__":
    main()
