"""
为已有数据库补充红尖尖固定来源类型（世界巡游 / 贸易许可证）。

背景：``SeedResourceCategories.sql`` 只在类型字典为空时执行（#21），
老库不会自动获得新默认类型。本脚本默认只读预览，加 ``--apply`` 才写入。

用法：
    python tools/add_red_gem_categories.py
    python tools/add_red_gem_categories.py --db data/AzurLaneStatisticalOfficeDB.db --apply

执行前请先备份数据库；脚本可重复执行，已存在的类型不会重复插入。
"""

import argparse
import os
import sqlite3
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from utils.constants import DEFAULT_DB_PATH, RESOURCE_TYPE_RED_GEM  # noqa: E402

CATEGORIES = (
    ("世界巡游", 25),
    ("贸易许可证", 35),
)


def _existing_names(conn: sqlite3.Connection) -> set:
    """读取红尖尖收入类型名称。"""
    rows = conn.execute(
        "SELECT name FROM resource_category"
        " WHERE resource_type = ? AND direction = 'income'",
        (RESOURCE_TYPE_RED_GEM,),
    ).fetchall()
    return {row[0] for row in rows}


def main() -> int:
    """
    执行补类型流程。

    Returns:
        进程退出码。
    """
    parser = argparse.ArgumentParser(description="补充红尖尖固定来源类型")
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help="数据库路径")
    parser.add_argument("--apply", action="store_true", help="实际写入（默认仅预览）")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    try:
        existing = _existing_names(conn)
        missing = [(name, order) for name, order in CATEGORIES if name not in existing]
        if not missing:
            print("红尖尖收入类型已存在，无需补充。")
            return 0

        print("待补充类型：")
        for name, order in missing:
            print(f"  - {name}（sort_order={order}）")
        if not args.apply:
            print("当前为预览模式；确认后加 --apply 写入。")
            return 0

        with conn:
            conn.executemany(
                "INSERT INTO resource_category"
                " (resource_type, direction, name, sort_order)"
                " VALUES (?, 'income', ?, ?)"
                " ON CONFLICT(resource_type, direction, name) DO NOTHING",
                [(RESOURCE_TYPE_RED_GEM, name, order) for name, order in missing],
            )
        print("已写入。当前红尖尖收入类型：")
        for name in sorted(_existing_names(conn)):
            print(f"  - {name}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
