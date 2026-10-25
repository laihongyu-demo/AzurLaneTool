"""舰队位置字段单元测试。

覆盖：舰种 → 舰队位置映射的完整性、旧库补列与回填（含幂等与人工值保护）、
仓储层读写往返、新增舰娘按舰种派生位置，以及一次性舰种修正脚本的可重复执行性。
"""

import importlib.util
import os
import shutil
import sqlite3
import tempfile
import unittest

from models.codex_model import CodexGroupModel
from repositories.codex_repository import CodexGroupRepository
from services.codex_ship_create_service import CodexShipCreateService, ShipCreateDraft
from utils import codex_options as options
from utils.constants import DEFAULT_DB_PATH
from utils.db_connection import DatabaseConnection
from utils.db_schema import ensureCodexGroupSchema, suspendCodexGroupModtimeTrigger
from utils.exceptions import ValidationError

# 旧库结构：没有 fleet_position 列
LEGACY_GROUP_SCHEMA = """
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
"""

# 新库结构：已含 fleet_position 列
NEW_GROUP_SCHEMA = """
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
    date_edit DATE,
    fleet_position TEXT
)
"""

# 真实库中存在的触发器：任何 UPDATE 都会把 date_edit 改写为当前时间
MODTIME_TRIGGER_SQL = """
CREATE TRIGGER update_codex_group_modtime
AFTER UPDATE ON codex_group
FOR EACH ROW
BEGIN
    UPDATE codex_group
    SET date_edit = datetime('now','localtime')
    WHERE codex_id = OLD.codex_id;
END
"""


def _loadFixTool():
    """按文件路径加载 ``tools/fix_codex_ship_typ.py``（tools 不是包）。"""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, "tools", "fix_codex_ship_typ.py")
    spec = importlib.util.spec_from_file_location("fix_codex_ship_typ_for_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FleetPositionOptionTest(unittest.TestCase):
    """舰种 → 位置映射的完整性。"""

    def testEveryShipTypHasPosition(self):
        """枚举中的每个舰种都必须登记位置。"""
        for ship_typ in options.SHIP_TYPS:
            self.assertIn(ship_typ, options.SHIP_TYP_FLEET_POSITION)

    def testPositionValuesAreDeclared(self):
        """映射结果只能是三种声明过的位置。"""
        for ship_typ, position in options.SHIP_TYP_FLEET_POSITION.items():
            self.assertIn(position, options.FLEET_POSITIONS, ship_typ)

    def testSpecificHullPositions(self):
        """特殊舰种的口径（2026-10-25 审核结论）。"""
        expected = {
            "浅水重炮舰": options.FLEET_POSITION_MAIN,
            "维修舰": options.FLEET_POSITION_MAIN,
            "弹药运输舰": options.FLEET_POSITION_VANGUARD,
            "潜水空母": options.FLEET_POSITION_SUBMARINE,
            "风帆V": options.FLEET_POSITION_VANGUARD,
            "风帆M": options.FLEET_POSITION_MAIN,
            "风帆S": options.FLEET_POSITION_SUBMARINE,
        }
        for ship_typ, position in expected.items():
            self.assertEqual(options.getFleetPosition(ship_typ), position, ship_typ)

    def testUnknownShipTypReturnsNone(self):
        """未登记舰种返回 None，不猜位置。"""
        self.assertIsNone(options.getFleetPosition("轻型航母舰"))
        self.assertIsNone(options.getFleetPosition(""))
        self.assertIsNone(options.getFleetPosition(None))


class FleetPositionSchemaTest(unittest.TestCase):
    """旧库补列与回填。"""

    def setUp(self):
        """每个用例使用独立临时库。"""
        self._temp_dir = tempfile.mkdtemp()
        self._db_path = os.path.join(self._temp_dir, "test_fleet_position.db")

    def tearDown(self):
        """清理临时库。"""
        if os.path.exists(self._temp_dir):
            shutil.rmtree(self._temp_dir)

    def _createDb(self, schema: str):
        """按给定结构建库。"""
        conn = sqlite3.connect(self._db_path)
        conn.executescript(schema)
        conn.commit()
        conn.close()

    def _columns(self):
        """读取 codex_group 列名集合。"""
        conn = sqlite3.connect(self._db_path)
        try:
            return {row[1] for row in conn.execute("PRAGMA table_info(codex_group)")}
        finally:
            conn.close()

    def _fetchAll(self):
        """读取 (codex_id, ship_typ, fleet_position)。"""
        conn = sqlite3.connect(self._db_path)
        try:
            return conn.execute(
                "SELECT codex_id, ship_typ, fleet_position FROM codex_group ORDER BY codex_id"
            ).fetchall()
        finally:
            conn.close()

    def testAddsColumnAndBackfills(self):
        """旧库补列后按舰种回填，全部行都有位置。"""
        self._createDb(LEGACY_GROUP_SCHEMA)
        conn = sqlite3.connect(self._db_path)
        conn.executemany(
            "INSERT INTO codex_group (codex_id, ship_name, ship_typ) VALUES (?, ?, ?)",
            [
                ("1", "拉菲", "驱逐舰"),
                ("2", "俾斯麦", "战列舰"),
                ("3", "伊13", "潜水空母"),
                ("4", "皇家财富号", "风帆S"),
            ],
        )
        conn.commit()
        conn.close()

        self.assertNotIn("fleet_position", self._columns())
        ensureCodexGroupSchema(self._db_path)
        self.assertIn("fleet_position", self._columns())

        self.assertEqual(
            self._fetchAll(),
            [
                ("1", "驱逐舰", options.FLEET_POSITION_VANGUARD),
                ("2", "战列舰", options.FLEET_POSITION_MAIN),
                ("3", "潜水空母", options.FLEET_POSITION_SUBMARINE),
                ("4", "风帆S", options.FLEET_POSITION_SUBMARINE),
            ],
        )

    def testIdempotentAndKeepsExistingValue(self):
        """重复执行不报错、不覆盖已有位置；未登记舰种保持为空。"""
        self._createDb(NEW_GROUP_SCHEMA)
        conn = sqlite3.connect(self._db_path)
        conn.executemany(
            "INSERT INTO codex_group (codex_id, ship_name, ship_typ, fleet_position)"
            " VALUES (?, ?, ?, ?)",
            [
                ("1", "拉菲", "驱逐舰", options.FLEET_POSITION_VANGUARD),
                ("2", "未知舰", "轻型航母舰", ""),
            ],
        )
        conn.commit()
        conn.close()

        ensureCodexGroupSchema(self._db_path)
        ensureCodexGroupSchema(self._db_path)

        rows = dict((row[0], row[2]) for row in self._fetchAll())
        self.assertEqual(rows["1"], options.FLEET_POSITION_VANGUARD)
        # 未登记舰种不被猜测，位置保持为空，等待舰种修正
        self.assertEqual(rows["2"], "")

    def testBackfillKeepsDateEditAndRebuildsTrigger(self):
        """回填不触发 date_edit 触发器，且触发器事后原样重建。"""
        self._createDb(LEGACY_GROUP_SCHEMA)
        conn = sqlite3.connect(self._db_path)
        conn.executescript(MODTIME_TRIGGER_SQL)
        conn.execute(
            "INSERT INTO codex_group (codex_id, ship_name, ship_typ, date_edit)"
            " VALUES (?, ?, ?, ?)",
            ("1", "拉菲", "驱逐舰", "2025-01-02 03:04:05"),
        )
        conn.commit()
        conn.close()

        ensureCodexGroupSchema(self._db_path)

        conn = sqlite3.connect(self._db_path)
        try:
            position, date_edit = conn.execute(
                "SELECT fleet_position, date_edit FROM codex_group WHERE codex_id = '1'"
            ).fetchone()
            # 触发器已重建：普通 UPDATE 仍会刷新 date_edit
            conn.execute("UPDATE codex_group SET ship_name = ship_name WHERE codex_id = '1'")
            refreshed = conn.execute(
                "SELECT date_edit FROM codex_group WHERE codex_id = '1'"
            ).fetchone()[0]
            conn.rollback()
        finally:
            conn.close()

        self.assertEqual(position, options.FLEET_POSITION_VANGUARD)
        # 回填前的历史编辑时间必须原样保留
        self.assertEqual(date_edit, "2025-01-02 03:04:05")
        # 触发器重建后行为与原来一致
        self.assertNotEqual(refreshed, "2025-01-02 03:04:05")

    def testSkipsWhenTableMissing(self):
        """表不存在时不建表、不抛错。"""
        conn = sqlite3.connect(self._db_path)
        conn.execute("CREATE TABLE unrelated (id INTEGER)")
        conn.commit()
        conn.close()

        ensureCodexGroupSchema(self._db_path)

        conn = sqlite3.connect(self._db_path)
        try:
            names = {row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            conn.close()
        self.assertNotIn("codex_group", names)
        self.assertIn("unrelated", names)


class FleetPositionRepositoryTest(unittest.TestCase):
    """仓储层读写往返。"""

    def setUp(self):
        """每个用例使用独立临时库。"""
        self._temp_dir = tempfile.mkdtemp()
        self._db_path = os.path.join(self._temp_dir, "test_fleet_repo.db")
        self._original_path = DatabaseConnection.getDbPath()
        conn = sqlite3.connect(self._db_path)
        conn.executescript(NEW_GROUP_SCHEMA)
        conn.commit()
        conn.close()
        DatabaseConnection.setDbPath(self._db_path)
        self._repository = CodexGroupRepository(self._db_path)

    def tearDown(self):
        """恢复数据库路径并清理。"""
        DatabaseConnection.setDbPath(self._original_path)
        if os.path.exists(self._temp_dir):
            shutil.rmtree(self._temp_dir)

    def testInsertAndFindRoundTrip(self):
        """新增与查询都带上 fleet_position。"""
        record = CodexGroupModel(
            codex_id="760",
            ship_name="铁角号",
            ship_level="未觉醒",
            ship_star=3,
            ship_rarity="SR",
            ship_typ="风帆S",
            ship_group="常规",
            ship_aid="2026/10/22",
            ship_camp="飓风之海",
            ship_liking="陌生",
            oath_status="N",
            codex_unlock="N",
            date_edit=None,
            fleet_position=options.FLEET_POSITION_SUBMARINE,
        )
        self._repository.insert(record)

        found = self._repository.findById("760")
        self.assertIsNotNone(found)
        self.assertEqual(found.fleet_position, options.FLEET_POSITION_SUBMARINE)

        found.fleet_position = options.FLEET_POSITION_MAIN
        self.assertTrue(self._repository.update(found))
        self.assertEqual(
            self._repository.findById("760").fleet_position,
            options.FLEET_POSITION_MAIN,
        )


class FleetPositionCreateServiceTest(unittest.TestCase):
    """新增舰娘按舰种派生位置。"""

    def setUp(self):
        """每个用例使用独立临时库。"""
        self._temp_dir = tempfile.mkdtemp()
        self._db_path = os.path.join(self._temp_dir, "test_fleet_create.db")
        self._original_path = DatabaseConnection.getDbPath()
        conn = sqlite3.connect(self._db_path)
        conn.executescript(NEW_GROUP_SCHEMA)
        conn.commit()
        conn.close()
        DatabaseConnection.setDbPath(self._db_path)
        self._service = CodexShipCreateService(CodexGroupRepository(self._db_path))

    def tearDown(self):
        """恢复数据库路径并清理。"""
        DatabaseConnection.setDbPath(self._original_path)
        if os.path.exists(self._temp_dir):
            shutil.rmtree(self._temp_dir)

    def _draft(self, ship_typ: str) -> ShipCreateDraft:
        """构造一份最小草稿。"""
        return ShipCreateDraft(
            codex_id="9001",
            ship_name="测试舰",
            ship_group="常规",
            ship_typ=ship_typ,
            ship_rarity="SSR",
            ship_star=3,
            ship_camp="飓风之海",
            ship_aid="2026/10/25",
        )

    def testDerivesPositionFromShipTyp(self):
        """位置由舰种派生，不依赖草稿输入。"""
        normalized = self._service.normalizeDraft(self._draft("风帆M"))
        self.assertEqual(normalized["fleet_position"], options.FLEET_POSITION_MAIN)

        normalized = self._service.normalizeDraft(self._draft("潜水空母"))
        self.assertEqual(normalized["fleet_position"], options.FLEET_POSITION_SUBMARINE)

    def testRejectsUnknownShipTyp(self):
        """错字 / 未登记舰种在录入阶段就被拒绝。"""
        with self.assertRaises(ValidationError):
            self._service.normalizeDraft(self._draft("轻型航母舰"))


class ShipTypFixToolTest(unittest.TestCase):
    """一次性舰种修正脚本的可重复执行性。"""

    def setUp(self):
        """每个用例使用独立临时库。"""
        self._temp_dir = tempfile.mkdtemp()
        self._db_path = os.path.join(self._temp_dir, "test_ship_typ_fix.db")
        conn = sqlite3.connect(self._db_path)
        conn.executescript(NEW_GROUP_SCHEMA)
        conn.executescript(MODTIME_TRIGGER_SQL)
        conn.executemany(
            "INSERT INTO codex_group (codex_id, ship_name, ship_typ, date_edit)"
            " VALUES (?, ?, ?, ?)",
            [
                ("Collab043", "科洛蒂娅·巴兰茨", "轻型航母舰", "2025-03-01 10:00:00"),
                ("Refit009", "博格.改", "轻型巡洋舰", "2025-04-02 11:00:00"),
                ("Refit062", "竞技神.改", "驱逐舰", "2025-05-03 12:00:00"),
                ("Refit109", "勇敢.改", "驱逐舰", "2025-06-04 13:00:00"),
            ],
        )
        conn.commit()
        conn.close()
        self._tool = _loadFixTool()

    def tearDown(self):
        """清理临时库。"""
        if os.path.exists(self._temp_dir):
            shutil.rmtree(self._temp_dir)

    def _fetch(self, codex_id):
        """读取单行 (ship_typ, fleet_position)。"""
        conn = sqlite3.connect(self._db_path)
        try:
            return conn.execute(
                "SELECT ship_typ, fleet_position FROM codex_group WHERE codex_id = ?",
                (codex_id,),
            ).fetchone()
        finally:
            conn.close()

    def testApplyFixesAndRecomputePosition(self):
        """错字值与派生舰舰种被修正，位置随之刷新；重复执行不再命中。"""
        ensureCodexGroupSchema(self._db_path)
        conn = sqlite3.connect(self._db_path)
        conn.isolation_level = None
        try:
            conn.execute("BEGIN")
            items = self._tool.collectFixes(conn)
            self.assertEqual(len(items), 3)
            with suspendCodexGroupModtimeTrigger(conn):
                self.assertEqual(self._tool.applyFixes(conn, items), 3)
            conn.execute("COMMIT")
            # 第二次执行：已修正的行不再命中
            conn.execute("BEGIN")
            self.assertEqual(self._tool.collectFixes(conn), [])
            conn.execute("ROLLBACK")
        finally:
            conn.close()

        self.assertEqual(
            self._fetch("Collab043"),
            ("轻型航空母舰", options.FLEET_POSITION_MAIN),
        )
        self.assertEqual(
            self._fetch("Refit009"),
            ("轻型航空母舰", options.FLEET_POSITION_MAIN),
        )
        self.assertEqual(
            self._fetch("Refit062"),
            ("轻型航空母舰", options.FLEET_POSITION_MAIN),
        )
        # 无关记录保持原样（补列回填后仍是原型舰种对应的位置）
        self.assertEqual(
            self._fetch("Refit109"),
            ("驱逐舰", options.FLEET_POSITION_VANGUARD),
        )
        # 批量修正不刷新历史编辑时间
        self.assertEqual(self._fetchDateEdit("Refit009"), "2025-04-02 11:00:00")
        self.assertEqual(self._fetchDateEdit("Collab043"), "2025-03-01 10:00:00")

    def _fetchDateEdit(self, codex_id):
        """读取单行 date_edit。"""
        conn = sqlite3.connect(self._db_path)
        try:
            return conn.execute(
                "SELECT date_edit FROM codex_group WHERE codex_id = ?", (codex_id,)
            ).fetchone()[0]
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
