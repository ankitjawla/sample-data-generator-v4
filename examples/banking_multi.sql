-- Multi-table: counterparties (parent) -> exposures (child), with a foreign key.
--   python -m sdgen.cli import-ddl examples/banking_multi.sql --out examples/banking_multi.config.json
--   python -m sdgen.cli generate  examples/banking_multi.config.json --out ./output --formats csv
CREATE TABLE counterparties (
    id            BIGINT       NOT NULL PRIMARY KEY,
    legal_name    VARCHAR(120) NOT NULL,
    country_code  VARCHAR(2)   NOT NULL,
    sector        VARCHAR(20)  CHECK (sector IN ('Bank','Corporate','Sovereign','Household'))
);
CREATE TABLE exposures (
    exposure_id      BIGINT        NOT NULL PRIMARY KEY,
    counterparty_id  BIGINT        NOT NULL REFERENCES counterparties(id),
    exposure_class   VARCHAR(20)   NOT NULL CHECK (exposure_class IN ('Corporate','Institution','Retail','Sovereign')),
    on_balance_flag  CHAR(3)       CHECK (on_balance_flag IN ('ON','OFF')),
    exposure_amount  DECIMAL(18,2) NOT NULL,
    booking_date     DATE          NOT NULL
);
