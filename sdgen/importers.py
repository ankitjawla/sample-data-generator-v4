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


# ---------------------------------------------------------------------------
# Generic XML schema extraction (Axiom DataSource / XSD / sample XML)
# ---------------------------------------------------------------------------
_XSD_NS = "http://www.w3.org/2001/XMLSchema"


def _localname(tag: str) -> str:
    return str(tag).rsplit("}", 1)[-1]


def _xsd_type(t: Optional[str]) -> LogicalType:
    u = str(t or "").split(":")[-1].lower()
    if u in {"integer", "int", "long", "short", "byte", "nonnegativeinteger",
             "positiveinteger", "unsignedint", "unsignedlong"}:
        return LogicalType.INTEGER
    if u in {"decimal", "double", "float"}:
        return LogicalType.DECIMAL
    if u in {"boolean"}:
        return LogicalType.BOOLEAN
    if u in {"date", "gyear", "gyearmonth"}:
        return LogicalType.DATE
    if u in {"datetime", "time"}:
        return LogicalType.DATETIME
    return LogicalType.STRING


def _infer_type(values: List[str]) -> Tuple[LogicalType, List[Any]]:
    vals = [v for v in (str(x).strip() for x in values) if v not in ("", "None")]
    if not vals:
        return LogicalType.STRING, []

    def _is_int(s):
        try:
            int(s); return True
        except ValueError:
            return False

    def _is_float(s):
        try:
            float(s); return True
        except ValueError:
            return False

    if all(_is_int(v) for v in vals):
        return LogicalType.INTEGER, []
    if all(_is_float(v) for v in vals):
        return LogicalType.DECIMAL, []
    if all(re.match(r"^\d{4}-\d{2}-\d{2}$", v) for v in vals):
        return LogicalType.DATE, []
    if all(re.match(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}", v) for v in vals):
        return LogicalType.DATETIME, []
    distinct = sorted({v for v in vals})
    if 1 < len(distinct) <= 8:  # low cardinality -> categorical with expected values
        return LogicalType.ENUM, distinct
    return LogicalType.STRING, []


def parse_xsd(root, apply_heuristics: bool = True, seed: int = 42,
              dirty_ratio: float = 0.05) -> GenerationConfig:
    """Parse an XSD (XML Schema) into a GenerationConfig."""
    ns = "{" + _XSD_NS + "}"
    table = "xml_table"
    cols: List[ColumnSpec] = []
    for e in root.iter():
        if _localname(e.tag) != "element":
            continue
        name = e.get("name")
        if not name:
            continue
        typ = e.get("type")
        restr = e.find(f"./{ns}simpleType/{ns}restriction")  # direct, not descendant
        if typ is None and restr is None:
            if e.find(f"./{ns}complexType") is not None and table == "xml_table":
                table = _strip(name)  # the record/wrapper element
            continue
        col = ColumnSpec(name=_strip(name),
                         type=_xsd_type(typ or (restr.get("base") if restr is not None else None)))
        if e.get("minOccurs") == "0" or str(e.get("nillable", "")).lower() == "true":
            col.nullable = True
        if restr is not None:
            enums = [x.get("value") for x in restr.findall(f"{ns}enumeration") if x.get("value") is not None]
            if enums:
                col.type = LogicalType.ENUM
                col.allowed_values = enums
            ml = restr.find(f"{ns}maxLength")
            if ml is not None and ml.get("value") and col.type == LogicalType.STRING:
                col.max_length = int(ml.get("value"))
        if apply_heuristics and col.type == LogicalType.STRING:
            col.type = _refine(col.name, col.max_length)
        cols.append(col)
    if not cols:
        raise ValueError("No <xs:element> field definitions found in the XSD.")
    return GenerationConfig(tables=[TableSpec(name=table, rows=1000, columns=cols)],
                            seed=seed, dirty_ratio=dirty_ratio)


def parse_xml_sample(root, apply_heuristics: bool = True, seed: int = 42,
                     dirty_ratio: float = 0.05) -> GenerationConfig:
    """Infer a schema from a sample XML data document (repeated record elements)."""
    from collections import Counter, OrderedDict

    candidates: Counter = Counter()
    for parent in root.iter():
        counts = Counter(_localname(c.tag) for c in list(parent))
        for tag, n in counts.items():
            if n >= 2:
                candidates[tag] += n
    if candidates:
        rec_tag = candidates.most_common(1)[0][0]
        records = [e for e in root.iter() if _localname(e.tag) == rec_tag]
        table = rec_tag
    else:
        records = [root]
        table = _localname(root.tag)

    fields: "OrderedDict[str, List[str]]" = OrderedDict()
    for rec in records[:100]:
        for a, v in rec.attrib.items():
            fields.setdefault(_localname(a), []).append(v)
        for child in list(rec):
            if len(list(child)) == 0:  # leaf element only
                fields.setdefault(_localname(child.tag), []).append((child.text or "").strip())
    if not fields:
        raise ValueError("Could not infer any fields from the XML sample.")

    cols: List[ColumnSpec] = []
    for name, vals in fields.items():
        lt, enum_vals = _infer_type(vals)
        col = ColumnSpec(name=_strip(name), type=lt)
        if enum_vals:
            col.allowed_values = enum_vals
        if apply_heuristics and col.type == LogicalType.STRING:
            col.type = _refine(col.name, None)
        cols.append(col)
    return GenerationConfig(tables=[TableSpec(name=table, rows=1000, columns=cols)],
                            seed=seed, dirty_ratio=dirty_ratio)


def parse_xml(xml_text: str, apply_heuristics: bool = True, seed: int = 42,
              dirty_ratio: float = 0.05) -> GenerationConfig:
    """Extract a schema from XML — auto-detects Axiom DataSource, XSD, or sample data."""
    import xml.etree.ElementTree as ET

    txt = xml_text.strip()
    if "DataSource:field" in txt or 'type="DataSource"' in txt or "type='DataSource'" in txt:
        return parse_axiom_xml(txt, apply_heuristics, seed, dirty_ratio)
    try:
        root = ET.fromstring(txt)
    except ET.ParseError:
        try:
            root = ET.fromstring(f"<root>{txt}</root>")
        except ET.ParseError as exc:
            raise ValueError(f"Could not parse XML: {exc}") from exc

    is_xsd = (_localname(root.tag).lower() == "schema"
              or any(str(e.tag).startswith("{" + _XSD_NS + "}") for e in root.iter()))
    if is_xsd:
        return parse_xsd(root, apply_heuristics, seed, dirty_ratio)
    return parse_xml_sample(root, apply_heuristics, seed, dirty_ratio)
