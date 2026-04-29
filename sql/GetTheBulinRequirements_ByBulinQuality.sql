WITH StarDetails AS (
    SELECT 
        ship_name,
        ship_rarity,
        ship_star,
        CASE 
            WHEN ship_rarity = 'N' THEN 4
            WHEN ship_rarity = 'R' THEN 5
            WHEN ship_rarity = 'SR' THEN 5
            WHEN ship_rarity = 'SSR' THEN 6
            WHEN ship_rarity = 'UR' THEN 6
            ELSE 0
        END AS max_star,
        CASE 
            WHEN ship_rarity = 'N' THEN 1
            WHEN ship_rarity = 'R' THEN 2
            WHEN ship_rarity = 'SR' THEN 2
            WHEN ship_rarity = 'SSR' THEN 3
            WHEN ship_rarity = 'UR' THEN 3
            ELSE 0
        END AS initial_star
    FROM codex_group
    WHERE ship_group NOT IN ('改造', '方案', 'META', '联动', '小船', 'μ兵装') AND codex_unlock = 'Y'
),
MaterialsRequired AS (
    SELECT 
        CASE 
            WHEN ship_rarity IN ('N', 'R', 'SR') THEN 'Universal Bulin'
            WHEN ship_rarity = 'SSR' THEN 'Trial Bulin MKII'
            WHEN ship_rarity = 'UR' THEN 'Specialized Bulin MKIII'
            ELSE NULL
        END AS material_type,
        CASE
            -- 计算升星所需总材料数量
            WHEN ship_star < max_star - 1 THEN 
                -- 若当前星级小于最大星级 - 1，每星升仲消耗 1 份材料
                (max_star - 1 - ship_star) + 2  -- 最后升一级需要2个
            WHEN ship_star = max_star - 1 THEN 
                -- 若当前星级为最大星级 - 1，则只需1次升星等级消耗2份材料
                2
            ELSE 0
        END AS materials_needed
    FROM StarDetails
    WHERE material_type IS NOT NULL
)
SELECT 
    material_type,
    SUM(materials_needed) AS total_neededMaterial
FROM MaterialsRequired
GROUP BY material_type
ORDER BY material_type DESC;