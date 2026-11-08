"""
世界巡游档期服务模块。

世界巡游档期是跨资源的独立概念：魔方任务看板与红尖尖任务看板都引用本服务，
不再各自计算「每 2 个自然月一期」的起止日期。
"""

from dataclasses import dataclass
from datetime import date
from typing import List, Optional

from utils import time_source
from utils.constants import CRUISE_PERIOD_MONTHS
from utils.exceptions import ValidationError
from utils.task_period import addMonths, cruisePeriodEnd, cruisePeriodStart


@dataclass
class WorldCruisePeriod:
    """
    世界巡游档期。

    Attributes:
        key: 档期键，起始月 ``yyyy-MM``。
        start: 起始日。
        end: 结束日（含）。
        label: 展示文案，如 ``2026-10-01 ~ 2026-11-30``。
    """

    key: str
    start: date
    end: date
    label: str


class WorldCruiseService:
    """世界巡游档期计算服务（无状态）。"""

    def getPeriod(self, when: date) -> WorldCruisePeriod:
        """
        获取指定日期所属的档期。

        Args:
            when: 任意日期。

        Returns:
            档期对象。
        """
        return self._buildPeriod(cruisePeriodStart(when))

    def getCurrentPeriod(self) -> WorldCruisePeriod:
        """
        获取今天所属的档期。

        Returns:
            当前档期。
        """
        return self.getPeriod(time_source.today())

    def getPeriodByKey(self, period_key: str) -> WorldCruisePeriod:
        """
        按档期键获取档期。

        Args:
            period_key: 起始月 ``yyyy-MM``。

        Returns:
            档期对象。

        Raises:
            ValidationError: 键格式非法或不是偶数月起始时抛出。
        """
        try:
            year_text, month_text = period_key.split("-")
            year = int(year_text)
            month = int(month_text)
            candidate = date(year, month, 1)
        except (ValueError, AttributeError):
            raise ValidationError(f"无效的世界巡游档期: {period_key}")

        start = cruisePeriodStart(candidate)
        if start.strftime("%Y-%m") != period_key:
            raise ValidationError(f"无效的世界巡游档期: {period_key}")
        return self._buildPeriod(start)

    def listPeriods(
        self, reference: Optional[date] = None, past_count: int = 12
    ) -> List[WorldCruisePeriod]:
        """
        列出参考日期所属档期及其之前的若干档期。

        返回顺序为当前档期在前、越早越靠后，便于下拉框默认选中当前期。

        Args:
            reference: 参考日期，默认今天。
            past_count: 额外列出的历史档期数量。

        Returns:
            档期列表。
        """
        current = self.getPeriod(reference or time_source.today())
        periods = [current]
        start = current.start
        for _ in range(max(0, past_count)):
            start = addMonths(start, -CRUISE_PERIOD_MONTHS)
            periods.append(self._buildPeriod(start))
        return periods

    def _buildPeriod(self, start: date) -> WorldCruisePeriod:
        """
        由档期起始日构造档期对象。

        Args:
            start: 档期起始日（偶数月 1 日）。

        Returns:
            档期对象。
        """
        end = cruisePeriodEnd(start)
        return WorldCruisePeriod(
            key=start.strftime("%Y-%m"),
            start=start,
            end=end,
            label=f"{start:%Y-%m-%d} ~ {end:%Y-%m-%d}",
        )
