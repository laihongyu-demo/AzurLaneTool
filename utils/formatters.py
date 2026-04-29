"""
数值格式化工具模块。

提供数值单位换算与格式化功能，支持K、M、B、T等单位自动转换。
"""

from typing import Union


def formatNumber(value: Union[int, float]) -> str:
    """
    将数值格式化为带单位的字符串。

    自动进行单位换算：
    - 1K = 1,000（千）
    - 1M = 1,000,000（百万）
    - 1B = 1,000,000,000（十亿）
    - 1T = 1,000,000,000,000（万亿）

    Args:
        value: 要格式化的数值，支持int或float类型。

    Returns:
        格式化后的字符串：
        - 小于1000的数值：返回整数形式，不带小数
        - 大于等于1000的数值：返回带单位的形式，保留一位小数
        - 负数：在数值前添加负号，按绝对值进行单位换算
        - 零：返回"0"

    Examples:
        >>> formatNumber(0)
        '0'
        >>> formatNumber(999)
        '999'
        >>> formatNumber(1000)
        '1.0K'
        >>> formatNumber(1500)
        '1.5K'
        >>> formatNumber(1000000)
        '1.0M'
    """
    if value == 0:
        return "0"

    is_negative = value < 0
    abs_value = abs(value)

    if abs_value < 1000:
        result = str(int(abs_value))
    elif abs_value < 1_000_000:
        result = f"{abs_value / 1000:.1f}K"
    elif abs_value < 1_000_000_000:
        result = f"{abs_value / 1_000_000:.1f}M"
    elif abs_value < 1_000_000_000_000:
        result = f"{abs_value / 1_000_000_000:.1f}B"
    else:
        result = f"{abs_value / 1_000_000_000_000:.1f}T"

    if is_negative:
        return f"-{result}"
    return result


def parseFormattedNumber(formatted: str) -> Union[int, float]:
    """
    将格式化字符串解析为数值。

    支持解析formatNumber函数生成的字符串格式。

    Args:
        formatted: 格式化后的字符串，如"1.5K"、"2.0M"等。

    Returns:
        解析后的数值。

    Raises:
        ValueError: 当字符串格式无效时抛出。

    Examples:
        >>> parseFormattedNumber("0")
        0
        >>> parseFormattedNumber("999")
        999
        >>> parseFormattedNumber("1.5K")
        1500.0
    """
    formatted = formatted.strip()

    if not formatted:
        raise ValueError("空字符串无法解析")

    is_negative = formatted.startswith("-")
    if is_negative:
        formatted = formatted[1:]

    if formatted[-1].isalpha():
        unit = formatted[-1].upper()
        number_str = formatted[:-1]
    else:
        unit = ""
        number_str = formatted

    try:
        number = float(number_str)
    except ValueError:
        raise ValueError(f"无效的数值格式: {formatted}")

    multipliers = {
        "": 1,
        "K": 1000,
        "M": 1_000_000,
        "B": 1_000_000_000,
        "T": 1_000_000_000_000
    }

    if unit not in multipliers:
        raise ValueError(f"无效的单位: {unit}")

    result = number * multipliers[unit]

    if is_negative:
        result = -result

    return result
