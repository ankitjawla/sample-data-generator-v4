"""Per-type value generators with a plugin registry.

Each ``LogicalType`` maps to a ``ValueGenerator`` registered via ``@register``.
Adding a new type is one class — the engine, importers and writers never change.
This registry/plugin design is the main structural difference from ``sdg``'s big
if/elif generator function.
"""

from __future__ import annotations

import random
import string as _string
import uuid as _uuid
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Callable, Dict, List

from .types import LogicalType
from .model import ColumnSpec


REGISTRY: Dict[LogicalType, Callable[..., "ValueGenerator"]] = {}


def register(lt: LogicalType):
    def deco(cls):
        REGISTRY[lt] = cls
        return cls
    return deco


class ValueGenerator:
    def __init__(self, col: ColumnSpec, rng: random.Random, faker):
        self.col = col
        self.rng = rng
        self.faker = faker

    def next(self) -> Any:
        raise NotImplementedError

    def boundary_values(self) -> List[Any]:
        return list(self.col.edge_values)


def make_generator(col: ColumnSpec, rng: random.Random, faker) -> ValueGenerator:
    # An explicit value domain ("expected values" / allowed_values) wins over the
    # declared type, so values entered in the Schema editor or config are honoured
    # even when the column's type wasn't switched to `enum`. Without this, e.g. a
    # `string` column with allowed_values would emit random strings instead.
    if col.allowed_values and col.type != LogicalType.ENUM:
        return REGISTRY[LogicalType.ENUM](col, rng, faker)
    cls = REGISTRY.get(col.type, REGISTRY[LogicalType.STRING])
    return cls(col, rng, faker)


# --- helpers ----------------------------------------------------------------
def _parse_date(v, default: datetime) -> datetime:
    if v is None:
        return default
    if isinstance(v, datetime):
        return v
    if isinstance(v, date):
        return datetime(v.year, v.month, v.day)
    s = str(v)
    if s.lower() == "today":
        return datetime(2026, 6, 16)  # fixed "today" so runs are reproducible
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return datetime(date.fromisoformat(s).year, date.fromisoformat(s).month,
                        date.fromisoformat(s).day)


def _num_range(col: ColumnSpec, lo_default, hi_default):
    p = col.params
    return p.get("min", lo_default), p.get("max", hi_default)


# --- generators -------------------------------------------------------------
@register(LogicalType.SEQ_ID)
class SeqIdGen(ValueGenerator):
    def __init__(self, col, rng, faker):
        super().__init__(col, rng, faker)
        self._n = int(col.params.get("start", 1))
        self._step = int(col.params.get("step", 1))

    def next(self):
        v = self._n
        self._n += self._step
        return v

    def boundary_values(self):
        # The running counter already covers the start value; emitting it again
        # here would duplicate the first generated id. Only user edges apply.
        return list(self.col.edge_values)


@register(LogicalType.INTEGER)
class IntegerGen(ValueGenerator):
    def next(self):
        lo, hi = _num_range(self.col, 0, 1_000_000)
        lo, hi = int(lo), int(hi)
        if hi < lo:
            lo, hi = hi, lo
        dist = self.col.params.get("distribution")
        if dist == "normal":
            mid, sd = (lo + hi) / 2, (hi - lo) / 6 or 1
            return int(max(lo, min(hi, round(self.rng.gauss(mid, sd)))))
        if dist == "exponential":
            span = (hi - lo) or 1
            return int(max(lo, min(hi, round(lo + min(span, self.rng.expovariate(3.0 / span))))))
        return self.rng.randint(lo, hi)

    def boundary_values(self):
        lo, hi = _num_range(self.col, 0, 1_000_000)
        return [int(lo), int(hi), 0] + list(self.col.edge_values)


@register(LogicalType.DECIMAL)
class DecimalGen(ValueGenerator):
    def _scale(self):
        return self.col.scale if self.col.scale is not None else int(self.col.params.get("scale", 2))

    def next(self):
        lo, hi = _num_range(self.col, 0.0, 1000.0)
        lo, hi = float(lo), float(hi)
        dist = self.col.params.get("distribution")
        if dist == "normal":
            mid, sd = (lo + hi) / 2, (hi - lo) / 6 or 1
            val = max(lo, min(hi, self.rng.gauss(mid, sd)))
        elif dist == "exponential":
            span = (hi - lo) or 1
            val = lo + min(span, self.rng.expovariate(3.0 / span))
        else:
            val = self.rng.uniform(lo, hi)
        q = Decimal(10) ** -self._scale()
        return float(Decimal(val).quantize(q, rounding=ROUND_HALF_UP))

    def boundary_values(self):
        lo, hi = _num_range(self.col, 0.0, 1000.0)
        return [float(lo), float(hi), 0.0] + list(self.col.edge_values)


@register(LogicalType.FLOAT)
class FloatGen(ValueGenerator):
    def next(self):
        lo, hi = _num_range(self.col, 0.0, 1000.0)
        return self.rng.uniform(float(lo), float(hi))

    def boundary_values(self):
        lo, hi = _num_range(self.col, 0.0, 1000.0)
        return [float(lo), float(hi), 0.0] + list(self.col.edge_values)


@register(LogicalType.BOOLEAN)
class BooleanGen(ValueGenerator):
    def next(self):
        return self.rng.choice([True, False])

    def boundary_values(self):
        return [True, False]


@register(LogicalType.ENUM)
class EnumGen(ValueGenerator):
    def next(self):
        vals = self.col.allowed_values or ["A", "B", "C"]
        return self.rng.choices(vals, weights=self.col.weights or None, k=1)[0]

    def boundary_values(self):
        return list(self.col.allowed_values) + list(self.col.edge_values)


@register(LogicalType.STRING)
class StringGen(ValueGenerator):
    def next(self):
        lo = int(self.col.params.get("min_length", 1))
        hi = int(self.col.max_length or self.col.params.get("max_length", 12))
        n = self.rng.randint(min(lo, hi), max(lo, hi))
        alphabet = _string.ascii_letters + _string.digits
        return "".join(self.rng.choice(alphabet) for _ in range(n))

    def boundary_values(self):
        hi = int(self.col.max_length or self.col.params.get("max_length", 12))
        return ["", "a", "Z" * hi] + list(self.col.edge_values)


@register(LogicalType.TEXT)
class TextGen(ValueGenerator):
    def next(self):
        if self.faker is not None and hasattr(self.faker, "text"):
            return self.faker.text(max_nb_chars=max(20, int(self.col.max_length or 200)))
        n_words = self.rng.randint(8, 20)
        return " ".join("".join(self.rng.choice(_string.ascii_lowercase)
                                for _ in range(self.rng.randint(3, 9))) for _ in range(n_words))

    def boundary_values(self):
        return ["", "a"] + list(self.col.edge_values)


@register(LogicalType.UUID)
class UuidGen(ValueGenerator):
    def next(self):
        return str(_uuid.UUID(int=self.rng.getrandbits(128)))


@register(LogicalType.DATE)
class DateGen(ValueGenerator):
    def _bounds(self):
        lo = _parse_date(self.col.params.get("start"), datetime(2015, 1, 1))
        hi = _parse_date(self.col.params.get("end"), datetime(2026, 6, 16))
        return (lo, hi) if lo <= hi else (hi, lo)

    def next(self):
        lo, hi = self._bounds()
        delta = (hi - lo).days or 1
        return (lo + timedelta(days=self.rng.randint(0, delta))).date().isoformat()

    def boundary_values(self):
        lo, hi = self._bounds()
        return [lo.date().isoformat(), hi.date().isoformat(), "2020-02-29"] + list(self.col.edge_values)


@register(LogicalType.DATETIME)
class DatetimeGen(DateGen):
    def next(self):
        lo, hi = self._bounds()
        secs = int((hi - lo).total_seconds()) or 1
        return (lo + timedelta(seconds=self.rng.randint(0, secs))).replace(microsecond=0).isoformat(sep=" ")

    def boundary_values(self):
        lo, hi = self._bounds()
        return [lo.isoformat(sep=" "), hi.isoformat(sep=" "), "2020-02-29 00:00:00"] + list(self.col.edge_values)


# --- Faker-backed semantic generators ---------------------------------------
def _faker_gen(lt: LogicalType, method: str):
    @register(lt)
    class _Gen(ValueGenerator):
        def next(self):
            if self.faker is not None and hasattr(self.faker, method):
                return getattr(self.faker, method)()
            # graceful fallback if Faker is unavailable
            return "".join(self.rng.choice(_string.ascii_lowercase) for _ in range(6))
    _Gen.__name__ = f"Faker_{method}"
    return _Gen


_faker_gen(LogicalType.NAME, "name")
_faker_gen(LogicalType.FIRST_NAME, "first_name")
_faker_gen(LogicalType.LAST_NAME, "last_name")
_faker_gen(LogicalType.EMAIL, "email")
_faker_gen(LogicalType.PHONE, "phone_number")
_faker_gen(LogicalType.COMPANY, "company")
_faker_gen(LogicalType.JOB, "job")
_faker_gen(LogicalType.CITY, "city")
_faker_gen(LogicalType.COUNTRY, "country")
_faker_gen(LogicalType.POSTCODE, "postcode")
_faker_gen(LogicalType.URL, "url")
_faker_gen(LogicalType.IPV4, "ipv4")


@register(LogicalType.ADDRESS)
class AddressGen(ValueGenerator):
    def next(self):
        if self.faker is not None:
            return self.faker.address().replace("\n", ", ")
        return f"{self.rng.randint(1, 999)} Main St"


@register(LogicalType.CURRENCY)
class CurrencyGen(ValueGenerator):
    def next(self):
        if self.faker is not None and hasattr(self.faker, "currency_code"):
            return self.faker.currency_code()
        return self.rng.choice(["EUR", "USD", "GBP", "JPY", "CHF"])

    def boundary_values(self):
        return list(self.col.edge_values)
