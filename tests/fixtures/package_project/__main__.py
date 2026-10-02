"""Package fixture using absolute imports, run via `python -m package_project`.

Exercises:
- absolute intra-package imports (from package_project.models import ...)
- cross-module dataclass usage
- deep module structure
"""

from package_project.models import Cart, CartItem, summarize
from package_project.service import checkout, restock


def main():
    cart = Cart()
    cart.add(CartItem(name="widget", unit_price=3, quantity=2))
    cart.add(CartItem(name="gadget", unit_price=10, quantity=1))
    print(summarize(cart))
    print(checkout(cart))
    store = restock({"widget": 5, "gadget": 2})
    print(store)


if __name__ == "__main__":
    main()
