"""Service layer for the absolute-import fixture package."""

from package_project.models import Cart, CartItem


def checkout(cart):
    total = cart.total()
    if total <= 0:
        return "empty cart"
    lines = 0
    for item in cart.items:
        lines += item.quantity
    return f"checked out {lines} unit(s) for {total}"


def restock(levels):
    inventory = {}
    for name, amount in sorted(levels.items()):
        inventory[name] = amount * 10
    return inventory
