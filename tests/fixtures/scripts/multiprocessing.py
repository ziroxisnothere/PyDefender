"""Fixture: multiprocessing with a __main__ guard (spawn/fork safe)."""

from multiprocessing import Process, Queue


def worker(number, results):
    total = 0
    for value in range(number + 1):
        total += value
    results.put((number, total))


def greeter(name, results):
    message = f"hello {name}"
    results.put((len(name), message))


if __name__ == "__main__":
    queue = Queue()
    processes = [
        Process(target=worker, args=(10, queue)),
        Process(target=worker, args=(100, queue)),
        Process(target=greeter, args=("pydefender", queue)),
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join()
    collected = []
    while not queue.empty():
        collected.append(queue.get())
    collected.sort(key=lambda item: str(item))
    for item in collected:
        print(item)
