# PyDefender Examples

## `basic_usage.py` - the standalone engine API

```bash
python examples/basic_usage.py
```

Demonstrates the three main entry points of the engine:

- `engine.obfuscate_source(source)` - protect a string in memory
- `engine.obfuscate(input, output)` - protect a file or directory tree
- dry runs (`ObfuscationConfig(dry_run=True)`) that write nothing

## Protecting a project for PyInstaller

The engine detects the modules your project imports
(`result.dependencies`) so you can feed them to packaging tools:

```python
from pydefender.engine import ObfuscationEngine, ObfuscationConfig

engine = ObfuscationEngine(ObfuscationConfig(level=2))
result = engine.obfuscate("src/", "protected/")

hidden_imports = [dependency for dependency in result.dependencies
                  if dependency != "<relative>"]
print("--hidden-import", " --hidden-import ".join(hidden_imports))
```

Then build as usual (use level 1 or 2 when local modules must stay
visible to PyInstaller's static analysis - see README, section
"PyInstaller compatibility"):

```bash
pydefender obfuscate src/ -o protected/ --level 2
pyinstaller --onefile protected/main.py
```
