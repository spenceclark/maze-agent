"""Version-stable seeded randomness (spec §16).

Each stream is identified by (root_seed, label). Draw i is derived from
SHA-256(f"{root_seed}:{label}:{i}"), so results never depend on Python's
`random` implementation, process hash seeds, or unrelated draws.
"""

import hashlib
from collections.abc import Sequence

PRNG_VERSION = "sha256_counter_v1"


class SeededStream:
    def __init__(self, root_seed: int, label: str) -> None:
        self._prefix = f"{root_seed}:{label}:"
        self._counter = 0

    def _next_u64(self) -> int:
        digest = hashlib.sha256(f"{self._prefix}{self._counter}".encode()).digest()
        self._counter += 1
        return int.from_bytes(digest[:8], "big")

    def below(self, n: int) -> int:
        """Uniform integer in [0, n) by rejection sampling."""
        if n <= 0:
            raise ValueError("n must be positive")
        limit = (1 << 64) - (1 << 64) % n
        while (value := self._next_u64()) >= limit:
            pass
        return value % n

    def choice[T](self, items: Sequence[T]) -> T:
        return items[self.below(len(items))]

    def sample[T](self, items: Sequence[T], k: int) -> list[T]:
        """k distinct items, in draw order (partial Fisher-Yates)."""
        pool = list(items)
        for i in range(k):
            j = i + self.below(len(pool) - i)
            pool[i], pool[j] = pool[j], pool[i]
        return pool[:k]
