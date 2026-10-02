"""Core logic of the relative-import fixture package."""

from .util import format_size, slugify

DEFAULT_STAGE_COUNT = 10


def describe_pipeline(name, level):
    label = slugify(name)
    stages = ["validation", "parsing", "transform", "output"]
    trimmed = stages[: max(1, min(len(stages), level + 1))]
    return f"{label}: {len(trimmed)} stage(s) at level {level}"


def build_report(files):
    total = 0
    lines = []
    for name, size in files:
        total += size
        lines.append(f"- {slugify(name)}: {format_size(size)}")
    lines.append(f"total: {format_size(total, precise=True)}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(describe_pipeline("PyDefender Engine", 3))
    print(build_report([("Main Module", 1536), ("Helper Module", 512)]))
    print("default stages:", DEFAULT_STAGE_COUNT)
