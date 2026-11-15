-- 图鉴相关表结构（codex_group / codex_tp / codex_buff / awakening_of_mind）
--
-- 历史背景：这四张表原本由图鉴导入流程（外部工具）维护，应用只做「按需补列 + 回填」。
-- 首次使用（#8）需要在没有数据库时得到一份可直接使用的空白模板，因此这里按当前库结构建空表：
--   * 只建结构，不写入任何图鉴数据；
--   * 幂等：全部 IF NOT EXISTS，已有表与数据不受影响；
--   * codex_group 保留 update_codex_group_modtime 触发器，与真实库行为一致
--     （批量回填必须用 utils.db_schema.suspendCodexGroupModtimeTrigger 包住）。
--
-- 字段与真实库一致；默认值只覆盖应用新增舰娘时总会显式写入的列，
-- 避免外部导入省略列时写入与界面口径不一致的值。

CREATE TABLE IF NOT EXISTS codex_group (
    codex_id       TEXT NOT NULL,
    ship_name      TEXT,
    ship_level     TEXT DEFAULT '未觉醒',
    ship_star      INTEGER,
    ship_rarity    TEXT,
    ship_typ       TEXT,
    ship_group     TEXT,
    ship_aid       NUMERIC NOT NULL,
    ship_camp      TEXT,
    ship_liking    TEXT DEFAULT '陌生',
    oath_status    TEXT DEFAULT 'N',
    codex_unlock   TEXT DEFAULT 'N',
    date_edit      NUMERIC,
    fleet_position TEXT,
    PRIMARY KEY (codex_id)
);

CREATE TABLE IF NOT EXISTS codex_tp (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    codex_id    TEXT NOT NULL,
    ship_name   TEXT,
    ship_camp   TEXT,
    ship_typ    TEXT,
    tp_value    INTEGER,
    unlock_cond TEXT,
    tp_unlock   TEXT DEFAULT 'N',
    date_edit   TEXT,
    FOREIGN KEY (codex_id) REFERENCES codex_group (codex_id)
);

CREATE TABLE IF NOT EXISTS codex_buff (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    codex_id    TEXT NOT NULL,
    ship_name   TEXT,
    ship_camp   TEXT,
    ship_typ    TEXT,
    boost_typ   TEXT NOT NULL,
    buff_typ    TEXT,
    buff_value  INTEGER,
    buff_cond   TEXT,
    buff_unlock TEXT DEFAULT 'N',
    FOREIGN KEY (codex_id) REFERENCES codex_group (codex_id)
);

-- 觉醒材料基准：按「稀有度 × 心智觉醒阶段」给出消耗。
-- 首次建库只建空表；基准值需要由后续种子/导入补齐（见 docs/20261115 方案文档「风险与后续」）。
CREATE TABLE IF NOT EXISTS awakening_of_mind (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ship_rarity  TEXT,
    am_phase     INTEGER,
    expend_gc    INTEGER,
    expend_limit INTEGER,
    expend_limit2 INTEGER
);

-- 任意 UPDATE 后把 date_edit 改写为当前时间（与真实库触发器同名同义）
CREATE TRIGGER IF NOT EXISTS update_codex_group_modtime
AFTER UPDATE ON codex_group
FOR EACH ROW
BEGIN
    UPDATE codex_group
    SET date_edit = datetime('now', 'localtime')
    WHERE codex_id = OLD.codex_id;
END;
