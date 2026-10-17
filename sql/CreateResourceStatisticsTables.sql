-- 资源统计相关表结构（魔方 / 红尖尖 / 等级经验基准）
--
-- 幂等脚本：全部使用 IF NOT EXISTS，应用启动时与迁移脚本都会执行。
-- 口径说明见 docs/资源统计迁移需求文档_20261017.md §6.1。

-- 日汇总行：明细日只存模式与结余锚点，汇总日才存收支
CREATE TABLE IF NOT EXISTS resource_daily (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    resource_type    TEXT NOT NULL CHECK (resource_type IN ('cube', 'red_gem')),
    record_date      TEXT NOT NULL,
    detail_mode      TEXT NOT NULL DEFAULT 'detail'
                     CHECK (detail_mode IN ('detail', 'summary_only')),
    income           INTEGER,
    expense          INTEGER,
    balance_override INTEGER CHECK (balance_override IS NULL OR balance_override >= 0),
    note             TEXT NOT NULL DEFAULT '',
    last_record_time TEXT,
    created_at       TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at       TEXT,
    UNIQUE (resource_type, record_date),
    CHECK (
        (detail_mode = 'summary_only' AND income IS NOT NULL AND expense IS NOT NULL)
     OR (detail_mode = 'detail'       AND income IS NULL     AND expense IS NULL)
    )
);

-- 明细：一笔收入或支出
CREATE TABLE IF NOT EXISTS resource_transaction (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    resource_type TEXT NOT NULL CHECK (resource_type IN ('cube', 'red_gem')),
    direction     TEXT NOT NULL CHECK (direction IN ('income', 'expense')),
    record_time   TEXT NOT NULL,
    category      TEXT NOT NULL,
    amount        INTEGER NOT NULL CHECK (amount > 0),
    note          TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at    TEXT
);

-- 事件字典：录入下拉候选，来自原表格枚举
CREATE TABLE IF NOT EXISTS resource_category (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    resource_type TEXT NOT NULL CHECK (resource_type IN ('cube', 'red_gem')),
    direction     TEXT NOT NULL CHECK (direction IN ('income', 'expense')),
    name          TEXT NOT NULL,
    sort_order    INTEGER NOT NULL DEFAULT 0,
    UNIQUE (resource_type, direction, name)
);

-- 等级 → 升级所需经验基准（由 data/commander_level.csv 导入）
CREATE TABLE IF NOT EXISTS commander_level_exp (
    level          INTEGER PRIMARY KEY CHECK (level BETWEEN 1 AND 200),
    level_up_exp   INTEGER CHECK (level_up_exp IS NULL OR level_up_exp > 0),
    cumulative_exp INTEGER CHECK (cumulative_exp IS NULL OR cumulative_exp > 0),
    note           TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_resource_transaction_time
    ON resource_transaction (resource_type, record_time);

-- resource_daily 已有 UNIQUE (resource_type, record_date)，无需重复建索引。
-- commander_info 的唯一索引由迁移脚本在时间规范化之后建立（见 tools/migrate_resource_statistics.py）。
-- 旧库（明细 record_date 仅日期、日汇总缺 last_record_time）由 utils/db_schema.py 的幂等升级逻辑自动迁移。
