"""
资源统计服务模块。

提供魔方 / 红尖尖的结余扫描、看板展示文本与只读查询。

本阶段（需求文档 v0.2）不提供任何写入接口，录入与编辑推迟到 #17。
"""

from typing import Dict, List, Optional

from models.resource_model import ResourceDailyModel
from repositories.resource_repository import ResourceRepository
from utils.constants import RESOURCE_DETAIL_MODE_DETAIL, RESOURCE_DISPLAY_NAMES
from utils.db_schema import isMissingTableError
from utils.exceptions import DatabaseError
from utils.unit_formatter import formatExact, formatValue

# 结余扫描结果的字段名，供视图层与卡片复用
BALANCE_DATE = "record_date"
BALANCE_INCOME = "income"
BALANCE_EXPENSE = "expense"
BALANCE_VALUE = "balance"
BALANCE_MODE = "detail_mode"
BALANCE_TRANSACTION_COUNT = "transaction_count"
BALANCE_OVERRIDE = "balance_override"
BALANCE_NOTE = "note"


class ResourceService:
    """
    资源统计服务类。

    结余是派生值：按日期顺序扫描日汇总行，明细日取 Σ明细，汇总日取存储值；
    遇到手填结余（锚点）则重设累计值。因此该服务只读，不存在缓存失效问题。
    """

    def __init__(self, resource_repository: Optional[ResourceRepository] = None):
        """
        初始化资源统计服务。

        Args:
            resource_repository: 资源数据访问实例。
        """
        self._resource_repository = resource_repository or ResourceRepository()

    def getBalanceSeries(self, resource_type: str) -> List[Dict]:
        """
        计算指定资源的逐日收支与结余。

        Args:
            resource_type: 资源类型，``cube`` 或 ``red_gem``。

        Returns:
            按日期升序的列表，每项包含 ``record_date``、``income``、``expense``、
            ``balance``、``detail_mode``、``transaction_count``、``balance_override``、``note``。
            表缺失或无数据时返回空列表。
        """
        try:
            daily_rows = self._resource_repository.findAllDaily(resource_type)
            totals = self._resource_repository.findTransactionTotals(resource_type)
        except DatabaseError as e:
            if isMissingTableError(e):
                return []
            raise

        series: List[Dict] = []
        balance = 0
        for row in daily_rows:
            income, expense, count = self._resolveDailyAmount(row, totals)
            if row.balance_override is not None:
                balance = int(row.balance_override)
            else:
                balance += income - expense

            series.append({
                BALANCE_DATE: row.record_date,
                BALANCE_INCOME: income,
                BALANCE_EXPENSE: expense,
                BALANCE_VALUE: balance,
                BALANCE_MODE: row.detail_mode,
                BALANCE_TRANSACTION_COUNT: count,
                BALANCE_OVERRIDE: row.balance_override,
                BALANCE_NOTE: row.note,
            })
        return series

    def _resolveDailyAmount(self, row: ResourceDailyModel, totals: Dict[str, Dict[str, int]]):
        """
        解析单日的收入、支出与明细笔数。

        Args:
            row: 日汇总行。
            totals: 按日期汇总的明细，来自 :meth:`getBalanceSeries` 的一次性查询。

        Returns:
            ``(income, expense, transaction_count)`` 三元组。
        """
        if row.detail_mode == RESOURCE_DETAIL_MODE_DETAIL:
            bucket = totals.get(row.record_date, {})
            return (
                int(bucket.get("income", 0)),
                int(bucket.get("expense", 0)),
                int(bucket.get("count", 0)),
            )
        return int(row.income or 0), int(row.expense or 0), 0

    def getBalance(self, resource_type: str) -> Optional[int]:
        """
        获取指定资源的当前结余（最后一个有记录日期的累计值）。

        Args:
            resource_type: 资源类型。

        Returns:
            结余数值；无数据时返回 None。
        """
        series = self.getBalanceSeries(resource_type)
        if not series:
            return None
        return series[-1][BALANCE_VALUE]

    def getLatestRecordDate(self, resource_type: str) -> Optional[str]:
        """
        获取指定资源最后一个有记录的日期。

        Args:
            resource_type: 资源类型。

        Returns:
            日期字符串 ``yyyy-MM-dd``；无数据时返回 None。
        """
        series = self.getBalanceSeries(resource_type)
        if not series:
            return None
        return series[-1][BALANCE_DATE]

    def getCardText(self, resource_type: str) -> str:
        """
        获取看板卡片显示文本。

        魔方 / 红尖尖属于"大概数值"口径：用 K/M/B/T 缩写并保留一位小数。

        Args:
            resource_type: 资源类型。

        Returns:
            卡片文本；无数据时为 ``-``。
        """
        balance = self.getBalance(resource_type)
        if balance is None:
            return "-"
        return formatValue(balance)

    def getCardTooltip(self, resource_type: str) -> str:
        """
        获取看板卡片悬停提示（精确数值 + 数据截止日期）。

        Args:
            resource_type: 资源类型。

        Returns:
            提示文本；无数据时说明暂无记录。
        """
        display_name = RESOURCE_DISPLAY_NAMES.get(resource_type, resource_type)
        series = self.getBalanceSeries(resource_type)
        if not series:
            return f"{display_name}：暂无记录"

        latest = series[-1]
        detail = "末次记录 " + str(latest[BALANCE_DATE])
        return f"{display_name}：{formatExact(latest[BALANCE_VALUE])}（{detail}）"

    def listDaily(
        self, resource_type: str, start_date: Optional[str] = None, end_date: Optional[str] = None
    ) -> List[Dict]:
        """
        按日期范围查询逐日收支与结余。

        Args:
            resource_type: 资源类型。
            start_date: 可选起始日期 ``yyyy-MM-dd``。
            end_date: 可选结束日期 ``yyyy-MM-dd``。

        Returns:
            列表，字段同 :meth:`getBalanceSeries`，按日期升序。
        """
        series = self.getBalanceSeries(resource_type)
        if start_date:
            series = [item for item in series if item[BALANCE_DATE] >= start_date]
        if end_date:
            series = [item for item in series if item[BALANCE_DATE] <= end_date]
        return series

    def getCategories(self, resource_type: str, direction: str) -> List[str]:
        """
        获取事件字典中的候选名称。

        Args:
            resource_type: 资源类型。
            direction: 方向，``income`` 或 ``expense``。

        Returns:
            事件名称列表；表缺失时返回空列表。
        """
        try:
            return [
                category.name
                for category in self._resource_repository.findCategories(resource_type, direction)
            ]
        except DatabaseError as e:
            if isMissingTableError(e):
                return []
            raise
