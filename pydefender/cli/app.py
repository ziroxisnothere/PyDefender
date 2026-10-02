"""CLI implementation: argument parsing and engine invocation.

There is deliberately no obfuscation logic in this module. All work is
performed by :class:`pydefender.engine.ObfuscationEngine`, guaranteeing
that the CLI and the Python API always behave identically.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

from pydefender.engine import ObfuscationConfig, ObfuscationEngine
from pydefender.engine.config import LEVELS
from pydefender.engine.exceptions import PyDefenderError

PROG = "pydefender"
_DESCRIPTION = "PyDefender - Python source-code obfuscator and protection tool."

_LEVEL_NAMES = {1: "light", 2: "standard", 3: "heavy"}


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
            "  pydefender obfuscate app.py --dry-run --integrity\n"
            "  pydefender check app.py\n"
            "\n"
            "The CLI is a thin wrapper around the PyDefender engine "
            "(pydefender.engine.ObfuscationEngine)."
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
        ".py files using the PyDefender engine. The protected code is "
        "functionally identical to the original.",
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
        "--dry-run",
        action="store_true",
        help="run the full pipeline but do not write any output",
    )
    parser_obfuscate.add_argument(
        "--integrity",
        action="store_true",
        help="embed a runtime integrity check (heavy loader) and report "
        "the output checksum",
    )
    parser_obfuscate.add_argument(
        "--seed",
        type=int,
        default=0,
        metavar="N",
        help="seed for reproducible output (default: 0)",
    )
    parser_obfuscate.add_argument(
        "--no-reproducible",
        action="store_true",
        help="allow non-deterministic transformations",
    )
    parser_obfuscate.add_argument(
        "--no-rename",
        action="store_true",
        help="disable identifier renaming",
    )
    parser_obfuscate.add_argument(
        "--no-strings",
        action="store_true",
        help="disable string-literal protection",
    )
    parser_obfuscate.add_argument(
        "--no-constants",
        action="store_true",
        help="disable numeric-constant protection",
    )
    parser_obfuscate.add_argument(
        "--no-control-flow",
        action="store_true",
        help="disable control-flow protection",
    )
    parser_obfuscate.add_argument(
        "--no-metadata",
        action="store_true",
        help="keep docstrings (disable metadata reduction)",
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


def _build_config(args: argparse.Namespace) -> ObfuscationConfig:
    """Translate CLI flags into an engine configuration."""
    return ObfuscationConfig(
        level=args.level,
        rename=False if args.no_rename else None,
        strings=False if args.no_strings else None,
        constants=False if args.no_constants else None,
        control_flow=False if args.no_control_flow else None,
        metadata=False if args.no_metadata else None,
        integrity=args.integrity,
        reproducible=not args.no_reproducible,
        seed=max(0, args.seed),
        dry_run=args.dry_run,
    )


def _print_result(args: argparse.Namespace, result) -> None:
    if args.quiet:
        return
    for source_file, destination in result.files:
        print(f"  {source_file} -> {destination}")
    if result.input_path is not None and result.input_path.is_file():
        print(
            f"{PROG}: {result.input_path} -> {result.output_path} "
            f"(level {result.level}: {_LEVEL_NAMES.get(result.level, '?')})"
        )
    if result.files:
        print(
            f"{PROG}: protected {len(result.files)} file(s) -> {result.output_path} "
            f"(level {result.level}: {_LEVEL_NAMES.get(result.level, '?')})"
        )
    if not args.quiet and result.warnings:
        for warning in result.warnings:
            print(f"{PROG}: warning: {warning}", file=sys.stderr)


def _run_obfuscate(args: argparse.Namespace) -> int:
    """Handle the ``obfuscate`` subcommand via the engine."""
    engine = ObfuscationEngine(_build_config(args))
    input_path = Path(args.input)
    if args.in_place:
        output_path = input_path
        overwrite = True
    else:
        output_path = args.output
        overwrite = args.force
    result = engine.obfuscate(input_path, output_path, overwrite=overwrite)
    _print_result(args, result)
    if not args.quiet:
        print(result)
    return 0


def _run_check(args: argparse.Namespace) -> int:
    """Handle the ``check`` subcommand via the engine."""
    engine = ObfuscationEngine()
    input_path = Path(args.input)
    report = engine.analyze(input_path)
    recommended = report["recommended_level"]
    print(f"PyDefender protection report: {input_path}")
    print(f"  lines              : {report['lines']}")
    print(f"  functions          : {report['functions']}")
    print(f"  classes            : {report['classes']}")
    print(f"  imports            : {report['imports']}")
    print(f"  comments           : {report['comments']}")
    print(f"  docstrings         : {report['docstrings']} of {report['scopes']} scopes")
    print(f"  recommended level  : {recommended} ({_LEVEL_NAMES.get(recommended, '?')})")
    return 0


def _run_version(args: argparse.Namespace) -> int:
    """Handle the ``version`` subcommand."""
    engine = ObfuscationEngine()
    info = engine.detect_environment()
    print(f"PyDefender {info.engine_version}")
    print(f"python {info.python_version} ({info.python_implementation})")
    print("https://github.com/ziroxisnothere/PyDefender")
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
