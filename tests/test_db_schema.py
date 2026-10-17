"""
表结构引导与就地升级单元测试。

覆盖：空库建表、v0.2 旧结构（明细仅日期）升级到 record_time、升级可重复执行。
"""

import os
import shutil
import sqlite3
import tempfile
import unittest

from utils.db_schema import ensureResourceStatisticsSchema

LEGACY_SCHEMA = """
CREATE TABLE resource_daily (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    resource_type    TEXT NOT NULL,
    record_date      TEXT NOT NULL,
    detail_mode      TEXT NOT NULL DEFAULT 'detail',
    income           INTEGER,
    expense          INTEGER,
    balance_override INTEGER,
    note             TEXT NOT NULL DEFAULT '',
    created_at       TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at       TEXT,
    UNIQUE (resource_type, record_date)
);
CREATE TABLE resource_transaction (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    resource_type TEXT NOT NULL,
    direction     TEXT NOT NULL,
    record_date   TEXT NOT NULL,
    category      TEXT NOT NULL,
    amount        INTEGER NOT NULL,
    note          TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at    TEXT
);
CREATE INDEX idx_resource_transaction_date
    ON resource_transaction (resource_type, record_date);
"""


def _columns(conn: sqlite3.Connection, table: str):
    """读取表的列名集合。"""
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


class TestSchemaBootstrap(unittest.TestCase):
    """表结构引导测试。"""

    def setUp(self):
        self._temp_dir = tempfile.mkdtemp(prefix="azurlane_schema_")
        self._db_path = os.path.join(self._temp_dir, "schema.db")

    def tearDown(self):
        shutil.rmtree(self._temp_dir, ignore_errors=True)

    def testCreatesTablesOnEmptyDatabase(self):
        """空库上建出四张表与时间索引。"""
        ensureResourceStatisticsSchema(self._db_path)

        conn = sqlite3.connect(self._db_path)
        try:
            tables = {
                row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            indexes = {
                row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
            }
            transaction_columns = _columns(conn, "resource_transaction")
        finally:
            conn.close()

        self.assertTrue(
            {"resource_daily", "resource_transaction", "resource_category", "commander_level_exp"}
            <= tables
        )
        self.assertIn("record_time", transaction_columns)
        self.assertNotIn("record_date", transaction_columns)
        self.assertIn("idx_resource_transaction_time", indexes)

    def testUpgradesLegacyRecordDateColumn(self):
        """旧结构的 record_date 被改名、补齐时分秒，并回填日汇总的末次时刻。"""
        conn = sqlite3.connect(self._db_path)
        try:
            conn.executescript(LEGACY_SCHEMA)
            conn.execute(
                "INSERT INTO resource_daily (resource_type, record_date, detail_mode,"
                " income, expense) VALUES ('cube', '2024-10-16', 'summary_only', 5, 1)"
            )
            conn.execute(
                "INSERT INTO resource_daily (resource_type, record_date, detail_mode)"
                " VALUES ('cube', '2024-10-17', 'detail')"
            )
            conn.executemany(
                "INSERT INTO resource_transaction (resource_type, direction, record_date,"
                " category, amount) VALUES ('cube', ?, '2024-10-17', '日常任务', ?)",
                [("income", 2), ("income", 1), ("expense", 3)],
            )
            conn.commit()
        finally:
            conn.close()

        ensureResourceStatisticsSchema(self._db_path)

        conn = sqlite3.connect(self._db_path)
        try:
            transaction_columns = _columns(conn, "resource_transaction")
            times = [
                row[0] for row in conn.execute(
                    "SELECT record_time FROM resource_transaction ORDER BY id"
                )
            ]
            daily = conn.execute(
                "SELECT record_date, last_record_time FROM resource_daily ORDER BY record_date"
            ).fetchall()
            indexes = {
                row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
            }
        finally:
            conn.close()

        self.assertIn("record_time", transaction_columns)
        self.assertNotIn("record_date", transaction_columns)
        self.assertEqual(times, ["2024-10-17 00:00:00"] * 3)
        self.assertEqual(daily[0], ("2024-10-16", None))
        self.assertEqual(daily[1], ("2024-10-17", "2024-10-17 00:00:00"))
        self.assertIn("idx_resource_transaction_time", indexes)

    def testUpgradeIsIdempotent(self):
        """重复执行不报错、不重复改数据。"""
        conn = sqlite3.connect(self._db_path)
        try:
            conn.executescript(LEGACY_SCHEMA)
            conn.execute(
                "INSERT INTO resource_transaction (resource_type, direction, record_date,"
                " category, amount) VALUES ('cube', 'income', '2024-10-16', '日常任务', 2)"
            )
            conn.commit()
        finally:
            conn.close()

        ensureResourceStatisticsSchema(self._db_path)
        ensureResourceStatisticsSchema(self._db_path)

        conn = sqlite3.connect(self._db_path)
        try:
            times = [
                row[0] for row in conn.execute("SELECT record_time FROM resource_transaction")
            ]
        finally:
            conn.close()

        self.assertEqual(times, ["2024-10-16 00:00:00"])


if __name__ == "__main__":
    unittest.main()
