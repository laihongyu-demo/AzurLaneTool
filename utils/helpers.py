"""
通用辅助函数模块。

提供项目中通用的辅助函数，如日期格式化、ID生成等。
"""

import uuid
from datetime import datetime
from typing import Any, Optional


def generateId() -> str:
    """
    生成唯一标识符。

    Returns:
        UUID 格式的唯一字符串。
    """
    return str(uuid.uuid4())


def formatDatetime(dt: Optional[datetime] = None, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """
    格式化日期时间。

    Args:
        dt: datetime 对象，默认为当前时间。
        fmt: 格式化字符串。

    Returns:
        格式化后的日期时间字符串。
    """
    if dt is None:
        dt = datetime.now()
    return dt.strftime(fmt)


def parseDatetime(dt_str: str, fmt: str = "%Y-%m-%d %H:%M:%S") -> Optional[datetime]:
    """
    解析日期时间字符串。

    Args:
        dt_str: 日期时间字符串。
        fmt: 格式化字符串。

    Returns:
        datetime 对象，解析失败返回 None。
    """
    try:
        return datetime.strptime(dt_str, fmt)
    except ValueError:
        return None


def safeGet(dictionary: dict, key: str, default: Any = None) -> Any:
    """
    安全获取字典值。

    Args:
        dictionary: 目标字典。
        key: 键名。
        default: 默认值。

    Returns:
        字典中的值或默认值。
    """
    return dictionary.get(key, default)


def truncateString(text: str, max_length: int = 50, suffix: str = "...") -> str:
    """
    截断字符串。

    Args:
        text: 原始字符串。
        max_length: 最大长度。
        suffix: 截断后缀。

    Returns:
        截断后的字符串。
    """
    if len(text) <= max_length:
        return text
    return text[:max_length - len(suffix)] + suffix


def formatNumber(value: float, decimal_places: int = 2) -> str:
    """
    格式化数字。

    Args:
        value: 数值。
        decimal_places: 小数位数。

    Returns:
        格式化后的数字字符串。
    """
    return f"{value:.{decimal_places}f}"


def formatCurrency(value: float, symbol: str = "¥") -> str:
    """
    格式化货币。

    Args:
        value: 金额数值。
        symbol: 货币符号。

    Returns:
        格式化后的货币字符串。
    """
    return f"{symbol}{value:,.2f}"
