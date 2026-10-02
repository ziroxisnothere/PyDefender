# PyDefender

**Python source-code obfuscator and protection tool**

[![PyPI - Version](https://img.shields.io/pypi/v/PyDefender)](https://pypi.org/project/PyDefender/)
[![Python Versions](https://img.shields.io/pypi/pyversions/PyDefender)](https://pypi.org/project/PyDefender/)
[![Tests](https://github.com/ziroxisnothere/PyDefender/actions/workflows/test.yml/badge.svg)](https://github.com/ziroxisnothere/PyDefender/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/ziroxisnothere/PyDefender/blob/main/LICENSE)

PyDefender turns readable Python source code into functionally identical, hard-to-read code. Its **standalone engine** is built entirely on the Python standard library (`ast`, `zlib`, `base64`, `hashlib`), ships with zero runtime dependencies, and protects your intellectual property before you ship scripts, tools or plugins to customers.

Every transformation is **semantic-preserving**: protected files run exactly like the originals, on every platform a normal Python file would run on.

## PyDefender Engine

The core of the project is a standalone, reusable engine that is independent from the CLI, GUI, PyPI wrapper and GitHub tooling. It works completely offline, never sends your source code anywhere, and contains no credentials or network code of any kind.

The engine implements a modular protection pipeline; every stage is independently testable and can be enabled or disabled through configuration:

```text
Input
 v
Validation
 v
Parsing (AST + dependency detection)
 v
Metadata Reduction       (docstring removal)
 v
Name Protection          (scope-safe identifier renaming)
 v
Constant Protection      (integer literal transforms)
 v
String Protection        (string literal encoding)
 v
Control-Flow Protection  (compile-time-false opaque branches)
 v
Code Generation          (unparse + compile smoke test)
 v
Packaging                (banner / heavy loader wrapper)
 v
Integrity Validation     (final compile check, checksum)
 v
Output
```

The CLI is a thin wrapper around the engine - `pydefender obfuscate input.py -o output.py` calls exactly the same public API that Python applications use. There is no second implementation of the protection logic.

## Installation

Install from PyPI:

```bash
pip install PyDefender
```

Or install from source:

```bash
git clone https://github.com/ziroxisnothere/PyDefender.git
cd PyDefender
pip install .
```

## Python API

### The engine

```python
from pydefender.engine import ObfuscationEngine, ObfuscationConfig

config = ObfuscationConfig(
    rename=True,
    strings=True,
    constants=True,
    control_flow=True,
)

engine = ObfuscationEngine(config)

result = engine.obfuscate(
    "main.py",
    "protected/main.py",
)

print(result)
```

The same engine protects source held in memory:

```python
result = engine.obfuscate_source(source_code)
protected_text = result.code
```

`engine.obfuscate()` accepts a single `.py` file or a whole directory tree (mirrored into the output directory, skipping `__pycache__`, virtual environments and other junk). A dry run performs the full pipeline without writing anything:

```python
result = engine.obfuscate("main.py", "dist/main.py", overwrite=True)  # writes
result = ObfuscationEngine(ObfuscationConfig(dry_run=True)) \
    .obfuscate("main.py")                                             # no writes
```

### ObfuscationConfig

| Option | Default | Meaning |
|---|---|---|
| `level` | `3` | Protection preset: `1` light (metadata), `2` standard (+ rename, constants, strings), `3` heavy (+ control flow, dead code, loader wrapper). |
| `rename` | follow level | Scope-safe renaming of function-local variables. |
| `strings` | follow level | Encoding of long string literals. |
| `constants` | follow level | Arithmetic rewrites of large integer literals. |
| `control_flow` | follow level | Opaque (compile-time-false) branches. |
| `dead_code` | follow level | Decoy statements inside those branches. |
| `metadata` | follow level | Docstring removal. |
| `compress` | follow level | Force the level-3 loader wrapper on/off. |
| `integrity` | `False` | Embed a runtime tamper check (level 3) and report the output SHA-256. |
| `reproducible` | `True` | Identical input + configuration produce byte-identical output. |
| `seed` | `0` | Seed for deterministic transformations. |
| `dry_run` | `False` | Run everything, write nothing. |
| `validate_syntax` | `True` | Compile-check every generated output. |
| `target_python` | `None` | Reject syntax newer than the target version, e.g. `"3.9"`. |
| `min_string_length` | `16` | Minimum string length considered by the string stage. |

Explicit stage flags override the level baseline: `True` adds a stage that is not part of the preset, `False` removes one that is. Example: `ObfuscationConfig(level=1, rename=True)` is "light + renaming".

### ObfuscationResult

Every run returns a result object with the protected `code`, input/output paths, per-stage reports and timings, detected dependencies, warnings, an optional integrity checksum and a human-readable `str(result)` summary. Nothing is ever written before the full pipeline - including a compile check - has succeeded, and PyDefender never deletes or modifies your original files.

## CLI

```text
pydefender --help
pydefender --version
```

### Obfuscate a single file

```bash
# Maximum protection (level 3), writes app_protected.py next to the input
pydefender obfuscate app.py --level 3

# Choose output path and level
pydefender obfuscate app.py -o dist/app.py --level 2

# Overwrite the original file in place
pydefender obfuscate app.py --in-place --level 3

# Full pipeline, report, but do not write anything
pydefender obfuscate app.py --dry-run --integrity
```

### Obfuscate a whole directory

```bash
# Mirrors src/ into dist/ (skips __pycache__, venvs, caches, ...)
pydefender obfuscate src/ -o dist/ --level 3

# Protect every .py file in place
pydefender obfuscate src/ --in-place --level 2
```

### Stage-level switches

```bash
pydefender obfuscate app.py --no-rename --no-strings   # keep identifiers, short code
pydefender obfuscate app.py --no-metadata               # keep docstrings
pydefender obfuscate app.py --seed 42                   # different deterministic output
```

### Analyze a file before protecting it

```bash
pydefender check app.py
```

Example report:

```text
PyDefender protection report: app.py
  lines              : 42
  functions          : 3
  classes            : 1
  imports            : 2
  comments           : 7
  docstrings         : 2 of 5 scopes
  recommended level  : 3 (heavy)
```

### Protection levels

| Level | Name       | What it does                                                                                                   |
|-------|------------|----------------------------------------------------------------------------------------------------------------|
| `1`   | light      | Strips all comments and docstrings while keeping the code readable in structure.                                |
| `2`   | standard   | Level 1 + renames function-local variables, transforms large integer literals and encodes long string literals. |
| `3`   | heavy      | Level 1 + compresses the entire source into a zlib/base85 payload executed by a minimal loader stub. Maximum protection for distribution. |

## PyInstaller compatibility

Protected files are plain Python source and work with frozen-application toolchains. The engine additionally helps where frozen builds need metadata:

- **Dependency detection** - every result reports the top-level modules your program imports. Use them as `--hidden-import` candidates.
- **No `__file__` tricks** - protected files never read their own path, so they behave identically inside `--onefile` and `--onedir` bundles.
- **Standalone loader** - the level-3 wrapper imports only `base64`, `zlib` (and `hashlib` when integrity is enabled). The standard library is always available in frozen applications, so level-3 protected *scripts* freeze fine.
- **Local modules** - PyInstaller's static analysis cannot see imports hidden inside a level-3 payload. When your project has *local* modules, either (a) protect at level 1 or 2 so imports stay visible, or (b) keep a thin unobfuscated launcher that statically imports your local modules and protect the heavy logic only. Never assume PyInstaller is installed - the engine never requires or invokes it.

Recommended workflow:

```bash
pydefender obfuscate src/ -o protected/ --level 2
pyinstaller --onefile protected/main.py        # --onedir works the same way
```

The engine is also compatible with Nuitka, cx_Freeze, py2exe, plain wheels and virtual environments: it produces standard Python source and has no dependency on any packager.

## Reverse-engineering resistance

PyDefender applies legitimate software-protection techniques: identifier renaming, metadata reduction, string and constant transformation, structural wrapping and integrity validation. All transformations are real, testable and behavior-preserving - the test suite runs every fixture program before and after protection and compares the behavior.

**Honest security statement:** do not expect the output to be impossible to crack. Python is inherently difficult to protect completely, because Python applications ultimately execute in an environment controlled by the user: bytecode can be inspected, runtime hooks can be installed and memory can be dumped. PyDefender raises the cost of understanding your code substantially and deters casual copying; it cannot make theft impossible.

## Integrity protection

With `integrity=True`, level-3 protected files embed a SHA-256 checksum of their payload and verify it before executing. If a protected file is modified unexpectedly, it raises a clear, named exception (`PyDefenderIntegrityError`) instead of running tampered code. The guard is non-destructive - it only reports - and user files are never deleted. The checksum of every protected file is also returned in the result (`result.integrity_checksum`) so you can verify outputs externally.

## Supported Python versions

| Python      | Supported |
|-------------|-----------|
| 3.9         | Yes       |
| 3.10        | Yes       |
| 3.11        | Yes       |
| 3.12        | Yes       |
| 3.13        | Yes       |

PyDefender itself has **no third-party dependencies**. Protected programs handle the full modern Python surface: packages, `__init__.py` files, relative and absolute imports, decorators, async/await, generators, context managers, type annotations, dataclasses, match/case, f-strings, comprehensions, lambdas and nested functions/classes. The test suite executes every construct before and after protection and compares behavior.

## Important notes

- Obfuscation is a deterrent, not cryptographic security (see the security statement above).
- Always keep your original, unprotected sources. PyDefender never needs them back, but you will.
- Code that introspects itself via `locals()` string keys (e.g. `locals()["my_var"]`) should be protected at level 1, because renamed locals will no longer match those string keys.
- Protected files require Python 3.9+ (the same versions PyDefender supports).

## GitHub

- **Repository:** <https://github.com/ziroxisnothere/PyDefender>
- **Issue tracker:** <https://github.com/ziroxisnothere/PyDefender/issues>
- **Releases:** <https://github.com/ziroxisnothere/PyDefender/releases>

### Continuous integration & release flow

- `.github/workflows/test.yml` runs the full test suite (including behavior-preservation fixtures) on Python 3.9 - 3.13 for every push and pull request, plus a PyInstaller `--onefile` smoke test.
- `.github/workflows/publish.yml` builds, validates and publishes the package to PyPI automatically whenever a GitHub Release is published, using PyPI Trusted Publishing (OIDC) - no API tokens or passwords are stored anywhere.

### Contributing

Bug reports and pull requests are welcome - see the issue and pull request templates. Run the tests locally with:

```bash
pip install pytest
python -m pytest tests/ -v
```

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
