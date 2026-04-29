"""
计算服务模块。

提供数据统计、分析和计算相关的业务逻辑。
"""

from typing import List, Dict, Any

from models.ship_model import ShipModel


class CalcService:
    """
    计算服务类。

    封装数据统计和计算相关的业务逻辑。
    """

    def computeStatistics(self, records: List[ShipModel]) -> Dict[str, Any]:
        """
        计算船舶数据的统计信息。

        Args:
            records: 船舶模型列表。

        Returns:
            包含统计信息的字典。
        """
        if not records:
            return {
                "count": 0,
                "total_capacity": 0,
                "mean_capacity": 0,
                "max_capacity": 0,
                "min_capacity": 0
            }

        capacities = [r.capacity for r in records]
        total = sum(capacities)
        count = len(capacities)

        return {
            "count": count,
            "total_capacity": total,
            "mean_capacity": total / count if count > 0 else 0,
            "max_capacity": max(capacities),
            "min_capacity": min(capacities)
        }

    def groupByStatus(self, records: List[ShipModel]) -> Dict[str, List[ShipModel]]:
        """
        按状态分组船舶数据。

        Args:
            records: 船舶模型列表。

        Returns:
            按状态分组的字典。
        """
        result = {}
        for record in records:
            status = record.status or "unknown"
            if status not in result:
                result[status] = []
            result[status].append(record)
        return result

    def calculateCapacityDistribution(self, records: List[ShipModel], bins: int = 5) -> Dict[str, int]:
        """
        计算载容量分布。

        Args:
            records: 船舶模型列表。
            bins: 分组数量。

        Returns:
            分布统计字典。
        """
        if not records:
            return {}

        capacities = [r.capacity for r in records]
        min_cap = min(capacities)
        max_cap = max(capacities)

        if min_cap == max_cap:
            return {f"{min_cap}": len(capacities)}

        bin_width = (max_cap - min_cap) / bins
        distribution = {}

        for i in range(bins):
            lower = min_cap + i * bin_width
            upper = min_cap + (i + 1) * bin_width
            key = f"{int(lower)}-{int(upper)}"
            distribution[key] = 0

        for cap in capacities:
            for i in range(bins):
                lower = min_cap + i * bin_width
                upper = min_cap + (i + 1) * bin_width
                if lower <= cap < upper or (i == bins - 1 and cap == upper):
                    key = f"{int(lower)}-{int(upper)}"
                    distribution[key] += 1
                    break

        return distribution
