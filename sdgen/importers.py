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


# ---------------------------------------------------------------------------
# Banking name heuristics (shared by the SQL*Loader and Axiom importers)
# ---------------------------------------------------------------------------
def _refine(name: str, size: Optional[int]) -> LogicalType:
    """Infer a better type for an otherwise-generic string column from its name.

    Faker-style names (email/phone/…) always win; numeric/date inference only
    kicks in when there is no explicit CHAR(n) length (size is None).
    """
    low = name.lower()
    for pat, t in _HEUR:
        if re.search(pat, low):
            return t
    if size is None:
        if re.search(r"(dt|date)$", low):
            return LogicalType.DATE
        if re.search(r"(amt|amount|bal|balance|val|value)$", low):
            return LogicalType.DECIMAL
        if re.search(r"(prcnt|pct|percent|rate|ratio|ccf|lgd|ead)$", low):
            return LogicalType.DECIMAL
    return LogicalType.STRING


# ---------------------------------------------------------------------------
# Oracle SQL*Loader control file (.ctl)
# ---------------------------------------------------------------------------
def _split_top_level(s: str) -> List[str]:
    """Split on commas that are not inside parentheses or quotes."""
    out, buf, depth, q = [], [], 0, None
    for ch in s:
        if q:
            buf.append(ch)
            if ch == q:
                q = None
            continue
        if ch in "'\"":
            q = ch
            buf.append(ch)
        elif ch == "(":
            depth += 1
            buf.append(ch)
        elif ch == ")":
            depth = max(0, depth - 1)
            buf.append(ch)
        elif ch == "," and depth == 0:
            out.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if "".join(buf).strip():
        out.append("".join(buf))
    return out


def _ctl_field_block(text: str) -> Optional[str]:
    """Return the contents of the parenthesised field list."""
    anchor = 0
    for pat in (r"\bNULLCOLS\b", r"FIELDS\s+TERMINATED\s+BY\s+\S+", r"INTO\s+TABLE\s+\S+"):
        m = re.search(pat, text, re.I)
        if m:
            anchor = m.end()
            break
    start = text.find("(", anchor)
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return text[start + 1:i]
    return text[start + 1:]


def _ctl_field_spec(rest: str) -> Tuple[LogicalType, Optional[int]]:
    r = rest.strip()
    ru = r.upper()
    size_m = re.search(r"\(\s*(\d+)", r)
    size = int(size_m.group(1)) if size_m else None
    if ru.startswith("DATE"):
        fmt = re.search(r"'([^']*)'", r)
        if fmt and re.search(r"hh|mi|ss", fmt.group(1), re.I):
            return LogicalType.DATETIME, None
        return LogicalType.DATE, None
    if ru.startswith("TIMESTAMP"):
        return LogicalType.DATETIME, None
    if ru.startswith(("INTEGER", "INT ")) or ru == "INT":
        return LogicalType.INTEGER, None
    if ru.startswith(("DECIMAL", "NUMERIC", "FLOAT", "ZONED")):
        return LogicalType.DECIMAL, None
    if ru.startswith(("CHAR", "VARCHAR", "VARCHARC", "RAW", "VARRAW")):
        return LogicalType.STRING, size
    return LogicalType.STRING, size  # no/unknown type -> Oracle defaults to CHAR


def parse_sqlloader_ctl(text: str, apply_heuristics: bool = True, seed: int = 42,
                        dirty_ratio: float = 0.05) -> GenerationConfig:
    """Parse an Oracle SQL*Loader control file (.ctl) into a GenerationConfig."""
    table = "loaded_table"
    mt = re.search(r"INTO\s+TABLE\s+([^\s(]+)", text, re.I)
    if mt:
        t = _strip(mt.group(1))
        if t and not t.startswith(("@", ":")) and re.match(r"[A-Za-z_]", t):
            table = t

    block = _ctl_field_block(text)
    if not block:
        raise ValueError("Could not find the field list '(…)' in the control file.")

    cols: List[ColumnSpec] = []
    for raw in _split_top_level(block):
        f = raw.strip()
        if not f:
            continue
        if re.match(r"(WHEN|CONSTANT|FILLER|POSITION)\b", f, re.I):
            continue
        m = re.match(r'^"?([A-Za-z_][\w$#]*)"?\s*(.*)$', f, re.S)
        if not m:
            continue
        name, rest = m.group(1), m.group(2)
        lt, size = _ctl_field_spec(rest)
        col = ColumnSpec(name=name, type=lt)
        if lt == LogicalType.STRING and size:
            col.max_length = size
        if apply_heuristics and col.type == LogicalType.STRING:
            col.type = _refine(name, size)
        cols.append(col)

    if not cols:
        raise ValueError("No fields parsed from the control file.")
    return GenerationConfig(tables=[TableSpec(name=table, rows=1000, columns=cols)],
                            seed=seed, dirty_ratio=dirty_ratio)


# ---------------------------------------------------------------------------
# Axiom "DataSource" schema (XML)
# ---------------------------------------------------------------------------
def _axiom_type(t: str) -> LogicalType:
    u = str(t).strip().upper()
    return {
        "INTEGER": LogicalType.INTEGER, "INT": LogicalType.INTEGER, "LONG": LogicalType.INTEGER,
        "FLOAT": LogicalType.DECIMAL, "DOUBLE": LogicalType.DECIMAL, "DECIMAL": LogicalType.DECIMAL,
        "NUMERIC": LogicalType.DECIMAL, "MONEY": LogicalType.DECIMAL,
        "BOOLEAN": LogicalType.BOOLEAN, "BOOL": LogicalType.BOOLEAN, "BIT": LogicalType.BOOLEAN,
        "DATE": LogicalType.DATE, "DATETIME": LogicalType.DATETIME, "TIMESTAMP": LogicalType.DATETIME,
        "STRING": LogicalType.STRING, "TEXT": LogicalType.TEXT, "CHAR": LogicalType.STRING,
    }.get(u, LogicalType.STRING)


def parse_axiom_xml(xml_text: str, apply_heuristics: bool = True, seed: int = 42,
                    dirty_ratio: float = 0.05) -> GenerationConfig:
    """Parse an Axiom 'DataSource' schema (XML) into a GenerationConfig."""
    import xml.etree.ElementTree as ET

    txt = xml_text.strip()
    try:
        root = ET.fromstring(txt)
    except ET.ParseError:
        try:
            root = ET.fromstring(f"<root>{txt}</root>")  # tolerate a pasted fragment
        except ET.ParseError as exc:
            raise ValueError(f"Could not parse Axiom XML: {exc}") from exc

    ds = root if root.get("type") == "DataSource" else root.find(".//object[@type='DataSource']")
    if ds is None:
        ds = root

    def _props(obj) -> Dict[str, Any]:
        return {p.get("name"): p.get("value") for p in obj.findall("property")}

    table = _strip(_props(ds).get("name") or "axiom_table")
    fields = ds.findall(".//object[@type='DataSource:field']")
    if not fields:
        fields = root.findall(".//object[@type='DataSource:field']")

    cols: List[ColumnSpec] = []
    for fobj in fields:
        p = _props(fobj)
        name = _strip(p.get("name") or "")
        if not name:
            continue
        col = ColumnSpec(name=name, type=_axiom_type(p.get("type", "STRING")))
        col.nullable = str(p.get("allowNulls", "true")).lower() == "true"
        if str(p.get("isAutoUniqueId", "false")).lower() == "true":
            col.type = LogicalType.SEQ_ID
            col.unique = True
            col.nullable = False
        if p.get("description"):
            col.description = p["description"]
        if apply_heuristics and col.type == LogicalType.STRING:
            col.type = _refine(name, None)
        cols.append(col)

    if not cols:
        raise ValueError("No <object type='DataSource:field'> entries found in the Axiom XML.")
    return GenerationConfig(tables=[TableSpec(name=table, rows=1000, columns=cols)],
                            seed=seed, dirty_ratio=dirty_ratio)
