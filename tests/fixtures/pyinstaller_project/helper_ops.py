"""Local helper module imported statically by the PyInstaller fixture."""


def transform_batch(records):
    totals = []
    for record in records:
        adjusted = dict(record)
        adjusted["square"] = record["square"] + 1
        totals.append(adjusted)
    return totals
