"""Import a database schema (CREATE TABLE DDL) into a GenerationConfig.

Mirrors the capability of ``sdg.ddl`` but targets sdgen's dataclass/JSON model
and always produces a multi-table-capable config (with foreign keys wired).
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from .types import LogicalType
from .model import GenerationConfig, TableSpec, ColumnSpec, ForeignKey


_INT = {"INT", "INTEGER", "BIGINT", "SMALLINT", "TINYINT", "MEDIUMINT", "SERIAL",
        "BIGSERIAL", "SMALLSERIAL", "INT2", "INT4", "INT8"}
_DEC = {"DECIMAL", "NUMERIC", "NUMBER", "MONEY", "SMALLMONEY", "DEC", "FLOAT",
        "REAL", "DOUBLE", "BINARY_DOUBLE", "BINARY_FLOAT"}
_BOOL = {"BOOLEAN", "BOOL", "BIT"}
_STR = {"CHAR", "NCHAR", "VARCHAR", "VARCHAR2", "NVARCHAR", "NVARCHAR2", "TEXT",
        "CLOB", "NCLOB", "NTEXT", "STRING", "CHARACTER", "TINYTEXT", "MEDIUMTEXT", "LONGTEXT"}
_UUID = {"UUID", "UNIQUEIDENTIFIER", "GUID"}
_DATE = {"DATE"}
_DT = {"DATETIME", "DATETIME2", "SMALLDATETIME", "TIMESTAMP", "TIMESTAMPTZ", "DATETIMEOFFSET"}

_HEUR: List[Tuple[str, LogicalType]] = [
    (r"e[\-_ ]?mail", LogicalType.EMAIL),
    (r"first[\-_ ]?name|fname", LogicalType.FIRST_NAME),
    (r"last[\-_ ]?name|surname", LogicalType.LAST_NAME),
    (r"full[\-_ ]?name|^name$|customer[\-_ ]?name|legal[\-_ ]?name", LogicalType.NAME),
    (r"phone|mobile|tel", LogicalType.PHONE),
    (r"company|employer|organisation|organization", LogicalType.COMPANY),
    (r"address|street", LogicalType.ADDRESS),
    (r"city|town", LogicalType.CITY),
    (r"^country$", LogicalType.COUNTRY),
    (r"currency", LogicalType.CURRENCY),
]


def _strip(name: str) -> str:
    s = str(name).strip()
    if len(s) >= 2 and ((s[0], s[-1]) in (("[", "]"), ("`", "`"), ('"', '"'))):
        return s[1:-1].strip()
    return s


def _word(t: str) -> str:
    return re.split(r"[\s(]", str(t).strip(), maxsplit=1)[0].upper()


def _map_type(sql_type: str) -> LogicalType:
    w = _word(sql_type)
    if w in _INT:
        return LogicalType.INTEGER
    if w in _DEC:
        return LogicalType.DECIMAL
    if w in _BOOL:
        return LogicalType.BOOLEAN
    if w in _UUID:
        return LogicalType.UUID
    if w in _DATE:
        return LogicalType.DATE
    if w in _DT:
        return LogicalType.DATETIME
    return LogicalType.STRING


def _enum_values(parsed: Dict[str, Any]) -> List[Any]:
    vals: List[Any] = []
    check = parsed.get("check")
    items = check if isinstance(check, list) else ([check] if check else [])
    for it in items:
        if isinstance(it, dict) and "in_statement" in it:
            vals += [_lit(x) for x in it["in_statement"].get("in", [])]
    if not vals and parsed.get("values"):
        vals = [_lit(x) for x in parsed["values"]]
    return vals


def _lit(raw: Any) -> Any:
    s = str(raw).strip()
    if len(s) >= 2 and s[0] in "'\"" and s[-1] == s[0]:
        return s[1:-1]
    try:
        return int(s)
    except ValueError:
        return s


def _column(parsed: Dict[str, Any], pk: List[str], heuristics: bool) -> Tuple[ColumnSpec, Optional[ForeignKey]]:
    name = _strip(parsed.get("name", ""))
    lt = _map_type(parsed.get("type", "string"))
    is_pk = name in pk
    enum_vals = _enum_values(parsed)

    if enum_vals:
        lt = LogicalType.ENUM
    elif lt == LogicalType.INTEGER and is_pk:
        lt = LogicalType.SEQ_ID  # nice 1,2,3 keys for a PK

    col = ColumnSpec(name=name, type=lt)
    col.nullable = bool(parsed.get("nullable", True)) and not is_pk
    col.unique = bool(parsed.get("unique")) or is_pk
    if enum_vals:
        col.allowed_values = enum_vals

    size = parsed.get("size")
    if lt == LogicalType.DECIMAL and isinstance(size, (list, tuple)) and len(size) == 2:
        col.scale = int(size[1])
    elif lt == LogicalType.STRING:
        if isinstance(size, int):
            col.max_length = size
        elif isinstance(size, (list, tuple)) and size and isinstance(size[0], int):
            col.max_length = int(size[0])

    if heuristics and lt == LogicalType.STRING:
        low = name.lower()
        for pat, t in _HEUR:
            if re.search(pat, low):
                col.type = t
                break

    fk = None
    ref = parsed.get("references")
    if isinstance(ref, dict) and ref.get("table"):
        fk = ForeignKey(column=name, ref_table=_strip(ref["table"]),
                        ref_column=_strip(ref["column"]) if ref.get("column") else None)
    return col, fk


def parse_ddl(ddl_text: str, apply_heuristics: bool = True, seed: int = 42,
              dirty_ratio: float = 0.05) -> GenerationConfig:
    from simple_ddl_parser import DDLParser
    try:
        result = DDLParser(ddl_text).run(group_by_type=True)
    except Exception as exc:
        raise ValueError(f"Could not parse DDL: {exc}") from exc

    tables_raw = result.get("tables", []) if isinstance(result, dict) else []
    if not tables_raw:
        raise ValueError("No CREATE TABLE statement found.")

    tables: List[TableSpec] = []
    for tbl in tables_raw:
        name = _strip(tbl.get("table_name") or "table")
        pk = [_strip(p) for p in (tbl.get("primary_key") or [])]
        cols, fks = [], []
        for pc in tbl.get("columns", []):
            if not pc.get("name"):
                continue
            col, fk = _column(pc, pk, apply_heuristics)
            cols.append(col)
            if fk:
                fks.append(fk)
        tables.append(TableSpec(name=name, rows=1000, columns=cols, primary_key=pk, foreign_keys=fks))

    return GenerationConfig(tables=tables, seed=seed, dirty_ratio=dirty_ratio)
