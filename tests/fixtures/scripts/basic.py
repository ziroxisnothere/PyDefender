"""Fixture: basic script with functions, locals and a main guard."""


def add(first, second):
    result = first + second
    return result


def describe(count):
    label = "items processed"
    total = count * 2
    return f"{count} {label} (doubled: {total})"


def average(values):
    accumulated = 0
    for value in values:
        accumulated += value
    return accumulated / len(values)


if __name__ == "__main__":
    print("sum:", add(20, 22))
    print(describe(50))
    print("avg:", average([2, 4, 6, 8]))
