"""
SQL文件加载工具模块。

提供从外部文件加载SQL语句的功能。
"""

import os
from typing import Optional


def loadSqlFile(filename: str, sql_dir: Optional[str] = None) -> str:
    """
    从sql目录加载SQL文件内容。

    Args:
        filename: 文件名（如'monthly_report.sql'）。
        sql_dir: SQL文件目录，为None时使用默认目录。

    Returns:
        SQL文件中的完整字符串。

    Raises:
        FileNotFoundError: 当文件不存在时抛出。
    """
    if sql_dir is None:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        sql_dir = os.path.join(base_dir, "sql")

    sql_path = os.path.join(sql_dir, filename)

    if not os.path.exists(sql_path):
        raise FileNotFoundError(f"SQL文件不存在: {sql_path}")

    with open(sql_path, "r", encoding="utf-8") as f:
        return f.read()
