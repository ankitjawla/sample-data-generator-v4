"""Config model for sdgen — dataclasses with JSON (de)serialisation.

A whole run is one ``GenerationConfig``: a list of tables (single-table is just a
one-element list), a global seed, a dirty-row ratio and a coverage spec. The JSON
form fully determines the output, so it is the reproducible artifact to check in.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

try:
    import yaml
    _HAS_YAML = True
except Exception:  # pragma: no cover
    _HAS_YAML = False

from .types import LogicalType, DirtyKind, COVERAGE_MODES


@dataclass
class CoverageSpec:
    mode: str = "edges"                       # off | edges | cartesian | pairwise
    columns: Optional[List[str]] = None
    cap: int = 5000


@dataclass
class ForeignKey:
    column: str
    ref_table: str
    ref_column: Optional[str] = None


@dataclass
class ColumnSpec:
    name: str
    type: LogicalType = LogicalType.STRING
    params: Dict[str, Any] = field(default_factory=dict)
    allowed_values: List[Any] = field(default_factory=list)   # enum domain
    weights: Optional[List[float]] = None
    nullable: bool = False
    null_probability: float = 0.0
    unique: bool = False
    max_length: Optional[int] = None
    precision: Optional[int] = None
    scale: Optional[int] = None
    edge_values: List[Any] = field(default_factory=list)      # must-appear values
    dirty_kinds: Optional[List[DirtyKind]] = None             # None => default for type
    dirty_examples: List[Any] = field(default_factory=list)   # forced bad values
    description: str = ""


@dataclass
class TableSpec:
    name: str = "table"
    rows: int = 1000
    columns: List[ColumnSpec] = field(default_factory=list)
    primary_key: List[str] = field(default_factory=list)
    foreign_keys: List[ForeignKey] = field(default_factory=list)
    constraints: List[str] = field(default_factory=list)   # cross-column rules, e.g. "start <= end"


@dataclass
class GenerationConfig:
    tables: List[TableSpec] = field(default_factory=list)
    seed: int = 42
    locale: str = "en_US"
    dirty_ratio: float = 0.0
    default_dirty_kinds: Optional[List[DirtyKind]] = None
    coverage: CoverageSpec = field(default_factory=CoverageSpec)
    emit_defect_labels: bool = True

    # -- convenience ----------------------------------------------------------
    def table(self, name: str) -> Optional[TableSpec]:
        return next((t for t in self.tables if t.name == name), None)

    # -- (de)serialisation ----------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        return {
            "seed": self.seed,
            "locale": self.locale,
            "dirty_ratio": self.dirty_ratio,
            "default_dirty_kinds": ([d.value for d in self.default_dirty_kinds]
                                    if self.default_dirty_kinds is not None else None),
            "coverage": {"mode": self.coverage.mode, "columns": self.coverage.columns,
                         "cap": self.coverage.cap},
            "emit_defect_labels": self.emit_defect_labels,
            "tables": [_table_to_dict(t) for t in self.tables],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, default=str)

    def to_yaml(self) -> str:
        if not _HAS_YAML:
            raise RuntimeError("PyYAML not installed (pip install pyyaml).")
        return yaml.safe_dump(self.to_dict(), sort_keys=False, allow_unicode=True)


def _table_to_dict(t: TableSpec) -> Dict[str, Any]:
    d: Dict[str, Any] = {
        "name": t.name,
        "rows": t.rows,
        "primary_key": t.primary_key,
        "foreign_keys": [{"column": fk.column, "ref_table": fk.ref_table,
                          "ref_column": fk.ref_column} for fk in t.foreign_keys],
        "columns": [_column_to_dict(c) for c in t.columns],
    }
    if t.constraints:
        d["constraints"] = t.constraints
    return d


def _column_to_dict(c: ColumnSpec) -> Dict[str, Any]:
    d: Dict[str, Any] = {"name": c.name, "type": c.type.value}
    if c.params:
        d["params"] = c.params
    if c.allowed_values:
        d["allowed_values"] = c.allowed_values
    if c.weights:
        d["weights"] = c.weights
    if c.nullable:
        d["nullable"] = True
        if c.null_probability:
            d["null_probability"] = c.null_probability
    if c.unique:
        d["unique"] = True
    for k in ("max_length", "precision", "scale"):
        v = getattr(c, k)
        if v is not None:
            d[k] = v
    if c.edge_values:
        d["edge_values"] = c.edge_values
    if c.dirty_kinds is not None:
        d["dirty_kinds"] = [dk.value for dk in c.dirty_kinds]
    if c.dirty_examples:
        d["dirty_examples"] = c.dirty_examples
    if c.description:
        d["description"] = c.description
    return d


def _column_from_dict(d: Dict[str, Any]) -> ColumnSpec:
    dirty_kinds = d.get("dirty_kinds")
    return ColumnSpec(
        name=d["name"],
        type=LogicalType(d.get("type", "string")),
        params=d.get("params", {}) or {},
        allowed_values=d.get("allowed_values", []) or [],
        weights=d.get("weights"),
        nullable=bool(d.get("nullable", False)),
        null_probability=float(d.get("null_probability", 0.0)),
        unique=bool(d.get("unique", False)),
        max_length=d.get("max_length"),
        precision=d.get("precision"),
        scale=d.get("scale"),
        edge_values=d.get("edge_values", []) or [],
        dirty_kinds=[DirtyKind(x) for x in dirty_kinds] if dirty_kinds is not None else None,
        dirty_examples=d.get("dirty_examples", []) or [],
        description=d.get("description", ""),
    )


def _table_from_dict(d: Dict[str, Any]) -> TableSpec:
    return TableSpec(
        name=d.get("name", "table"),
        rows=int(d.get("rows", 1000)),
        columns=[_column_from_dict(c) for c in d.get("columns", [])],
        primary_key=list(d.get("primary_key", [])),
        foreign_keys=[ForeignKey(column=fk.get("column"), ref_table=fk.get("ref_table"),
                                 ref_column=fk.get("ref_column"))
                      for fk in d.get("foreign_keys", []) if fk.get("column") and fk.get("ref_table")],
        constraints=list(d.get("constraints", [])),
    )


def config_from_dict(data: Dict[str, Any]) -> GenerationConfig:
    # Accept either a full config ({"tables": [...]}) or a bare single table.
    if "tables" not in data and "columns" in data:
        data = {"tables": [data], "seed": data.get("seed", 42)}
    cov = data.get("coverage", {}) or {}
    ddk = data.get("default_dirty_kinds")
    return GenerationConfig(
        tables=[_table_from_dict(t) for t in data.get("tables", [])],
        seed=int(data.get("seed", 42)),
        locale=str(data.get("locale", "en_US")),
        dirty_ratio=float(data.get("dirty_ratio", 0.0)),
        default_dirty_kinds=[DirtyKind(x) for x in ddk] if ddk is not None else None,
        coverage=CoverageSpec(mode=cov.get("mode", "edges"), columns=cov.get("columns"),
                              cap=int(cov.get("cap", 5000))),
        emit_defect_labels=bool(data.get("emit_defect_labels", True)),
    )


def load_config(text: str) -> GenerationConfig:
    """Load a config from JSON or YAML text (auto-detected)."""
    s = text.strip()
    if s.startswith("{") or s.startswith("["):
        data = json.loads(s)
    elif _HAS_YAML:
        data = yaml.safe_load(s)
    else:
        data = json.loads(s)
    return config_from_dict(data)


def load_config_file(path: str) -> GenerationConfig:
    with open(path, encoding="utf-8") as f:
        return load_config(f.read())


def validate_config(cfg: GenerationConfig) -> List[str]:
    errors: List[str] = []
    if not cfg.tables:
        errors.append("Config has no tables.")
    if not (0.0 <= cfg.dirty_ratio <= 1.0):
        errors.append("`dirty_ratio` must be between 0 and 1.")
    if cfg.coverage.mode not in COVERAGE_MODES:
        errors.append(f"Unknown coverage mode '{cfg.coverage.mode}'.")

    names = [t.name for t in cfg.tables]
    if len(set(names)) != len(names):
        errors.append("Duplicate table names.")

    for t in cfg.tables:
        if t.rows <= 0:
            errors.append(f"[{t.name}] rows must be positive.")
        col_names = {c.name for c in t.columns}
        if not t.columns:
            errors.append(f"[{t.name}] has no columns.")
        for c in t.columns:
            if c.type == LogicalType.ENUM and not c.allowed_values:
                errors.append(f"[{t.name}.{c.name}] enum needs allowed_values.")
            if c.weights and c.allowed_values and len(c.weights) != len(c.allowed_values):
                errors.append(f"[{t.name}.{c.name}] weights length must match allowed_values.")
            if not (0.0 <= c.null_probability <= 1.0):
                errors.append(f"[{t.name}.{c.name}] null_probability must be 0..1.")
            if c.unique and c.nullable:
                errors.append(f"[{t.name}.{c.name}] cannot be both unique and nullable.")
        for fk in t.foreign_keys:
            if fk.column not in col_names:
                errors.append(f"[{t.name}] FK column '{fk.column}' not in table.")
            if fk.ref_table not in names:
                errors.append(f"[{t.name}] FK references unknown table '{fk.ref_table}'.")
    return errors
