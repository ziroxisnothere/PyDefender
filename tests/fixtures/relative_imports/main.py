"""Entry point of the relative-import fixture package (run via -m)."""

from .core import DEFAULT_STAGE_COUNT, build_report, describe_pipeline
from .util import format_size


def main():
    print(describe_pipeline("PyDefender Engine", 3))
    print(build_report([("Main Module", 1536), ("Helper Module", 512)]))
    print("default stages:", DEFAULT_STAGE_COUNT)
    print("format check:", format_size(2048, precise=True))


if __name__ == "__main__":
    main()
