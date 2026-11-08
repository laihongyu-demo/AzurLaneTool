"""
任务周期计算模块。

把日 / 周 / 月 / 双月巡游期的计算从魔方任务服务中独立出来，供魔方、红尖尖
以及后续其它资源模块共用。本模块只做纯日期计算，不访问数据库、不依赖 Qt。
"""

import calendar
from datetime import date, timedelta
from typing import Dict, Tuple

from models.task_period import TaskPeriodInfo
from utils.constants import (
    CRUISE_PERIOD_MONTHS, RECORD_DATE_FORMAT, TASK_PERIOD_CRUISE, TASK_PERIOD_DAY,
    TASK_PERIOD_MONTH, TASK_PERIOD_WEEK, TASK_PERIODS,
)


def addMonths(value: date, months: int) -> date:
    """
    在日期上增减自然月（月末自动取该月最后一天）。

    Args:
        value: 基准日期。
        months: 增减的月数（可为负）。

    Returns:
        计算后的日期。
    """
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def cruisePeriodStart(when: date) -> date:
    """
    计算世界巡游「本期」的起始日。

    规则：每 2 个自然月为一期，起点为偶数月 1 日 00:00。

    Args:
        when: 任意日期。

    Returns:
        本期起始日。
    """
    month = when.month - (when.month % CRUISE_PERIOD_MONTHS)
    if month <= 0:
        return date(when.year - 1, 12, 1)
    return date(when.year, month, 1)


def cruisePeriodEnd(when: date) -> date:
    """
    计算世界巡游「本期」的结束日（含）。

    Args:
        when: 任意日期。

    Returns:
        本期结束日。
    """
    return addMonths(cruisePeriodStart(when), CRUISE_PERIOD_MONTHS) - timedelta(days=1)


def weekRange(when: date) -> Tuple[date, date]:
    """
    计算 ISO 周（周一 ~ 周日）的起止日期。

    Args:
        when: 任意日期。

    Returns:
        ``(周一, 周日)``。
    """
    monday = when - timedelta(days=when.weekday())
    return monday, monday + timedelta(days=6)


def monthRange(when: date) -> Tuple[date, date]:
    """
    计算自然月的起止日期。

    Args:
        when: 任意日期。

    Returns:
        ``(1 日, 月末)``。
    """
    last_day = calendar.monthrange(when.year, when.month)[1]
    return date(when.year, when.month, 1), date(when.year, when.month, last_day)


def buildPeriodKey(period_type: str, when: date) -> str:
    """
    按周期类型生成周期键。

    Args:
        period_type: ``day`` / ``week`` / ``month`` / ``cruise``。
        when: 归属日期。

    Returns:
        周期键：``2026-10-17`` / ``2026-W42`` / ``2026-10``（月与期为 ``yyyy-MM``）。

    Raises:
        ValidationError: 周期类型未知时抛出。
    """
    from utils.exceptions import ValidationError

    if period_type == TASK_PERIOD_DAY:
        return when.strftime(RECORD_DATE_FORMAT)
    if period_type == TASK_PERIOD_WEEK:
        iso_year, iso_week, _ = when.isocalendar()
        return f"{iso_year:04d}-W{iso_week:02d}"
    if period_type == TASK_PERIOD_MONTH:
        return when.strftime("%Y-%m")
    if period_type == TASK_PERIOD_CRUISE:
        return cruisePeriodStart(when).strftime("%Y-%m")
    raise ValidationError(f"未知的周期类型: {period_type}")


def periodRange(period_type: str, when: date) -> Tuple[date, date]:
    """
    计算某周期的起止日期。

    Args:
        period_type: 周期类型。
        when: 归属日期。

    Returns:
        ``(起始日, 结束日)``，均含当天。

    Raises:
        ValidationError: 周期类型未知时抛出。
    """
    from utils.exceptions import ValidationError

    if period_type == TASK_PERIOD_DAY:
        return when, when
    if period_type == TASK_PERIOD_WEEK:
        return weekRange(when)
    if period_type == TASK_PERIOD_MONTH:
        return monthRange(when)
    if period_type == TASK_PERIOD_CRUISE:
        return cruisePeriodStart(when), cruisePeriodEnd(when)
    raise ValidationError(f"未知的周期类型: {period_type}")


def formatPeriodLabel(period_type: str, start: date, end: date) -> str:
    """
    生成周期展示文案。

    Args:
        period_type: 周期类型。
        start: 起始日。
        end: 结束日。

    Returns:
        展示文案。
    """
    if period_type == TASK_PERIOD_DAY:
        return start.strftime(RECORD_DATE_FORMAT)
    if period_type == TASK_PERIOD_WEEK:
        iso_year, iso_week, _ = start.isocalendar()
        return f"{iso_year} 第 {iso_week} 周（{start:%m-%d} ~ {end:%m-%d}）"
    if period_type == TASK_PERIOD_MONTH:
        return start.strftime("%Y-%m")
    return f"{start:%Y-%m-%d} ~ {end:%Y-%m-%d}"


def buildPeriodInfo(period_type: str, when: date) -> TaskPeriodInfo:
    """
    构造一个周期的展示信息。

    Args:
        period_type: 周期类型。
        when: 归属日期。

    Returns:
        周期展示信息。
    """
    start, end = periodRange(period_type, when)
    return TaskPeriodInfo(
        period_type=period_type,
        period_key=buildPeriodKey(period_type, when),
        label=formatPeriodLabel(period_type, start, end),
        start=start.strftime(RECORD_DATE_FORMAT),
        end=end.strftime(RECORD_DATE_FORMAT),
    )


def getPeriodInfo(when: date) -> Dict[str, TaskPeriodInfo]:
    """
    构造日 / 周 / 月 / 期四个周期的展示信息。

    Args:
        when: 归属日期。

    Returns:
        周期类型 → 周期展示信息。
    """
    return {period_type: buildPeriodInfo(period_type, when) for period_type in TASK_PERIODS}
