"""
统一时间源模块。

视图层与需要「当前日期 / 时刻」的服务统一从这里取时间，便于：
1. 测试通过 ``unittest.mock.patch("utils.time_source.now")`` 模拟跨天；
2. 刷新策略只比较日期版本，不必查询数据库。

``now()`` 截断到秒，与数据库 ``yyyy-MM-dd HH:mm:ss`` 的口径一致。
"""

from datetime import date, datetime


def now() -> datetime:
    """
    返回当前本地时刻（截断到秒）。

    Returns:
        当前时刻。
    """
    return datetime.now().replace(microsecond=0)


def today() -> date:
    """
    返回当前本地日期。

    Returns:
        当前日期。
    """
    return date.today()
