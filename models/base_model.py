"""
基础模型类模块。

提供所有数据模型的基类，包含通用的序列化和反序列化方法。
"""

from abc import ABC
from dataclasses import dataclass, asdict, fields
from typing import Dict, Any, Optional


@dataclass
class BaseModel(ABC):
    """
    数据模型基类。

    所有数据实体类应继承此类，以获得统一的序列化和反序列化能力。
    """

    def toDict(self) -> Dict[str, Any]:
        """
        将模型实例转换为字典。

        Returns:
            包含所有字段的字典。
        """
        return asdict(self)

    @classmethod
    def fromDict(cls, data: Dict[str, Any]) -> 'BaseModel':
        """
        从字典创建模型实例。

        Args:
            data: 包含字段数据的字典。

        Returns:
            模型实例。
        """
        valid_fields = {f.name for f in fields(cls)}
        filtered_data = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered_data)

    def update(self, **kwargs) -> None:
        """
        更新模型字段值。

        Args:
            **kwargs: 要更新的字段键值对。
        """
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
