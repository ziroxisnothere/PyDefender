"""Fixture: generators, yield from, generator expressions, send/close."""


def countdown(start):
    while start > 0:
        yield start
        start -= 1


def chained(start):
    yield from countdown(start)
    yield 0
    yield -1


def accumulator():
    running = 0
    while True:
        received = yield running
        if received is None:
            received = 1
        running += received


def squares(limit):
    return (value * value for value in range(limit))


if __name__ == "__main__":
    print(list(chained(4)))
    print(sum(squares(6)))
    gen = accumulator()
    print(next(gen))
    print(gen.send(5))
    print(gen.send(7))
    gen.close()
    filtered = [value for value in chained(3) if value % 2 == 1]
    print("odd:", filtered)
