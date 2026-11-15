"""
数据库异常的用户可读文案模块。

视图层只负责展示，不解析底层 SQLite 报错文本：缺表、缺列、库损坏这类常见场景
统一在这里翻译成中文提示，避免把 ``no such table: codex_group`` 原文甩给用户，
也避免各面板各自拼一段措辞不一致的文案（#28）。
"""

import re
from typing import Optional

from utils.db_schema import isMissingColumnError, isMissingTableError

# 图鉴相关表由图鉴导入维护，应用不负责建表；缺这几张表通常意味着
# 「空库 / 还没导入图鉴数据」，而不是程序缺陷。
CODEX_TABLES = ("codex_group", "codex_tp", "codex_buff", "awakening_of_mind")

# SQLite 驱动给出的损坏类报错：文件被替换、被截断或根本不是数据库
_CORRUPT_MARKERS = (
    "file is not a database",
    "database disk image is malformed",
    "file is encrypted",
)

_MISSING_TABLE_PATTERN = re.compile(r"no such table:\s*([^\s:;]+)", re.IGNORECASE)
_MISSING_COLUMN_PATTERN = re.compile(r"no such column:\s*([^\s;]+)", re.IGNORECASE)
_MISSING_COLUMN_QUALIFIED_PATTERN = re.compile(
    r"has no column named\s+([^\s;]+)", re.IGNORECASE
)


def describeDataLoadError(exc: Exception) -> str:
    """
    把读取数据时的异常翻译成面板可直接展示的中文提示。

    区分三类场景，便于用户判断该做什么：

    - 表缺失：空库或图鉴数据未导入 → 提示先初始化数据库；
    - 列缺失：旧库结构未升级 → 提示重启应用完成升级；
    - 文件损坏：库被替换 / 截断 → 提示检查数据目录或恢复备份。

    其它异常回退为「读取数据失败 + 原始信息」，保留排查线索。

    Args:
        exc: 读取数据时捕获到的异常（通常是 ``DatabaseError``）。

    Returns:
        面向用户的一句中文提示（不换行）。
    """
    message = str(exc)

    if isMissingTableError(exc):
        table = _extract(_MISSING_TABLE_PATTERN, message)
        if table and table in CODEX_TABLES:
            return (
                f"图鉴数据表 {table} 缺失：当前数据库还没有图鉴数据，本页暂不可用；"
                "请先初始化数据库（或导入图鉴数据）后重新刷新，其它页签不受影响。"
            )
        if table:
            return (
                f"数据表 {table} 缺失：当前数据库缺少该表，本页暂不可用；"
                "请先初始化数据库后重新刷新。"
            )
        return "数据表缺失：当前数据库缺少所需的表，本页暂不可用；请先初始化数据库后重新刷新。"

    if isMissingColumnError(exc):
        column = _extract(_MISSING_COLUMN_QUALIFIED_PATTERN, message) or _extract(
            _MISSING_COLUMN_PATTERN, message
        )
        if column:
            return f"数据表结构过旧（缺少列 {column}）：请重启应用完成结构升级，然后重新刷新。"
        return "数据表结构过旧：请重启应用完成结构升级，然后重新刷新。"

    if _isCorruptDatabaseError(exc):
        return (
            "数据库文件已损坏或不是有效的 SQLite 数据库："
            "请检查数据目录，必要时从备份恢复后重启应用。"
        )

    return f"读取数据失败：{message}"


def _extract(pattern: "re.Pattern[str]", message: str) -> Optional[str]:
    """
    从报错文本里取出表名 / 列名。

    Args:
        pattern: 带一个捕获组的正则。
        message: 原始报错文本。

    Returns:
        捕获到的标识符；匹配不到时返回 ``None``。
    """
    match = pattern.search(message)
    return match.group(1) if match else None


def _isCorruptDatabaseError(exc: Exception) -> bool:
    """
    判断异常是否属于「数据库文件本身不可用」。

    Args:
        exc: 捕获到的异常。

    Returns:
        命中损坏类报错返回 True。
    """
    message = str(exc).lower()
    return any(marker in message for marker in _CORRUPT_MARKERS)
