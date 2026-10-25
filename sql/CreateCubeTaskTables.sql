-- 资源任务看板表结构与任务定义
--
-- 幂等：全部 IF NOT EXISTS；任务定义用 ON CONFLICT DO UPDATE，保证定义以本文件为准。
-- 表名为历史名称，现同时承载魔方（18 项）与红尖尖世界巡游（6 项）任务。
-- 口径见 docs/魔方任务看板需求方案_20261017.md 与 docs/20261024_红尖尖固定来源方案.md。

CREATE TABLE IF NOT EXISTS cube_task (
    code         TEXT PRIMARY KEY,
    resource_type TEXT NOT NULL DEFAULT 'cube' CHECK (resource_type IN ('cube', 'red_gem')),
    grp          TEXT NOT NULL CHECK (grp IN ('daily', 'weekly', 'signin', 'cruise')),
    name         TEXT NOT NULL,
    short_name   TEXT NOT NULL DEFAULT '',
    reward       INTEGER NOT NULL CHECK (reward > 0),
    period_type  TEXT NOT NULL CHECK (period_type IN ('day', 'week', 'month', 'cruise')),
    category     TEXT NOT NULL,
    sort_order   INTEGER NOT NULL DEFAULT 0,
    active       INTEGER NOT NULL DEFAULT 1
);

-- 完成记录：一条记录对应一笔收入；transaction_id 为空表示"仅标记不记账"（期初对齐的兜底）
-- 建造任务（daily_build_once）额外挂两笔联动：
--   expense_transaction_id：建造支出明细（使用建造券时为空，表示不扣魔方）；
--   event_id：本次建造关联 / 计数的进行中活动，取消时据此回滚券抽次数。
CREATE TABLE IF NOT EXISTS cube_task_completion (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    task_code              TEXT NOT NULL,
    period_key             TEXT NOT NULL,
    completed_at           TEXT NOT NULL,
    transaction_id         INTEGER,
    expense_transaction_id INTEGER,
    event_id               INTEGER,
    created_at             TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    UNIQUE (task_code, period_key)
);

CREATE INDEX IF NOT EXISTS idx_cube_task_completion_period
    ON cube_task_completion (period_key);

-- 任务定义（18 项）。奖励合计：每日 4 / 每周 12 / 每月 30 / 每期 50
-- short_name 用于看板卡片（单行），name 作为完整名称放进 tooltip
INSERT INTO cube_task (code, grp, name, short_name, reward, period_type, category, sort_order, active) VALUES
    ('daily_battle_win',  'daily',  '日常任务·舰队出征，获得 3 次战斗胜利',      '战斗×3',          2, 'day',    '日常任务', 10, 1),
    ('daily_build_once',  'daily',  '日常任务·建造舰船 1 次',                    '建造',            1, 'day',    '日常任务', 20, 1),
    ('daily_hard_stage',  'daily',  '日常任务·舰队出征，通关主线困难海域 1 次',  '困难海域',        1, 'day',    '日常任务', 30, 1),
    ('weekly_pt_150',     'weekly', '周常任务·周常 PT 累计 150',                 'PT 150',          3, 'week',   '周常任务', 110, 1),
    ('weekly_pt_350',     'weekly', '周常任务·周常 PT 累计 350',                 'PT 350',          3, 'week',   '周常任务', 120, 1),
    ('weekly_pt_750',     'weekly', '周常任务·周常 PT 累计 750',                 'PT 750',          6, 'week',   '周常任务', 130, 1),
    ('signin_1',          'signin', '每月签到·1',                                '签到 1',          3, 'month',  '每月签到', 210, 1),
    ('signin_2',          'signin', '每月签到·2',                                '签到 2',          6, 'month',  '每月签到', 220, 1),
    ('signin_3',          'signin', '每月签到·3',                                '签到 3',          9, 'month',  '每月签到', 230, 1),
    ('signin_4',          'signin', '每月签到·4',                                '签到 4',         12, 'month',  '每月签到', 240, 1),
    ('cruise_lv05',       'cruise', '世界巡游·5 级',                             '5 级',            5, 'cruise', '世界巡游', 310, 1),
    ('cruise_lv15',       'cruise', '世界巡游·15 级',                            '15 级',           7, 'cruise', '世界巡游', 320, 1),
    ('cruise_lv25',       'cruise', '世界巡游·25 级',                            '25 级',           5, 'cruise', '世界巡游', 330, 1),
    ('cruise_lv35',       'cruise', '世界巡游·35 级',                            '35 级',           8, 'cruise', '世界巡游', 340, 1),
    ('cruise_lv45',       'cruise', '世界巡游·45 级',                            '45 级',           5, 'cruise', '世界巡游', 350, 1),
    ('cruise_lv55',       'cruise', '世界巡游·55 级',                            '55 级',           7, 'cruise', '世界巡游', 360, 1),
    ('cruise_lv65',       'cruise', '世界巡游·65 级',                            '65 级',           5, 'cruise', '世界巡游', 370, 1),
    ('cruise_lv75',       'cruise', '世界巡游·75 级',                            '75 级',           8, 'cruise', '世界巡游', 380, 1)
ON CONFLICT(code) DO UPDATE SET
    resource_type = 'cube',
    grp         = excluded.grp,
    name        = excluded.name,
    short_name  = excluded.short_name,
    reward      = excluded.reward,
    period_type = excluded.period_type,
    category    = excluded.category,
    sort_order  = excluded.sort_order;

-- 红尖尖固定来源：世界巡游（大月卡）6 档，每档 50，每期合计 300
INSERT INTO cube_task
    (code, resource_type, grp, name, short_name, reward, period_type, category, sort_order, active)
VALUES
    ('red_cruise_lv10', 'red_gem', 'cruise', '世界巡游·10 级', '10 级', 50, 'cruise', '世界巡游', 410, 1),
    ('red_cruise_lv20', 'red_gem', 'cruise', '世界巡游·20 级', '20 级', 50, 'cruise', '世界巡游', 420, 1),
    ('red_cruise_lv40', 'red_gem', 'cruise', '世界巡游·40 级', '40 级', 50, 'cruise', '世界巡游', 430, 1),
    ('red_cruise_lv60', 'red_gem', 'cruise', '世界巡游·60 级', '60 级', 50, 'cruise', '世界巡游', 440, 1),
    ('red_cruise_lv70', 'red_gem', 'cruise', '世界巡游·70 级', '70 级', 50, 'cruise', '世界巡游', 450, 1),
    ('red_cruise_lv80', 'red_gem', 'cruise', '世界巡游·80 级', '80 级', 50, 'cruise', '世界巡游', 460, 1)
ON CONFLICT(code) DO UPDATE SET
    resource_type = excluded.resource_type,
    grp         = excluded.grp,
    name        = excluded.name,
    short_name  = excluded.short_name,
    reward      = excluded.reward,
    period_type = excluded.period_type,
    category    = excluded.category,
    sort_order  = excluded.sort_order,
    active      = excluded.active;
