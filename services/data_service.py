"""
数据服务模块。

提供数据相关的业务逻辑处理。
"""

from typing import List, Dict, Any, Optional

from models.ship_model import ShipModel
from repositories.ship_repository import ShipRepository
from utils.exceptions import ValidationError


class DataService:
    """
    数据服务类。

    封装数据相关的业务逻辑，协调 Repository 进行数据操作。
    """

    def __init__(self, ship_repository: Optional[ShipRepository] = None):
        """
        初始化数据服务。

        Args:
            ship_repository: 船舶数据访问实例。
        """
        self._ship_repository = ship_repository or ShipRepository()

    def getAllShips(self) -> List[ShipModel]:
        """
        获取所有船舶数据。

        Returns:
            船舶模型列表。
        """
        return self._ship_repository.findAll()

    def getShipById(self, ship_id: int) -> Optional[ShipModel]:
        """
        根据 ID 获取船舶详情。

        Args:
            ship_id: 船舶 ID。

        Returns:
            船舶模型实例。
        """
        return self._ship_repository.findById(ship_id)

    def createShip(self, name: str, capacity: int, launch_date: str = None, status: str = "active") -> int:
        """
        创建新船舶记录。

        Args:
            name: 船舶名称。
            capacity: 载容量。
            launch_date: 下水日期。
            status: 船舶状态。

        Returns:
            新记录 ID。

        Raises:
            ValidationError: 当数据验证失败时抛出。
        """
        if not name or not name.strip():
            raise ValidationError("船舶名称不能为空")
        if capacity <= 0:
            raise ValidationError("载容量必须大于 0")

        ship = ShipModel(
            name=name.strip(),
            capacity=capacity,
            launch_date=launch_date,
            status=status
        )
        return self._ship_repository.insert(ship)

    def updateShip(self, ship: ShipModel) -> bool:
        """
        更新船舶记录。

        Args:
            ship: 船舶模型实例。

        Returns:
            更新是否成功。
        """
        return self._ship_repository.update(ship)

    def deleteShip(self, ship_id: int) -> bool:
        """
        删除船舶记录。

        Args:
            ship_id: 船舶 ID。

        Returns:
            删除是否成功。
        """
        return self._ship_repository.delete(ship_id)

    def getShipsByStatus(self, status: str) -> List[ShipModel]:
        """
        根据状态获取船舶列表。

        Args:
            status: 船舶状态。

        Returns:
            船舶模型列表。
        """
        return self._ship_repository.findByStatus(status)

    def getTotalCount(self) -> int:
        """
        获取船舶总数。

        Returns:
            船舶总数。
        """
        return self._ship_repository.count()
