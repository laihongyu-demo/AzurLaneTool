"""
用户数据模型模块。

定义用户相关的数据实体类。
"""

from dataclasses import dataclass
from typing import Optional
from datetime import datetime

from models.base_model import BaseModel


@dataclass
class UserModel(BaseModel):
    """
    用户数据模型类。

    Attributes:
        username: 用户名。
        start_date: 开始日期字符串（格式：YYYY-MM-DD）。
    """

    username: str = ""
    start_date: str = ""

    def getStartDateAsDate(self) -> Optional[datetime]:
        """
        将开始日期字符串转换为datetime对象。

        Returns:
            datetime对象，转换失败返回None。
        """
        if not self.start_date:
            return None
        try:
            return datetime.strptime(self.start_date, "%Y-%m-%d")
        except ValueError:
            return None
