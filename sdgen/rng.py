"""Seeded randomness with stable per-column sub-streams.

Unlike the ``sdg`` engine (one RNG threaded by call order), sdgen derives a
*stable* sub-stream per (table, column) from the global seed using a CRC32 of the
name — so adding/removing a column doesn't reshuffle the others, and output is
reproducible across processes (Python's ``hash()`` is salted, so we can't use it).
"""

from __future__ import annotations

import random
import zlib

try:
    from faker import Faker
    _HAS_FAKER = True
except Exception:  # pragma: no cover
    _HAS_FAKER = False


class RngBundle:
    def __init__(self, seed: int, locale: str = "en_US"):
        self.seed = int(seed)
        self.master = random.Random(self.seed)
        if _HAS_FAKER:
            self.faker = Faker(locale)
            self.faker.seed_instance(self.seed)
        else:  # pragma: no cover - faker is a hard dep in practice
            self.faker = None

    def for_column(self, table: str, column: str) -> random.Random:
        h = zlib.crc32(f"{table}.{column}".encode("utf-8")) & 0xFFFFFFFF
        return random.Random(self.seed ^ h)

    def stream(self, label: str) -> random.Random:
        h = zlib.crc32(label.encode("utf-8")) & 0xFFFFFFFF
        return random.Random(self.seed ^ h)


def has_faker() -> bool:
    return _HAS_FAKER
