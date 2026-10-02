"""Fixture: decorators (function, method, class), functools.wraps, annotations."""

import functools


def logged(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        outcome = func(*args, **kwargs)
        return outcome

    return wrapper


def annotate(description):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return f"[{description}] {func(*args, **kwargs)}"

        return wrapper

    return decorator


def enforce_positive(method):
    @functools.wraps(method)
    def wrapper(self, value):
        if value <= 0:
            raise ValueError("must be positive")
        return method(self, value)

    return wrapper


def register(cls):
    cls.registered = True
    return cls


@logged
def plain_sum(first, second):
    nested = first + second
    return nested


@annotate("math")
def product(first, second):
    combined = first * second
    return combined


class Wallet:
    @enforce_positive
    def deposit(self, amount):
        self.balance = getattr(self, "balance", 0) + amount
        return self.balance


@register
class Registered:
    pass


if __name__ == "__main__":
    print(plain_sum(3, 4))
    print(product(6, 7))
    print(plain_sum.__name__)
    wallet = Wallet()
    print(wallet.deposit(50))
    print(wallet.deposit(25))
    try:
        wallet.deposit(-5)
    except ValueError as error:
        print("rejected:", error)
    print(Registered.registered)
