"""Fixture: dataclasses with annotations, defaults, defaults factories, methods."""

from dataclasses import dataclass, field
from typing import List


@dataclass
class Point:
    x: int
    y: int = 10

    def magnitude(self):
        return (self.x ** 2 + self.y ** 2) ** 0.5

    def shifted(self, dx, dy):
        return Point(self.x + dx, self.y + dy)


@dataclass
class Inventory:
    name: str
    tags: List[str] = field(default_factory=list)
    quantity: int = 0

    def add(self, amount):
        self.quantity += amount
        return self.quantity

    def describe(self):
        return f"{self.name}: {self.quantity} ({', '.join(self.tags) or 'no tags'})"


@dataclass(frozen=True)
class Config:
    host: str
    port: int


if __name__ == "__main__":
    point = Point(3, 4)
    print("mag:", point.magnitude())
    print(point.shifted(1, 1))
    store = Inventory("gems", tags=["red", "rare"])
    print(store.add(25))
    print(store.add(5))
    print(store.describe())
    config = Config("localhost", 8080)
    print(config.host, config.port)
