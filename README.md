# PyDefender

**Python source-code obfuscator and protection tool**

[![PyPI - Version](https://img.shields.io/pypi/v/PyDefender)](https://pypi.org/project/PyDefender/)
[![Python Versions](https://img.shields.io/pypi/pyversions/PyDefender)](https://pypi.org/project/PyDefender/)
[![Tests](https://github.com/ziroxisnothere/PyDefender/actions/workflows/test.yml/badge.svg)](https://github.com/ziroxisnothere/PyDefender/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/ziroxisnothere/PyDefender/blob/main/LICENSE)

PyDefender turns readable Python source code into functionally identical, hard-to-read code. It is built entirely on the Python standard library (`ast`, `zlib`, `base64`), ships with zero runtime dependencies, and protects your intellectual property before you ship scripts, tools or plugins to customers.

Every transformation is **semantic-preserving**: protected files run exactly like the originals, on every platform a normal Python file would run on.

## Features

- **Three protection levels** — from light comment/docstring stripping to full source compression into a base85/zlib loader stub (see the table below).
- **Scope-safe local variable renaming** — closures, `nonlocal`, `global`, class bodies and comprehensions are analyzed with the Python `ast` module, so protected code behaves identically.
- **Parameter safety** — function parameters are never renamed, so keyword-argument call sites keep working.
- **Stable module API** — imports and module-level names are left untouched, so protected modules can still be imported by other code.
- **Directory mode** — obfuscate a whole project tree with mirrored output structure.
- **CLI + Python API** — use it from the terminal or embed it in your own build scripts.
- **Zero dependencies** — pure standard library, Python 3.9 – 3.13, cross-platform.
- **Deterministic output** — the same input always produces the same protected file, which keeps builds reproducible.

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

## CLI usage

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

# Overwrite an existing output file without failing
pydefender obfuscate app.py -o dist/app.py --level 3 --force
```

### Obfuscate a whole directory

```bash
# Mirrors src/ into dist/ (skips __pycache__, venvs, caches, ...)
pydefender obfuscate src/ -o dist/ --level 3

# Protect every .py file in place
pydefender obfuscate src/ --in-place --level 2
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
| `2`   | standard   | Level 1 + renames function-local variables to opaque names using scope-safe AST analysis.                       |
| `3`   | heavy      | Level 1 + compresses the entire source into a zlib/base85 payload executed by a minimal loader stub. Maximum protection for distribution. |

## Python API

```python
from pydefender import obfuscate_source, obfuscate_file, analyze_source

# Protect a string of source code (returns protected source)
protected = obfuscate_source(source_code, level=3)

# Protect a file (returns the output path)
output_path = obfuscate_file("app.py", "dist/app.py", level=3)

# Inspect a file before protecting it
report = analyze_source(source_code)
print(report["functions"], report["recommended_level"])
```

## How it works

PyDefender parses your source with the built-in `ast` module and applies semantic-preserving transformations. Comments and docstrings are removed at every level. At level 2, a scope-aware renamer walks each function scope, collects every local binding (assignments, loop targets, `with`/`except` targets, walrus operators, imports) and renames only names that are provably safe to rename — closures, `nonlocal`/`global` names, nested-scope references, parameters and module-level names are always excluded. At level 3, the resulting source is serialized, zlib-compressed and base85-encoded into a tiny self-contained loader stub, so no readable source remains in the file.

## Supported Python versions

| Python      | Supported |
|-------------|-----------|
| 3.9         | ✅        |
| 3.10        | ✅        |
| 3.11        | ✅        |
| 3.12        | ✅        |
| 3.13        | ✅        |

PyDefender itself has **no third-party dependencies** — a plain `pip install PyDefender` is all you need. Continuous integration tests every supported version on every push.

## Important notes

- Obfuscation is a deterrent, not cryptographic security. A determined attacker with enough time can always reconstruct logic from bytecode; PyDefender raises the cost of doing so substantially.
- Always keep your original, unprotected sources. PyDefender never needs them back, but you will.
- Code that introspects itself via `locals()` string keys (e.g. `locals()["my_var"]`) should be protected at level 1 or 3, or left out of renaming, because renamed locals will no longer match those string keys.
- Protected files require Python 3.9+ (the same versions PyDefender supports).

## GitHub

- **Repository:** <https://github.com/ziroxisnothere/PyDefender>
- **Issue tracker:** <https://github.com/ziroxisnothere/PyDefender/issues>
- **Releases:** <https://github.com/ziroxisnothere/PyDefender/releases>

### Continuous integration & release flow

- `.github/workflows/test.yml` runs the full test suite and CLI smoke test on Python 3.9 – 3.13 for every push and pull request.
- `.github/workflows/publish.yml` builds, validates and publishes the package to PyPI automatically whenever a GitHub Release is published, using PyPI Trusted Publishing (OIDC) — no API tokens or passwords are stored anywhere.

### Contributing

Bug reports and pull requests are welcome. For larger changes, please open an issue first to discuss what you would like to change. Run the tests locally with:

```bash
pip install pytest
python -m pytest tests/ -v
```

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
