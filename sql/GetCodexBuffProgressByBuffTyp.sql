-- 科技属性按 Buff 属性类型（buff_typ）汇总 buff_value。
-- 只读；由 CodexBuffRepository.getProgressByBuffTyp() 通过 loadSqlFile() 加载。
-- 口径：
--   total_value：该 buff_typ 下所有记录的 buff_value 之和；
--   unlocked_value：buff_unlock='Y' 的记录的 buff_value 之和。
SELECT
    TRIM(buff_typ) AS buff_typ,
    COALESCE(SUM(buff_value), 0) AS total_value,
    COALESCE(SUM(CASE WHEN buff_unlock = 'Y' THEN buff_value ELSE 0 END), 0) AS unlocked_value
FROM codex_buff
WHERE buff_typ IS NOT NULL
  AND TRIM(buff_typ) <> ''
GROUP BY TRIM(buff_typ)
ORDER BY TRIM(buff_typ);
