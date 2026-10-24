-- 类型字典：按使用习惯排序（sort_order 越小越靠前）
--
-- 仅在 resource_category 为空时由 utils/db_schema.py 执行一次（见 _seedCategoriesIfEmpty）。
-- 之后用户的改名 / 顺序 / 停用状态一律以库为准，启动不再覆盖（#21）。
-- 顺序由使用频率决定，新类型统一补在各自方向末尾；「未知」永远是最后一项。
--
-- 这里的 ON CONFLICT DO NOTHING 只是防重放兜底：同一份脚本重复执行不会产生重复行。

-- ---- 魔方 · 收入 ----
INSERT INTO resource_category (resource_type, direction, name, sort_order) VALUES
    ('cube', 'income', '军事委托',     10),
    ('cube', 'income', '活动签到',     20),
    ('cube', 'income', '活动任务',     30),
    ('cube', 'income', '活动商店',     40),
    ('cube', 'income', '贸易许可证',   50),
    ('cube', 'income', '节日奖励',     60),
    ('cube', 'income', '礼包',         70),
    ('cube', 'income', '军火商店',     80),
    ('cube', 'income', '军需商店',     90),
    ('cube', 'income', '作战档案',    100),
    ('cube', 'income', '主线任务',    110),
    ('cube', 'income', '手册任务',    120),
    ('cube', 'income', '海域探索',    130),
    ('cube', 'income', '直购',        140),
    -- 历史遗留、使用极少，排在列表后段
    ('cube', 'income', '补给商店',   9500),
    ('cube', 'income', '未知',       9999)
ON CONFLICT(resource_type, direction, name) DO NOTHING;

-- ---- 魔方 · 支出 ----
INSERT INTO resource_category (resource_type, direction, name, sort_order) VALUES
    ('cube', 'expense', '轻型建造',  10),
    ('cube', 'expense', '重型建造',  20),
    ('cube', 'expense', '特型建造',  30),
    ('cube', 'expense', '活动建造',  40),
    ('cube', 'expense', '祈愿建造',  50),
    ('cube', 'expense', '开发船坞',  60),
    ('cube', 'expense', '军部研究',  70)
ON CONFLICT(resource_type, direction, name) DO NOTHING;

-- ---- 红尖尖 · 收入 ----
INSERT INTO resource_category (resource_type, direction, name, sort_order) VALUES
    ('red_gem', 'income', '军事委托',  10),
    ('red_gem', 'income', '礼包',      20),
    ('red_gem', 'income', '世界巡游',  25),
    ('red_gem', 'income', '月卡',      30),
    ('red_gem', 'income', '贸易许可证', 35),
    ('red_gem', 'income', '活动任务',  40),
    ('red_gem', 'income', '维护奖励',  50),
    ('red_gem', 'income', '节日奖励',  60),
    ('red_gem', 'income', '岛屿计划',  70),
    ('red_gem', 'income', '主线任务',  80),
    ('red_gem', 'income', '充值',      90)
ON CONFLICT(resource_type, direction, name) DO NOTHING;

-- ---- 红尖尖 · 支出 ----
INSERT INTO resource_category (resource_type, direction, name, sort_order) VALUES
    ('red_gem', 'expense', '皮肤',    10),
    ('red_gem', 'expense', '礼包',    20),
    ('red_gem', 'expense', '石油',    30),
    ('red_gem', 'expense', '船坞',    40),
    ('red_gem', 'expense', '戒指',    50),
    ('red_gem', 'expense', '心智',    60),
    ('red_gem', 'expense', '密语',    70),
    ('red_gem', 'expense', '星彩奖',  80),
    ('red_gem', 'expense', '物资',    90)
ON CONFLICT(resource_type, direction, name) DO NOTHING;
