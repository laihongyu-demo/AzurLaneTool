"""
界限突破服务单元测试。

覆盖：单次突破、突破至满星时同步解锁科技点的「满星」条件，
以及「科技属性不存在满星条件」这一口径（属性表不应被触碰）。
"""

import os
import shutil
import sqlite3
import tempfile
import unittest

from services.limit_break_service import LimitBreakService
from utils.constants import DEFAULT_DB_PATH
from utils.db_connection import DatabaseConnection

CREATE_SQL = [
    """
    CREATE TABLE codex_group (
        codex_id TEXT NOT NULL PRIMARY KEY,
        ship_name TEXT,
        ship_level TEXT DEFAULT '未觉醒',
        ship_star INTEGER,
        ship_rarity TEXT,
        ship_typ TEXT,
        ship_group TEXT,
        ship_aid NUMERIC,
        ship_camp TEXT,
        ship_liking TEXT DEFAULT '陌生',
        oath_status TEXT DEFAULT 'N',
        codex_unlock TEXT DEFAULT 'N',
        date_edit DATE
    )
    """,
    """
    CREATE TABLE codex_tp (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        codex_id TEXT NOT NULL,
        ship_name TEXT,
        ship_camp TEXT,
        ship_typ TEXT,
        tp_value INTEGER,
        unlock_cond TEXT,
        tp_unlock TEXT DEFAULT 'N',
        date_edit DATE
    )
    """,
    """
    CREATE TABLE codex_buff (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        codex_id TEXT NOT NULL,
        ship_name TEXT,
        ship_camp TEXT,
        ship_typ TEXT,
        boost_typ TEXT NOT NULL,
        buff_typ TEXT,
        buff_value INTEGER,
        buff_cond TEXT,
        buff_unlock TEXT DEFAULT 'N'
    )
    """,
]

# (codex_id, 名称, 星级, 稀有度, 分组)
GROUP_FIXTURE = [
    ('1', '测试四星', 4, 'SSR', '常规'),
    ('2', '测试满星', 6, 'SSR', '常规'),
    ('3', '测试改造', 3, 'SSR', '改造'),
]

TP_FIXTURE = [
    ('1', '测试四星', '白鹰联邦', '驱逐舰', 10, '解锁', 'Y'),
    ('1', '测试四星', '白鹰联邦', '驱逐舰', 22, '满星', 'N'),
    ('1', '测试四星', '白鹰联邦', '驱逐舰', 16, 'Lv.120', 'N'),
    ('2', '测试满星', '白鹰联邦', '驱逐舰', 10, '解锁', 'Y'),
    ('2', '测试满星', '白鹰联邦', '驱逐舰', 22, '满星', 'Y'),
    ('2', '测试满星', '白鹰联邦', '驱逐舰', 16, 'Lv.120', 'N'),
]

BUFF_FIXTURE = [
    ('1', '测试四星', '白鹰联邦', '驱逐舰', '驱逐', '耐久', 1, '解锁', 'Y'),
    ('1', '测试四星', '白鹰联邦', '驱逐舰', '驱逐', '机动', 1, 'Lv.120', 'N'),
    ('2', '测试满星', '白鹰联邦', '驱逐舰', '驱逐', '耐久', 1, '解锁', 'Y'),
]


class LimitBreakServiceTestCase(unittest.TestCase):
    """界限突破服务测试基类。"""

    def setUp(self):
        """创建临时数据库。"""
        self._temp_dir = tempfile.mkdtemp()
        self._db_path = os.path.join(self._temp_dir, 'limit_break.db')
        DatabaseConnection.setDbPath(self._db_path)
        self._createDatabase()
        self._service = LimitBreakService()

    def tearDown(self):
        """清理临时目录。"""
        DatabaseConnection.setDbPath(DEFAULT_DB_PATH)
        shutil.rmtree(self._temp_dir, ignore_errors=True)

    def _createDatabase(self):
        """建立表结构并写入夹具数据。"""
        conn = sqlite3.connect(self._db_path)
        cursor = conn.cursor()
        for sql in CREATE_SQL:
            cursor.execute(sql)

        for codex_id, name, star, rarity, group in GROUP_FIXTURE:
            cursor.execute(
                "INSERT INTO codex_group (codex_id, ship_name, ship_star, ship_rarity,"
                " ship_typ, ship_group, ship_aid, ship_camp, codex_unlock)"
                " VALUES (?, ?, ?, ?, '驱逐舰', ?, '2026/01/01', '白鹰联邦', 'Y')",
                (codex_id, name, star, rarity, group)
            )
        for row in TP_FIXTURE:
            cursor.execute(
                "INSERT INTO codex_tp (codex_id, ship_name, ship_camp, ship_typ, tp_value,"
                " unlock_cond, tp_unlock) VALUES (?, ?, ?, ?, ?, ?, ?)", row
            )
        for row in BUFF_FIXTURE:
            cursor.execute(
                "INSERT INTO codex_buff (codex_id, ship_name, ship_camp, ship_typ, boost_typ,"
                " buff_typ, buff_value, buff_cond, buff_unlock)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", row
            )
        conn.commit()
        conn.close()

    def _rows(self, table: str, codex_id: str):
        """读取指定表的行。"""
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            return [dict(row) for row in conn.execute(
                f'SELECT * FROM {table} WHERE codex_id = ?', (codex_id,))]
        finally:
            conn.close()

    def _starOf(self, codex_id: str) -> int:
        """读取星级。"""
        conn = sqlite3.connect(self._db_path)
        try:
            return conn.execute(
                'SELECT ship_star FROM codex_group WHERE codex_id = ?', (codex_id,)
            ).fetchone()[0]
        finally:
            conn.close()


class TestLimitBreak(LimitBreakServiceTestCase):
    """界限突破测试类。"""

    def testLimitBreakIncrementsStar(self):
        """单次突破星级 +1，且未满星时不改科技点解锁状态。"""
        result = self._service.limitBreak('1')

        self.assertTrue(result.success)
        self.assertEqual((result.old_star, result.new_star), (4, 5))
        self.assertFalse(result.is_full_star)
        self.assertEqual(result.tp_value, 0)

        tp = {row['unlock_cond']: row['tp_unlock'] for row in self._rows('codex_tp', '1')}
        self.assertEqual(tp, {'解锁': 'Y', '满星': 'N', 'Lv.120': 'N'})

    def testLimitBreakToMaxUnlocksFullStarTp(self):
        """突破至满星时，科技点的「满星」条件被置为已解锁。"""
        result = self._service.limitBreak('1')
        self.assertFalse(result.is_full_star)

        result = self._service.limitBreak('1')
        self.assertTrue(result.success)
        self.assertEqual((result.old_star, result.new_star), (5, 6))
        self.assertTrue(result.is_full_star)
        self.assertEqual(result.tp_value, 22)

        tp = {row['unlock_cond']: row['tp_unlock'] for row in self._rows('codex_tp', '1')}
        self.assertEqual(tp, {'解锁': 'Y', '满星': 'Y', 'Lv.120': 'N'})

    def testLimitBreakMaxUnlocksFullStarTp(self):
        """界限突破·MAX 同样解锁科技点的「满星」条件。"""
        result = self._service.limitBreakMax('1')

        self.assertTrue(result.success)
        self.assertEqual(self._starOf('1'), 6)
        self.assertEqual(result.tp_value, 22)

        tp = {row['unlock_cond']: row['tp_unlock'] for row in self._rows('codex_tp', '1')}
        self.assertEqual(tp['满星'], 'Y')

    def testDoesNotTouchBuffTable(self):
        """科技属性不存在「满星」条件，突破不应改动属性表。"""
        before = self._rows('codex_buff', '1')

        self._service.limitBreak('1')
        self._service.limitBreak('1')

        after = self._rows('codex_buff', '1')
        self.assertEqual(
            [(row['boost_typ'], row['buff_cond'], row['buff_typ'], row['buff_value'],
              row['buff_unlock']) for row in after],
            [(row['boost_typ'], row['buff_cond'], row['buff_typ'], row['buff_value'],
              row['buff_unlock']) for row in before]
        )

    def testRejectsRefitGroup(self):
        """改造分组不支持界限突破。"""
        result = self._service.limitBreak('3')

        self.assertFalse(result.success)
        self.assertIn('改造', result.message)

    def testRejectsAlreadyFullStar(self):
        """已达满星时不再重复突破。"""
        result = self._service.limitBreak('2')

        self.assertFalse(result.success)
        self.assertIn('已达到满星', result.message)


if __name__ == '__main__':
    unittest.main()
