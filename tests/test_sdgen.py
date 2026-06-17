"""Test suite for sdgen (version 4 — the superset)."""

from __future__ import annotations

import itertools

import pytest

from sdgen.types import LogicalType, DirtyKind
from sdgen.model import (
    GenerationConfig, TableSpec, ColumnSpec, ForeignKey, CoverageSpec,
    config_from_dict, load_config, validate_config,
)
from sdgen.engine import generate, coverage_report
from sdgen.importers import parse_ddl
from sdgen.presets import preset_config, banking_dataset, EXPOSURE_CLASSES
from sdgen.writers import write_dataset, CsvOptions


def _cfg(mode="edges", dirty=0.0, rows=200):
    return GenerationConfig(
        seed=42, dirty_ratio=dirty, coverage=CoverageSpec(mode=mode),
        tables=[TableSpec(name="t", rows=rows, columns=[
            ColumnSpec(name="id", type=LogicalType.SEQ_ID, unique=True),
            ColumnSpec(name="cls", type=LogicalType.ENUM,
                       allowed_values=["A", "B", "C", "D"]),
            ColumnSpec(name="flag", type=LogicalType.ENUM, allowed_values=["ON", "OFF"]),
            ColumnSpec(name="amount", type=LogicalType.DECIMAL,
                       params={"min": 0, "max": 1000}, scale=2),
        ])],
    )


def test_json_roundtrip():
    cfg = _cfg()
    reloaded = config_from_dict(cfg.to_dict())
    assert [t.name for t in reloaded.tables] == ["t"]
    assert reloaded.tables[0].columns[1].allowed_values == ["A", "B", "C", "D"]


def test_validate_ok_and_errors():
    assert validate_config(_cfg()) == []
    bad = GenerationConfig(tables=[TableSpec(name="t", columns=[
        ColumnSpec(name="x", type=LogicalType.ENUM)])])  # enum without values
    assert any("enum needs allowed_values" in e for e in validate_config(bad))


def test_generation_is_deterministic():
    a = generate(_cfg(dirty=0.1))["t"].rows
    b = generate(_cfg(dirty=0.1))["t"].rows
    assert a == b


def test_seq_id_unique_and_sequential():
    rows = generate(_cfg())["t"].rows
    ids = [r["id"] for r in rows]
    assert len(ids) == len(set(ids))


def test_enum_within_allowed_when_clean():
    rows = generate(_cfg(dirty=0.0))["t"].rows
    assert {r["cls"] for r in rows} <= {"A", "B", "C", "D"}


def test_cartesian_covers_all_combinations():
    rows = generate(_cfg(mode="cartesian"))["t"].rows
    combos = {(r["cls"], r["flag"]) for r in rows}
    assert combos == set(itertools.product(["A", "B", "C", "D"], ["ON", "OFF"]))


def test_pairwise_has_fewer_rows_but_all_pairs():
    rows = generate(_cfg(mode="pairwise"))["t"].rows
    pairs = {(r["cls"], r["flag"]) for r in rows}
    assert pairs == set(itertools.product(["A", "B", "C", "D"], ["ON", "OFF"]))


def test_dirty_ledger_records_defects():
    ds = generate(_cfg(dirty=0.2))["t"]
    assert ds.defect_ledger
    assert all({"row", "column", "kind"} <= set(rec) for rec in ds.defect_ledger)
    assert "_defect" in ds.header


def test_multitable_referential_integrity_clean():
    cfg = banking_dataset()
    cfg.dirty_ratio = 0.0
    for t in cfg.tables:
        t.rows = 50
    ds = generate(cfg)
    parent_ids = {r["id"] for r in ds["counterparties"].rows}
    assert all(r["counterparty_id"] in parent_ids for r in ds["exposures"].rows)
    rep = coverage_report(cfg, ds)
    edge = "exposures.counterparty_id->counterparties.id"
    assert rep["foreign_keys"][edge]["integrity_ok"] is True


def test_ddl_import_to_config():
    ddl = ("CREATE TABLE c (id BIGINT PRIMARY KEY, n VARCHAR(10));\n"
           "CREATE TABLE e (id BIGINT PRIMARY KEY, c_id BIGINT REFERENCES c(id), "
           "kind VARCHAR(10) CHECK (kind IN ('X','Y')));")
    cfg = parse_ddl(ddl)
    assert {t.name for t in cfg.tables} == {"c", "e"}
    e = cfg.table("e")
    assert e.foreign_keys[0].ref_table == "c"
    kind = next(c for c in e.columns if c.name == "kind")
    assert kind.type == LogicalType.ENUM and kind.allowed_values == ["X", "Y"]


def test_preset_generates():
    cfg = preset_config("basel_exposure")
    cfg.dirty_ratio = 0.0
    cfg.tables[0].rows = 50
    rows = generate(cfg)["exposures"].rows
    assert {r["exposure_class"] for r in rows} <= set(EXPOSURE_CLASSES)


# --- v4 superset features + review-fix regressions -------------------------

def test_new_column_types_generate():
    cfg = GenerationConfig(tables=[TableSpec(name="t", rows=30, columns=[
        ColumnSpec(name="f", type=LogicalType.FLOAT, params={"min": 0, "max": 10}),
        ColumnSpec(name="u", type=LogicalType.URL),
        ColumnSpec(name="ip", type=LogicalType.IPV4),
        ColumnSpec(name="note", type=LogicalType.TEXT),
    ])])
    rows = generate(cfg)["t"].rows
    assert len(rows) == 30 and all(0 <= r["f"] <= 10 for r in rows)


def test_constraints_repaired_on_clean_rows():
    cfg = GenerationConfig(tables=[TableSpec(name="t", rows=100, columns=[
        ColumnSpec(name="start", type=LogicalType.DATE, params={"start": "2020-01-01", "end": "2020-06-01"}),
        ColumnSpec(name="end", type=LogicalType.DATE, params={"start": "2020-01-01", "end": "2020-12-01"}),
    ], constraints=["start <= end"])])
    rows = generate(cfg)["t"].rows
    assert all(r["start"] <= r["end"] for r in rows)


def test_yaml_roundtrip():
    cfg = banking_dataset()
    reloaded = load_config(cfg.to_yaml())
    assert [t.name for t in reloaded.tables] == [t.name for t in cfg.tables]
    assert reloaded.table("exposures").foreign_keys[0].ref_table == "counterparties"


def test_unique_exhaustion_raises():
    cfg = GenerationConfig(tables=[TableSpec(name="t", rows=10, columns=[
        ColumnSpec(name="c", type=LogicalType.ENUM, allowed_values=["A", "B", "C"], unique=True)])])
    with pytest.raises(ValueError):
        generate(cfg)


def test_validate_flags_unique_nullable():
    cfg = GenerationConfig(tables=[TableSpec(name="t", columns=[
        ColumnSpec(name="x", type=LogicalType.INTEGER, unique=True, nullable=True)])])
    assert any("nullable" in e for e in validate_config(cfg))


def test_format_violation_defect():
    cfg = GenerationConfig(seed=1, dirty_ratio=1.0, tables=[TableSpec(name="t", rows=40, columns=[
        ColumnSpec(name="email", type=LogicalType.EMAIL, dirty_kinds=[DirtyKind.FORMAT_VIOLATION])])])
    ds = generate(cfg)["t"]
    assert any(rec["kind"] == "format_violation" for rec in ds.defect_ledger)


def test_writers_all_formats(tmp_path):
    cfg = preset_config("basel_exposure")
    cfg.tables[0].rows = 20
    ds = generate(cfg)["exposures"]
    written = write_dataset(ds, str(tmp_path), formats=["csv", "tsv", "json", "sql", "parquet"],
                            csv_options=CsvOptions())
    assert set(written) == {"csv", "tsv", "json", "sql", "parquet"}


def test_path_traversal_filename_sanitised(tmp_path):
    import os
    cfg = preset_config("basel_exposure")
    cfg.tables[0].rows = 5
    ds = generate(cfg)["exposures"]
    written = write_dataset(ds, str(tmp_path), base="../evil", formats=["csv"])
    assert os.path.dirname(os.path.abspath(written["csv"])) == str(tmp_path)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
