"""
认知觉醒服务单元测试。

覆盖：

- 觉醒等级推进与事务写入
- **本次觉醒消耗的材料**：按「稀有度 × 跨过的阶段」从 awakening_of_mind 求和
- 四阶 → 五阶不消耗材料（只需经验），状态栏显示「本次消耗：无」
- 状态栏消息中的材料数量不换算、带千分符
"""

import os
import shutil
import sqlite3
import tempfile
import unittest

from services.awaken_service import AwakenResult, AwakenService
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
    """
    CREATE TABLE awakening_of_mind (
        id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
        ship_rarity STRING(255),
        am_phase INTEGER(32),
        expend_gc INTEGER,
        expend_limit INTEGER,
        expend_limit2 INTEGER
    )
    """,
]

# 基准表夹具：SSR 用真实数值（阶段1-5），便于与游戏口径对照
SSR_PHASES = [
    (1, 2000, 200, 0),
    (2, 4000, 400, 0),
    (3, 6000, 600, 0),
    (4, 10000, 1000, 0),
    (5, 3000, 300, 150),
]

# (codex_id, 名称, 等级, 稀有度)
SHIP_FIXTURE = [
    ('1', '测试SSR未觉醒', '未觉醒', 'SSR'),
    ('2', '测试SSR一阶', '认知觉醒一阶', 'SSR'),
    ('3', '测试SSR四阶', '认知觉醒四阶', 'SSR'),
    ('4', '测试SSR二阶', '认知觉醒二阶', 'SSR'),
]


class AwakenServiceTestCase(unittest.TestCase):
    """觉醒服务测试基类。"""

    def setUp(self):
        """创建临时数据库。"""
        self._temp_dir = tempfile.mkdtemp()
        self._db_path = os.path.join(self._temp_dir, 'awaken.db')
        DatabaseConnection.setDbPath(self._db_path)
        self._createDatabase()
        self._service = AwakenService()

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

        for codex_id, name, level, rarity in SHIP_FIXTURE:
            cursor.execute(
                'INSERT INTO codex_group (codex_id, ship_name, ship_level, ship_rarity,'
                ' ship_star, ship_typ, ship_group, ship_aid, ship_camp, codex_unlock)'
                " VALUES (?, ?, ?, ?, 3, '驱逐舰', '常规', '2026/01/01', '白鹰联邦', 'Y')",
                (codex_id, name, level, rarity)
            )

        for phase, gc, limit, limit2 in SSR_PHASES:
            cursor.execute(
                'INSERT INTO awakening_of_mind (ship_rarity, am_phase, expend_gc,'
                ' expend_limit, expend_limit2) VALUES (?, ?, ?, ?, ?)',
                ('SSR', phase, gc, limit, limit2)
            )

        for cond, value in (('解锁', 10), ('满星', 22), ('Lv.120', 16)):
            cursor.execute(
                'INSERT INTO codex_tp (codex_id, ship_name, ship_camp, ship_typ, tp_value,'
                " unlock_cond, tp_unlock) VALUES ('1', '测试SSR未觉醒', '白鹰联邦', '驱逐舰', ?, ?, 'N')",
                (value, cond)
            )
        conn.commit()
        conn.close()

    def _connect(self) -> sqlite3.Connection:
        """打开测试库连接。"""
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _levelOf(self, codex_id: str) -> str:
        """读取当前等级。"""
        conn = self._connect()
        try:
            return conn.execute(
                'SELECT ship_level FROM codex_group WHERE codex_id = ?', (codex_id,)
            ).fetchone()['ship_level']
        finally:
            conn.close()


class TestAwakenConsume(AwakenServiceTestCase):
    """觉醒材料消耗测试类。"""

    def testFirstAwakenConsumesPhaseOne(self):
        """未觉醒 → 一阶：消耗阶段 1。"""
        result = self._service.awakenShip('1', '认知觉醒一阶')

        self.assertTrue(result.success)
        self.assertEqual(
            (result.expend_gc, result.expend_limit, result.expend_limit2), (2000, 200, 0)
        )
        self.assertIn('物资 2,000', result.toStatusBarMessage())
        self.assertIn('心智单元 200', result.toStatusBarMessage())
        self.assertNotIn('心智单元Ⅱ', result.toStatusBarMessage())

    def testMultiPhaseAwakenSumsPhases(self):
        """一阶 → 三阶：消耗阶段 2 与 3。"""
        result = self._service.awakenShip('2', '认知觉醒三阶')

        self.assertEqual(
            (result.expend_gc, result.expend_limit), (4000 + 6000, 400 + 600)
        )
        self.assertIn('物资 10,000', result.toStatusBarMessage())

    def testFourthToFifthConsumesNothing(self):
        """四阶 → 五阶不需要材料（只需经验）。"""
        result = self._service.awakenShip('3', '认知觉醒五阶')

        self.assertTrue(result.success)
        self.assertEqual(
            (result.expend_gc, result.expend_limit, result.expend_limit2), (0, 0, 0)
        )
        self.assertEqual(result.formatConsume(), '本次消耗：无')
        self.assertIn('本次消耗：无', result.toStatusBarMessage())

    def testFifthToPhaseIIConsumesPhaseFive(self):
        """五阶 → 认知觉醒II：只消耗阶段 5（含心智单元Ⅱ）。"""
        service = AwakenService()
        service.awakenShip('3', '认知觉醒五阶')

        result = service.awakenShip('3', '认知觉醒II')
        self.assertEqual(
            (result.expend_gc, result.expend_limit, result.expend_limit2), (3000, 300, 150)
        )
        self.assertIn('心智单元Ⅱ 150', result.toStatusBarMessage())

    def testMissingBaselineTableDoesNotBreakAwaken(self):
        """基准表缺失时觉醒仍成功，消耗显示为 0。"""
        conn = self._connect()
        conn.execute('DROP TABLE awakening_of_mind')
        conn.commit()
        conn.close()

        result = self._service.awakenShip('1', '认知觉醒一阶')

        self.assertTrue(result.success)
        self.assertEqual(result.formatConsume(), '本次消耗：无')

    def testStatusBarMessageKeepsThousandsSeparator(self):
        """材料数量不换算，千位以上带千分符。"""
        result = AwakenResult(
            success=True, ship_name='测试', old_level='未觉醒', new_level='认知觉醒四阶',
            expend_gc=22000, expend_limit=2200, expend_limit2=0
        )
        message = result.toStatusBarMessage()

        self.assertIn('物资 22,000', message)
        self.assertIn('心智单元 2,200', message)
        self.assertNotIn('22.0K', message)


if __name__ == '__main__':
    unittest.main()
