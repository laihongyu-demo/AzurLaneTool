"""
数值单位换算与格式化模块。

提供大数值的自动单位转换功能，支持 K/M/B/T 单位输出；
另提供不做换算、仅加千分符的精确格式化（用于需要看清精确数值的场合）。
"""

from typing import Union


_KILO = 1_000
_MEGA = 1_000_000
_GIGA = 1_000_000_000
_TERA = 1_000_000_000_000

_UNITS = [
    (_TERA, "T"),
    (_GIGA, "B"),
    (_MEGA, "M"),
    (_KILO, "K"),
]


def formatValue(value: Union[int, float]) -> str:
    """
    将数值转换为带单位的可读字符串。

    转换规则：
    - 小于 1,000：直接返回整数格式，无小数，无单位
    - 1,000 ~ 999,999：转换为 K 单位，保留一位小数
    - 1,000,000 ~ 999,999,999：转换为 M 单位，保留一位小数
    - 1,000,000,000 ~ 999,999,999,999：转换为 B 单位，保留一位小数
    - 大于等于 1,000,000,000,000：转换为 T 单位，保留一位小数

    特殊处理：
    - 0 返回 "0"
    - 负数保留负号后按绝对值转换

    Args:
        value: 需要格式化的数值（整数或浮点数）。

    Returns:
        格式化后的字符串，如 "1.5K"、"12.3M"、"999"、"0"。

    Examples:
        >>> formatValue(0)
        '0'
        >>> formatValue(999)
        '999'
        >>> formatValue(1000)
        '1.0K'
        >>> formatValue(1500)
        '1.5K'
        >>> formatValue(1000000)
        '1.0M'
        >>> formatValue(123456789)
        '123.5M'
    """
    if value < 0:
        return f"-{_formatAbsValue(abs(value))}"
    return _formatAbsValue(value)


def formatExact(value: Union[int, float, None]) -> str:
    """
    将数值格式化为带千分符的精确字符串（不做单位换算）。

    与 :func:`formatValue` 的区别：本函数不换算为 K/M/B/T，保留完整数值，
    便于核对“精确的材料变化”，例如 ``5593200`` → ``5,593,200``。

    Args:
        value: 需要格式化的数值；``None`` 视为 0。

    Returns:
        带千分符的字符串，如 ``"12,345"``、``"0"``、``"-1,500"``。

    Examples:
        >>> formatExact(0)
        '0'
        >>> formatExact(999)
        '999'
        >>> formatExact(5593200)
        '5,593,200'
        >>> formatExact(-1500)
        '-1,500'
    """
    if value is None:
        return "0"

    if isinstance(value, float) and not value.is_integer():
        return f"{value:,}"

    return f"{int(value):,}"


def _formatAbsValue(value: Union[int, float]) -> str:
    """
    格式化非负数值。

    Args:
        value: 非负数值。

    Returns:
        格式化后的字符串。
    """
    if value < _KILO:
        return str(int(value))

    for threshold, suffix in _UNITS:
        if value >= threshold:
            converted = round(value / threshold, 1)
            return f"{converted:.1f}{suffix}"

    return str(int(value))