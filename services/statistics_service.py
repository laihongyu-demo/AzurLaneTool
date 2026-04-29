"""
统计服务模块。

提供数据统计相关的业务逻辑处理。
"""

from typing import Dict, Any, Optional, List

from repositories.codex_repository import CodexGroupRepository, CodexTpRepository
from utils.exceptions import DatabaseError


class StatisticsService:
    """
    统计服务类。

    封装数据统计相关的业务逻辑，提供可扩展的统计接口。
    """

    def __init__(
        self,
        group_repository: Optional[CodexGroupRepository] = None,
        tp_repository: Optional[CodexTpRepository] = None
    ):
        """
        初始化统计服务。

        Args:
            group_repository: 舰娘图鉴组数据访问实例。
            tp_repository: TP数据访问实例。
        """
        self._group_repository = group_repository or CodexGroupRepository()
        self._tp_repository = tp_repository or CodexTpRepository()

    def getUnlockStatistics(self) -> Dict[str, Any]:
        """
        获取解锁统计信息。

        收藏率计算排除联动舰娘（ship_group='联动'）。
        数量显示格式为"不含联动总数（含联动总数）"。

        Returns:
            包含解锁统计的字典。
        """
        all_ships = self._group_repository.findAll()
        all_ships_excluding_collab = self._group_repository.findAllExcludingCollab()

        locked_ships = [s for s in all_ships if s.codex_unlock == "N"]
        unlocked_ships = [s for s in all_ships if s.codex_unlock == "Y"]

        locked_excluding_collab = [s for s in all_ships_excluding_collab if s.codex_unlock == "N"]
        unlocked_excluding_collab = [s for s in all_ships_excluding_collab if s.codex_unlock == "Y"]

        total_excluding_collab = len(all_ships_excluding_collab)
        unlock_rate = (
            len(unlocked_excluding_collab) / total_excluding_collab * 100
            if total_excluding_collab > 0 else 0
        )

        return {
            "total": len(all_ships),
            "total_excluding_collab": total_excluding_collab,
            "locked": len(locked_ships),
            "locked_excluding_collab": len(locked_excluding_collab),
            "unlocked": len(unlocked_ships),
            "unlocked_excluding_collab": len(unlocked_excluding_collab),
            "unlock_rate": unlock_rate
        }

    def getTpStatistics(self) -> Dict[str, Any]:
        """
        获取科技点统计信息。

        Returns:
            包含科技点统计的字典：
            - total_tp: 全部科技点总值
            - unlocked_tp: 当前科技点总值
            - completion_rate: 科技点完成率
        """
        total_tp = self._tp_repository.getTotalTpValue()
        unlocked_tp = self._tp_repository.getUnlockedTpValue()

        completion_rate = (unlocked_tp / total_tp * 100) if total_tp > 0 else 0

        return {
            "total_tp": total_tp,
            "unlocked_tp": unlocked_tp,
            "completion_rate": completion_rate
        }

    def getBulinRequirements(self) -> Dict[str, Any]:
        """
        获取布里需求统计信息。

        Returns:
            包含布里需求统计的字典：
            - universal_bulin: 泛用型布里数量
            - trial_bulin_mkii: 试作型布里MKII数量
            - specialized_bulin_mkiii: 特装型布里MKIII数量
        """
        bulin_data = self._group_repository.getBulinRequirements()

        result = {
            "universal_bulin": 0,
            "trial_bulin_mkii": 0,
            "specialized_bulin_mkiii": 0
        }

        for item in bulin_data:
            material_type = item.get("material_type", "")
            total_needed = item.get("total_neededMaterial", 0)

            if material_type == "Universal Bulin":
                result["universal_bulin"] = total_needed
            elif material_type == "Trial Bulin MKII":
                result["trial_bulin_mkii"] = total_needed
            elif material_type == "Specialized Bulin MKIII":
                result["specialized_bulin_mkiii"] = total_needed

        return result

    def getRemainingLevelingCount(self) -> int:
        """
        获取剩余练级数量。

        Returns:
            符合条件的舰娘数量。
        """
        return self._group_repository.getRemainingLevelingCount()

    def getAllStatistics(self) -> Dict[str, Any]:
        """
        获取所有统计信息。

        Returns:
            包含所有统计数据的字典，预留扩展接口。
        """
        return {
            "unlock": self.getUnlockStatistics(),
            "tp": self.getTpStatistics(),
            "bulin": self.getBulinRequirements(),
            "remaining_leveling": self.getRemainingLevelingCount()
        }

    def refreshStatistics(self) -> Dict[str, Any]:
        """
        刷新并获取最新统计数据。

        Returns:
            最新的统计数据字典。
        """
        return self.getAllStatistics()
