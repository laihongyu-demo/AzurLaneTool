"""
舰娘誓约功能单元测试。

测试覆盖：
- 数据访问层：findOathable() 查询正确性、updateOathStatus() 更新正确性
- 业务逻辑层：getOathableShips()、oathShip() 正确性
- 边界条件：已誓约、改造舰娘排除、不存在的ID
"""

import unittest
import os
import sqlite3
import tempfile
import shutil

from repositories.codex_repository import CodexGroupRepository
from services.codex_oath_service import CodexOathService
from utils.db_connection import DatabaseConnection
from utils.exceptions import ValidationError


class TestOathRepository(unittest.TestCase):
    """誓约数据访问层测试类。"""

    @classmethod
    def setUpClass(cls):
        """测试类初始化。"""
        cls._test_db_dir = tempfile.mkdtemp()
        cls._test_db_path = os.path.join(cls._test_db_dir, "test_oath_repo.db")
        DatabaseConnection.setDbPath(cls._test_db_path)
        cls._createTestDatabase()

    @classmethod
    def tearDownClass(cls):
        """测试类清理。"""
        DatabaseConnection.setDbPath("")
        if os.path.exists(cls._test_db_dir):
            shutil.rmtree(cls._test_db_dir)

    @classmethod
    def _createTestDatabase(cls):
        """创建测试数据库。"""
        conn = sqlite3.connect(cls._test_db_path)
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE codex_group (
                codex_id INTEGER PRIMARY KEY,
                ship_name TEXT,
                ship_level TEXT,
                ship_star INTEGER,
                ship_rarity TEXT,
                ship_typ TEXT,
                ship_group TEXT,
                ship_aid TEXT,
                ship_camp TEXT,
                ship_liking TEXT,
                oath_status TEXT,
                codex_unlock TEXT,
                date_edit TEXT
            )
        """)

        # 常规舰娘 - 未誓约
        cursor.execute("""
            INSERT INTO codex_group (codex_id, ship_name, ship_typ, ship_rarity, ship_camp, ship_group, ship_aid, oath_status, codex_unlock)
            VALUES (1, '拉菲', '驱逐舰', 'SR', '白鹰联邦', '常规', '2017/1/1', 'N', 'Y')
        """)
        # 常规舰娘 - 已誓约（不应出现在可誓约列表中）
        cursor.execute("""
            INSERT INTO codex_group (codex_id, ship_name, ship_typ, ship_rarity, ship_camp, ship_group, ship_aid, oath_status, codex_unlock)
            VALUES (2, '标枪', '驱逐舰', 'SR', '皇家', '常规', '2017/1/1', 'Y', 'Y')
        """)
        # 常规舰娘 - 未誓约
        cursor.execute("""
            INSERT INTO codex_group (codex_id, ship_name, ship_typ, ship_rarity, ship_camp, ship_group, ship_aid, oath_status, codex_unlock)
            VALUES (3, '企业', '航母', 'SSR', '白鹰联邦', '常规', '2017/6/1', 'N', 'Y')
        """)
        # 改造舰娘 - 未誓约（应被排除）
        cursor.execute("""
            INSERT INTO codex_group (codex_id, ship_name, ship_typ, ship_rarity, ship_camp, ship_group, ship_aid, oath_status, codex_unlock)
            VALUES (4, '拉菲改', '驱逐舰', 'SSR', '白鹰联邦', '改造', '2018/1/1', 'N', 'Y')
        """)
        # 常规舰娘 - 未誓约、未解锁（应被排除）
        cursor.execute("""
            INSERT INTO codex_group (codex_id, ship_name, ship_typ, ship_rarity, ship_camp, ship_group, ship_aid, oath_status, codex_unlock)
            VALUES (5, '未解锁舰娘', '驱逐舰', 'SR', '白鹰联邦', '常规', '2020/1/1', 'N', 'N')
        """)

        conn.commit()
        conn.close()

    def setUp(self):
        """测试初始化。"""
        self._repository = CodexGroupRepository()

    def testFindOathable(self):
        """测试查询可誓约舰娘：应排除已誓约和改造舰娘。"""
        ships = self._repository.findOathable()
        # 有效未誓约非改造：id 1, 3 = 2
        self.assertEqual(len(ships), 2)
        ship_ids = [s.codex_id for s in ships]
        self.assertIn('1', ship_ids)
        self.assertIn('3', ship_ids)
        self.assertNotIn('2', ship_ids)  # 已誓约
        self.assertNotIn('4', ship_ids)  # 改造
        self.assertNotIn('5', ship_ids)  # 未解锁

    def testFindOathableExcludesUnlocked(self):
        """测试未解锁的舰娘不出现在可誓约列表中。"""
        ships = self._repository.findOathable()
        for ship in ships:
            self.assertEqual(ship.codex_unlock, "Y")

    def testFindOathableExcludesOathed(self):
        """测试已誓约舰娘不出现在可誓约列表中。"""
        ships = self._repository.findOathable()
        for ship in ships:
            self.assertEqual(ship.oath_status, "N")

    def testFindOathableExcludesRefit(self):
        """测试改造舰娘不出现在可誓约列表中。"""
        ships = self._repository.findOathable()
        for ship in ships:
            self.assertNotEqual(ship.ship_group, "改造")

    def testUpdateOathStatus(self):
        """测试更新誓约状态。"""
        result = self._repository.updateOathStatus(1, "Y")
        self.assertTrue(result)

        # 验证状态已更新
        ship = self._repository.findById(1)
        self.assertEqual(ship.oath_status, "Y")

    def testUpdateOathStatusNonExistent(self):
        """测试更新不存在的舰娘。"""
        result = self._repository.updateOathStatus(999, "Y")
        self.assertFalse(result)


class TestOathService(unittest.TestCase):
    """誓约业务逻辑层测试类。"""

    @classmethod
    def setUpClass(cls):
        """测试类初始化。"""
        cls._test_db_dir = tempfile.mkdtemp()
        cls._test_db_path = os.path.join(cls._test_db_dir, "test_oath_service.db")
        DatabaseConnection.setDbPath(cls._test_db_path)

        conn = sqlite3.connect(cls._test_db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE codex_group (
                codex_id INTEGER PRIMARY KEY,
                ship_name TEXT,
                ship_level TEXT,
                ship_star INTEGER,
                ship_rarity TEXT,
                ship_typ TEXT,
                ship_group TEXT,
                ship_aid TEXT,
                ship_camp TEXT,
                ship_liking TEXT,
                oath_status TEXT,
                codex_unlock TEXT,
                date_edit TEXT
            )
        """)

        cursor.execute("""
            INSERT INTO codex_group (codex_id, ship_name, ship_typ, ship_rarity, ship_camp, ship_group, ship_aid, oath_status, codex_unlock)
            VALUES (1, '拉菲', '驱逐舰', 'SR', '白鹰联邦', '常规', '2017/1/1', 'N', 'Y')
        """)
        cursor.execute("""
            INSERT INTO codex_group (codex_id, ship_name, ship_typ, ship_rarity, ship_camp, ship_group, ship_aid, oath_status, codex_unlock)
            VALUES (2, '标枪', '驱逐舰', 'SR', '皇家', '常规', '2017/1/1', 'Y', 'Y')
        """)
        cursor.execute("""
            INSERT INTO codex_group (codex_id, ship_name, ship_typ, ship_rarity, ship_camp, ship_group, ship_aid, oath_status, codex_unlock)
            VALUES (3, '改造舰娘', '驱逐舰', 'SSR', '白鹰联邦', '改造', '2018/1/1', 'N', 'Y')
        """)

        conn.commit()
        conn.close()

    @classmethod
    def tearDownClass(cls):
        """测试类清理。"""
        DatabaseConnection.setDbPath("")
        if os.path.exists(cls._test_db_dir):
            shutil.rmtree(cls._test_db_dir)

    def setUp(self):
        """测试初始化：重置数据库状态。"""
        # 重置id=1的誓约状态，确保测试间状态独立
        repository = CodexGroupRepository()
        repository.updateOathStatus(1, "N")
        self._service = CodexOathService()

    def testGetOathableShips(self):
        """测试获取可誓约舰娘列表。"""
        ships = self._service.getOathableShips()
        # 只有 id=1 是未誓约非改造
        self.assertEqual(len(ships), 1)
        self.assertEqual(ships[0].codex_id, '1')

    def testOathShipSuccess(self):
        """测试誓约成功。"""
        result = self._service.oathShip(1)
        self.assertTrue(result.success)
        self.assertEqual(result.ship_name, "拉菲")

        # 验证状态已更新
        ship = self._service.getShipById(1)
        self.assertEqual(ship.oath_status, "Y")

    def testOathShipAlreadyOathed(self):
        """测试誓约已誓约的舰娘。"""
        result = self._service.oathShip(2)
        self.assertFalse(result.success)
        self.assertIn("已经誓约", result.message)

    def testOathShipRefit(self):
        """测试誓约改造舰娘。"""
        result = self._service.oathShip(3)
        self.assertFalse(result.success)
        self.assertIn("改造", result.message)

    def testOathShipNotFound(self):
        """测试誓约不存在的舰娘。"""
        result = self._service.oathShip(999)
        self.assertFalse(result.success)
        self.assertIn("未找到", result.message)

    def testOathShipInvalidId(self):
        """测试无效的图鉴ID。"""
        with self.assertRaises(ValidationError):
            self._service.oathShip(None)

        with self.assertRaises(ValidationError):
            self._service.oathShip("")

    def testOathResultStatusBarMessage(self):
        """测试誓约结果状态栏消息。"""
        result = self._service.oathShip(1)
        self.assertTrue(result.success)
        msg = result.toStatusBarMessage()
        self.assertIn("拉菲", msg)
        self.assertIn("誓约成功", msg)

        fail_result = self._service.oathShip(2)
        self.assertFalse(fail_result.success)
        self.assertEqual(fail_result.toStatusBarMessage(), fail_result.message)


if __name__ == "__main__":
    unittest.main()