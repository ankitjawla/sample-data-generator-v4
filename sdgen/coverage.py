"""Coverage passes: per-column edges, full cartesian, or greedy pairwise.

Combination columns are the enum and boolean columns (optionally restricted by
``coverage.columns``). Cartesian is capped; pairwise covers every value pair in
far fewer rows. Implemented independently of ``sdg`` for a fair comparison.
"""

from __future__ import annotations

import itertools
from typing import Any, Dict, List, Optional

from .types import LogicalType
from .model import TableSpec, GenerationConfig


def _combo_columns(t: TableSpec, restrict: Optional[List[str]]) -> Dict[str, List[Any]]:
    out: Dict[str, List[Any]] = {}
    for c in t.columns:
        if restrict is not None and c.name not in restrict:
            continue
        if c.type == LogicalType.ENUM and c.allowed_values:
            out[c.name] = list(c.allowed_values)
        elif c.type == LogicalType.BOOLEAN:
            out[c.name] = [True, False]
    return out


def _cartesian(value_sets, cap):
    cols = list(value_sets)
    possible = 1
    for c in cols:
        possible *= max(1, len(value_sets[c]))
    combos, truncated = [], False
    for i, tup in enumerate(itertools.product(*(value_sets[c] for c in cols))):
        if i >= cap:
            truncated = True
            break
        combos.append(dict(zip(cols, tup)))
    return combos, possible, truncated


def _pairwise(value_sets):
    cols = list(value_sets)
    if len(cols) == 1:
        return [{cols[0]: v} for v in value_sets[cols[0]]]
    pos = {c: i for i, c in enumerate(cols)}
    uncovered = set()
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            for a in value_sets[cols[i]]:
                for b in value_sets[cols[j]]:
                    uncovered.add((cols[i], a, cols[j], b))

    def demand(c, v):
        return sum(1 for k in uncovered if (k[0] == c and k[1] == v) or (k[2] == c and k[3] == v))

    order = sorted(cols, key=lambda c: -len(value_sets[c]))
    rows, guard = [], 0
    while uncovered and guard < len(uncovered) + len(cols) + 10:
        guard += 1
        row = {}
        for c in order:
            best_v, best = value_sets[c][0], -1
            for v in value_sets[c]:
                covered = 0
                for c2, v2 in row.items():
                    key = (c2, v2, c, v) if pos[c2] < pos[c] else (c, v, c2, v2)
                    if key in uncovered:
                        covered += 1
                score = covered * 100_000 + demand(c, v)
                if score > best:
                    best, best_v = score, v
            row[c] = best_v
        covered_now = 0
        for i in range(len(cols)):
            for j in range(i + 1, len(cols)):
                ci, cj = cols[i], cols[j]
                k = (ci, row[ci], cj, row[cj])
                if k in uncovered:
                    uncovered.discard(k)
                    covered_now += 1
        if covered_now == 0:
            break
        rows.append(row)
    return rows


def _pairwise_capped(value_sets, cap):
    combos = _pairwise(value_sets)
    truncated = False
    if len(combos) > cap:
        combos, truncated = combos[:cap], True
    possible = 1
    for c in value_sets:
        possible *= max(1, len(value_sets[c]))
    return combos, possible, truncated


def _append_edges(rows, t: TableSpec, edge_cols, boundaries, gens) -> None:
    names = {c.name for c in edge_cols}
    needed = max((len(boundaries[c.name]) for c in edge_cols), default=0)
    for i in range(needed):
        rows.append({
            c.name: (boundaries[c.name][i] if (c.name in names and i < len(boundaries[c.name]))
                     else gens[c.name].next())
            for c in t.columns
        })


def build_coverage_rows(t: TableSpec, cfg: GenerationConfig, gens, rows) -> Optional[Dict[str, Any]]:
    """Append coverage rows to ``rows`` in place; return a combinations summary or None."""
    mode = cfg.coverage.mode
    if mode == "off":
        return None
    boundaries = {c.name: gens[c.name].boundary_values() for c in t.columns}

    if mode in ("cartesian", "pairwise"):
        combo_cols = _combo_columns(t, cfg.coverage.columns)
        if combo_cols:
            if mode == "cartesian":
                combos, possible, truncated = _cartesian(combo_cols, cfg.coverage.cap)
            else:
                combos, possible, truncated = _pairwise_capped(combo_cols, cfg.coverage.cap)
            for combo in combos:
                rows.append({
                    c.name: (combo[c.name] if c.name in combo else gens[c.name].next())
                    for c in t.columns
                })
            non_combo = [c for c in t.columns if c.name not in combo_cols]
            _append_edges(rows, t, non_combo, boundaries, gens)
            return {"mode": mode, "columns": list(combo_cols.keys()),
                    "combinations_generated": len(combos),
                    "combinations_possible": possible, "truncated": truncated}
        _append_edges(rows, t, list(t.columns), boundaries, gens)
        return None

    # edges (default)
    needed = min(max((len(v) for v in boundaries.values()), default=0), t.rows)
    for i in range(needed):
        rows.append({
            c.name: (boundaries[c.name][i] if i < len(boundaries[c.name]) else gens[c.name].next())
            for c in t.columns
        })
    return None
