"""Enumerations shared across the sdgen engine.

Version 4 — the clean superset. An explicit ``LogicalType`` enum + plugin registry
of generators, JSON *and* YAML config, per-column RNG sub-streams, multi-table
foreign keys, cross-column constraints, and a per-cell defect ledger. Combines the
breadth of v1 (many column types, all writers, fault strategies) with the clean
architecture of v2.
"""

from __future__ import annotations

from enum import Enum


class LogicalType(str, Enum):
    SEQ_ID = "seq_id"          # 1, 2, 3, …
    INTEGER = "integer"
    DECIMAL = "decimal"
    FLOAT = "float"
    BOOLEAN = "boolean"
    DATE = "date"
    DATETIME = "datetime"
    ENUM = "enum"              # categorical with allowed_values
    STRING = "string"
    TEXT = "text"             # longer free text
    UUID = "uuid"
    # Faker-backed semantic types
    NAME = "name"
    FIRST_NAME = "first_name"
    LAST_NAME = "last_name"
    EMAIL = "email"
    PHONE = "phone"
    URL = "url"
    IPV4 = "ipv4"
    COMPANY = "company"
    JOB = "job"
    ADDRESS = "address"
    CITY = "city"
    COUNTRY = "country"
    POSTCODE = "postcode"
    CURRENCY = "currency"


NUMERIC_TYPES = {LogicalType.INTEGER, LogicalType.DECIMAL, LogicalType.FLOAT, LogicalType.SEQ_ID}
DATE_TYPES = {LogicalType.DATE, LogicalType.DATETIME}
FAKER_TYPES = {
    LogicalType.NAME, LogicalType.FIRST_NAME, LogicalType.LAST_NAME,
    LogicalType.EMAIL, LogicalType.PHONE, LogicalType.URL, LogicalType.IPV4,
    LogicalType.COMPANY, LogicalType.JOB, LogicalType.ADDRESS, LogicalType.CITY,
    LogicalType.COUNTRY, LogicalType.POSTCODE, LogicalType.CURRENCY,
}


class DirtyKind(str, Enum):
    EMBEDDED_DELIMITER = "embedded_delimiter"  # stray comma/quote/newline in a field
    WHITESPACE = "whitespace"                  # leading/trailing spaces
    NULL_VARIANT = "null_variant"              # NULL / "" / " " / "N/A"
    TYPE_MISMATCH = "type_mismatch"            # text in a numeric column, etc.
    OUT_OF_RANGE = "out_of_range"              # below min / above max
    FORMAT_VIOLATION = "format_violation"      # malformed email / date / url / phone
    LEADING_ZERO = "leading_zero"              # "007" or scientific notation
    DATE_AMBIGUITY = "date_ambiguity"          # 03/04/2020 or invalid 2023-13-45
    ENCODING = "encoding"                      # unicode / mojibake / control chars
    INVALID_ENUM_CASE = "invalid_enum_case"    # corporate / CORPORATE / Corp
    TRUNCATION = "truncation"                  # value cut short
    DUPLICATE_PK = "duplicate_pk"              # repeated unique key
    BROKEN_FK = "broken_fk"                    # FK to a non-existent parent


_FAKER_DIRTY = [DirtyKind.NULL_VARIANT, DirtyKind.WHITESPACE, DirtyKind.EMBEDDED_DELIMITER,
                DirtyKind.ENCODING, DirtyKind.TRUNCATION, DirtyKind.FORMAT_VIOLATION]

# Which dirty kinds make sense for which logical types (gating).
DIRTY_FOR_TYPE = {
    LogicalType.SEQ_ID: [DirtyKind.NULL_VARIANT, DirtyKind.TYPE_MISMATCH, DirtyKind.DUPLICATE_PK,
                         DirtyKind.LEADING_ZERO],
    LogicalType.INTEGER: [DirtyKind.NULL_VARIANT, DirtyKind.TYPE_MISMATCH, DirtyKind.OUT_OF_RANGE,
                          DirtyKind.LEADING_ZERO],
    LogicalType.DECIMAL: [DirtyKind.NULL_VARIANT, DirtyKind.TYPE_MISMATCH, DirtyKind.OUT_OF_RANGE],
    LogicalType.FLOAT: [DirtyKind.NULL_VARIANT, DirtyKind.TYPE_MISMATCH, DirtyKind.OUT_OF_RANGE],
    LogicalType.BOOLEAN: [DirtyKind.NULL_VARIANT, DirtyKind.TYPE_MISMATCH],
    LogicalType.DATE: [DirtyKind.NULL_VARIANT, DirtyKind.DATE_AMBIGUITY, DirtyKind.TYPE_MISMATCH,
                       DirtyKind.FORMAT_VIOLATION],
    LogicalType.DATETIME: [DirtyKind.NULL_VARIANT, DirtyKind.DATE_AMBIGUITY, DirtyKind.TYPE_MISMATCH,
                           DirtyKind.FORMAT_VIOLATION],
    LogicalType.ENUM: [DirtyKind.NULL_VARIANT, DirtyKind.INVALID_ENUM_CASE, DirtyKind.EMBEDDED_DELIMITER,
                       DirtyKind.WHITESPACE],
    LogicalType.STRING: [DirtyKind.NULL_VARIANT, DirtyKind.WHITESPACE, DirtyKind.EMBEDDED_DELIMITER,
                         DirtyKind.ENCODING, DirtyKind.TRUNCATION],
    LogicalType.TEXT: [DirtyKind.NULL_VARIANT, DirtyKind.WHITESPACE, DirtyKind.EMBEDDED_DELIMITER,
                       DirtyKind.ENCODING, DirtyKind.TRUNCATION],
    LogicalType.UUID: [DirtyKind.NULL_VARIANT, DirtyKind.TRUNCATION, DirtyKind.TYPE_MISMATCH,
                       DirtyKind.FORMAT_VIOLATION],
    LogicalType.EMAIL: _FAKER_DIRTY,
    LogicalType.URL: _FAKER_DIRTY,
    LogicalType.PHONE: _FAKER_DIRTY,
    LogicalType.IPV4: _FAKER_DIRTY,
}


class OutputFormat(str, Enum):
    CSV = "csv"
    TSV = "tsv"
    JSON = "json"
    JSONL = "jsonl"
    PARQUET = "parquet"
    XLSX = "xlsx"
    SQL = "sql"
    TXT = "txt"


COVERAGE_MODES = ["off", "edges", "cartesian", "pairwise"]
