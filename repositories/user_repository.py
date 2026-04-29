"""
用户数据访问模块。

封装用户数据的读取操作。
"""

import json
import os
from typing import Optional

from models.user_model import UserModel
from utils.exceptions import DatabaseError


class UserRepository:
    """
    用户数据访问类。

    封装用户数据的读取操作（从JSON文件）。
    """

    def __init__(self, file_path: Optional[str] = None):
        """
        初始化用户数据访问。

        Args:
            file_path: user.json文件路径，默认为data/user.json。
        """
        if file_path is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            file_path = os.path.join(base_dir, "data", "user.json")
        self._filePath = file_path

    def loadUser(self) -> Optional[UserModel]:
        """
        加载用户数据。

        Returns:
            用户模型实例，文件不存在或解析失败返回None。

        Raises:
            DatabaseError: 当文件读取失败时抛出。
        """
        if not os.path.exists(self._filePath):
            return None

        try:
            with open(self._filePath, "r", encoding="utf-8") as f:
                data = json.load(f)
            return UserModel.fromDict(data)
        except json.JSONDecodeError as e:
            raise DatabaseError(f"解析用户数据失败: {e}")
        except IOError as e:
            raise DatabaseError(f"读取用户数据失败: {e}")

    def getStartDate(self) -> Optional[str]:
        """
        获取用户开始日期。

        Returns:
            开始日期字符串，不存在返回None。
        """
        user = self.loadUser()
        if user is None:
            return None
        return user.start_date
