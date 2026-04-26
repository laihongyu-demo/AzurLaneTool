"""
基础数据模型模块。

定义所有数据模型的基类，提供通用的数据转换方法。
"""

from dataclasses import dataclass, fields
from typing import Any, Dict


@dataclass
class BaseModel:
    """
    数据模型基类。

    提供从字典创建实例的通用方法。
    """

    @classmethod
    def fromDict(cls, data: Dict[str, Any]) -> "BaseModel":
        """
        从字典创建模型实例。

        仅提取与类字段匹配的键值对，忽略多余字段。

        Args:
            data: 包含模型数据的字典。

        Returns:
            模型实例。
        """
        field_names = {f.name for f in fields(cls)}
        filtered_data = {k: v for k, v in data.items() if k in field_names}
        return cls(**filtered_data)
