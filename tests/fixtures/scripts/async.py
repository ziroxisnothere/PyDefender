"""Fixture: async/await, async context managers, async iteration, gather."""

import asyncio


class AsyncCounter:
    def __init__(self, stop):
        self.current = 0
        self.stop = stop

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.current = 0
        return False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.current >= self.stop:
            raise StopAsyncIteration
        self.current += 1
        await asyncio.sleep(0)
        return self.current


async def compute(value):
    await asyncio.sleep(0)
    return value * 3


async def run_all():
    async with AsyncCounter(4) as counter:
        async for number in counter:
            print("tick", number)
    results = await asyncio.gather(compute(2), compute(5), compute(9))
    print("gathered:", results)
    total = 0
    for partial in results:
        total += partial
    print("total:", total)


if __name__ == "__main__":
    asyncio.run(run_all())
