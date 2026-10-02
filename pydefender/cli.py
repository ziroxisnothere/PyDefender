"""Command-line interface for PyDefender.

The console entry point is ``pydefender:main`` (see ``pyproject.toml``).
``main()`` returns an integer exit code:

* ``0``  success
* ``1``  runtime error (unreadable input, invalid source, ...)
* ``2``  usage error (handled by argparse)
* ``130`` interrupted by the user (Ctrl+C)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

from pydefender.obfuscator import (
    GITHUB_URL,
    LEVELS,
    PyDefenderError,
    analyze_file,
    obfuscate_file,
)

PROG = "pydefender"
_DESCRIPTION = "PyDefender - Python source-code obfuscator and protection tool."

#: Directories skipped when obfuscating a whole directory tree.
_SKIPPED_DIRS = {
    "__pycache__",
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "env",
    "build",
    "dist",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    "htmlcov",
    "node_modules",
    ".idea",
    ".vscode",
    ".eggs",
}


def _version_string() -> str:
    """Return the PyDefender version (best effort)."""
    try:
        from importlib.metadata import version as _dist_version

        return _dist_version("PyDefender")
    except Exception:
        try:
            from pydefender import __version__

            return __version__
        except Exception:
            return "0.1.0"


def build_parser() -> argparse.ArgumentParser:
    """Build the ``pydefender`` argument parser."""
    parser = argparse.ArgumentParser(
        prog=PROG,
        description=_DESCRIPTION,
        epilog=(
            "examples:\n"
            "  pydefender obfuscate app.py --level 3\n"
            "  pydefender obfuscate src/ -o dist/ --level 3\n"
            "  pydefender check app.py\n"
            "\n"
            f"project home: {GITHUB_URL}"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {_version_string()}",
    )

    subparsers = parser.add_subparsers(
        dest="command",
        title="commands",
        metavar="COMMAND",
    )
    subparsers.required = True

    parser_obfuscate = subparsers.add_parser(
        "obfuscate",
        help="obfuscate a Python source file or directory",
        description="Obfuscate a Python source file or a directory tree of "
        ".py files. The protected code is functionally identical to the "
        "original.",
    )
    parser_obfuscate.add_argument("input", help="Python source file or directory")
    parser_obfuscate.add_argument(
        "-o",
        "--output",
        help="output file or directory (default: <name>_protected.py next "
        "to the input; required for directory input unless --in-place)",
    )
    parser_obfuscate.add_argument(
        "-l",
        "--level",
        type=int,
        choices=sorted(LEVELS),
        default=3,
        help="protection level: 1=light, 2=standard, 3=heavy (default: 3)",
    )
    parser_obfuscate.add_argument(
        "--in-place",
        action="store_true",
        help="overwrite the input file(s) instead of writing a copy",
    )
    parser_obfuscate.add_argument(
        "--force",
        action="store_true",
        help="overwrite existing output files without failing",
    )
    parser_obfuscate.add_argument(
        "--quiet",
        action="store_true",
        help="suppress progress output",
    )
    parser_obfuscate.set_defaults(func=_run_obfuscate)

    parser_check = subparsers.add_parser(
        "check",
        help="analyze a Python source file and print a protection report",
        description="Print line/function/class/comment statistics for a "
        "Python file and recommend a protection level.",
    )
    parser_check.add_argument("input", help="Python source file")
    parser_check.set_defaults(func=_run_check)

    parser_version = subparsers.add_parser(
        "version",
        help="print version information",
        description="Print the PyDefender version and project links.",
    )
    parser_version.set_defaults(func=_run_version)

    return parser


def _should_skip(directory: Path) -> bool:
    """Return True if ``directory`` should be excluded from directory scans."""
    return directory.name in _SKIPPED_DIRS or directory.name.startswith(".")


def _collect_python_files(input_dir: Path):
    """Recursively collect ``*.py`` files under ``input_dir``."""
    for path in sorted(input_dir.rglob("*.py")):
        if any(_should_skip(parent) for parent in path.relative_to(input_dir).parents):
            continue
        yield path


def _resolve_output(args: argparse.Namespace, input_path: Path) -> Path:
    """Resolve the output path for a single-file obfuscation."""
    if args.in_place:
        return input_path
    if args.output:
        output = Path(args.output)
        if output.is_dir():
            return output / f"{input_path.stem}_protected.py"
        return output
    return input_path.with_name(f"{input_path.stem}_protected.py")


def _obfuscate_single(args: argparse.Namespace, input_path: Path) -> int:
    """Obfuscate one file and print a progress line."""
    output = _resolve_output(args, input_path)
    if not args.in_place and output.exists() and not args.force:
        raise PyDefenderError(f"output already exists (use --force to overwrite): {output}")
    written = obfuscate_file(input_path, output, level=args.level)
    if not args.quiet:
        print(
            f"{PROG}: {input_path} -> {written} "
            f"(level {args.level}: {LEVELS[args.level]})"
        )
    return 0


def _obfuscate_directory(args: argparse.Namespace, input_dir: Path) -> int:
    """Obfuscate every ``*.py`` file below ``input_dir``."""
    if args.in_place:
        output_dir = input_dir
    elif args.output:
        output_dir = Path(args.output)
    else:
        raise PyDefenderError(
            "obfuscating a directory requires --output DIRECTORY (or --in-place)"
        )

    files = list(_collect_python_files(input_dir))
    if not files:
        raise PyDefenderError(f"no Python files found under: {input_dir}")

    count = 0
    for source_file in files:
        relative = source_file.relative_to(input_dir)
        destination = output_dir / relative
        same_file = destination.exists() and destination.resolve() == source_file.resolve()
        if (
            not args.in_place
            and not same_file
            and destination.exists()
            and not args.force
        ):
            raise PyDefenderError(
                f"output already exists (use --force to overwrite): {destination}"
            )
        obfuscate_file(source_file, destination, level=args.level)
        count += 1
        if not args.quiet:
            print(f"  {source_file} -> {destination}")

    if not args.quiet:
        print(
            f"{PROG}: protected {count} file(s) -> {output_dir} "
            f"(level {args.level}: {LEVELS[args.level]})"
        )
    return 0


def _run_obfuscate(args: argparse.Namespace) -> int:
    """Handle the ``obfuscate`` subcommand."""
    input_path = Path(args.input)
    if not input_path.exists():
        raise PyDefenderError(f"input path does not exist: {input_path}")
    if input_path.is_dir():
        return _obfuscate_directory(args, input_path)
    return _obfuscate_single(args, input_path)


def _run_check(args: argparse.Namespace) -> int:
    """Handle the ``check`` subcommand."""
    input_path = Path(args.input)
    report = analyze_file(input_path)
    recommended = report["recommended_level"]
    print(f"PyDefender protection report: {input_path}")
    print(f"  lines              : {report['lines']}")
    print(f"  functions          : {report['functions']}")
    print(f"  classes            : {report['classes']}")
    print(f"  imports            : {report['imports']}")
    print(f"  comments           : {report['comments']}")
    print(f"  docstrings         : {report['docstrings']} of {report['scopes']} scopes")
    print(f"  recommended level  : {recommended} ({LEVELS[recommended]})")
    return 0


def _run_version(args: argparse.Namespace) -> int:
    """Handle the ``version`` subcommand."""
    print(f"PyDefender {_version_string()}")
    print(GITHUB_URL)
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run the PyDefender command-line interface.

    Args:
        argv: Argument list (defaults to ``sys.argv[1:]``).

    Returns:
        The process exit code as an integer.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except PyDefenderError as exc:
        print(f"{PROG}: error: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"{PROG}: error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print(f"{PROG}: interrupted", file=sys.stderr)
        return 130
