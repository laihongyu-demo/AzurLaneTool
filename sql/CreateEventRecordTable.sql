-- 活动记录表结构
--
-- 幂等脚本：全部 IF NOT EXISTS，应用启动与一次性导入脚本都会执行。
-- 口径见 docs/20261022_活动记录方案与导入报告.md：
--   build_cost 为单次建造消耗的魔方数（1 或 2），用于把关联魔方折算成建造次数；
--   build_count 为手工 / 历史建造次数（NULL = 未统计，0 表示确实 0 次）；
--     有明细关联时展示值改为「关联魔方 ÷ build_cost + 券抽次数」，本列作为无关联时的回退值；
--   use_ticket / ticket_build_count 记录建造券抽（不消耗魔方），仅在有关联明细时参与合计；
--   event_type / status 用自由文本，避免以后扩展类型或状态时再做表结构迁移。
--   关联关系存放在 resource_transaction.event_id（一条明细最多关联一个活动）。

CREATE TABLE IF NOT EXISTS event_record (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    event_date  TEXT NOT NULL,
    event_type  TEXT NOT NULL DEFAULT '',
    name        TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT '',
    status_note TEXT NOT NULL DEFAULT '',
    -- 单次建造消耗的魔方数：1（轻型）或 2（重型 / 特型 / 多数活动池）
    build_cost  INTEGER NOT NULL DEFAULT 2 CHECK (build_cost IN (1, 2)),
    -- 是否使用过建造券；券抽不消耗魔方，单独补充次数
    use_ticket  INTEGER NOT NULL DEFAULT 0 CHECK (use_ticket IN (0, 1)),
    ticket_build_count INTEGER CHECK (ticket_build_count IS NULL OR ticket_build_count >= 0),
    -- 手工 / 历史建造次数；有明细关联时展示值改为「关联魔方 ÷ build_cost + 券抽」
    build_count INTEGER CHECK (build_count IS NULL OR build_count >= 0),
    note        TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at  TEXT
);

CREATE INDEX IF NOT EXISTS idx_event_record_date
    ON event_record (event_date);
