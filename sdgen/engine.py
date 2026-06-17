"""Generation orchestrator: clean values + edge coverage + uniqueness + FK integrity.

Always multi-table aware (a single table is a one-element dataset). Tables are
produced parent-first so child foreign keys can be filled with real parent keys.
Combinatorial coverage and dirty-data injection are layered on in later modules.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .model import GenerationConfig, TableSpec
from .rng import RngBundle
from .generators import make_generator


@dataclass
class Dataset:
    table: str
    header: List[str]
    rows: List[Dict[str, Any]]
    defect_ledger: List[Dict[str, Any]] = field(default_factory=list)


def toposort(cfg: GenerationConfig) -> List[TableSpec]:
    by_name = {t.name: t for t in cfg.tables}
    deps = {t.name: {fk.ref_table for fk in t.foreign_keys
                     if fk.ref_table in by_name and fk.ref_table != t.name}
            for t in cfg.tables}
    order: List[str] = []
    seen, temp = set(), set()

    def visit(name: str):
        if name in seen:
            return
        if name in temp:
            raise ValueError(f"Cyclic foreign keys involving table '{name}'.")
        temp.add(name)
        for d in sorted(deps.get(name, ())):
            visit(d)
        temp.discard(name)
        seen.add(name)
        order.append(name)

    for t in cfg.tables:
        visit(t.name)
    return [by_name[n] for n in order]


def _pk_or_first(parent: Optional[TableSpec], key_map: Optional[Dict[str, List[Any]]]) -> Optional[str]:
    """Pick the referenced key deterministically: prefer the parent's declared
    primary key, else the alphabetically-first unique column (not dict order)."""
    if not key_map:
        return None
    if parent is not None:
        for pk in parent.primary_key:
            if pk in key_map:
                return pk
    return sorted(key_map)[0]


def _comparable(v) -> bool:
    return v is not None and isinstance(v, (int, float, str)) and not isinstance(v, bool)


def _apply_constraints(rows: List[Dict[str, Any]], constraints: List[str]) -> None:
    """Repair simple 'A <op> B' cross-column rules by ordering the two values.

    Supports <=, <, >=, > between two columns (numeric or ISO-date strings).
    Mixed/incomparable types are skipped rather than raising.
    """
    for rule in constraints:
        m = re.match(r"\s*(\w+)\s*(<=|<|>=|>)\s*(\w+)\s*$", str(rule))
        if not m:
            continue
        left, op, right = m.groups()
        for row in rows:
            lv, rv = row.get(left), row.get(right)
            if not (_comparable(lv) and _comparable(rv)) or type(lv) is not type(rv):
                continue
            try:
                if op in ("<=", "<") and not (lv <= rv):
                    row[left], row[right] = min(lv, rv), max(lv, rv)
                elif op in (">=", ">") and not (lv >= rv):
                    row[left], row[right] = max(lv, rv), min(lv, rv)
            except TypeError:
                continue


def generate(cfg: GenerationConfig):
    """Generate every table. Returns {table_name: Dataset}."""
    bundle = RngBundle(cfg.seed, cfg.locale)
    parent_keys: Dict[str, Dict[str, List[Any]]] = {}
    datasets: Dict[str, Dataset] = {}

    for t in toposort(cfg):
        ds = _generate_table(t, cfg, bundle, parent_keys)
        datasets[t.name] = ds
        parent_keys[t.name] = {
            c.name: [r.get(c.name) for r in ds.rows] for c in t.columns if c.unique
        }
    return datasets


def _generate_table(t: TableSpec, cfg: GenerationConfig, bundle: RngBundle,
                    parent_keys: Dict[str, Dict[str, List[Any]]]) -> Dataset:
    from .coverage import build_coverage_rows  # local import (module added in coverage phase)
    from .dirty import inject_dirty

    gens = {c.name: make_generator(c, bundle.for_column(t.name, c.name), bundle.faker)
            for c in t.columns}
    null_rng = {c.name: bundle.stream(f"{t.name}.{c.name}.null")
                for c in t.columns if c.nullable and c.null_probability}

    rows: List[Dict[str, Any]] = []
    combo_meta = build_coverage_rows(t, cfg, gens, rows)

    # Clean fill to the row target. Seed uniqueness from any coverage rows so a
    # clean value can't collide with a value already placed during coverage.
    unique_seen = {c.name: set() for c in t.columns if c.unique}
    for row in rows:
        for c in t.columns:
            if c.unique and c.name in row:
                unique_seen[c.name].add(row[c.name])
    while len(rows) < t.rows:
        row: Dict[str, Any] = {}
        for c in t.columns:
            v = gens[c.name].next()
            if c.unique:
                tries = 0
                while v in unique_seen[c.name] and tries < 1000:
                    v = gens[c.name].next()
                    tries += 1
                if v in unique_seen[c.name]:
                    raise ValueError(
                        f"Cannot generate {t.rows} unique values for '{t.name}.{c.name}': "
                        f"value space exhausted. Widen its range/length or reduce rows.")
                unique_seen[c.name].add(v)
            if c.name in null_rng and null_rng[c.name].random() < c.null_probability:
                v = None
            row[c.name] = v
        rows.append(row)

    # Referential integrity: fill child FK columns from realised parent keys.
    for fk in t.foreign_keys:
        ref_col = fk.ref_column or _pk_or_first(cfg.table(fk.ref_table), parent_keys.get(fk.ref_table))
        pvals = [v for v in parent_keys.get(fk.ref_table, {}).get(ref_col or "", []) if v is not None]
        if not pvals:
            continue
        frng = bundle.stream(f"{t.name}.{fk.column}.fk")
        for row in rows:
            row[fk.column] = frng.choice(pvals)

    # Cross-column constraints — best-effort repair on the clean rows.
    if t.constraints:
        _apply_constraints(rows, t.constraints)

    header = [c.name for c in t.columns]
    ledger = inject_dirty(t, cfg, bundle, rows, parent_keys)
    if ledger and cfg.emit_defect_labels:
        header = header + ["_defect"]
        for rec in ledger:
            rows[rec["row"]].setdefault("_defect", "")
            tag = f"{rec['column']}:{rec['kind']}"
            rows[rec["row"]]["_defect"] = (
                tag if not rows[rec["row"]]["_defect"] else rows[rec["row"]]["_defect"] + "|" + tag)
        for row in rows:
            row.setdefault("_defect", "")

    return Dataset(table=t.name, header=header, rows=rows, defect_ledger=ledger)


def coverage_report(cfg: GenerationConfig, datasets) -> Dict[str, Any]:
    """Per-table edge coverage + dataset-wide FK integrity."""
    report: Dict[str, Any] = {"seed": cfg.seed, "tables": {}, "foreign_keys": {}}
    for t in cfg.tables:
        ds = datasets[t.name]
        present = {c.name: {r.get(c.name) for r in ds.rows} for c in t.columns}
        missing = []
        gens_boundaries = {c.name: c.edge_values for c in t.columns}
        for c in t.columns:
            for ev in gens_boundaries[c.name]:
                if ev not in present[c.name]:
                    missing.append(f"{c.name}={ev}")
        report["tables"][t.name] = {
            "rows": len(ds.rows),
            "defects": len(ds.defect_ledger),
            "declared_edges_missing": missing,
        }
        for fk in t.foreign_keys:
            ref = datasets.get(fk.ref_table)
            if not ref:
                continue
            ref_tbl = cfg.table(fk.ref_table)
            ref_col = fk.ref_column or (ref_tbl.primary_key[0] if ref_tbl and ref_tbl.primary_key
                                        else next((c.name for c in ref_tbl.columns if c.unique), None))
            if not ref_col:
                continue
            valid = {r.get(ref_col) for r in ref.rows}
            broken = sum(1 for r in ds.rows if r.get(fk.column) not in valid)
            report["foreign_keys"][f"{t.name}.{fk.column}->{fk.ref_table}.{ref_col}"] = {
                "child_rows": len(ds.rows), "broken_refs": broken,
                "integrity_ok": broken == 0,
            }
    return report
