"""Dirty-data injection with a per-cell defect ledger.

A ``dirty_ratio`` fraction of rows get one defect each. The kind is chosen from
the column's ``dirty_kinds`` (or the per-type defaults), and is gated so it makes
sense for the column type. Unlike ``sdg``'s single ``_fault_type`` column, every
defect is recorded as a ledger entry ``{row, column, kind}`` — the engine can
fold these into an optional ``_defect`` column.
"""

from __future__ import annotations

import random
from typing import Any, Dict, List

from .types import LogicalType, DirtyKind, DIRTY_FOR_TYPE, NUMERIC_TYPES
from .model import TableSpec, GenerationConfig, ColumnSpec


_ENCODING_SAMPLES = [
    "café", "naïve", "“smart quotes”", "Mojibake: Ã©",
    "﻿BOM-prefixed", "tab\tinside", "emoji \U0001f4a5", "rtl‮override",
]
_NULL_VARIANTS = [None, "", " ", "N/A", "NULL"]


def _eligible_kinds(col: ColumnSpec, cfg: GenerationConfig, is_fk: bool) -> List[DirtyKind]:
    if col.dirty_kinds is not None:
        kinds = list(col.dirty_kinds)
    elif cfg.default_dirty_kinds is not None:
        base = DIRTY_FOR_TYPE.get(col.type, [DirtyKind.NULL_VARIANT])
        kinds = [k for k in cfg.default_dirty_kinds if k in base] or list(base)
    else:
        kinds = list(DIRTY_FOR_TYPE.get(col.type, [DirtyKind.NULL_VARIANT]))
    if col.unique and DirtyKind.DUPLICATE_PK not in kinds:
        kinds = kinds + [DirtyKind.DUPLICATE_PK]
    if is_fk and DirtyKind.BROKEN_FK not in kinds:
        kinds = kinds + [DirtyKind.BROKEN_FK]
    return kinds


def _broken_fk_value(parent_vals, rng):
    nums = [v for v in parent_vals if isinstance(v, int) and not isinstance(v, bool)]
    if nums:
        return max(nums) + rng.randint(1_000_000, 9_999_999)
    return f"__MISSING_FK_{rng.randint(1000, 9999)}__"


def _apply(kind: DirtyKind, col: ColumnSpec, rows, idx, rng,
           fk_parent_vals) -> Any:
    base = rows[idx].get(col.name)
    if col.dirty_examples and rng.random() < 0.3:
        return rng.choice(col.dirty_examples)

    if kind == DirtyKind.NULL_VARIANT:
        return rng.choice(_NULL_VARIANTS)
    if kind == DirtyKind.WHITESPACE:
        return f"  {base}  "
    if kind == DirtyKind.EMBEDDED_DELIMITER:
        s = str(base)
        cut = len(s) // 2 or 1
        return rng.choice([f"{s[:cut]},{s[cut:]}", f'{s[:cut]}"{s[cut:]}',
                           f"{s[:cut]}\n{s[cut:]}", f'"{s}'])
    if kind == DirtyKind.TYPE_MISMATCH:
        if col.type in NUMERIC_TYPES:
            return rng.choice(["thirty", "N/A", "12.3.4", "—"])
        return rng.choice([12345, True, 3.14])
    if kind == DirtyKind.OUT_OF_RANGE:
        if col.type in NUMERIC_TYPES:
            lo = col.params.get("min", 0)
            return rng.choice([lo - 999999, 10 ** 12, -1])
        return rng.choice(["OUT_OF_RANGE", "###"])
    if kind == DirtyKind.LEADING_ZERO:
        return rng.choice([f"00{base}", "1.2E+10"])
    if kind == DirtyKind.DATE_AMBIGUITY:
        return rng.choice(["31/12/2020", "2023-13-45", "0000-00-00", "Jan 5 2021"])
    if kind == DirtyKind.FORMAT_VIOLATION:
        t = col.type
        if t == LogicalType.EMAIL:
            return rng.choice(["not-an-email", "missing@tld", "@nodomain.com", "a b@c.com"])
        if t == LogicalType.URL:
            return rng.choice(["htp:/bad", "www nospace", "://x"])
        if t == LogicalType.IPV4:
            return rng.choice(["999.1.1.1", "1.2.3", "abc.def.ghi.jkl"])
        if t == LogicalType.PHONE:
            return rng.choice(["abc-def", "12", "++1()"])
        if t in (LogicalType.DATE, LogicalType.DATETIME):
            return rng.choice(["31/12/2020", "2020.13.01", "Jan 5 2021"])
        if t == LogicalType.UUID:
            return "not-a-uuid"
        return rng.choice(["###bad###", "<<>>"])
    if kind == DirtyKind.ENCODING:
        return rng.choice(_ENCODING_SAMPLES)
    if kind == DirtyKind.INVALID_ENUM_CASE:
        if col.allowed_values:
            v = str(rng.choice(col.allowed_values))
            cand = [v.upper(), v.lower(), v.title(), v[: max(1, len(v) - 2)]]
            bad = [c for c in cand if c not in {str(x) for x in col.allowed_values}]
            return rng.choice(bad) if bad else v.swapcase()
        return str(base).swapcase()
    if kind == DirtyKind.TRUNCATION:
        s = str(base)
        return s[: max(1, len(s) // 2)]
    if kind == DirtyKind.DUPLICATE_PK:
        others = [r.get(col.name) for j, r in enumerate(rows) if j != idx]
        return rng.choice(others) if others else base
    if kind == DirtyKind.BROKEN_FK:
        return _broken_fk_value(fk_parent_vals or [0], rng)
    return base


def inject_dirty(t: TableSpec, cfg: GenerationConfig, bundle, rows,
                 parent_keys: Dict[str, Dict[str, List[Any]]]) -> List[Dict[str, Any]]:
    ledger: List[Dict[str, Any]] = []
    if cfg.dirty_ratio <= 0 or not rows:
        return ledger
    rng = bundle.stream(f"dirty.{t.name}")
    n = len(rows)
    n_dirty = int(round(n * cfg.dirty_ratio))
    if n_dirty <= 0:
        return ledger

    fk_by_col = {fk.column: fk for fk in t.foreign_keys}
    chosen = rng.sample(range(n), min(n_dirty, n))
    for idx in chosen:
        col = rng.choice(t.columns)
        is_fk = col.name in fk_by_col
        kinds = _eligible_kinds(col, cfg, is_fk)
        if not kinds:
            continue
        kind = rng.choice(kinds)
        fk_parent_vals = None
        if kind == DirtyKind.BROKEN_FK and is_fk:
            fk = fk_by_col[col.name]
            ref_col = fk.ref_column or next(iter(parent_keys.get(fk.ref_table, {})), None)
            fk_parent_vals = parent_keys.get(fk.ref_table, {}).get(ref_col or "")
        rows[idx][col.name] = _apply(kind, col, rows, idx, rng, fk_parent_vals)
        ledger.append({"row": idx, "column": col.name, "kind": kind.value})
    return ledger
