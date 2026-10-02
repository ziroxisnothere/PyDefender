"""Data models for the absolute-import fixture package."""

from dataclasses import dataclass, field
from typing import List


@dataclass
class CartItem:
    name: str
    unit_price: int
    quantity: int = 1

    @property
    def subtotal(self):
        return self.unit_price * self.quantity


@dataclass
class Cart:
    items: List[CartItem] = field(default_factory=list)

    def add(self, item):
        self.items.append(item)
        return len(self.items)

    def total(self):
        running = 0
        for item in self.items:
            running += item.subtotal
        return running


def summarize(cart):
    count = len(cart.items)
    return f"{count} item type(s), total {cart.total()}"
