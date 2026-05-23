"""
心智计算服务模块。

提供觉醒材料需求总量计算相关的业务逻辑处理。
"""

from dataclasses import dataclass
from typing import Dict, Optional

from repositories.codex_repository import CodexGroupRepository
from utils.exceptions import DatabaseError


TARGET_PHASE_FIVE = 4
TARGET_PHASE_II = 5


@dataclass
class MentalCalculationResult:
    """
    心智计算结果数据类。

    Attributes:
        expend_gc: 物资总需求。
        expend_limit: 心智单元总需求。
        expend_limit2: 心智单元Ⅱ总需求。
        target_phase: 目标阶段（4或5）。
        success: 计算是否成功。
        message: 结果消息。
    """
    expend_gc: int = 0
    expend_limit: int = 0
    expend_limit2: int = 0
    target_phase: int = 0
    success: bool = True
    message: str = ""

    def toStatusBarMessage(self) -> str:
        """生成statusBar显示消息。"""
        if not self.success:
            return self.message

        phase_name = "认知觉醒五阶" if self.target_phase == TARGET_PHASE_FIVE else "认知觉醒Ⅱ"
        return (
            f"心智计算完成 | 目标: {phase_name} | "
            f"物资: {self.expend_gc} | "
            f"心智单元: {self.expend_limit} | "
            f"心智单元Ⅱ: {self.expend_limit2}"
        )


class MentalCalculationService:
    """
    心智计算服务类。

    封装觉醒材料总量计算的业务逻辑。
    """

    def __init__(
        self,
        group_repository: Optional[CodexGroupRepository] = None
    ):
        """
        初始化心智计算服务。

        Args:
            group_repository: 舰娘图鉴组数据访问实例。
        """
        self._group_repository = group_repository or CodexGroupRepository()

    def calculate(self, include_phase_ii: bool = False) -> MentalCalculationResult:
        """
        计算所有已解锁舰娘从当前状态提升至指定阶段所需的心智材料总量。

        Args:
            include_phase_ii: 是否包含认知觉醒II阶段（True=至认知觉醒II, False=至认知觉醒五阶）。

        Returns:
            MentalCalculationResult 计算结果对象。
        """
        target_phase = TARGET_PHASE_II if include_phase_ii else TARGET_PHASE_FIVE

        try:
            materials = self._group_repository.calculateMentalMaterials(target_phase)

            return MentalCalculationResult(
                expend_gc=materials.get("expend_gc", 0),
                expend_limit=materials.get("expend_limit", 0),
                expend_limit2=materials.get("expend_limit2", 0),
                target_phase=target_phase,
                success=True
            )
        except DatabaseError as e:
            return MentalCalculationResult(
                success=False,
                message=f"心智计算失败: {e}"
            )
        except Exception as e:
            return MentalCalculationResult(
                success=False,
                message=f"心智计算发生异常: {e}"
            )