"""
SQL 文件加载辅助模块。

提供从 sql/ 目录加载 SQL 文件的功能。
"""

import os
from typing import Optional

from utils.constants import SQL_DIR
from utils.exceptions import DatabaseError


def loadSqlFile(filename: str, sql_dir: Optional[str] = None) -> str:
    """
    从 sql/ 目录加载 SQL 文件内容。

    Args:
        filename: SQL 文件名（如 'monthly_report.sql'）。
        sql_dir: 可选的自定义 SQL 目录路径。

    Returns:
        SQL 文件中的完整字符串。

    Raises:
        DatabaseError: 当文件不存在或读取失败时抛出。
    """
    base_dir = sql_dir or SQL_DIR
    sql_path = os.path.join(base_dir, filename)

    if not os.path.exists(sql_path):
        raise DatabaseError(f"SQL 文件不存在: {sql_path}")

    try:
        with open(sql_path, 'r', encoding='utf-8') as f:
            return f.read()
    except IOError as e:
        raise DatabaseError(f"SQL 文件读取失败: {e}")


def loadSqlTemplate(filename: str, **kwargs) -> str:
    """
    加载 SQL 模板并进行参数替换。

    Args:
        filename: SQL 模板文件名。
        **kwargs: 模板参数。

    Returns:
        替换后的 SQL 语句。

    Raises:
        DatabaseError: 当文件操作失败时抛出。
    """
    sql_template = loadSqlFile(filename)
    try:
        return sql_template.format(**kwargs)
    except KeyError as e:
        raise DatabaseError(f"SQL 模板参数缺失: {e}")
