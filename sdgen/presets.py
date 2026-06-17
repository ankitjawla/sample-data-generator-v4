"""Banking / regulatory presets for sdgen (dataclass/JSON model)."""

from __future__ import annotations

from typing import Callable, Dict, List

from .types import LogicalType, DirtyKind
from .model import GenerationConfig, TableSpec, ColumnSpec, ForeignKey, CoverageSpec


EXPOSURE_CLASSES = ["Corporate", "Institution", "Retail", "Sovereign", "CentralBank",
                    "Equity", "RetailSME", "CoveredBond", "Securitisation", "OtherAssets"]
ON_BALANCE_FLAGS = ["ON", "OFF"]
CREDIT_RATINGS = ["AAA", "AA", "A", "BBB", "BB", "B", "CCC", "CC", "C", "D"]
CURRENCY_CODES = ["EUR", "USD", "GBP", "JPY", "CHF", "CAD", "AUD", "CNY", "SEK", "NOK"]
COUNTRY_CODES = ["GB", "US", "DE", "FR", "IT", "ES", "NL", "IE", "CH", "JP", "SG", "HK"]
PRODUCT_TYPES = ["Loan", "Bond", "Derivative", "Repo", "Guarantee", "CreditLine", "Lease"]
SECTORS = ["Bank", "Corporate", "Sovereign", "Household", "Insurance", "Fund"]


def exposure_class_col(name="exposure_class") -> ColumnSpec:
    return ColumnSpec(name=name, type=LogicalType.ENUM, allowed_values=list(EXPOSURE_CLASSES),
                      dirty_examples=["corporate", "CORP", "Retial", ""])


def on_balance_flag_col(name="on_balance_flag") -> ColumnSpec:
    return ColumnSpec(name=name, type=LogicalType.ENUM, allowed_values=list(ON_BALANCE_FLAGS),
                      nullable=True, null_probability=0.05,
                      dirty_kinds=[DirtyKind.NULL_VARIANT, DirtyKind.INVALID_ENUM_CASE,
                                   DirtyKind.EMBEDDED_DELIMITER],
                      dirty_examples=[", ", "on", "Y", "1"])  # the stray-comma case


def currency_col(name="currency_code") -> ColumnSpec:
    return ColumnSpec(name=name, type=LogicalType.ENUM, allowed_values=list(CURRENCY_CODES),
                      dirty_examples=["eur", "US", "XXX"])


def country_col(name="country_code") -> ColumnSpec:
    return ColumnSpec(name=name, type=LogicalType.ENUM, allowed_values=list(COUNTRY_CODES),
                      dirty_examples=["gb", "USA", "ZZ"])


def rating_col(name="credit_rating") -> ColumnSpec:
    return ColumnSpec(name=name, type=LogicalType.ENUM, allowed_values=list(CREDIT_RATINGS),
                      nullable=True, null_probability=0.03, dirty_examples=["AAB", "10"])


def product_type_col(name="product_type") -> ColumnSpec:
    return ColumnSpec(name=name, type=LogicalType.ENUM, allowed_values=list(PRODUCT_TYPES))


def sector_col(name="sector") -> ColumnSpec:
    return ColumnSpec(name=name, type=LogicalType.ENUM, allowed_values=list(SECTORS))


def lei_col(name="lei_code") -> ColumnSpec:
    return ColumnSpec(name=name, type=LogicalType.STRING, max_length=20,
                      params={"min_length": 20, "max_length": 20},
                      nullable=True, null_probability=0.05, dirty_examples=["TOO_SHORT", ""])


def amount_col(name="exposure_amount") -> ColumnSpec:
    return ColumnSpec(name=name, type=LogicalType.DECIMAL, params={"min": 0, "max": 1_000_000_000},
                      scale=2, edge_values=[0, 0.01], dirty_examples=[-100.0, "1,000.00"])


def booking_date_col(name="booking_date") -> ColumnSpec:
    return ColumnSpec(name=name, type=LogicalType.DATE, params={"start": "2015-01-01", "end": "today"},
                      edge_values=["2015-01-01", "2020-02-29"], dirty_examples=["2023-13-45", "31/12/2020"])


PRESET_COLUMNS: Dict[str, Callable[[], ColumnSpec]] = {
    "Exposure class": exposure_class_col,
    "On/off-balance flag": on_balance_flag_col,
    "Currency code": currency_col,
    "Country code": country_col,
    "Credit rating": rating_col,
    "Product type": product_type_col,
    "Counterparty sector": sector_col,
    "LEI code": lei_col,
    "Exposure amount": amount_col,
    "Booking date": booking_date_col,
}


def _exposure_table(name="exposures", rows=1000) -> TableSpec:
    return TableSpec(name=name, rows=rows, primary_key=["exposure_id"], columns=[
        ColumnSpec(name="exposure_id", type=LogicalType.SEQ_ID, unique=True),
        ColumnSpec(name="counterparty_id", type=LogicalType.INTEGER, params={"min": 1, "max": 100_000}),
        exposure_class_col(), on_balance_flag_col(), product_type_col(),
        amount_col(), currency_col(), country_col(), rating_col(), booking_date_col(),
    ])


def _counterparty_table(name="counterparties", rows=200) -> TableSpec:
    return TableSpec(name=name, rows=rows, primary_key=["id"], columns=[
        ColumnSpec(name="id", type=LogicalType.SEQ_ID, unique=True),
        ColumnSpec(name="legal_name", type=LogicalType.COMPANY),
        lei_col(), country_col(), sector_col(),
    ])


PRESET_CONFIGS: Dict[str, Callable[[], GenerationConfig]] = {
    "basel_exposure": lambda: GenerationConfig(tables=[_exposure_table()], seed=42, dirty_ratio=0.05),
    "counterparty": lambda: GenerationConfig(tables=[_counterparty_table()], seed=42, dirty_ratio=0.05),
}


def list_presets() -> List[str]:
    return list(PRESET_CONFIGS.keys()) + ["banking-dataset"]


def preset_config(name: str) -> GenerationConfig:
    if name == "banking-dataset":
        return banking_dataset()
    if name not in PRESET_CONFIGS:
        raise KeyError(f"Unknown preset '{name}'. Available: {', '.join(list_presets())}")
    return PRESET_CONFIGS[name]()


def banking_dataset() -> GenerationConfig:
    parent = _counterparty_table()
    child = _exposure_table()
    child.foreign_keys = [ForeignKey(column="counterparty_id", ref_table="counterparties", ref_column="id")]
    return GenerationConfig(tables=[parent, child], seed=42, dirty_ratio=0.05,
                            coverage=CoverageSpec(mode="edges"))
