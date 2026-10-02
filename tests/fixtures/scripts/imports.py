"""Fixture: absolute imports, dynamic importlib usage, stdlib only."""

import importlib
import json
import math
from os import path


def circle_metrics(radius):
    area = math.pi * radius ** 2
    circumference = 2 * math.pi * radius
    return area, circumference


def json_roundtrip(payload):
    encoded = json.dumps(payload, sort_keys=True)
    decoded = json.loads(encoded)
    return decoded["name"], encoded


def dynamic_module_lookup():
    string_module = importlib.import_module("string")
    return string_module.ascii_lowercase[:5]


def path_exists(target):
    present = path.exists(target)
    return isinstance(present, bool)


if __name__ == "__main__":
    area, circumference = circle_metrics(3)
    print("area:", round(area, 4))
    print("circ:", round(circumference, 4))
    print("json:", json_roundtrip({"name": "pydefender", "level": 3}))
    print("dyn:", dynamic_module_lookup())
    print("path:", path_exists("."))
