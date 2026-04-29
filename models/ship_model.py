"""
船舶数据模型模块。

定义船舶实体的数据结构。
"""

from dataclasses import dataclass
from datetime import date
from typing import Optional

from models.base_model import BaseModel


@dataclass
class ShipModel(BaseModel):
    """
    船舶数据模型。

    Attributes:
        id: 船舶唯一标识。
        name: 船舶名称。
        capacity: 载容量。
        launch_date: 下水日期。
        status: 船舶状态。
    """

    id: Optional[int] = None
    name: str = ""
    capacity: int = 0
    launch_date: Optional[date] = None
    status: str = "active"

    def __post_init__(self):
        if isinstance(self.launch_date, str):
            from utils.helpers import parseDatetime
            parsed = parseDatetime(self.launch_date, "%Y-%m-%d")
            if parsed:
                self.launch_date = parsed.date()
