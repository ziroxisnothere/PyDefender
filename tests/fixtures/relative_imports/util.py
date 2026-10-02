"""Utilities of the relative-import fixture package."""


def slugify(name):
    cleaned = name.strip().lower()
    parts = cleaned.replace("_", "-").split()
    return "-".join(parts)


def format_size(size_bytes, precise=False):
    kib = size_bytes / 1024
    if precise:
        return f"{kib:.2f} KiB"
    return f"{int(kib) + 1} KiB"
