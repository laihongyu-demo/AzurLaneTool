"""
舰娘誓约服务模块。

提供舰娘誓约相关的业务逻辑处理。
"""

import sqlite3
from dataclasses import dataclass
from typing import List, Optional

from models.codex_model import CodexGroupModel
from repositories.codex_repository import CodexGroupRepository
from utils.exceptions import DatabaseError, ValidationError


@dataclass
class OathResult:
    """
    誓约结果数据类。

    Attributes:
        success: 是否成功。
        ship_name: 舰娘名称。
        message: 结果消息。
    """
    success: bool
    ship_name: str = ""
    message: str = ""

    def toStatusBarMessage(self) -> str:
        """生成statusBar显示消息。"""
        if not self.success:
            return self.message
        return f"舰娘\"{self.ship_name}\"誓约成功"


class CodexOathService:
    """
    舰娘誓约服务类。

    封装舰娘誓约相关的业务逻辑。
    """

    def __init__(
        self,
        group_repository: Optional[CodexGroupRepository] = None
    ):
        """
        初始化誓约服务。

        Args:
            group_repository: 舰娘图鉴组数据访问实例。
        """
        self._group_repository = group_repository or CodexGroupRepository()

    def getOathableShips(self) -> List[CodexGroupModel]:
        """
        获取可进行誓约的舰娘列表。

        筛选条件：oath_status = 'N' 且 ship_group != '改造'。
        排序条件：ship_aid降序、codex_id降序。

        Returns:
            可誓约舰娘模型列表。
        """
        return self._group_repository.findOathable()

    def getShipById(self, codex_id) -> Optional[CodexGroupModel]:
        """
        根据ID获取舰娘详情。

        Args:
            codex_id: 图鉴ID。

        Returns:
            舰娘模型实例。
        """
        codex_id = str(codex_id) if codex_id is not None else ""
        return self._group_repository.findById(codex_id)

    def oathShip(self, codex_id) -> OathResult:
        """
        执行舰娘誓约。

        将指定舰娘的 oath_status 字段更新为 'Y'。

        Args:
            codex_id: 图鉴ID。

        Returns:
            OathResult 誓约结果对象。

        Raises:
            ValidationError: 当参数验证失败时抛出。
            DatabaseError: 当数据库操作失败时抛出。
        """
        if codex_id is None:
            raise ValidationError("无效的图鉴ID")

        codex_id = str(codex_id).strip()
        if not codex_id:
            raise ValidationError("图鉴ID不能为空")

        ship = self._group_repository.findById(codex_id)
        if ship is None:
            return OathResult(
                success=False,
                message=f"未找到图鉴ID为 {codex_id} 的舰娘"
            )

        if ship.ship_group == "改造":
            return OathResult(
                success=False,
                ship_name=ship.ship_name,
                message=f"舰娘 '{ship.ship_name}' 为改造类型，无法进行誓约"
            )

        if ship.oath_status == "Y":
            return OathResult(
                success=False,
                ship_name=ship.ship_name,
                message=f"舰娘 '{ship.ship_name}' 已经誓约"
            )

        try:
            updated = self._group_repository.updateOathStatus(codex_id, "Y")
            if not updated:
                return OathResult(
                    success=False,
                    ship_name=ship.ship_name,
                    message=f"舰娘 '{ship.ship_name}' 誓约更新失败"
                )

            return OathResult(
                success=True,
                ship_name=ship.ship_name,
                message=f"舰娘 '{ship.ship_name}' 誓约成功"
            )
        except sqlite3.Error as e:
            raise DatabaseError(f"誓约操作失败: {e}")