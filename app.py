"""Streamlit UI for sdgen v4 — the clean superset generator.

Run:  streamlit run app.py
Superset of v1+v2+v3: dataclass JSON *and* YAML config, plugin-registry engine,
per-column RNG sub-streams, multi-table foreign keys, cross-column constraints,
the full fault taxonomy, all writers, and a per-cell defect ledger. Indigo accent.
"""

from __future__ import annotations

import base64
import json
import os
import time
from collections import Counter

import pandas as pd
import streamlit as st

from sdgen.model import config_from_dict, load_config, validate_config, _column_to_dict
from sdgen.engine import generate, coverage_report
from sdgen.writers import CsvOptions, QUOTING_MODES, render_csv, render_json
from sdgen.presets import PRESET_COLUMNS, list_presets, preset_config
from sdgen.types import COVERAGE_MODES, LogicalType, DirtyKind

try:
    from sdgen.importers import parse_ddl, parse_sqlloader_ctl, parse_xml
    _HAS_DDL = True
except Exception:
    _HAS_DDL = False

st.set_page_config(page_title="Sample Data Generator v4 (superset)", page_icon="🛠️", layout="wide")

ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")

# ----------------------------------------------------------------------------
# Branding — left & right of the title. Drop logos in assets/ (capgemini.* /
# barclays.*) to override the text wordmarks. Set a name to "" to hide a side.
# These ship in a PUBLIC repo, so edit to taste (own company/client, or blank).
# ----------------------------------------------------------------------------
BRAND_LEFT = os.environ.get("SDG_BRAND_LEFT", "Capgemini")
BRAND_LEFT_TAG = os.environ.get("SDG_BRAND_LEFT_TAG", "Engineering")
BRAND_RIGHT = os.environ.get("SDG_BRAND_RIGHT", "Barclays")
BRAND_RIGHT_TAG = os.environ.get("SDG_BRAND_RIGHT_TAG", "Client")


# ----------------------------------------------------------------------------
# Help + glossary
# ----------------------------------------------------------------------------
HELP = {
    "seed": "The random seed. The SAME seed always produces the SAME data — ideal for "
            "repeatable tests. Change it for a different draw. Example: `42`.",
    "dirty_ratio": "Share of rows that receive at least one dirty value. "
                   "Example: 0.05 = 5%. Set to 0 for clean data only.",
    "coverage_mode": "How thoroughly to cover value combinations:\n\n"
                     "• `edges` — one row per boundary value (default)\n"
                     "• `cartesian` — every combination of enum/boolean columns\n"
                     "• `pairwise` — every value pair, in far fewer rows\n"
                     "• `off` — pure random fill",
    "coverage_cap": "Safety limit on rows added by cartesian coverage, so a few wide "
                    "categoricals can't explode into millions of rows. Example: `5000`.",
    "formats": "Output file types to write: CSV, JSON, JSONL, SQL, XLSX.",
    "delimiter": "Field separator for CSV. Examples: `,` (comma), `;`, `|` (pipe).",
    "quoting": "`minimal` keeps the file valid; `none` writes unquoted fields so an "
               "embedded-comma fault actually shifts columns (a negative test).",
    "encoding": "Character encoding. `utf-8` is standard; `cp1252`/`latin-1` test "
                "legacy-encoding handling.",
    "bom": "Adds a UTF-8 byte-order mark — some Windows tools (e.g. Excel) expect it.",
    "ddl": "Paste a `CREATE TABLE`. `CHECK (col IN …)` and `ENUM(…)` become enum columns "
           "whose expected values are exactly those; `REFERENCES` become foreign keys.",
    "preset": "Ready-made banking configs (single exposure feed, counterparties, or a "
              "linked dataset) with sensible expected values and fault examples baked in.",
    "config": "The full JSON config — the reproducible artifact. Build it from DDL/presets, "
              "edit it here, and check it into git. Same config + seed ⇒ identical data.",
}

GLOSSARY_DIRTY = {
    "embedded_delimiter": "Stray comma / quote / newline inside a field.",
    "whitespace": "Leading / trailing spaces around the value.",
    "null_variant": "NULL / empty string / ' ' / 'N/A' where a value is required.",
    "type_mismatch": "Wrong type — e.g. 'thirty' in a numeric column.",
    "out_of_range": "Value below min / above max.",
    "format_violation": "Malformed email / date / url / phone / ip.",
    "leading_zero": "Stripped leading zeros or scientific notation (007, 1.2E+10).",
    "date_ambiguity": "Ambiguous or invalid date (03/04/2020, 2023-13-45).",
    "encoding": "Unicode / mojibake / smart quotes / control characters.",
    "invalid_enum_case": "Invalid enum casing — corporate / CORPORATE / Corp.",
    "truncation": "Value cut short.",
    "duplicate_pk": "Repeated value in a unique key.",
    "broken_fk": "Foreign key pointing at a non-existent parent row.",
}
GLOSSARY_COVERAGE = {
    "off": "No coverage pass — purely random rows.",
    "edges": "One row per boundary value per column (default).",
    "cartesian": "Every combination of the enum/boolean columns (capped).",
    "pairwise": "Every pair of values co-occurs at least once — far fewer rows.",
}


# ----------------------------------------------------------------------------
# Branded header (teal accent)
# ----------------------------------------------------------------------------
def _logo_html(basename: str, css_class: str):
    for ext in ("svg", "png", "jpg", "jpeg", "webp"):
        path = os.path.join(ASSETS_DIR, f"{basename}.{ext}")
        if os.path.exists(path):
            mime = "svg+xml" if ext == "svg" else ext
            with open(path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            return f'<img class="brand-logo {css_class}" src="data:image/{mime};base64,{b64}"/>'
    return None


def render_header():
    st.markdown(
        """
        <style>
        .block-container { padding-top: 1.4rem; }
        .app-header {
            display: flex; align-items: center; justify-content: space-between;
            gap: 1rem; padding: 18px 26px; margin-bottom: 8px; border-radius: 16px;
            background: linear-gradient(120deg, #1e1b4b 0%, #4f46e5 55%, #8b7cf6 100%);
            box-shadow: 0 8px 26px rgba(30, 27, 75, 0.30);
        }
        .app-title { text-align: center; flex: 1; }
        .title-main { color: #ffffff; font-size: 1.7rem; font-weight: 800; line-height: 1.15; }
        .title-sub { color: #e0e7ff; font-size: .86rem; margin-top: 4px; font-weight: 500; }
        .brand-box {
            background: rgba(255,255,255,.96); border-radius: 12px; padding: 10px 18px;
            min-width: 150px; text-align: center; box-shadow: 0 2px 8px rgba(0,0,0,.18);
        }
        .brand-logo { max-height: 40px; max-width: 170px; display: block; margin: 0 auto; }
        .wordmark { font-weight: 800; letter-spacing: .4px; }
        .wordmark.cap { color: #0070ad; font-size: 1.35rem; font-style: italic; }
        .wordmark.bar { color: #00aeef; font-size: 1.2rem; text-transform: uppercase; letter-spacing: 1px; }
        .brand-tag { display:block; font-size:.6rem; color:#6b7280; letter-spacing:1.5px;
                     text-transform: uppercase; margin-top: 2px; font-weight:600; }
        .stTabs [data-baseweb="tab-list"] { gap: 6px; }
        .stTabs [data-baseweb="tab"] { border-radius: 9px 9px 0 0; padding: 8px 16px; font-weight: 600; }
        .stTabs [aria-selected="true"] { background: #eef2ff; color: #4f46e5; }
        .stButton button[kind="primary"] {
            background: linear-gradient(120deg, #4f46e5, #8b7cf6); border: none; font-weight: 700;
        }
        .how-banner {
            background: #eef2ff; border: 1px solid #c7d2fe; border-left: 4px solid #4f46e5;
            border-radius: 8px; padding: 10px 14px; font-size: .9rem; color: #312e81;
        }
        .v-badge { display:inline-block; background:#4f46e5; color:#fff; font-size:.62rem;
                   font-weight:700; padding:2px 8px; border-radius:10px; letter-spacing:1px; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    def _brand_box(logo_base, css, name, tag, side):
        inner = _logo_html(logo_base, f"{css}-img")
        if inner is None:
            if not name:
                return ""
            inner = (f'<span class="wordmark {css}">{name}</span>'
                     f'<span class="brand-tag">{tag}</span>')
        return f'<div class="brand-box brand-{side}">{inner}</div>'

    cap_box = _brand_box("capgemini", "cap", BRAND_LEFT, BRAND_LEFT_TAG, "left")
    bar_box = _brand_box("barclays", "bar", BRAND_RIGHT, BRAND_RIGHT_TAG, "right")
    st.markdown(
        f"""
        <div class="app-header">
            {cap_box}
            <div class="app-title">
                <div class="title-main">🛠️ Sample Data Generator <span class="v-badge">V4 · superset</span></div>
                <div class="title-sub">Everything in one clean package · JSON + YAML · multi-table FK ·
                    constraints · full fault taxonomy · all writers · per-cell defect ledger · no LLM</div>
            </div>
            {bar_box}
        </div>
        """,
        unsafe_allow_html=True,
    )


# ----------------------------------------------------------------------------
# Dirty-cell highlighting + defect breakdown
# ----------------------------------------------------------------------------
def _fault_columns_of(tag) -> list:
    return [p.split(":")[0] for p in str(tag).split("|") if ":" in p] if tag else []


def _style_dirty(df: pd.DataFrame, defect_col: str = "_defect"):
    if defect_col not in df.columns:
        return df
    cols = list(df.columns)
    di = cols.index(defect_col)

    def _row(row):
        out = [""] * len(cols)
        tag = row[defect_col]
        if isinstance(tag, str) and tag.strip():
            out = ["background-color: #fff1f0"] * len(cols)
            for cname in _fault_columns_of(tag):
                if cname in cols:
                    out[cols.index(cname)] = "background-color: #ffa39e; font-weight: 600"
            out[di] = "background-color: #fff1b8; font-weight: 600"
        return out

    return df.style.apply(_row, axis=1)


def _defect_breakdown(rows, defect_col: str = "_defect"):
    c = Counter()
    for r in rows:
        tag = r.get(defect_col)
        if isinstance(tag, str) and tag.strip():
            for p in tag.split("|"):
                if ":" in p:
                    c[p.split(":", 1)[1]] += 1
    if not c:
        return None
    return pd.DataFrame({"defects": dict(c)}).sort_values("defects", ascending=False)


def _ds_to_df(ds):
    return pd.DataFrame([{c: r.get(c) for c in ds.header} for r in ds.rows], columns=ds.header)


# ----------------------------------------------------------------------------
# Schema editor (visual column grid) — round-trip helpers
# ----------------------------------------------------------------------------
_TYPE_VALUES = [t.value for t in LogicalType]
_DIRTY_VALUES = [d.value for d in DirtyKind]
_SCHEMA_COLS = ["name", "type", "max_length", "expected_values", "nullable", "unique",
                "null_probability", "scale", "weights", "edge_values", "dirty_examples",
                "dirty_kinds", "params", "description"]


def _smart(v):
    """Cast a pasted token to int/float when it looks numeric, else keep the string."""
    s = str(v).strip()
    if s == "":
        return s
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        return s


def _parse_list(text):
    """Split a comma-separated cell into a typed list (empty -> [])."""
    s = "" if text is None else str(text).strip()
    return [_smart(p) for p in (p.strip() for p in s.split(",")) if p != ""] if s else []


def _list_to_text(values):
    return ", ".join(str(v) for v in values) if values else ""


def _b(v):
    """Safe bool from a grid cell (NaN/None -> False; avoids bool(nan)==True)."""
    return bool(v) if pd.notna(v) else False


def _s(v):
    """Safe str from a grid cell (NaN/None -> '')."""
    return str(v) if pd.notna(v) else ""


def _columns_to_rows(tbl):
    """A config table dict -> one grid row per column."""
    rows = []
    for c in tbl.get("columns", []):
        params = c.get("params") or {}
        rows.append({
            "name": c.get("name", ""),
            "type": c.get("type", "string"),
            "max_length": c.get("max_length"),
            "expected_values": _list_to_text(c.get("allowed_values")),
            "nullable": bool(c.get("nullable", False)),
            "unique": bool(c.get("unique", False)),
            "null_probability": float(c.get("null_probability", 0.0) or 0.0),
            "scale": c.get("scale"),
            "weights": _list_to_text(c.get("weights")),
            "edge_values": _list_to_text(c.get("edge_values")),
            "dirty_examples": _list_to_text(c.get("dirty_examples")),
            "dirty_kinds": _list_to_text(c.get("dirty_kinds")),
            "params": json.dumps(params) if params else "",
            "description": c.get("description", ""),
        })
    return rows


def _schema_dataframe(tbl):
    """Build a typed DataFrame the data_editor can render cleanly."""
    df = pd.DataFrame(_columns_to_rows(tbl), columns=_SCHEMA_COLS)
    for c in ("max_length", "scale", "null_probability"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    for c in ("nullable", "unique"):
        df[c] = df[c].fillna(False).astype(bool)
    for c in ("name", "type", "expected_values", "weights", "edge_values",
              "dirty_examples", "dirty_kinds", "params", "description"):
        df[c] = df[c].fillna("").astype(str)
    return df


def _rows_to_columns(edited_df):
    """Edited grid -> list of config column dicts (nameless rows dropped)."""
    cols = []
    for _, r in edited_df.iterrows():
        name = _s(r.get("name")).strip()
        if not name:
            continue
        col = {"name": name, "type": _s(r.get("type")).strip() or "string"}
        if _b(r.get("nullable")):
            col["nullable"] = True
            npv = r.get("null_probability")
            npv = float(npv) if pd.notna(npv) else 0.0
            if npv:
                col["null_probability"] = npv
        if _b(r.get("unique")):
            col["unique"] = True
        ml = r.get("max_length")
        if pd.notna(ml) and _s(ml) != "":
            col["max_length"] = int(float(ml))
        sc = r.get("scale")
        if pd.notna(sc) and _s(sc) != "":
            col["scale"] = int(float(sc))
        av = _parse_list(_s(r.get("expected_values")))
        if av:
            col["allowed_values"] = av
        wt = _parse_list(_s(r.get("weights")))
        if wt:
            col["weights"] = [float(x) for x in wt]
        ev = _parse_list(_s(r.get("edge_values")))
        if ev:
            col["edge_values"] = ev
        de = _parse_list(_s(r.get("dirty_examples")))
        if de:
            col["dirty_examples"] = de
        dk = [p.strip() for p in _s(r.get("dirty_kinds")).split(",")
              if p.strip() in _DIRTY_VALUES]
        if dk:
            col["dirty_kinds"] = dk
        pj = _s(r.get("params")).strip()
        if pj:
            try:
                parsed = json.loads(pj)
                if isinstance(parsed, dict) and parsed:
                    col["params"] = parsed
            except Exception:
                pass
        desc = _s(r.get("description")).strip()
        if desc:
            col["description"] = desc
        cols.append(col)
    return cols


_DEFAULT_CONFIG = {
    "seed": 42, "dirty_ratio": 0.05, "coverage": {"mode": "edges"},
    "tables": [{
        "name": "exposures", "rows": 1000,
        "columns": [
            {"name": "exposure_id", "type": "seq_id", "unique": True},
            {"name": "exposure_class", "type": "enum",
             "allowed_values": ["Corporate", "Institution", "Retail", "Sovereign"]},
            {"name": "on_balance_flag", "type": "enum", "allowed_values": ["ON", "OFF"],
             "nullable": True, "null_probability": 0.05},
            {"name": "amount", "type": "decimal", "params": {"min": 0, "max": 1000000}, "scale": 2},
            {"name": "booking_date", "type": "date"},
        ],
    }],
}

if "config_json" not in st.session_state:
    st.session_state.config_json = json.dumps(_DEFAULT_CONFIG, indent=2)

render_header()


def _current_config_dict():
    # Accept JSON or YAML in the editor; normalise to a canonical dict.
    return load_config(st.session_state.config_json).to_dict()


def _load_preset_config(name: str):
    st.session_state.config_json = preset_config(name).to_json()


# ---- Sidebar: run overrides + output ----
with st.sidebar:
    st.header("⚙️ Run settings (override config)")
    seed = st.number_input("Seed", min_value=0, value=42, step=1, help=HELP["seed"])
    dirty = st.slider("Dirty row ratio", 0.0, 1.0, 0.05, 0.01, help=HELP["dirty_ratio"])
    cov_mode = st.selectbox("Coverage mode", COVERAGE_MODES,
                            index=COVERAGE_MODES.index("edges"), help=HELP["coverage_mode"])
    cov_cap = st.number_input("Max combination rows", 1, 1_000_000, 5000, step=100,
                              help=HELP["coverage_cap"])
    st.header("📤 Output")
    formats = st.multiselect("File formats", ["csv", "tsv", "json", "jsonl", "parquet", "sql", "xlsx"],
                             default=["csv"], help=HELP["formats"])
    with st.expander("📐 CSV options (test file parsing)"):
        csv_delim = st.text_input("Delimiter", ",", max_chars=3, help=HELP["delimiter"])
        csv_quote = st.selectbox("Quoting", QUOTING_MODES, index=0, help=HELP["quoting"])
        csv_enc = st.selectbox("Encoding", ["utf-8", "latin-1", "cp1252"], index=0, help=HELP["encoding"])
        csv_bom = st.checkbox("Prepend UTF-8 BOM", value=False, help=HELP["bom"])

csv_opts = CsvOptions(delimiter=csv_delim or ",", quoting=csv_quote, encoding=csv_enc, bom=csv_bom)

tab_guide, tab_import, tab_schema, tab_config, tab_generate = st.tabs(
    ["🚀 Start here", "📥 Import / Presets", "🧱 Schema editor",
     "🧩 Config (JSON/YAML)", "▶️ Generate"])

# ---- Tab: Start here / Guide ----
with tab_guide:
    st.markdown(
        '<div class="how-banner">👋 <b>New here?</b> This tool turns a table schema into realistic '
        'test data <i>plus</i> deliberate garbage rows — so you can prove your pipeline accepts the '
        'good and rejects the bad. Three steps, no coding.</div>',
        unsafe_allow_html=True)
    st.write("")

    g1, g2, g3 = st.columns(3)
    with g1.container(border=True):
        st.markdown("#### 1 · Describe the table")
        st.caption("Paste a `CREATE TABLE` or load a banking preset on the **Import / Presets** tab. "
                   "`CHECK (… IN …)` lists become your expected values; `REFERENCES` become FKs.")
    with g2.container(border=True):
        st.markdown("#### 2 · Refine the columns")
        st.caption("Use the **🧱 Schema editor** to set each column's type, length and expected "
                   "values in a grid (no JSON), or edit the **Config (JSON)** directly. Set seed, "
                   "dirty ratio and coverage in the sidebar.")
    with g3.container(border=True):
        st.markdown("#### 3 · Generate & download")
        st.caption("Hit **Generate** — clean vs **dirty** cells are highlighted, with a defect "
                   "breakdown, FK integrity and downloads (CSV / Excel / JSON / SQL).")

    st.divider()
    st.subheader("⚡ Load a worked example")
    st.caption("Fastest way to learn the tool — a ready-made config with expected values & fault "
               "examples. Load one, then open the **Generate** tab.")
    e1, e2, e3 = st.columns(3)
    if e1.button("🏦 Banking exposures", use_container_width=True):
        _load_preset_config("basel_exposure")
        st.toast("Loaded 'Banking exposures' — open ▶️ Generate", icon="🏦")
        st.rerun()
    if e2.button("🔗 Multi-table (FK)", use_container_width=True):
        _load_preset_config("banking-dataset")
        st.toast("Loaded multi-table dataset — open ▶️ Generate", icon="🔗")
        st.rerun()
    if e3.button("🏢 Counterparties", use_container_width=True):
        _load_preset_config("counterparty")
        st.toast("Loaded 'Counterparties' — open ▶️ Generate", icon="🏢")
        st.rerun()

    st.divider()
    st.subheader("📖 Glossary")
    with st.expander("Dirty-data kinds — the garbage we inject"):
        st.dataframe(pd.DataFrame([{"kind": k, "what it injects": v}
                                   for k, v in GLOSSARY_DIRTY.items()]),
                     use_container_width=True, hide_index=True)
    with st.expander("Coverage modes — how value combinations are covered"):
        st.dataframe(pd.DataFrame([{"mode": k, "meaning": v}
                                   for k, v in GLOSSARY_COVERAGE.items()]),
                     use_container_width=True, hide_index=True)
    with st.expander("Column types"):
        st.write("  ".join(f"`{t.value}`" for t in LogicalType))

# ---- Tab: Import / Presets ----
with tab_import:
    st.markdown(
        '<div class="how-banner">📥 <b>Fastest start.</b> Paste a <code>CREATE TABLE</code> or '
        'load a banking preset and the JSON config is drafted for you — including expected values '
        'from <code>CHECK (… IN …)</code> and foreign keys from <code>REFERENCES</code>. '
        'Then tweak it in the <b>Config</b> tab.</div>',
        unsafe_allow_html=True)
    st.write("")
    st.subheader("Paste an interface document / schema")
    _FORMATS = {
        "CREATE TABLE (DDL)": ("ddl",
            "CREATE TABLE exposures (\n  id BIGINT PRIMARY KEY,\n"
            "  cls VARCHAR(20) CHECK (cls IN ('A','B'))\n);"),
        "Oracle SQL*Loader (.ctl)": ("ctl",
            "LOAD DATA INTO TABLE my_feed\nFIELDS TERMINATED BY '|'\nTRAILING NULLCOLS (\n"
            "  RetPrcnt,\n  AppTyp CHAR (10),\n  ExpOfISAmt,\n  MatDt DATE 'dd/mm/yyyy'\n)"),
        "XML (Axiom / XSD / sample)": ("xml",
            '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">\n'
            '  <xs:element name="my_feed"><xs:complexType><xs:sequence>\n'
            '    <xs:element name="id" type="xs:integer"/>\n'
            '    <xs:element name="amount" type="xs:decimal" minOccurs="0"/>\n'
            '    <xs:element name="status"><xs:simpleType><xs:restriction base="xs:string">\n'
            '      <xs:enumeration value="A"/><xs:enumeration value="B"/>\n'
            '    </xs:restriction></xs:simpleType></xs:element>\n'
            '  </xs:sequence></xs:complexType></xs:element>\n</xs:schema>'),
    }
    if not _HAS_DDL:
        st.warning("Importers need `simple-ddl-parser` (pip install -r requirements.txt).")
    else:
        choice = st.segmented_control("Schema format", list(_FORMATS.keys()),
                                      default="CREATE TABLE (DDL)") or "CREATE TABLE (DDL)"
        kind, placeholder = _FORMATS[choice]
        src = st.text_area(f"Paste {choice}", height=200, key="schema_src", placeholder=placeholder,
                           help="Paste the upstream interface document. CHECK-lists / ENUMs become "
                                "expected values; field types (and, for DDL, foreign keys) are mapped, "
                                "with banking name heuristics (…Amt→decimal, …Dt→date).")
        if st.button("🔎 Parse into config", type="primary"):
            try:
                cfg = (parse_ddl(src) if kind == "ddl"
                       else parse_sqlloader_ctl(src) if kind == "ctl"
                       else parse_xml(src))
                st.session_state.config_json = cfg.to_json()
                ncol = sum(len(t.columns) for t in cfg.tables)
                st.toast(f"Imported {len(cfg.tables)} table(s) · {ncol} columns", icon="📥")
                st.success(f"Imported {len(cfg.tables)} table(s), {ncol} columns. Open the "
                           "🧱 **Schema editor** tab to set data types, lengths & expected values "
                           "per column (or edit the raw JSON in the Config tab), then Generate.")
            except Exception as e:
                st.error(f"Could not parse: {e}")

    st.divider()
    st.subheader("🏦 Banking presets")
    st.caption("No schema to hand? Start from a ready-made regulatory template, or drop "
               "preset columns (exposure class, on/off-balance flag, currency…) into the config.")
    pc1, pc2 = st.columns(2)
    with pc1:
        preset = st.selectbox("Template config", list_presets(), help=HELP["preset"])
        if st.button(f"📥 Load '{preset}'"):
            _load_preset_config(preset)
            st.toast(f"Loaded preset '{preset}'", icon="🏦")
            st.success(f"Loaded preset '{preset}'. See the Config tab.")
    with pc2:
        cols = st.multiselect("…or add preset columns to first table", list(PRESET_COLUMNS.keys()))
        if st.button("➕ Append columns") and cols:
            try:
                data = _current_config_dict()
            except Exception as exc:
                st.error(f"Fix the config first: {exc}")
                data = None
            if data and data.get("tables"):
                for label in cols:
                    data["tables"][0]["columns"].append(_column_to_dict(PRESET_COLUMNS[label]()))
                st.session_state.config_json = json.dumps(data, indent=2)
                st.success(f"Added {len(cols)} column(s) to '{data['tables'][0]['name']}'.")

# ---- Tab: Schema editor (visual column grid) ----
with tab_schema:
    st.markdown(
        '<div class="how-banner">🧱 <b>Edit the schema as a table — one row per column.</b> '
        'After importing a big DDL / XML / SQL*Loader file, set each column\'s <b>data type</b>, '
        '<b>length</b> and <b>expected values</b> here without touching JSON. Edit the grid, then '
        '<b>Apply</b> to write it back to the config.</div>',
        unsafe_allow_html=True)
    st.write("")

    try:
        _schema_cfg = load_config(st.session_state.config_json).to_dict()
        _schema_err = None
    except Exception as exc:
        _schema_cfg, _schema_err = None, str(exc)

    if _schema_err:
        st.error(f"Fix the config before editing the schema: {_schema_err}")
    elif not _schema_cfg.get("tables"):
        st.info("No tables yet — import a schema or load a preset on the 📥 Import / Presets tab.")
    else:
        st.caption("`expected values`, `edge values`, `dirty examples` and `weights` are "
                   "comma-separated. `params` is JSON, e.g. "
                   '`{"min":0,"max":1000}` or `{"start":"2015-01-01","end":"today"}`. '
                   "Use the grid's ➕ / 🗑 controls to add or remove columns.")
        st.info("💡 Setting **expected values** on a column makes the generator emit **only those "
                "values** (categorical) — whatever the type. Then click **Apply**, and switch to "
                "▶️ Generate to see them.")
        edited_tables = []  # (table_dict, rows_value, edited_df)
        for ti, tbl in enumerate(_schema_cfg["tables"]):
            st.markdown(f"#### 🗂️ Table: `{tbl.get('name', 'table')}`")
            rc1, rc2 = st.columns([1, 3])
            rows_val = rc1.number_input("Rows", min_value=1, max_value=10_000_000,
                                        value=int(tbl.get("rows", 1000)), step=100,
                                        key=f"schema_rows_{ti}")
            note = []
            if tbl.get("primary_key"):
                note.append("PK: " + ", ".join(tbl["primary_key"]))
            if tbl.get("foreign_keys"):
                note.append("FK: " + ", ".join(f"{fk['column']}→{fk['ref_table']}"
                                                for fk in tbl["foreign_keys"]))
            if note:
                rc2.caption(" · ".join(note) + "  — kept as-is (edit keys in the Config tab)")

            edited = st.data_editor(
                _schema_dataframe(tbl), key=f"schema_editor_{ti}", use_container_width=True,
                num_rows="dynamic", hide_index=True,
                column_config={
                    "name": st.column_config.TextColumn("name"),
                    "type": st.column_config.SelectboxColumn("type", options=_TYPE_VALUES),
                    "max_length": st.column_config.NumberColumn(
                        "length", min_value=0, step=1, help="Max length for string columns."),
                    "expected_values": st.column_config.TextColumn(
                        "expected values",
                        help="Allowed/expected values (the enum domain), comma-separated."),
                    "nullable": st.column_config.CheckboxColumn("nullable"),
                    "unique": st.column_config.CheckboxColumn("unique"),
                    "null_probability": st.column_config.NumberColumn(
                        "null %", min_value=0.0, max_value=1.0, step=0.01, format="%.2f"),
                    "scale": st.column_config.NumberColumn(
                        "scale", min_value=0, step=1, help="Decimal places."),
                    "weights": st.column_config.TextColumn(
                        "weights", help="Enum sampling weights, comma-separated (match expected values)."),
                    "edge_values": st.column_config.TextColumn(
                        "edge values", help="Values guaranteed to appear in the output."),
                    "dirty_examples": st.column_config.TextColumn(
                        "dirty examples", help="Forced bad values to inject as dirty data."),
                    "dirty_kinds": st.column_config.TextColumn(
                        "dirty kinds",
                        help="Restrict defect kinds (comma-separated). Valid: " + ", ".join(_DIRTY_VALUES)),
                    "params": st.column_config.TextColumn(
                        "params (JSON)", help='e.g. {"min":0,"max":1000} or {"start":"2015-01-01","end":"today"}'),
                    "description": st.column_config.TextColumn("description"),
                })
            edited_tables.append((tbl, int(rows_val), edited))

            tbl["_constraints_new"] = st.text_area(
                "Cross-column constraints (one per line, e.g. `start_date <= end_date`)",
                "\n".join(tbl.get("constraints", []) or []), height=70, key=f"schema_cons_{ti}")
            st.divider()

        if st.button("✅ Apply schema changes to config", type="primary"):
            try:
                for tbl, rows_val, edited in edited_tables:
                    tbl["rows"] = rows_val
                    tbl["columns"] = _rows_to_columns(edited)
                    cons_list = [ln.strip() for ln in str(tbl.pop("_constraints_new", "")).splitlines()
                                 if ln.strip()]
                    if cons_list:
                        tbl["constraints"] = cons_list
                    else:
                        tbl.pop("constraints", None)
                new_cfg = config_from_dict(_schema_cfg)
                st.session_state.config_json = new_cfg.to_json()
                errs = validate_config(new_cfg)
                ncols = sum(len(t.columns) for t in new_cfg.tables)
                if errs:
                    st.warning("Applied, but the config has issues:\n- " + "\n- ".join(errs))
                else:
                    st.success(f"Applied · {len(new_cfg.tables)} table(s) · {ncols} columns. "
                               "Open the Config or ▶️ Generate tab.")
                st.toast("Schema applied to config", icon="🧱")
                # Reset the grid widgets so they re-seed from the canonical config
                # (otherwise stale per-cell edits would be re-applied on top).
                for i in range(len(edited_tables)):
                    st.session_state.pop(f"schema_editor_{i}", None)
                st.rerun()
            except Exception as exc:
                st.error(f"Could not apply schema: {exc}")

# ---- Tab: Config (JSON / YAML) ----
with tab_config:
    st.markdown(
        '<div class="how-banner">🧩 <b>This config is the source of truth.</b> JSON <i>or</i> YAML — '
        'both are accepted. Build it from DDL or a preset on the left, edit it here, <b>Validate</b>, '
        'and download it to check into git. Same config + seed ⇒ identical data.</div>',
        unsafe_allow_html=True)
    st.write("")
    st.subheader("Generation config")
    st.session_state.config_json = st.text_area("Config (JSON or YAML)", st.session_state.config_json,
                                                height=420, help=HELP["config"])
    cca, ccb, ccc = st.columns(3)
    if cca.button("✅ Validate"):
        try:
            errs = validate_config(config_from_dict(_current_config_dict()))
            if not errs:
                st.success("Config is valid.")
            else:
                st.error("Issues:\n- " + "\n- ".join(errs))
        except Exception as e:
            st.error(f"Invalid config: {e}")
    try:
        _cfg_obj = load_config(st.session_state.config_json)
        ccb.download_button("⬇️ config.json", _cfg_obj.to_json(), "config.json", "application/json")
        ccc.download_button("⬇️ config.yaml", _cfg_obj.to_yaml(), "config.yaml", "text/yaml")
    except Exception:
        ccb.caption("Fix the config to enable downloads.")

# ---- Tab: Generate ----
with tab_generate:
    st.markdown(
        '<div class="how-banner">▶️ <b>Produce the data.</b> The sidebar sets seed, dirty ratio, '
        'coverage and CSV options. Generate, preview each table with dirty cells highlighted, and '
        'download. Multi-table configs show <b>foreign-key integrity</b>.</div>',
        unsafe_allow_html=True)
    st.write("")
    try:
        data = _current_config_dict()
        cfg = config_from_dict(data)
        cfg.seed = int(seed)
        cfg.dirty_ratio = float(dirty)
        cfg.coverage.mode = cov_mode
        cfg.coverage.cap = int(cov_cap)
        errors = validate_config(cfg)
    except Exception as e:
        cfg, errors = None, [f"Invalid JSON config: {e}"]

    if errors:
        st.error("Fix these before generating:")
        for e in errors:
            st.write(f"- {e}")
    else:
        st.success(f"{len(cfg.tables)} table(s) · seed {cfg.seed} · "
                   f"dirty {cfg.dirty_ratio:.0%} · coverage '{cfg.coverage.mode}'.")
        gen_col, _ = st.columns([1, 3])
        if gen_col.button("▶️ Generate", type="primary", use_container_width=True):
            try:
                with st.status("Generating dataset…", expanded=True) as status:
                    t0 = time.perf_counter()
                    st.write("⚙️ Building values, coverage & foreign keys…")
                    datasets = generate(cfg)
                    report = coverage_report(cfg, datasets)
                    tot = sum(len(d.rows) for d in datasets.values())
                    defs = sum(len(d.defect_ledger) for d in datasets.values())
                    st.write(f"✓ {tot:,} rows across {len(datasets)} table(s)")
                    st.write(f"✓ Injected {defs} dirty cells (per-cell defect ledger)")
                    st.session_state.v2_datasets = datasets
                    st.session_state.v2_report = report
                    status.update(label=f"Done in {time.perf_counter() - t0:.2f}s · {tot:,} rows",
                                  state="complete", expanded=False)
                st.toast(f"Generated {tot:,} rows · {defs} dirty cells", icon="✅")
            except Exception as exc:
                st.error(f"Generation failed: {exc}")

    datasets = st.session_state.get("v2_datasets")
    if datasets and not errors:
        report = st.session_state.get("v2_report", {})
        total_rows = sum(len(ds.rows) for ds in datasets.values())
        total_defects = sum(len(ds.defect_ledger) for ds in datasets.values())
        fk = report.get("foreign_keys", {})
        fk_ok = all(info["integrity_ok"] for info in fk.values()) if fk else True
        edges_missing = sum(len(t.get("declared_edges_missing", []))
                            for t in report.get("tables", {}).values())
        healthy = fk_ok and edges_missing == 0

        seed_used = report.get("seed", cfg.seed)
        summary = (f"Generated **{total_rows:,} rows** across **{len(datasets)} table(s)**. "
                   f"**{total_defects}** cells were deliberately corrupted and tagged in `_defect`. "
                   f"Seed **{seed_used}** — re-run with this config for identical data.")
        if healthy:
            st.success(summary)
        else:
            st.warning(summary)

        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Tables", len(datasets))
        m2.metric("Total rows", f"{total_rows:,}")
        m3.metric("Dirty cells", total_defects)
        m4.metric("FK integrity", "n/a" if not fk else ("OK" if fk_ok else "orphans"))
        m5.metric("Data health", "🟢 Pass" if healthy else "🟡 Review")

        if fk:
            st.markdown("**Foreign-key integrity**")
            for edge, info in fk.items():
                icon = "✅" if info["integrity_ok"] else "⚠️"
                st.write(f"{icon} `{edge}` — {info['broken_refs']}/{info['child_rows']} broken")

        # Preview with table picker, view filter, dirty-cell highlighting
        st.subheader("Preview")
        pick = st.selectbox("Table", list(datasets.keys()))
        ds = datasets[pick]
        df = _ds_to_df(ds)
        has_tags = "_defect" in df.columns and (df["_defect"].astype(str).str.strip() != "").any()
        view = st.segmented_control("Show", ["All rows", "Dirty rows only", "Clean rows only"],
                                    default="All rows") or "All rows"
        if has_tags and view != "All rows":
            mask = df["_defect"].astype(str).str.strip() != ""
            df_view = df[mask] if view == "Dirty rows only" else df[~mask]
        else:
            df_view = df
        st.caption(f"Showing {min(len(df_view), 100)} of {len(df_view):,} rows · "
                   "🟥 corrupted cell · 🟨 defect tag")
        st.dataframe(_style_dirty(df_view.head(100)), use_container_width=True, hide_index=True)

        if has_tags:
            dirty_df = df[df["_defect"].astype(str).str.strip() != ""]
            st.download_button(f"⬇️ Negative-test pack — {len(dirty_df)} dirty rows (CSV)",
                               dirty_df.to_csv(index=False), f"{pick}_dirty.csv", "text/csv")

        with st.expander("🧪 How to use this in your pipeline test"):
            st.markdown("- **Clean rows** (blank `_defect`) should load successfully.\n"
                        "- **Dirty rows** (non-empty `_defect`) should be **rejected** by your "
                        "ingestion / validation layer.\n"
                        "- The tag (e.g. `on_balance_flag:embedded_delimiter`) names the corrupted "
                        "column and the defect kind.")
            st.code("# pseudo-assertion\nrejected = your_loader(rows)\n"
                    "expected = {i for i, r in enumerate(rows) if r.get('_defect')}\n"
                    "assert rejected == expected", language="python")

        cc1, cc2 = st.columns(2)
        with cc1:
            st.markdown("**Defect breakdown** (selected table)")
            fb = _defect_breakdown(ds.rows)
            if fb is not None:
                st.bar_chart(fb, horizontal=True)
            else:
                st.caption("No dirty rows.")
        with cc2:
            st.markdown("**Reproduce / inspect**")
            with st.popover("🔁 Reproduce this dataset"):
                st.caption("Same config + seed ⇒ byte-identical data. Paste into a ticket.")
                st.code(cfg.to_json(), language="json")
                st.code("python -m sdgen.cli generate config.json --formats csv", language="bash")
            with st.popover("📊 Raw report (JSON)"):
                st.json(report)

        st.subheader("Download")
        d1, d2 = st.columns(2)
        d1.download_button("⬇️ CSV", render_csv(ds, csv_opts), f"{pick}.csv", "text/csv")
        d2.download_button("⬇️ JSON", render_json(ds), f"{pick}.json", "application/json")
