"""
任务周期值对象模块。

定义与具体资源无关的周期展示信息，供魔方 / 红尖尖任务看板共用。
"""

from dataclasses import dataclass


@dataclass
class TaskPeriodInfo:
    """
    单个周期的展示信息。

    Attributes:
        period_type: 周期类型，``day`` / ``week`` / ``month`` / ``cruise``。
        period_key: 周期键。
        label: 展示文案（如 ``2026 第 42 周（10-12 ~ 10-18）``）。
        start: 起始日期 ``yyyy-MM-dd``。
        end: 结束日期 ``yyyy-MM-dd``。
    """

    period_type: str
    period_key: str
    label: str
    start: str
    end: str
