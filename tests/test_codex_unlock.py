"""
舰娘解锁功能单元测试。
"""

import unittest
import os
import sqlite3
import tempfile
import shutil

from models.codex_model import CodexGroupModel, CodexTpModel, CodexBuffModel
from repositories.codex_repository import (
    CodexGroupRepository, CodexTpRepository, CodexBuffRepository
)
from services.codex_unlock_service import CodexUnlockService
from utils.db_connection import DatabaseConnection


class TestCodexModels(unittest.TestCase):
    """舰娘模型测试类。"""

    def testCodexGroupModel(self):
        """测试舰娘图鉴组模型。"""
        data = {
            "codex_id": 1,
            "ship_name": "测试舰娘",
            "ship_level": "Lv.1",
            "ship_star": 5,
            "ship_rarity": "SSR",
            "ship_typ": "驱逐舰",
            "ship_group": "常规",
            "ship_aid": "2024/1/1",
            "ship_camp": "白鹰联邦",
            "ship_liking": "陌生",
            "oath_status": "N",
            "codex_unlock": "N",
            "date_edit": None
        }
        model = CodexGroupModel.fromDict(data)
        self.assertEqual(model.codex_id, 1)
        self.assertEqual(model.ship_name, "测试舰娘")
        self.assertEqual(model.codex_unlock, "N")

    def testCodexTpModel(self):
        """测试TP模型。"""
        data = {
            "id": 1,
            "codex_id": 1,
            "ship_name": "测试舰娘",
            "ship_camp": "白鹰联邦",
            "ship_typ": "驱逐舰",
            "tp_value": 5,
            "unlock_cond": "解锁",
            "tp_unlock": "N",
            "date_edit": None
        }
        model = CodexTpModel.fromDict(data)
        self.assertEqual(model.codex_id, 1)
        self.assertEqual(model.unlock_cond, "解锁")
        self.assertEqual(model.tp_unlock, "N")

    def testCodexBuffModel(self):
        """测试Buff模型。"""
        data = {
            "id": 1,
            "codex_id": 1,
            "ship_name": "测试舰娘",
            "ship_camp": "白鹰联邦",
            "ship_typ": "驱逐舰",
            "boost_typ": "驱逐",
            "buff_typ": "耐久",
            "buff_value": 1,
            "buff_cond": "解锁",
            "buff_unlock": "N"
        }
        model = CodexBuffModel.fromDict(data)
        self.assertEqual(model.codex_id, 1)
        self.assertEqual(model.buff_cond, "解锁")
        self.assertEqual(model.buff_unlock, "N")


class TestCodexUnlockService(unittest.TestCase):
    """舰娘解锁服务测试类。"""

    @classmethod
    def setUpClass(cls):
        """测试类初始化。"""
        cls._test_db_dir = tempfile.mkdtemp()
        cls._test_db_path = os.path.join(cls._test_db_dir, "test.db")
        DatabaseConnection.setDbPath(cls._test_db_path)
        cls._createTestDatabase()

    @classmethod
    def tearDownClass(cls):
        """测试类清理。"""
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

        cursor.execute("""
            CREATE TABLE codex_tp (
                id INTEGER PRIMARY KEY,
                codex_id INTEGER,
                ship_name TEXT,
                ship_camp TEXT,
                ship_typ TEXT,
                tp_value INTEGER,
                unlock_cond TEXT,
                tp_unlock TEXT,
                date_edit TEXT
            )
        """)

        cursor.execute("""
            CREATE TABLE codex_buff (
                id INTEGER PRIMARY KEY,
                codex_id INTEGER,
                ship_name TEXT,
                ship_camp TEXT,
                ship_typ TEXT,
                boost_typ TEXT,
                buff_typ TEXT,
                buff_value INTEGER,
                buff_cond TEXT,
                buff_unlock TEXT
            )
        """)

        cursor.execute("""
            INSERT INTO codex_group (codex_id, ship_name, ship_typ, ship_rarity, ship_camp, ship_group, ship_aid, codex_unlock)
            VALUES (1, '测试舰娘1', '驱逐舰', 'SSR', '白鹰联邦', '常规', '2024/1/1', 'N')
        """)
        cursor.execute("""
            INSERT INTO codex_group (codex_id, ship_name, ship_typ, ship_rarity, ship_camp, ship_group, ship_aid, codex_unlock)
            VALUES (2, '测试舰娘2', '巡洋舰', 'SR', '皇家', '常规', '2024/6/1', 'Y')
        """)
        cursor.execute("""
            INSERT INTO codex_group (codex_id, ship_name, ship_typ, ship_rarity, ship_camp, ship_group, ship_aid, codex_unlock)
            VALUES (3, '联动舰娘1', '驱逐舰', 'SSR', '联动阵营', '联动', '2024/3/1', 'N')
        """)
        cursor.execute("""
            INSERT INTO codex_group (codex_id, ship_name, ship_typ, ship_rarity, ship_camp, ship_group, ship_aid, codex_unlock)
            VALUES (4, '联动舰娘2', '巡洋舰', 'SR', '联动阵营', '联动', '2024/4/1', 'Y')
        """)

        cursor.execute("""
            INSERT INTO codex_tp (codex_id, ship_name, ship_camp, ship_typ, tp_value, unlock_cond, tp_unlock)
            VALUES (1, '测试舰娘1', '白鹰联邦', '驱逐舰', 5, '解锁', 'N')
        """)
        cursor.execute("""
            INSERT INTO codex_tp (codex_id, ship_name, ship_camp, ship_typ, tp_value, unlock_cond, tp_unlock)
            VALUES (1, '测试舰娘1', '白鹰联邦', '驱逐舰', 10, '满星', 'N')
        """)

        cursor.execute("""
            INSERT INTO codex_buff (codex_id, ship_name, ship_camp, ship_typ, boost_typ, buff_typ, buff_value, buff_cond, buff_unlock)
            VALUES (1, '测试舰娘1', '白鹰联邦', '驱逐舰', '驱逐', '耐久', 1, '解锁', 'N')
        """)
        cursor.execute("""
            INSERT INTO codex_buff (codex_id, ship_name, ship_camp, ship_typ, boost_typ, buff_typ, buff_value, buff_cond, buff_unlock)
            VALUES (1, '测试舰娘1', '白鹰联邦', '驱逐舰', '驱逐', '炮击', 1, 'Lv.120', 'N')
        """)

        conn.commit()
        conn.close()

    def setUp(self):
        """测试初始化。"""
        self._service = CodexUnlockService()

    def testGetLockedShips(self):
        """测试获取未解锁舰娘列表。"""
        ships = self._service.getLockedShips()
        self.assertEqual(len(ships), 2)

    def testGetUnlockedShips(self):
        """测试获取已解锁舰娘列表。"""
        ships = self._service.getUnlockedShips()
        self.assertEqual(len(ships), 2)

    def testGetUnlockStatistics(self):
        """测试获取解锁统计。"""
        stats = self._service.getUnlockStatistics()

        self.assertEqual(stats["total"], 4)
        self.assertEqual(stats["total_excluding_collab"], 2)
        self.assertEqual(stats["locked"], 2)
        self.assertEqual(stats["locked_excluding_collab"], 1)
        self.assertEqual(stats["unlocked"], 2)
        self.assertEqual(stats["unlocked_excluding_collab"], 1)
        self.assertEqual(stats["unlock_rate"], 50.0)

    def testUnlockShip(self):
        """测试解锁舰娘。"""
        success, message = self._service.unlockShip(1)
        self.assertTrue(success)
        self.assertIn("解锁成功", message)

        ship = self._service.getShipById(1)
        self.assertEqual(ship.codex_unlock, "Y")

    def testUnlockAlreadyUnlockedShip(self):
        """测试解锁已解锁的舰娘。"""
        success, message = self._service.unlockShip(2)
        self.assertFalse(success)
        self.assertIn("已经解锁", message)


class TestCodexGroupRepositoryExcludingCollab(unittest.TestCase):
    """舰娘图鉴数据访问层排除联动测试类。"""

    @classmethod
    def setUpClass(cls):
        """测试类初始化。"""
        cls._test_db_dir = tempfile.mkdtemp()
        cls._test_db_path = os.path.join(cls._test_db_dir, "test.db")
        DatabaseConnection.setDbPath(cls._test_db_path)
        cls._createTestDatabase()

    @classmethod
    def tearDownClass(cls):
        """测试类清理。"""
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

        cursor.execute("""
            INSERT INTO codex_group (codex_id, ship_name, ship_typ, ship_rarity, ship_camp, ship_group, ship_aid, codex_unlock)
            VALUES (1, '常规舰娘1', '驱逐舰', 'SSR', '白鹰联邦', '常规', '2024/1/1', 'Y')
        """)
        cursor.execute("""
            INSERT INTO codex_group (codex_id, ship_name, ship_typ, ship_rarity, ship_camp, ship_group, ship_aid, codex_unlock)
            VALUES (2, '常规舰娘2', '巡洋舰', 'SR', '皇家', '常规', '2024/6/1', 'N')
        """)
        cursor.execute("""
            INSERT INTO codex_group (codex_id, ship_name, ship_typ, ship_rarity, ship_camp, ship_group, ship_aid, codex_unlock)
            VALUES (3, '联动舰娘1', '驱逐舰', 'SSR', '联动阵营', '联动', '2024/3/1', 'Y')
        """)
        cursor.execute("""
            INSERT INTO codex_group (codex_id, ship_name, ship_typ, ship_rarity, ship_camp, ship_group, ship_aid, codex_unlock)
            VALUES (4, '联动舰娘2', '巡洋舰', 'SR', '联动阵营', '联动', '2024/4/1', 'N')
        """)

        conn.commit()
        conn.close()

    def setUp(self):
        """测试初始化。"""
        self._repository = CodexGroupRepository()

    def testFindAllExcludingCollab(self):
        """测试查询所有舰娘（排除联动）。"""
        ships = self._repository.findAllExcludingCollab()
        self.assertEqual(len(ships), 2)
        for ship in ships:
            self.assertNotEqual(ship.ship_group, "联动")

    def testFindUnlockedExcludingCollab(self):
        """测试查询已解锁舰娘（排除联动）。"""
        ships = self._repository.findUnlockedExcludingCollab()
        self.assertEqual(len(ships), 1)
        self.assertEqual(ships[0].ship_name, "常规舰娘1")

    def testFindLockedExcludingCollab(self):
        """测试查询未解锁舰娘（排除联动）。"""
        ships = self._repository.findLockedExcludingCollab()
        self.assertEqual(len(ships), 1)
        self.assertEqual(ships[0].ship_name, "常规舰娘2")


class TestCodexGroupRepositorySorting(unittest.TestCase):
    """舰娘图鉴数据访问层排序测试类。"""

    @classmethod
    def setUpClass(cls):
        """测试类初始化。"""
        cls._test_db_dir = tempfile.mkdtemp()
        cls._test_db_path = os.path.join(cls._test_db_dir, "test.db")
        DatabaseConnection.setDbPath(cls._test_db_path)
        cls._createTestDatabase()

    @classmethod
    def tearDownClass(cls):
        """测试类清理。"""
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

        cursor.execute("""
            INSERT INTO codex_group (codex_id, ship_name, ship_typ, ship_rarity, ship_camp, ship_group, ship_aid, codex_unlock)
            VALUES (1, '舰娘A', '驱逐舰', 'SSR', '白鹰联邦', '常规', '2024/1/1', 'N')
        """)
        cursor.execute("""
            INSERT INTO codex_group (codex_id, ship_name, ship_typ, ship_rarity, ship_camp, ship_group, ship_aid, codex_unlock)
            VALUES (2, '舰娘B', '巡洋舰', 'SR', '皇家', '常规', '2024/6/1', 'N')
        """)
        cursor.execute("""
            INSERT INTO codex_group (codex_id, ship_name, ship_typ, ship_rarity, ship_camp, ship_group, ship_aid, codex_unlock)
            VALUES (3, '舰娘C', '驱逐舰', 'SSR', '白鹰联邦', '常规', '2024/6/1', 'N')
        """)
        cursor.execute("""
            INSERT INTO codex_group (codex_id, ship_name, ship_typ, ship_rarity, ship_camp, ship_group, ship_aid, codex_unlock)
            VALUES (4, '舰娘D', '巡洋舰', 'SR', '皇家', '常规', '2024/3/1', 'Y')
        """)

        conn.commit()
        conn.close()

    def setUp(self):
        """测试初始化。"""
        self._repository = CodexGroupRepository()

    def testFindLockedSorting(self):
        """测试未解锁舰娘排序（ship_aid降序、codex_id降序）。"""
        ships = self._repository.findLocked()
        self.assertEqual(len(ships), 3)

        self.assertEqual(ships[0].ship_name, "舰娘C")
        self.assertEqual(ships[0].ship_aid, "2024/6/1")
        self.assertEqual(ships[0].codex_id, 3)

        self.assertEqual(ships[1].ship_name, "舰娘B")
        self.assertEqual(ships[1].ship_aid, "2024/6/1")
        self.assertEqual(ships[1].codex_id, 2)

        self.assertEqual(ships[2].ship_name, "舰娘A")
        self.assertEqual(ships[2].ship_aid, "2024/1/1")
        self.assertEqual(ships[2].codex_id, 1)


if __name__ == "__main__":
    unittest.main()
