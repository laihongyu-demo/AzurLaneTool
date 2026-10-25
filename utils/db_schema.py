"""
数据库表结构引导模块。

负责在应用启动时确保资源统计 / 任务看板 / 贸易许可证相关表存在（幂等 DDL），
把早期版本的表结构就地升级到当前口径（明细精确到秒），并为历史图鉴表
``codex_group`` 补齐舰队位置列并按舰种回填，同时提供"表 / 列不存在"
异常的识别辅助。
"""

import sqlite3
from contextlib import contextmanager
from typing import Iterator, Optional, Set

from utils import codex_options
from utils.db_connection import DatabaseConnection, DatabaseContext
from utils.sql_loader import loadSqlFile

RESOURCE_SCHEMA_FILE = "CreateResourceStatisticsTables.sql"
CUBE_TASK_SCHEMA_FILE = "CreateCubeTaskTables.sql"
TRADE_LICENSE_SCHEMA_FILE = "CreateTradeLicenseTable.sql"
EVENT_SCHEMA_FILE = "CreateEventRecordTable.sql"
CATEGORY_SEED_FILE = "SeedResourceCategories.sql"

# 历史图鉴表：由图鉴导入维护，应用只做「按需补列 + 回填」，不建表
CODEX_GROUP_TABLE = "codex_group"
# 该触发器会在 codex_group 任意 UPDATE 后把 date_edit 改为当前时间
CODEX_GROUP_MODTIME_TRIGGER = "update_codex_group_modtime"

# 仅日期（yyyy-MM-dd）的写法长度；用于识别需要补时分秒的旧值
LEGACY_DATE_LENGTH = 10


def ensureResourceStatisticsSchema(db_path: Optional[str] = None) -> None:
    """
    确保资源统计、魔方 / 红尖尖任务看板与贸易许可证相关表、索引与任务定义就位，
    并把旧结构升级到当前口径。

    执行 ``sql/CreateResourceStatisticsTables.sql``、``sql/CreateCubeTaskTables.sql``、
    ``sql/CreateTradeLicenseTable.sql`` 与 ``sql/SeedResourceCategories.sql``
    （DDL 全部 ``IF NOT EXISTS``，任务定义用 ``ON CONFLICT DO UPDATE``），
    随后运行幂等升级步骤：

    - 明细的 ``record_date``（仅日期）→ ``record_time``（``yyyy-MM-dd HH:mm:ss``）
    - 日汇总补齐 ``last_record_time``（该日最后一笔的准确时刻）
    - 明细补齐 ``event_id``（活动关联，可空）
    - 活动记录的 ``draws``（抽数）重命名为 ``build_count``（建造次数）
    - 活动记录补齐 ``build_cost`` / ``use_ticket`` / ``ticket_build_count``（单耗与券抽）
    - 任务定义补齐 ``short_name`` / ``resource_type``
    - 任务完成记录补齐 ``expense_transaction_id`` / ``event_id``（建造任务的两笔联动）
    - 类型字典补齐 ``is_active``（1 启用 / 0 停用）
    - 重建明细上的时间索引

    类型字典只在表为空时播种：用户自助维护（#21）后的改名、顺序与停用状态
    不会被启动流程覆盖。

    可重复调用；不会破坏既有数据。

    Args:
        db_path: 可选的数据库路径，默认使用全局配置。

    Raises:
        DatabaseError: 当 SQL 文件缺失或执行失败时抛出。
    """
    resource_sql = loadSqlFile(RESOURCE_SCHEMA_FILE)
    task_sql = loadSqlFile(CUBE_TASK_SCHEMA_FILE)
    trade_license_sql = loadSqlFile(TRADE_LICENSE_SCHEMA_FILE)
    event_sql = loadSqlFile(EVENT_SCHEMA_FILE)
    category_sql = loadSqlFile(CATEGORY_SEED_FILE)
    path = db_path or DatabaseConnection.getDbPath()
    with DatabaseContext(path) as conn:
        # 先升级旧结构：表不存在时各步骤自动跳过，不会误建/误改
        _upgradeLegacySchema(conn)
        _upgradeCubeTaskSchema(conn)
        # event_id 必须先补列，随后资源脚本里的 event_id 索引才有列可建
        _upgradeEventTransactionColumn(conn)
        _upgradeEventRecordSchema(conn)
        conn.executescript(resource_sql)
        conn.executescript(task_sql)
        conn.executescript(trade_license_sql)
        conn.executescript(event_sql)
        _upgradeResourceCategorySchema(conn)
        # 类型字典仅在为空时播种；已有数据时不再改写顺序/名称/停用状态
        _seedCategoriesIfEmpty(conn, category_sql)
        _backfillLastRecordTime(conn)


def ensureCodexGroupSchema(db_path: Optional[str] = None) -> None:
    """
    确保 ``codex_group`` 具备 ``fleet_position``（舰队位置）列，并按舰种回填。

    ``codex_group`` 是历史图鉴表，应用不负责建表；这里只做两件事：

    1. 缺列时 ``ALTER TABLE`` 补列（``fleet_position`` 允许为空，不打断旧库写入）；
    2. 按 :data:`utils.codex_options.SHIP_TYP_FLEET_POSITION` 回填空值。

    回填只填空值，不会覆盖已有结果，因此可重复执行；表不存在时直接跳过。

    Args:
        db_path: 可选的数据库路径，默认使用全局配置。
    """
    path = db_path or DatabaseConnection.getDbPath()
    with DatabaseContext(path) as conn:
        columns = _tableColumns(conn, CODEX_GROUP_TABLE)
        if not columns:
            return
        if "fleet_position" not in columns:
            conn.execute(
                f"ALTER TABLE {CODEX_GROUP_TABLE} ADD COLUMN fleet_position STRING(32)"
            )
        # 回填会 UPDATE 全部行，必须避开 date_edit 触发器，否则历史编辑时间被刷成本次运行时间
        with suspendCodexGroupModtimeTrigger(conn):
            _backfillFleetPosition(conn)


@contextmanager
def suspendCodexGroupModtimeTrigger(conn: sqlite3.Connection) -> Iterator[bool]:
    """
    临时移除 ``codex_group`` 的 ``update_codex_group_modtime`` 触发器，退出时原样重建。

    该触发器会在该表任意 UPDATE 之后把 ``date_edit`` 改写为当前时间。批量回填 /
    修正舰种时若不处理，会把全表（或整批）历史编辑时间刷成本次运行时间——
    2026-10-12 的数据修正已踩过一次。SQLite 的 DDL 参与事务，因此
    「DROP → 写入 → 原样 CREATE」在同一事务内完成，失败可整体回滚。

    Args:
        conn: 数据库连接（调用方负责事务的提交 / 回滚）。

    Yields:
        触发器存在并被临时移除时返回 True，否则返回 False（无触发器时不做任何事）。
    """
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'trigger' AND name = ?",
        (CODEX_GROUP_MODTIME_TRIGGER,),
    ).fetchone()
    trigger_sql = row[0] if row else None
    if not trigger_sql:
        yield False
        return
    conn.execute(f"DROP TRIGGER {CODEX_GROUP_MODTIME_TRIGGER}")
    try:
        yield True
    finally:
        conn.execute(trigger_sql)


def _backfillFleetPosition(conn: sqlite3.Connection) -> None:
    """
    按舰种口径回填 ``fleet_position``。

    只处理空值（NULL / 空串），保留已人工确认的位置；未登记舰种保持为空，
    由使用方显示为「未分类」而不是猜一个位置。

    Args:
        conn: 数据库连接。
    """
    for ship_typ, position in codex_options.SHIP_TYP_FLEET_POSITION.items():
        conn.execute(
            f"UPDATE {CODEX_GROUP_TABLE} SET fleet_position = ?"
            " WHERE ship_typ = ? AND (fleet_position IS NULL OR fleet_position = '')",
            (position, ship_typ),
        )


def _tableColumns(conn: sqlite3.Connection, table: str) -> Set[str]:
    """
    读取表的列名集合。

    Args:
        conn: 数据库连接。
        table: 表名。

    Returns:
        列名集合；表不存在时返回空集合（PRAGMA 不抛错）。
    """
    try:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    except sqlite3.Error:
        return set()


def _upgradeLegacySchema(conn: sqlite3.Connection) -> None:
    """
    把 v0.2 的表结构就地升级为「明细精确到秒」的当前口径。

    只做列级调整，不创建索引与表（那些交给 SQL 脚本，保证全新库与旧库走同一份定义）。
    全部步骤都以列是否存在为前提，因此可重复执行。

    Args:
        conn: 数据库连接。
    """
    transaction_columns = _tableColumns(conn, "resource_transaction")
    if "record_date" in transaction_columns and "record_time" not in transaction_columns:
        conn.execute("ALTER TABLE resource_transaction RENAME COLUMN record_date TO record_time")
        conn.execute(
            "UPDATE resource_transaction SET record_time = record_time || ' 00:00:00'"
            " WHERE length(record_time) = ?",
            (LEGACY_DATE_LENGTH,),
        )

    # 旧索引名与新口径不符，统一由 SQL 脚本重建为 idx_resource_transaction_time
    conn.execute("DROP INDEX IF EXISTS idx_resource_transaction_date")

    daily_columns = _tableColumns(conn, "resource_daily")
    if daily_columns and "last_record_time" not in daily_columns:
        conn.execute("ALTER TABLE resource_daily ADD COLUMN last_record_time TEXT")


def _upgradeCubeTaskSchema(conn: sqlite3.Connection) -> None:
    """
    为早期的 ``cube_task`` 补 ``short_name`` / ``resource_type`` 列，
    并为 ``cube_task_completion`` 补建造任务联动列。

    新库由 SQL 脚本直接建出这些列，这里只处理已存在但缺列的老库；可重复执行。
    老库的现有任务默认归到 ``cube``，红尖尖任务由后续 SQL 脚本幂等写入；
    历史完成记录没有建造联动，两列为空即表示「没有支出 / 没有关联活动」。

    Args:
        conn: 数据库连接。
    """
    columns = _tableColumns(conn, "cube_task")
    if columns and "short_name" not in columns:
        conn.execute("ALTER TABLE cube_task ADD COLUMN short_name TEXT NOT NULL DEFAULT ''")
    if columns and "resource_type" not in columns:
        conn.execute(
            "ALTER TABLE cube_task ADD COLUMN resource_type TEXT NOT NULL DEFAULT 'cube'"
        )

    completion_columns = _tableColumns(conn, "cube_task_completion")
    if completion_columns and "expense_transaction_id" not in completion_columns:
        conn.execute(
            "ALTER TABLE cube_task_completion ADD COLUMN expense_transaction_id INTEGER"
        )
    if completion_columns and "event_id" not in completion_columns:
        conn.execute("ALTER TABLE cube_task_completion ADD COLUMN event_id INTEGER")


def _upgradeEventTransactionColumn(conn: sqlite3.Connection) -> None:
    """
    为明细补 ``event_id`` 列（活动记录关联，可空）。

    新库由资源脚本直接建出该列；老库在这里补列，之后由脚本创建 ``event_id`` 索引。
    必须在执行资源脚本之前调用，否则索引会因为列还不存在而失败。可重复执行。

    Args:
        conn: 数据库连接。
    """
    columns = _tableColumns(conn, "resource_transaction")
    if columns and "event_id" not in columns:
        conn.execute("ALTER TABLE resource_transaction ADD COLUMN event_id INTEGER")


def _upgradeEventRecordSchema(conn: sqlite3.Connection) -> None:
    """
    升级活动记录表：旧列 ``draws`` 改名 ``build_count``，并补齐单耗 / 建造券字段。

    - ``draws``（抽数）→ ``build_count``（建造次数），数据保留；
    - ``build_cost``：单次消耗魔方数，旧数据默认 2；
    - ``use_ticket``：是否使用建造券，旧数据默认 0；
    - ``ticket_build_count``：券抽次数，旧数据为 NULL。

    全部以列是否存在为前提，可重复执行。

    Args:
        conn: 数据库连接。
    """
    columns = _tableColumns(conn, "event_record")
    if not columns:
        return
    if "draws" in columns and "build_count" not in columns:
        conn.execute("ALTER TABLE event_record RENAME COLUMN draws TO build_count")
        columns = _tableColumns(conn, "event_record")

    if "build_cost" not in columns:
        conn.execute(
            "ALTER TABLE event_record ADD COLUMN build_cost INTEGER NOT NULL DEFAULT 2"
        )
    if "use_ticket" not in columns:
        conn.execute(
            "ALTER TABLE event_record ADD COLUMN use_ticket INTEGER NOT NULL DEFAULT 0"
        )
    if "ticket_build_count" not in columns:
        conn.execute("ALTER TABLE event_record ADD COLUMN ticket_build_count INTEGER")


def _upgradeResourceCategorySchema(conn: sqlite3.Connection) -> None:
    """
    为类型字典补 ``is_active`` 列（停用 / 启用，#21）。

    新库由 SQL 脚本直接建出该列；老库在这里补默认值 1（全部启用），
    可重复执行，不会改动已存在的名称与顺序。

    Args:
        conn: 数据库连接。
    """
    columns = _tableColumns(conn, "resource_category")
    if columns and "is_active" not in columns:
        conn.execute(
            "ALTER TABLE resource_category"
            " ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1))"
        )


def _seedCategoriesIfEmpty(conn: sqlite3.Connection, seed_sql: str) -> None:
    """
    仅在类型字典为空时写入默认类型。

    改成「空表播种」而不是每次启动 upsert，是为了让用户自助维护（#21）的结果——
    改名、排序、停用——在重启后保留；否则启动会把 ``sort_order`` 写回默认值，
    并让改名后的旧名称重新出现。

    Args:
        conn: 数据库连接。
        seed_sql: ``sql/SeedResourceCategories.sql`` 的内容。
    """
    row = conn.execute("SELECT COUNT(*) FROM resource_category").fetchone()
    if row and int(row[0]) > 0:
        return
    conn.executescript(seed_sql)


def _backfillLastRecordTime(conn: sqlite3.Connection) -> None:
    """
    为明细日回填「最后一笔时刻」。

    历史数据的时刻统一为 00:00:00，展示层会退化为仅日期；
    后续正常录入（#17）会在写入时维护该列。

    Args:
        conn: 数据库连接。
    """
    daily_columns = _tableColumns(conn, "resource_daily")
    if "last_record_time" not in daily_columns:
        return

    conn.execute(
        """
        UPDATE resource_daily
           SET last_record_time = (
               SELECT MAX(t.record_time) FROM resource_transaction t
                WHERE t.resource_type = resource_daily.resource_type
                  AND substr(t.record_time, 1, 10) = resource_daily.record_date
           )
         WHERE detail_mode = 'detail' AND last_record_time IS NULL
        """
    )


def isMissingTableError(exc: Exception) -> bool:
    """
    判断异常是否由"表不存在"引起。

    迁移尚未执行、或用户使用旧库时，新表可能缺失。业务层据此降级为空结果，
    而不是把数据库异常抛到界面上。

    Args:
        exc: 捕获到的异常。

    Returns:
        是"no such table"类错误返回 True。
    """
    return "no such table" in str(exc).lower()


def isMissingColumnError(exc: Exception) -> bool:
    """
    判断异常是否由"列不存在"引起。

    结构升级未执行时可能出现，业务层同样按降级处理。

    Args:
        exc: 捕获到的异常。

    Returns:
        是"no such column"类错误返回 True。
    """
    return "no such column" in str(exc).lower()
