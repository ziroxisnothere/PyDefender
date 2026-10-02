"""Fixture: classes, inheritance, properties, dunders, static/class methods."""


class Animal:
    kingdom = "Animalia"

    def __init__(self, name, sound):
        self.name = name
        self.sound = sound

    def speak(self):
        return f"{self.name} says {self.sound}"

    def __repr__(self):
        return f"Animal({self.name!r})"

    @classmethod
    def taxonomy(cls):
        return f"class {cls.__name__} in {cls.kingdom}"

    @staticmethod
    def is_alive():
        return True


class Dog(Animal):
    def __init__(self, name):
        super().__init__(name, "woof")

    @property
    def call(self):
        return f"{self.name}! {self.sound}!"

    def fetch(self, item, times=1):
        carried = []
        for attempt in range(times):
            carried.append(f"{item}-{attempt + 1}")
        return carried


if __name__ == "__main__":
    generic = Animal("Generic", "...")
    buddy = Dog("Buddy")
    print(generic.speak())
    print(buddy.speak())
    print(buddy.call)
    print(buddy.fetch("ball", times=3))
    print(Dog.taxonomy())
    print(Animal.is_alive())
    print(repr(buddy))
    print(buddy.kingdom, Dog.kingdom)
