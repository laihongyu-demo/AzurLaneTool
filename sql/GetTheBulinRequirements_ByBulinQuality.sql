-- 布里（升星材料）需求统计
--
-- 统计范围：已解锁的「常规」舰娘（排除 改造 / 方案 / META / 联动 / 小船 / μ兵装 与 UNIV 三艘布里）
-- 升星规则：不论稀有度均可升星 3 次，材料消耗为 1 + 1 + 2（最后一次升星消耗 2 份）
--           → 剩余需求 = 剩余升星次数 + 1（如 SSR 3★ 升满需 4 份、5★ 升满需 2 份）
-- 稀有度口径：N=4 / R=SR=5 / SSR=UR=6；方案舰使用 PRY / DR，不消耗布里，故不在布里种类映射中
--
-- 下列占位符由 utils/codex_options.py 的 RARITY_MAX_STAR / RARITY_BULIN_TYPE 生成
-- （由 CodexGroupRepository.getBulinRequirements 通过 loadSqlTemplate 注入）：
--   {max_star_case}      : 稀有度 → 满星阈值
--   {material_type_case} : 稀有度 → 布里种类（未登记稀有度返回 NULL，随后被过滤）
WITH StarDetails AS (
    SELECT
        ship_rarity,
        ship_star,
        {max_star_case} AS max_star
    FROM codex_group
    WHERE ship_group NOT IN ('改造', '方案', 'META', '联动', '小船', 'μ兵装')
      AND ship_camp != 'UNIV'
      AND codex_unlock = 'Y'
),
MaterialsRequired AS (
    SELECT
        {material_type_case} AS material_type,
        CASE
            -- 剩余升星次数 + 1：每次升星 1 份，最后一次为 2 份
            WHEN ship_star IS NULL OR ship_star >= max_star THEN 0
            ELSE max_star - ship_star + 1
        END AS materials_needed
    FROM StarDetails
)
SELECT
    material_type,
    SUM(materials_needed) AS total_neededMaterial
FROM MaterialsRequired
WHERE material_type IS NOT NULL
GROUP BY material_type
ORDER BY material_type DESC;
