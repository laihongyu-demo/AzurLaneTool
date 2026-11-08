"""舰娘图鉴舰种录入修正（一次性，2026-10-25 审核通过）。

修正两类历史录入错误，并重算受影响行的舰队位置（``fleet_position``）：

1. **错字舰种**：``轻型航母舰`` → ``轻型航空母舰``（3 条联动舰）；
2. **派生舰舰种与原型不一致**：改造 / META 变体应沿用原型舰种——
   博格.改、竞技神.改 → 轻型航空母舰；小天鹅.改 → 驱逐舰；
   加古.改 → 重型巡洋舰；彗星.改 → 驱逐舰；卡尔斯鲁厄.改 → 轻型巡洋舰；
   贝利.改 → 重型巡洋舰；博伊西·META → 轻型巡洋舰。

``霞DOA`` 这类带阵营后缀的同名舰（同理 ``约克DE``、``天城CV``、``加贺BB``）
是不同舰娘重名，不属于派生舰，不在修正范围内。

用法::

    python tools/fix_codex_ship_typ.py             # 只报告（默认 dry-run）
    python tools/fix_codex_ship_typ.py --apply     # 备份后写库

脚本可重复执行：每条修正都以「当前舰种 == 预期旧值」为前置条件，
已修正（或被人为改动）的行会被跳过，不会二次覆盖。

写库时会临时移除 ``codex_group`` 的 ``date_edit`` 触发器并在同一事务内原样重建，
避免批量修正把历史编辑时间刷成本次运行时间。
"""

import argparse
import os
import shutil
import sqlite3
import sys
from dataclasses import dataclass
from typing import List, Optional

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from utils import codex_options as options  # noqa: E402
from utils.constants import DEFAULT_DB_PATH  # noqa: E402
from utils.db_schema import ensureCodexGroupSchema, suspendCodexGroupModtimeTrigger  # noqa: E402
from utils.time_source import now as nowTimestamp  # noqa: E402

CODEX_GROUP_TABLE = "codex_group"

# 错字舰种：(错误值, 正确值)
TYPO_FIX = ("轻型航母舰", "轻型航空母舰")

# 派生舰舰种修正：(图鉴ID, 预期当前值, 修正值, 原型说明)
SHIP_TYP_FIXES = (
    ("Refit009", "轻型巡洋舰", "轻型航空母舰", "原型 博格 为轻型航空母舰"),
    ("Refit062", "驱逐舰", "轻型航空母舰", "原型 竞技神 为轻型航空母舰"),
    ("Refit004", "重型巡洋舰", "驱逐舰", "原型 小天鹅 为驱逐舰"),
    ("Refit016", "驱逐舰", "重型巡洋舰", "原型 加古 为重型巡洋舰"),
    ("Refit024", "轻型巡洋舰", "驱逐舰", "原型 彗星 为驱逐舰"),
    ("Refit026", "驱逐舰", "轻型巡洋舰", "原型 卡尔斯鲁厄 为轻型巡洋舰"),
    ("Refit029", "重型巡洋舰", "驱逐舰", "原型 贝利 为驱逐舰"),
    ("META053", "驱逐舰", "轻型巡洋舰", "原型 博伊西 为轻型巡洋舰"),
)


@dataclass
class FixItem:
    """一条待修正记录。"""

    codex_id: str
    ship_name: str
    old_typ: str
    new_typ: str
    reason: str


def collectFixes(conn: sqlite3.Connection) -> List[FixItem]:
    """
    收集需要修正的记录。

    以「当前舰种 == 预期旧值」为前置条件，因此重复执行时已修正的行不会被重复收集。

    Args:
        conn: 数据库连接。

    Returns:
        待修正记录列表。
    """
    items: List[FixItem] = []

    typo_old, typo_new = TYPO_FIX
    for codex_id, ship_name in conn.execute(
        f"SELECT codex_id, ship_name FROM {CODEX_GROUP_TABLE} WHERE ship_typ = ? ORDER BY codex_id",
        (typo_old,),
    ):
        items.append(FixItem(str(codex_id), str(ship_name), typo_old, typo_new, "错字舰种"))

    for codex_id, expected, new_typ, reason in SHIP_TYP_FIXES:
        row = conn.execute(
            f"SELECT ship_name, ship_typ FROM {CODEX_GROUP_TABLE} WHERE codex_id = ?",
            (codex_id,),
        ).fetchone()
        if row is None:
            continue
        if row[1] != expected:
            continue
        items.append(FixItem(codex_id, str(row[0]), expected, new_typ, reason))

    return items


def applyFixes(conn: sqlite3.Connection, items: List[FixItem]) -> int:
    """
    应用修正，并同步重算受影响行的舰队位置。

    Args:
        conn: 数据库连接（调用方负责事务）。
        items: 待修正记录。

    Returns:
        实际更新的行数。
    """
    updated = 0
    for item in items:
        cursor = conn.execute(
            f"UPDATE {CODEX_GROUP_TABLE} SET ship_typ = ? WHERE codex_id = ? AND ship_typ = ?",
            (item.new_typ, item.codex_id, item.old_typ),
        )
        if cursor.rowcount <= 0:
            continue
        updated += cursor.rowcount
        position = options.getFleetPosition(item.new_typ)
        if position:
            # 位置由舰种派生，舰种改了必须同步刷新，否则回填逻辑不会覆盖旧值
            conn.execute(
                f"UPDATE {CODEX_GROUP_TABLE} SET fleet_position = ? WHERE codex_id = ?",
                (position, item.codex_id),
            )
    return updated


def summarize(conn: sqlite3.Connection) -> List[str]:
    """
    汇总当前舰队位置的分布。

    Args:
        conn: 数据库连接。

    Returns:
        每行一条的文本摘要。
    """
    lines: List[str] = []
    columns = {row[1] for row in conn.execute(f"PRAGMA table_info({CODEX_GROUP_TABLE})")}
    if "fleet_position" not in columns:
        lines.append("fleet_position 列不存在（尚未执行补列回填）")
        return lines

    for position, count in conn.execute(
        f"SELECT fleet_position, COUNT(*) FROM {CODEX_GROUP_TABLE}"
        " GROUP BY fleet_position ORDER BY COUNT(*) DESC"
    ):
        label = position if position else "（空）"
        lines.append(f"  {label}: {count}")

    unknown = [
        (ship_typ, count)
        for ship_typ, count in conn.execute(
            f"SELECT ship_typ, COUNT(*) FROM {CODEX_GROUP_TABLE} GROUP BY ship_typ"
        )
        if options.getFleetPosition(ship_typ) is None
    ]
    if unknown:
        lines.append("  未登记舰种（位置为空）: " + "、".join(f"{t}×{c}" for t, c in unknown))
    return lines


def backupDatabase(db_path: str, backup_dir: str) -> str:
    """
    备份数据库文件。

    Args:
        db_path: 数据库路径。
        backup_dir: 备份目录。

    Returns:
        备份文件路径。
    """
    os.makedirs(backup_dir, exist_ok=True)
    stamp = nowTimestamp().strftime("%Y%m%d_%H%M%S")
    stem = os.path.splitext(os.path.basename(db_path))[0]
    target = os.path.join(backup_dir, f"{stem}_{stamp}_before_ship_typ_fix.db")
    shutil.copy2(db_path, target)
    return target


def main(argv: Optional[List[str]] = None) -> int:
    """
    命令行入口。

    Args:
        argv: 参数列表，默认取 ``sys.argv[1:]``。

    Returns:
        进程退出码：0 成功。
    """
    parser = argparse.ArgumentParser(description="舰娘图鉴舰种录入修正（一次性）")
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help="目标数据库路径")
    parser.add_argument("--backup-dir", default=os.path.join(PROJECT_ROOT, "data", "backup"),
                        help="备份目录（--apply 时自动备份）")
    parser.add_argument("--apply", action="store_true", help="正式写库（默认只报告）")
    args = parser.parse_args(argv)

    if not os.path.exists(args.db):
        print(f"数据库不存在: {args.db}")
        return 1

    if args.apply:
        backup_path = backupDatabase(args.db, args.backup_dir)
        print(f"已备份: {backup_path}")
        # 先补列并按舰种回填，保证后续重算位置时列已存在
        ensureCodexGroupSchema(args.db)

    conn = sqlite3.connect(args.db)
    conn.isolation_level = None
    try:
        conn.execute("BEGIN")
        try:
            items = collectFixes(conn)
            updated = 0
            if args.apply:
                # 修正会 UPDATE 全批目标行，必须避开 date_edit 触发器
                with suspendCodexGroupModtimeTrigger(conn):
                    updated = applyFixes(conn, items)
                conn.execute("COMMIT")
            else:
                conn.execute("ROLLBACK")
        except Exception:
            conn.execute("ROLLBACK")
            raise

        print(f"{'已修正' if args.apply else '待修正'}记录: {len(items)} 条，更新 {updated} 行")
        if items:
            print("| 图鉴ID | 舰名 | 原舰种 | 现舰种 | 依据 |")
            print("| --- | --- | --- | --- | --- |")
            for item in items:
                print(f"| {item.codex_id} | {item.ship_name} | {item.old_typ} |"
                      f" {item.new_typ} | {item.reason} |")
        print("\n舰队位置分布:")
        for line in summarize(conn):
            print(line)
        if not args.apply:
            print("\n（dry-run：未写库；确认后加 --apply 执行）")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
