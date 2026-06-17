"""Command-line interface for sdgen (version 2).

    python -m sdgen.cli generate config.json --out ./output --formats csv json
    python -m sdgen.cli validate config.json
    python -m sdgen.cli import-ddl schema.sql --out config.json
    python -m sdgen.cli preset basel_exposure --out config.json
"""

from __future__ import annotations

import argparse
import json
import sys

from .model import load_config, validate_config
from .engine import generate, coverage_report
from .writers import write_all, CsvOptions, QUOTING_MODES


def _read(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    with open(path, encoding="utf-8") as f:
        return f.read()


def _cmd_validate(args) -> int:
    errors = validate_config(load_config(_read(args.config)))
    if errors:
        print("INVALID config:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("Config is valid.")
    return 0


def _cmd_generate(args) -> int:
    cfg = load_config(_read(args.config))
    if args.seed is not None:
        cfg.seed = args.seed
    if args.rows is not None:
        for t in cfg.tables:
            t.rows = args.rows
    if args.coverage_mode is not None:
        cfg.coverage.mode = args.coverage_mode
    if args.dirty_ratio is not None:
        cfg.dirty_ratio = args.dirty_ratio
    errors = validate_config(cfg)
    if errors:
        print("Refusing to generate; config is invalid:")
        for e in errors:
            print(f"  - {e}")
        return 1
    datasets = generate(cfg)
    report = coverage_report(cfg, datasets)
    opts = CsvOptions(delimiter=args.delimiter, quoting=args.quoting,
                      encoding=args.encoding, bom=args.bom,
                      line_ending="\r\n" if args.line_ending == "windows" else "\n")
    written = write_all(datasets, args.out, formats=args.formats, csv_options=opts, report=report)
    print("Wrote:")
    for name, files in written.items():
        for fmt, path in files.items():
            print(f"  {name} [{fmt}]: {path}")
    print("\nCoverage / FK report:")
    print(json.dumps(report, indent=2, default=str))
    return 0


def _cmd_import_ddl(args) -> int:
    from .importers import parse_ddl
    cfg = parse_ddl(_read(args.ddl), apply_heuristics=not args.no_heuristics)
    text = cfg.to_json()
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"Wrote config ({len(cfg.tables)} table(s)) to {args.out}")
    else:
        sys.stdout.write(text)
    return 0


def _cmd_preset(args) -> int:
    from .presets import list_presets, preset_config
    if args.name in (None, "list"):
        print("Available presets:")
        for n in list_presets():
            print(f"  - {n}")
        return 0
    try:
        cfg = preset_config(args.name)
    except KeyError as exc:
        print(str(exc))
        return 1
    text = cfg.to_json()
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"Wrote preset '{args.name}' to {args.out}")
    else:
        sys.stdout.write(text)
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="sdgen", description="Sample data generator v2 (no LLM).")
    sub = p.add_subparsers(dest="command", required=True)

    g = sub.add_parser("generate", help="Generate data from a JSON config.")
    g.add_argument("config")
    g.add_argument("--out", default="./output")
    g.add_argument("--formats", nargs="+", default=["csv"])
    g.add_argument("--rows", type=int, default=None)
    g.add_argument("--seed", type=int, default=None)
    g.add_argument("--coverage-mode", default=None)
    g.add_argument("--dirty-ratio", type=float, default=None)
    g.add_argument("--delimiter", default=",")
    g.add_argument("--quoting", default="minimal", choices=QUOTING_MODES)
    g.add_argument("--encoding", default="utf-8")
    g.add_argument("--bom", action="store_true")
    g.add_argument("--line-ending", default="unix", choices=["unix", "windows"])
    g.set_defaults(func=_cmd_generate)

    v = sub.add_parser("validate", help="Validate a JSON config.")
    v.add_argument("config")
    v.set_defaults(func=_cmd_validate)

    d = sub.add_parser("import-ddl", help="Convert CREATE TABLE DDL into a JSON config.")
    d.add_argument("ddl")
    d.add_argument("--out", default=None)
    d.add_argument("--no-heuristics", action="store_true")
    d.set_defaults(func=_cmd_import_ddl)

    pr = sub.add_parser("preset", help="Emit a ready-made banking config.")
    pr.add_argument("name", nargs="?", default="list")
    pr.add_argument("--out", default=None)
    pr.set_defaults(func=_cmd_preset)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
