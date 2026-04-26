"""
用户服务模块。

提供用户相关的业务逻辑处理。
"""

from datetime import datetime, date
from typing import Optional

from models.user_model import UserModel
from repositories.user_repository import UserRepository
from utils.exceptions import DatabaseError


class UserService:
    """
    用户服务类。

    封装用户相关的业务逻辑，如执勤天数计算。
    """

    def __init__(self, user_repository: Optional[UserRepository] = None):
        """
        初始化用户服务。

        Args:
            user_repository: 用户数据访问实例。
        """
        self._user_repository = user_repository or UserRepository()

    def getUser(self) -> Optional[UserModel]:
        """
        获取用户信息。

        Returns:
            用户模型实例。
        """
        return self._user_repository.loadUser()

    def getDutyDays(self) -> int:
        """
        计算执勤天数。

        从user.json中读取start_date，计算与当前日期的间隔天数。

        Returns:
            执勤天数，如果无法计算则返回0。
        """
        user = self._user_repository.loadUser()
        if user is None:
            return 0

        start_date = user.getStartDateAsDate()
        if start_date is None:
            return 0

        today = date.today()
        delta = today - start_date.date()
        return max(0, delta.days)

    def getDutyDaysText(self) -> str:
        """
        获取执勤天数显示文本。

        Returns:
            执勤天数文本，格式为"X天"。
        """
        days = self.getDutyDays()
        return f"{days}天"
