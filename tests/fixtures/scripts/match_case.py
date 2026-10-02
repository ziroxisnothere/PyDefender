"""Fixture: match/case statements (requires Python 3.10+)."""


def classify(command):
    match command:
        case "start":
            return "starting"
        case "stop" | "halt":
            return "stopping"
        case {"op": "add", "value": amount}:
            return f"adding {amount}"
        case [first, second] if first == "pair":
            return f"pair of {second}"
        case _:
            return "unknown"


def shape_area(shape):
    match shape:
        case ("circle", radius):
            return 3.14159 * radius * radius
        case ("rect", width, height):
            return width * height
        case _:
            return 0.0


if __name__ == "__main__":
    print(classify("start"))
    print(classify("halt"))
    print(classify({"op": "add", "value": 41}))
    print(classify(["pair", "socks"]))
    print(classify("nope"))
    print(round(shape_area(("circle", 2)), 4))
    print(shape_area(("rect", 3, 4)))
    print(shape_area(("blob",)))
