-- 科技属性按增益目标舰种（boost_typ）× Buff 属性类型（buff_typ）汇总 buff_value。
-- 只读；由 CodexBuffRepository.getMatrixByBoostTypAndBuffTyp() 加载。
-- 口径：
--   total_value：该组合下所有记录的 buff_value 之和；
--   unlocked_value：buff_unlock='Y' 的记录的 buff_value 之和；
--   record_count：该组合的记录条数（用于区分「无记录」与「有记录但未解锁」）。
SELECT
    TRIM(boost_typ) AS boost_typ,
    TRIM(buff_typ) AS buff_typ,
    COALESCE(SUM(buff_value), 0) AS total_value,
    COALESCE(SUM(CASE WHEN buff_unlock = 'Y' THEN buff_value ELSE 0 END), 0) AS unlocked_value,
    COUNT(*) AS record_count
FROM codex_buff
WHERE boost_typ IS NOT NULL
  AND TRIM(boost_typ) <> ''
  AND buff_typ IS NOT NULL
  AND TRIM(buff_typ) <> ''
GROUP BY TRIM(boost_typ), TRIM(buff_typ);
