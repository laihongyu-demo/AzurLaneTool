-- 指挥官快照表结构（commander_info）
--
-- 首次使用（#8）需要建出空白模板；历史库中该表由早期迁移脚本建立，
-- 结构以 tools/migrate_resource_statistics.py 为准。
-- 等级经验基准 commander_level_exp 定义在 CreateResourceStatisticsTables.sql，这里不重复。
--
-- 幂等：IF NOT EXISTS；唯一索引按 statistics_date 去重（迁移脚本在时间规范化后同样建这个索引）。

CREATE TABLE IF NOT EXISTS commander_info (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    statistics_date  TEXT DEFAULT CURRENT_TIMESTAMP,
    commander_level  INTEGER NOT NULL CHECK (commander_level BETWEEN 1 AND 999),
    commander_exp    INTEGER NOT NULL CHECK (commander_exp >= 0)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_commander_info_date
    ON commander_info (statistics_date);
