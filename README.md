# 🛠️ Sample Data Generator — v4 (the superset)

The clean, do-everything version. One package (`sdgen`) that combines the breadth
of v1, the clean architecture of v2, and the polished UI from v3 — then goes
beyond all three. Generate **production-like sample data** from a schema, **plus
deliberate garbage rows** that break pipelines, with edge-case + combinatorial
coverage, multi-table foreign keys, cross-column constraints, and fully
reproducible seeded output. **Pure Python, no LLM.**

> Part of a 4-version comparison set:
> [v1](https://github.com/ankitjawla/sample-data-generator) ·
> [v2](https://github.com/ankitjawla/sample-data-generator-v2) ·
> [v3](https://github.com/ankitjawla/sample-data-generator-v3) · **v4 (this one)**

## What makes v4 the superset

| Capability | v1 | v2 | **v4** |
|---|:--:|:--:|:--:|
| Clean dataclass engine + plugin-registry generators | – | ✓ | ✓ |
| Multi-table foreign keys + referential integrity | – | ✓ | ✓ |
| Per-cell **defect ledger** (`_defect` column) | – | ✓ | ✓ |
| Per-column reproducible RNG sub-streams | – | ✓ | ✓ |
| **JSON _and_ YAML** config | YAML | JSON | **both** |
| Column types | 24 | 18 | **26** |
| Writers (CSV/TSV/JSON/JSONL/Parquet/XLSX/SQL) | ✓ | partial | **all 7** |
| Distributions (uniform/normal/exponential) | ✓ | partial | ✓ |
| **Cross-column constraints** (`start <= end`) | ✓ | – | ✓ |
| Fault/dirty taxonomy incl. `format_violation`, `broken_fk` | ✓ | ✓ | **union** |
| DDL paste-import + banking presets | ✓ | ✓ | ✓ |
| Enhanced UI: Guide tab, dirty-cell highlighting, charts, KPIs | ✓ | ✓ | ✓ |
| **Reviewed & hardened** (unique-exhaustion, path-traversal, FK determinism) | — | — | ✓ |

## Install & run

Only **Python 3** is needed. The launchers create/reuse a venv, install deps, run.

| OS | Launcher (runs on **http://localhost:8504**) |
|----|----|
| **Windows** | double-click `run.bat` (or `run.ps1`) |
| **macOS** | double-click `run.command` |
| **Linux** | `./run.sh` |

Manual: `pip install -r requirements.txt && streamlit run app.py`

## How to use the app

Five-step flow across four tabs:

1. **🚀 Start here** — 3-step guide, one-click worked examples, glossary.
2. **📥 Import / Presets** — paste a `CREATE TABLE` (CHECK-lists → expected
   values, REFERENCES → foreign keys) or load a banking preset.
3. **🧩 Config (JSON/YAML)** — the reproducible source of truth; edit, validate,
   download as JSON **or** YAML.
4. **▶️ Generate** — staged progress, **dirty cells highlighted** (🟥 corrupted ·
   🟨 defect tag), a "dirty rows only" negative-test pack, defect-mix chart, KPI
   cards with a **Data-health verdict**, FK-integrity summary, a 🔁 reproduce
   recipe, and a pipeline-test teaching callout. Download per table.

## Copy-paste example (JSON; YAML works too)

```json
{
  "seed": 42,
  "dirty_ratio": 0.08,
  "coverage": { "mode": "cartesian" },
  "tables": [
    { "name": "counterparties", "rows": 200, "primary_key": ["id"], "columns": [
        { "name": "id", "type": "seq_id", "unique": true },
        { "name": "legal_name", "type": "company" },
        { "name": "sector", "type": "enum", "allowed_values": ["Bank","Corporate","Sovereign"] } ] },
    { "name": "exposures", "rows": 5000,
      "foreign_keys": [ { "column": "counterparty_id", "ref_table": "counterparties", "ref_column": "id" } ],
      "constraints": ["start_date <= end_date"],
      "columns": [
        { "name": "exposure_id", "type": "seq_id", "unique": true },
        { "name": "counterparty_id", "type": "integer" },
        { "name": "exposure_class", "type": "enum",
          "allowed_values": ["Corporate","Institution","Retail","Sovereign"] },
        { "name": "on_balance_flag", "type": "enum", "allowed_values": ["ON","OFF"],
          "nullable": true, "null_probability": 0.05, "dirty_examples": [", ", "on"] },
        { "name": "exposure_amount", "type": "decimal", "params": {"min":0,"max":5000000}, "scale": 2 },
        { "name": "email", "type": "email" },
        { "name": "start_date", "type": "date", "params": {"start":"2015-01-01","end":"2020-01-01"} },
        { "name": "end_date", "type": "date", "params": {"start":"2020-01-01","end":"today"} } ] }
  ]
}
```

## CLI

```bash
python -m sdgen.cli validate   config.json          # or config.yaml
python -m sdgen.cli generate   config.yaml --out ./output --formats csv tsv parquet xlsx sql
python -m sdgen.cli import-ddl  schema.sql --out config.json
python -m sdgen.cli preset      banking-dataset --out config.json
```

`generate` flags: `--seed --rows --coverage-mode --dirty-ratio --delimiter
--quoting {minimal,all,nonnumeric,none} --encoding --bom --line-ending`.

## Library

```python
from sdgen import load_config_file, validate_config, generate, coverage_report
from sdgen.writers import write_all, CsvOptions

cfg = load_config_file("config.yaml")          # JSON or YAML auto-detected
assert not validate_config(cfg)
datasets = generate(cfg)                         # {table_name: Dataset}
write_all(datasets, "./output", formats=["csv", "parquet"],
          report=coverage_report(cfg, datasets))
```

## Architecture

```
sdgen/
├── types.py        # LogicalType (26), DirtyKind (13), OutputFormat, coverage modes
├── model.py        # dataclasses + JSON/YAML IO + validation (+ constraints)
├── rng.py          # RngBundle: seeded per-column sub-streams
├── generators.py   # plugin registry: one class per type
├── coverage.py     # edges / cartesian (capped) / pairwise
├── dirty.py        # full dirty taxonomy + defect ledger
├── engine.py       # orchestrator: clean + coverage + FK + constraints + dirty
├── importers.py    # CREATE TABLE DDL -> config
├── writers.py      # csv/tsv/json/jsonl/parquet/xlsx/sql (+ path-safe filenames)
├── presets.py      # banking/regulatory configs + columns
└── cli.py          # generate / validate / import-ddl / preset
```

## Quality

Built from a code review of v1–v3 (51 confirmed findings). v4 fixes the
highest-impact ones: unique-column exhaustion now **fails fast** instead of
silently emitting duplicates; output filenames are **path-traversal-safe**;
foreign-key target selection is **deterministic** (prefers the primary key);
parent NULLs are excluded from FK pools; the UI **catches generation errors**.
`pytest` covers determinism, coverage, FK integrity, constraints, YAML round-trip,
the new types, and each fix.
