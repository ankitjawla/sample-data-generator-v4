"""sdgen v4 — the clean superset sample data generator (no LLM).

Combines the breadth of v1 (many column types, all writers, fault strategies,
YAML) with the clean architecture of v2 (dataclass + JSON config, plugin-registry
generators, per-column RNG sub-streams, multi-table foreign keys, per-cell defect
ledger) plus cross-column constraints. One clean package with everything.
"""

from __future__ import annotations

from .types import LogicalType, DirtyKind, OutputFormat, COVERAGE_MODES
from .model import (
    GenerationConfig, TableSpec, ColumnSpec, ForeignKey, CoverageSpec,
    load_config, load_config_file, config_from_dict, validate_config,
)
from .engine import generate, coverage_report, Dataset

__all__ = [
    "LogicalType", "DirtyKind", "OutputFormat", "COVERAGE_MODES",
    "GenerationConfig", "TableSpec", "ColumnSpec", "ForeignKey", "CoverageSpec",
    "load_config", "load_config_file", "config_from_dict", "validate_config",
    "generate", "coverage_report", "Dataset",
]

__version__ = "4.0.0"
