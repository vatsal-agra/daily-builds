"""Ray: origin + direction."""


class Ray:
    __slots__ = ('origin', 'direction')

    def __init__(self, origin, direction):
        self.origin = origin
        self.direction = direction

    def at(self, t):
        return self.origin + t * self.direction

    def __repr__(self):
        return f"Ray({self.origin!r} + t*{self.direction!r})"
