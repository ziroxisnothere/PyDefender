"""Package fixture using relative imports (run with `python -m relative_imports.main`).

This package intentionally exercises:
- __init__.py with relative imports
- intra-package relative imports (from .core import ...)
- from . import sibling module access
- functions/classes shared across modules
"""

from .core import build_report, describe_pipeline
from .util import format_size, slugify

__all__ = ["build_report", "describe_pipeline", "format_size", "slugify"]
