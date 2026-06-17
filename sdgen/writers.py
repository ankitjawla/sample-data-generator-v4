"""Output writers: configurable delimited text, JSON, JSONL, SQL, XLSX.

The delimited writer gives byte-level control (delimiter / quoting / encoding /
BOM / line endings); ``quoting="none"`` writes unescaped fields so an
``embedded_delimiter`` defect actually breaks a parser. Integers render as ``1``.
"""

from __future__ import annotations

import csv as _csv
import io
import json
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .engine import Dataset


QUOTING_MODES = ["minimal", "all", "nonnumeric", "none"]
_QUOTING_MAP = {
    "minimal": _csv.QUOTE_MINIMAL, "all": _csv.QUOTE_ALL,
    "nonnumeric": _csv.QUOTE_NONNUMERIC, "none": _csv.QUOTE_NONE,
}


@dataclass
class CsvOptions:
    delimiter: str = ","
    quoting: str = "minimal"
    encoding: str = "utf-8"
    bom: bool = False
    line_ending: str = "\n"
    null_token: str = ""


def _cell(value: Any, null_token: str) -> str:
    if value is None:
        return null_token
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    return str(value)


def render_csv(ds: Dataset, options: CsvOptions) -> str:
    cols = ds.header
    if options.quoting == "none":
        lines = [options.delimiter.join(cols)]
        for row in ds.rows:
            lines.append(options.delimiter.join(_cell(row.get(c), options.null_token) for c in cols))
        return options.line_ending.join(lines) + options.line_ending
    buf = io.StringIO()
    w = _csv.writer(buf, delimiter=options.delimiter, quoting=_QUOTING_MAP[options.quoting],
                    lineterminator=options.line_ending)
    w.writerow(cols)
    for row in ds.rows:
        w.writerow([_cell(row.get(c), options.null_token) for c in cols])
    return buf.getvalue()


def render_json(ds: Dataset, lines: bool = False) -> str:
    records = [{c: r.get(c) for c in ds.header} for r in ds.rows]
    if lines:
        return "\n".join(json.dumps(r, ensure_ascii=False, default=str) for r in records) + "\n"
    return json.dumps(records, ensure_ascii=False, indent=2, default=str)


def _ident(name: str) -> str:
    return '"' + re.sub(r"[^A-Za-z0-9_]", "_", str(name)) + '"'


def _sql_literal(v: Any) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"


def render_sql(ds: Dataset, table: Optional[str] = None) -> str:
    table = table or ds.table
    cols = ds.header
    col_list = ", ".join(_ident(c) for c in cols)
    out = [f"CREATE TABLE IF NOT EXISTS {_ident(table)} (",
           ",\n".join(f"    {_ident(c)} TEXT" for c in cols), ");", ""]
    for row in ds.rows:
        vals = ", ".join(_sql_literal(row.get(c)) for c in cols)
        out.append(f"INSERT INTO {_ident(table)} ({col_list}) VALUES ({vals});")
    return "\n".join(out) + "\n"


def _dataframe(ds: Dataset):
    import pandas as pd
    df = pd.DataFrame([{c: r.get(c) for c in ds.header} for r in ds.rows], columns=ds.header)
    return df


def write_dataset(ds: Dataset, out_dir: str, base: Optional[str] = None,
                  formats: Optional[List[str]] = None,
                  csv_options: Optional[CsvOptions] = None) -> Dict[str, str]:
    formats = formats or ["csv"]
    # Strip any path components to prevent traversal via a crafted table/base name.
    base = os.path.basename(str(base if base is not None else ds.table)).strip() or "data"
    os.makedirs(out_dir, exist_ok=True)
    opts = csv_options or CsvOptions()
    written: Dict[str, str] = {}
    for fmt in formats:
        path = os.path.join(out_dir, f"{base}.{fmt}")
        if fmt in ("csv", "tsv"):
            tsv_opts = opts if fmt == "csv" else CsvOptions(
                delimiter="\t", quoting=opts.quoting, encoding=opts.encoding,
                bom=opts.bom, line_ending=opts.line_ending, null_token=opts.null_token)
            enc = "utf-8-sig" if (tsv_opts.bom and tsv_opts.encoding.lower().replace("-", "") == "utf8") else tsv_opts.encoding
            with open(path, "w", encoding=enc, newline="") as f:
                f.write(render_csv(ds, tsv_opts))
        elif fmt in ("json", "jsonl"):
            with open(path, "w", encoding="utf-8") as f:
                f.write(render_json(ds, lines=(fmt == "jsonl")))
        elif fmt == "sql":
            with open(path, "w", encoding="utf-8") as f:
                f.write(render_sql(ds))
        elif fmt == "xlsx":
            try:
                _dataframe(ds).to_excel(path, index=False)
            except Exception:
                _dataframe(ds).astype(str).to_excel(path, index=False)
        elif fmt == "parquet":
            try:
                _dataframe(ds).to_parquet(path, index=False)
            except Exception:
                _dataframe(ds).astype(str).to_parquet(path, index=False)
        else:
            raise ValueError(f"Unknown format: {fmt}")
        written[fmt] = path
    return written


def write_all(datasets: Dict[str, Dataset], out_dir: str,
              formats: Optional[List[str]] = None,
              csv_options: Optional[CsvOptions] = None,
              report: Optional[Dict[str, Any]] = None) -> Dict[str, Dict[str, str]]:
    written: Dict[str, Dict[str, str]] = {}
    for name, ds in datasets.items():
        written[name] = write_dataset(ds, out_dir, base=name, formats=formats, csv_options=csv_options)
    if report is not None:
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, "_coverage_report.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, default=str)
        written.setdefault("_report", {})["json"] = path
    return written
