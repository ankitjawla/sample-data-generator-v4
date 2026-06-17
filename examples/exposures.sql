-- Single-table banking exposure feed. Import into a JSON config:
--   python -m sdgen.cli import-ddl examples/exposures.sql --out examples/exposures.config.json
CREATE TABLE exposures (
    exposure_id      BIGINT        NOT NULL PRIMARY KEY,
    counterparty     VARCHAR(120)  NOT NULL,
    exposure_class   VARCHAR(20)   NOT NULL CHECK (exposure_class IN ('Corporate','Institution','Retail','Sovereign','CentralBank')),
    on_balance_flag  CHAR(3)       CHECK (on_balance_flag IN ('ON','OFF')),
    exposure_amount  DECIMAL(18,2) NOT NULL,
    currency_code    CHAR(3)       NOT NULL,
    booking_date     DATE          NOT NULL,
    risk_rating      SMALLINT,
    email            VARCHAR(200)
);
