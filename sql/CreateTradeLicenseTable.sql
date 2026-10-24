-- 贸易许可证（小月卡）购买记录
--
-- 幂等：IF NOT EXISTS。该表只记录购买 / 续约与期初登记，不自动记录每日 1 魔方。
-- 口径见 docs/20261024_红尖尖固定来源方案.md §4。

CREATE TABLE IF NOT EXISTS trade_license_purchase (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    purchase_time  TEXT NOT NULL,
    start_date     TEXT NOT NULL,
    end_date       TEXT NOT NULL,
    days           INTEGER NOT NULL DEFAULT 30 CHECK (days > 0),
    amount         INTEGER NOT NULL DEFAULT 500 CHECK (amount >= 0),
    transaction_id INTEGER,
    note           TEXT NOT NULL DEFAULT '',
    created_at     TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    CHECK (end_date >= start_date)
);

CREATE INDEX IF NOT EXISTS idx_trade_license_purchase_end
    ON trade_license_purchase (end_date);
