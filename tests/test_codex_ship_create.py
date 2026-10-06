"""
舰娘新增功能单元测试。

测试覆盖：
- 图鉴ID自动生成：纯数字分组共用序列、前缀分组补零递增
- 业务逻辑层：新增舰娘三表写入、冗余字段注入、默认状态为未解锁
- 特殊分组：联动、μ兵装、小船、改造不写入科技点与科技属性
- 校验规则：图鉴ID重复、名称缺失、日期格式、科技点/科技属性取值
- 事务完整性：写入失败时整体回滚
- SQL预览：语句内容与特殊分组跳过
"""

import os
import shutil
import sqlite3
import tempfile
import unittest

from services.codex_ship_create_service import (
    CodexShipCreateService, ShipCreateDraft
)
from utils.constants import DEFAULT_DB_PATH
from utils.db_connection import DatabaseConnection
from utils.exceptions import DatabaseError, ValidationError


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
        ship_aid NUMERIC NOT NULL,
        ship_camp TEXT,
        ship_liking TEXT DEFAULT '陌生',
        oath_status TEXT DEFAULT 'N',
        codex_unlock TEXT DEFAULT 'N',
        date_edit NUMERIC
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
        date_edit DATE,
        FOREIGN KEY (codex_id) REFERENCES codex_group (codex_id)
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
        buff_unlock TEXT DEFAULT 'N',
        FOREIGN KEY (codex_id) REFERENCES codex_group (codex_id)
    )
    """
]


class TestCodexShipCreateService(unittest.TestCase):
    """舰娘新增服务测试类。"""

    def setUp(self):
        """测试初始化：每个用例使用独立的临时数据库。"""
        self._test_db_dir = tempfile.mkdtemp()
        self._test_db_path = os.path.join(self._test_db_dir, "test_ship_create.db")
        DatabaseConnection.setDbPath(self._test_db_path)
        self._createTestDatabase()
        self._service = CodexShipCreateService()

    def tearDown(self):
        """测试清理。"""
        DatabaseConnection.setDbPath(DEFAULT_DB_PATH)
        if os.path.exists(self._test_db_dir):
            shutil.rmtree(self._test_db_dir)

    def _createTestDatabase(self):
        """创建测试数据库并写入基线数据。"""
        conn = sqlite3.connect(self._test_db_path)
        cursor = conn.cursor()

        for sql in CREATE_SQL:
            cursor.execute(sql)

        baseline = [
            ('756', '安土', '战列巡洋舰', 'UR', '重樱群岛', '常规', '2026/08/08'),
            ('739', '小舰娘', '驱逐舰', 'SR', '白鹰联邦', '小船', '2026/01/01'),
            ('638', '兵装舰娘', '驱逐舰', 'SR', '白鹰联邦', 'μ兵装', '2026/01/02'),
            ('META065', '胜利·META', '航空母舰', 'SSR', 'META', 'META', '2026/08/01'),
            ('Plan047', '邓肯', '战列巡洋舰', 'PRY', '皇家海军', '方案', '2026/07/09'),
            ('Collab086', 'A2', '重型巡洋舰', 'SSR', 'NieRAutomata', '联动', '2026/07/16'),
            ('Refit109', '勇敢.改', '驱逐舰', 'SSR', '皇家海军', '改造', '2026/09/08'),
        ]

        for codex_id, name, ship_typ, rarity, camp, group, aid in baseline:
            cursor.execute(
                """
                INSERT INTO codex_group (codex_id, ship_name, ship_typ, ship_rarity,
                       ship_camp, ship_group, ship_aid, codex_unlock)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'N')
                """,
                (codex_id, name, ship_typ, rarity, camp, group, aid)
            )

        conn.commit()
        conn.close()

    def _buildDraft(self, **overrides) -> ShipCreateDraft:
        """构建默认草稿，支持字段覆盖。"""
        data = {
            "codex_id": "757",
            "ship_name": "测试舰娘",
            "ship_group": "常规",
            "ship_typ": "战列巡洋舰",
            "ship_rarity": "UR",
            "ship_star": 3,
            "ship_camp": "重樱群岛",
            "ship_aid": "2026/08/08",
            "ship_level": "未觉醒",
            "ship_liking": "陌生",
            "oath_status": "N",
            "date_edit": "2026-08-08 18:00:00",
            "tp_values": {"解锁": "26", "满星": "52", "Lv.120": "39"},
            "buff_text": {
                "解锁": "战巡/战列/航战 耐久+1",
                "Lv.120": "战巡/战列/航战 炮击+1",
            },
        }
        data.update(overrides)
        return ShipCreateDraft(**data)

    def _countRows(self, table: str, codex_id: str) -> int:
        """统计指定表中某图鉴ID的记录数。"""
        conn = sqlite3.connect(self._test_db_path)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                f"SELECT COUNT(*) AS c FROM {table} WHERE codex_id = ?", (codex_id,)
            ).fetchone()
            return row["c"]
        finally:
            conn.close()

    def _fetchOne(self, sql: str, params: tuple = ()) -> sqlite3.Row:
        """查询单条记录。"""
        conn = sqlite3.connect(self._test_db_path)
        conn.row_factory = sqlite3.Row
        try:
            return conn.execute(sql, params).fetchone()
        finally:
            conn.close()

    # ---------- 图鉴ID自动生成 ----------

    def testGetNextCodexIdForNumericGroups(self):
        """纯数字分组（常规、小船、μ兵装）共用同一套数字序列。"""
        self.assertEqual(self._service.getNextCodexId("常规"), "757")
        self.assertEqual(self._service.getNextCodexId("小船"), "757")
        self.assertEqual(self._service.getNextCodexId("μ兵装"), "757")

    def testGetNextCodexIdForPrefixedGroups(self):
        """前缀分组按三位补零递增。"""
        self.assertEqual(self._service.getNextCodexId("META"), "META066")
        self.assertEqual(self._service.getNextCodexId("方案"), "Plan048")
        self.assertEqual(self._service.getNextCodexId("联动"), "Collab087")
        self.assertEqual(self._service.getNextCodexId("改造"), "Refit110")

    # ---------- 正常新增 ----------

    def testCreateShipWritesThreeTables(self):
        """常规分组新增应写入图鉴、科技点、科技属性三张表。"""
        result = self._service.createShip(self._buildDraft())

        self.assertTrue(result.success)
        self.assertEqual(result.codex_id, "757")
        self.assertEqual(result.tp_count, 3)
        self.assertEqual(result.buff_count, 6)

        ship = self._fetchOne("SELECT * FROM codex_group WHERE codex_id = '757'")
        self.assertIsNotNone(ship)
        self.assertEqual(ship["ship_name"], "测试舰娘")
        self.assertEqual(ship["ship_group"], "常规")
        self.assertEqual(ship["ship_star"], 3)
        self.assertEqual(ship["codex_unlock"], "N")
        self.assertEqual(ship["date_edit"], "2026-08-08 18:00:00")

        self.assertEqual(self._countRows("codex_tp", "757"), 3)
        self.assertEqual(self._countRows("codex_buff", "757"), 6)

    def testCreateShipPropagatesRedundantFields(self):
        """科技点与科技属性的冗余字段应自动带出且默认未解锁。"""
        self._service.createShip(self._buildDraft())

        tp = self._fetchOne(
            "SELECT * FROM codex_tp WHERE codex_id = '757' AND unlock_cond = '解锁'"
        )
        self.assertEqual(tp["ship_name"], "测试舰娘")
        self.assertEqual(tp["ship_camp"], "重樱群岛")
        self.assertEqual(tp["ship_typ"], "战列巡洋舰")
        self.assertEqual(tp["tp_value"], 26)
        self.assertEqual(tp["tp_unlock"], "N")

        buff = self._fetchOne(
            "SELECT * FROM codex_buff WHERE codex_id = '757' AND boost_typ = '战巡' AND buff_cond = '解锁'"
        )
        self.assertEqual(buff["ship_name"], "测试舰娘")
        self.assertEqual(buff["ship_camp"], "重樱群岛")
        self.assertEqual(buff["buff_typ"], "耐久")
        self.assertEqual(buff["buff_value"], 1)
        self.assertEqual(buff["buff_unlock"], "N")

    def testCreateRefitShipSkipsTpAndBuff(self):
        """改造类型不写入科技点与科技属性，并使用改造字段形态。"""
        draft = self._buildDraft(
            codex_id="Refit110",
            ship_name="测试改",
            ship_group="改造",
            ship_typ="驱逐舰",
            ship_rarity="SSR",
            ship_star=0,
            ship_level="null",
            ship_liking="null",
            oath_status="null",
            tp_values={},
            buff_text={}
        )

        result = self._service.createShip(draft)

        self.assertTrue(result.success)
        self.assertEqual(result.tp_count, 0)
        self.assertEqual(result.buff_count, 0)
        self.assertEqual(self._countRows("codex_tp", "Refit110"), 0)
        self.assertEqual(self._countRows("codex_buff", "Refit110"), 0)

        ship = self._fetchOne("SELECT * FROM codex_group WHERE codex_id = 'Refit110'")
        self.assertEqual(ship["ship_level"], "null")
        self.assertEqual(ship["ship_star"], 0)
        self.assertEqual(ship["ship_liking"], "null")
        self.assertEqual(ship["oath_status"], "null")

    def testCreateCollabShipSkipsTpAndBuff(self):
        """联动类型不写入科技点与科技属性。"""
        draft = self._buildDraft(
            codex_id="Collab087",
            ship_name="2B",
            ship_group="联动",
            ship_camp="NieRAutomata",
            tp_values={},
            buff_text={}
        )

        result = self._service.createShip(draft)

        self.assertTrue(result.success)
        self.assertEqual(self._countRows("codex_tp", "Collab087"), 0)
        self.assertEqual(self._countRows("codex_buff", "Collab087"), 0)

    # ---------- 校验规则 ----------

    def testCreateShipRejectsDuplicateCodexId(self):
        """图鉴ID已存在时应拒绝新增。"""
        draft = self._buildDraft(codex_id="756")

        with self.assertRaises(ValidationError):
            self._service.createShip(draft)

    def testCreateShipRejectsEmptyName(self):
        """舰娘名称不能为空。"""
        with self.assertRaises(ValidationError):
            self._service.createShip(self._buildDraft(ship_name="   "))

    def testCreateShipRejectsInvalidShipAid(self):
        """实装日期格式必须为 yyyy/MM/dd。"""
        with self.assertRaises(ValidationError):
            self._service.createShip(self._buildDraft(ship_aid="2026-08-08"))

    def testCreateShipRejectsInvalidTpValue(self):
        """科技点数值必须为整数。"""
        draft = self._buildDraft(tp_values={"解锁": "abc", "满星": "52", "Lv.120": "39"})

        with self.assertRaises(ValidationError) as ctx:
            self._service.createShip(draft)

        self.assertIn("科技点（解锁）", str(ctx.exception))

    def testCreateShipRejectsIncompleteTpValues(self):
        """科技点三档需同时填写。"""
        draft = self._buildDraft(tp_values={"解锁": "26"})

        with self.assertRaises(ValidationError) as ctx:
            self._service.createShip(draft)

        self.assertIn("同时填写", str(ctx.exception))
        self.assertIn("满星", str(ctx.exception))

    def testCreateShipRejectsUnknownTpCond(self):
        """未知的科技点条件被拒绝。"""
        draft = self._buildDraft(tp_values={"觉醒": "26"})

        with self.assertRaises(ValidationError) as ctx:
            self._service.createShip(draft)

        self.assertIn("未知的科技点解锁条件", str(ctx.exception))

    def testCreateShipRejectsTpRowsForNoTpBuffGroup(self):
        """联动、μ兵装、小船、改造类型不得录入科技点。"""
        for ship_group in ("联动", "μ兵装", "小船", "改造"):
            draft = self._buildDraft(codex_id="9001", ship_group=ship_group)
            with self.assertRaises(ValidationError):
                self._service.createShip(draft)

    def testCreateShipRejectsBuffTextForNoTpBuffGroup(self):
        """联动、μ兵装、小船、改造类型不得录入科技属性文本。"""
        draft = self._buildDraft(
            codex_id="9002",
            ship_group="改造",
            tp_values={},
            buff_text={"解锁": "驱逐 耐久+1"}
        )

        with self.assertRaises(ValidationError) as ctx:
            self._service.createShip(draft)

        self.assertIn("不支持录入科技属性", str(ctx.exception))

    def testCreateShipRejectsInvalidBuffText(self):
        """科技属性文本格式错误时按行号报错。"""
        draft = self._buildDraft(buff_text={"解锁": "战巡 耐久"})

        with self.assertRaises(ValidationError) as ctx:
            self._service.createShip(draft)

        self.assertIn("第 1 行", str(ctx.exception))

    def testCreateShipRejectsUnknownBuffCond(self):
        """未知的科技属性条件被拒绝。"""
        draft = self._buildDraft(buff_text={"满星": "战巡 耐久+1"})

        with self.assertRaises(ValidationError) as ctx:
            self._service.createShip(draft)

        self.assertIn("未知的科技属性解锁条件", str(ctx.exception))

    def testCreateShipAllowsEmptyTpAndBuff(self):
        """科技点与科技属性全空时仍可新增（如无记录的舰娘）。"""
        draft = self._buildDraft(
            codex_id="757",
            ship_name="无科技数据舰",
            tp_values={},
            buff_text={}
        )

        result = self._service.createShip(draft)

        self.assertTrue(result.success)
        self.assertEqual(result.tp_count, 0)
        self.assertEqual(result.buff_count, 0)
        self.assertEqual(self._countRows("codex_group", "757"), 1)

    # ---------- 事务完整性 ----------

    def testCreateShipRollsBackOnFailure(self):
        """科技属性写入失败时，图鉴记录应整体回滚。"""
        conn = sqlite3.connect(self._test_db_path)
        conn.execute(
            """
            CREATE TRIGGER fail_buff_insert BEFORE INSERT ON codex_buff
            BEGIN
                SELECT RAISE(ABORT, 'boom');
            END
            """
        )
        conn.commit()
        conn.close()

        try:
            with self.assertRaises(DatabaseError):
                self._service.createShip(self._buildDraft())

            self.assertEqual(self._countRows("codex_group", "757"), 0)
            self.assertEqual(self._countRows("codex_tp", "757"), 0)
        finally:
            conn = sqlite3.connect(self._test_db_path)
            conn.execute("DROP TRIGGER fail_buff_insert")
            conn.commit()
            conn.close()

    # ---------- 文本解析与规范化 ----------

    def testParseBuffRows(self):
        """服务层文本解析返回展开后的明细行。"""
        rows = self._service.parseBuffRows({
            "解锁": "轻航/正航 反潜+1",
            "Lv.120": "轻航/正航 装填+1",
        })

        self.assertEqual(len(rows), 4)
        self.assertEqual(
            [(row["boost_typ"], row["buff_cond"], row["buff_typ"], row["buff_value"]) for row in rows],
            [
                ("轻航", "解锁", "反潜", 1),
                ("正航", "解锁", "反潜", 1),
                ("轻航", "Lv.120", "装填", 1),
                ("正航", "Lv.120", "装填", 1),
            ]
        )

    def testNormalizeDraftReturnsRows(self):
        """规范化草稿返回可直接写入的明细行。"""
        normalized = self._service.normalizeDraft(self._buildDraft())

        self.assertEqual(len(normalized["tp_rows"]), 3)
        self.assertEqual(
            [row["unlock_cond"] for row in normalized["tp_rows"]],
            ["解锁", "满星", "Lv.120"]
        )
        self.assertEqual([row["tp_value"] for row in normalized["tp_rows"]], [26, 52, 39])
        self.assertEqual(len(normalized["buff_rows"]), 6)

    def testGetGroupFieldDefaultsAndStar(self):
        """分组默认形态与默认星级。"""
        refit_defaults = self._service.getGroupFieldDefaults("改造")
        self.assertEqual(refit_defaults["ship_level"], "null")
        self.assertEqual(refit_defaults["ship_liking"], "null")
        self.assertEqual(refit_defaults["oath_status"], "null")

        normal_defaults = self._service.getGroupFieldDefaults("常规")
        self.assertEqual(normal_defaults["ship_level"], "未觉醒")

        self.assertEqual(self._service.getDefaultStar("常规", "SR"), 2)
        self.assertEqual(self._service.getDefaultStar("常规", "SSR"), 3)
        self.assertEqual(self._service.getDefaultStar("改造", "SSR"), 0)

    # ---------- SQL预览 ----------

    def testBuildPreviewSqlContainsThreeStatements(self):
        """常规分组的SQL预览应包含三张表的插入语句。"""
        sql = self._service.buildPreviewSql(self._buildDraft())

        self.assertIn("INSERT INTO codex_group", sql)
        self.assertIn("INSERT INTO codex_tp", sql)
        self.assertIn("INSERT INTO codex_buff", sql)
        self.assertIn("'757'", sql)
        self.assertIn("'测试舰娘'", sql)

    def testBuildPreviewSqlSkipsTpBuffForRefit(self):
        """改造类型的SQL预览不应包含科技点与科技属性语句。"""
        sql = self._service.buildPreviewSql(self._buildDraft(
            codex_id="Refit110",
            ship_group="改造",
            ship_level="null",
            ship_liking="null",
            oath_status="null",
            tp_values={},
            buff_text={}
        ))

        self.assertIn("INSERT INTO codex_group", sql)
        self.assertNotIn("INSERT INTO codex_tp", sql)
        self.assertNotIn("INSERT INTO codex_buff", sql)
        self.assertIn("'null'", sql)

    def testFindDuplicateShips(self):
        """同分组同名舰娘可被检出。"""
        duplicates = self._service.findDuplicateShips("安土", "常规")
        self.assertEqual(len(duplicates), 1)
        self.assertEqual(duplicates[0].codex_id, "756")

        self.assertEqual(self._service.findDuplicateShips("安土", "META"), [])
        self.assertEqual(self._service.findDuplicateShips("", "常规"), [])


if __name__ == "__main__":
    unittest.main()
