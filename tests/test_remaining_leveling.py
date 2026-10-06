"""
剩余练级数量统计单元测试。

测试覆盖：
- 数据访问层：getRemainingLevelingCount() 默认口径与可选追加排除口径
- 业务逻辑层：material_pending（需消耗心智单元）与 leveling_required（还需练级）两个口径
- 等级口径：五阶/Ⅱ 两口径都排除；一阶只排除练级口径；四阶只排除材料口径
- 边界条件：联动/改造分组、UNIV 阵营、字符串 null 等级、未解锁舰娘
- 视图层：统计卡片按“主值（括弧）”格式展示并带提示
"""

import os
import shutil
import sqlite3
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from repositories.codex_repository import CodexGroupRepository  # noqa: E402
from services.statistics_service import StatisticsService  # noqa: E402
from utils.codex_options import LEVELS_EXP_SUFFICIENT, LEVELS_NO_MATERIAL  # noqa: E402
from utils.constants import DEFAULT_DB_PATH  # noqa: E402
from utils.db_connection import DatabaseConnection  # noqa: E402

CREATE_GROUP_SQL = """
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
"""

CREATE_TP_SQL = """
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
"""

CREATE_BUFF_SQL = """
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
"""

# (codex_id, 等级, 分组, 阵营, 是否已解锁)
#
# 参与统计的等级样本（已通过分组与阵营过滤）：
#   未觉醒   : 1、2、3           → 3
#   一阶     : 4、5              → 2（另有 22 为 UNIV 阵营，被排除）
#   二阶     : 6                 → 1
#   四阶     : 7、8、9、10        → 4
#   五阶     : 11 ~ 15           → 5（两口径都排除）
#   Ⅱ        : 16 ~ 21           → 6（两口径都排除）
#
# 预期：
#   默认口径（原定义）      = 3 + 2 + 1 + 4      = 10
#   material_pending       = 10 - 四阶4          = 6
#   leveling_required      = 10 - 一阶2          = 8
FIXTURE = [
    ('1', '未觉醒', '常规', '白鹰联邦', 'Y'),
    ('2', '未觉醒', '常规', '白鹰联邦', 'Y'),
    ('3', '未觉醒', 'META', 'META', 'N'),          # 未解锁仍计入（现状口径）
    ('4', '认知觉醒一阶', '常规', '皇家海军', 'Y'),
    ('5', '认知觉醒一阶', '方案', '自由鸢尾', 'Y'),
    ('6', '认知觉醒二阶', '常规', '重樱群岛', 'Y'),
    ('7', '认知觉醒四阶', '常规', '铁血公国', 'Y'),
    ('8', '认知觉醒四阶', '常规', '铁血公国', 'Y'),
    ('9', '认知觉醒四阶', 'META', 'META', 'Y'),
    ('10', '认知觉醒四阶', '常规', '白鹰联邦', 'Y'),
    ('11', '认知觉醒五阶', '常规', '白鹰联邦', 'Y'),
    ('12', '认知觉醒五阶', '常规', '白鹰联邦', 'Y'),
    ('13', '认知觉醒五阶', 'META', 'META', 'Y'),
    ('14', '认知觉醒五阶', '方案', '皇家海军', 'Y'),
    ('15', '认知觉醒五阶', '常规', '重樱群岛', 'Y'),
    ('16', '认知觉醒Ⅱ', '常规', '白鹰联邦', 'Y'),
    ('17', '认知觉醒Ⅱ', '常规', '白鹰联邦', 'Y'),
    ('18', '认知觉醒Ⅱ', 'META', 'META', 'Y'),
    ('19', '认知觉醒Ⅱ', '方案', '皇家海军', 'Y'),
    ('20', '认知觉醒Ⅱ', '常规', '重樱群岛', 'Y'),
    ('21', '认知觉醒Ⅱ', '常规', '铁血公国', 'Y'),
    ('22', '认知觉醒一阶', '常规', 'UNIV', 'Y'),    # 阵营 UNIV → 不参与统计
    ('23', '未觉醒', '联动', 'NieRAutomata', 'Y'),  # 联动分组 → 不参与统计
    ('24', 'null', '改造', '皇家海军', 'Y'),        # 改造分组 → 不参与统计
]

EXPECTED_DEFAULT = 10
EXPECTED_MATERIAL_PENDING = 6
EXPECTED_LEVELING_REQUIRED = 8


class TestRemainingLevelingStatistics(unittest.TestCase):
    """剩余练级数量统计测试类。"""

    def setUp(self):
        """测试初始化：每个用例使用独立的临时数据库。"""
        self._test_db_dir = tempfile.mkdtemp()
        self._test_db_path = os.path.join(self._test_db_dir, "test_leveling.db")
        DatabaseConnection.setDbPath(self._test_db_path)
        self._createTestDatabase()

        self._repository = CodexGroupRepository()
        self._service = StatisticsService()

    def tearDown(self):
        """测试清理。"""
        DatabaseConnection.setDbPath(DEFAULT_DB_PATH)
        if os.path.exists(self._test_db_dir):
            shutil.rmtree(self._test_db_dir)

    def _createTestDatabase(self):
        """创建测试数据库并写入等级样本。"""
        conn = sqlite3.connect(self._test_db_path)
        cursor = conn.cursor()
        cursor.execute(CREATE_GROUP_SQL)
        cursor.execute(CREATE_TP_SQL)
        cursor.execute(CREATE_BUFF_SQL)

        for codex_id, ship_level, ship_group, ship_camp, codex_unlock in FIXTURE:
            cursor.execute(
                """
                INSERT INTO codex_group (codex_id, ship_name, ship_level, ship_star, ship_rarity,
                       ship_typ, ship_group, ship_aid, ship_camp, codex_unlock)
                VALUES (?, ?, ?, 3, 'SR', '驱逐舰', ?, '2026/01/01', ?, ?)
                """,
                (codex_id, f"测试舰{codex_id}", ship_level, ship_group, ship_camp, codex_unlock)
            )

        conn.commit()
        conn.close()

    def _levelRowCount(self, ship_level: str) -> int:
        """统计样本中指定等级的总行数（不应用分组/阵营过滤）。"""
        conn = sqlite3.connect(self._test_db_path)
        try:
            return conn.execute(
                "SELECT COUNT(*) FROM codex_group WHERE ship_level = ?", (ship_level,)
            ).fetchone()[0]
        finally:
            conn.close()

    def _participatingCount(self, ship_level: str) -> int:
        """统计参与口径计算的指定等级行数（应用分组与阵营过滤）。"""
        conn = sqlite3.connect(self._test_db_path)
        try:
            return conn.execute(
                """
                SELECT COUNT(*) FROM codex_group
                WHERE ship_level = ?
                  AND ship_group IN ('常规', 'META', '方案')
                  AND ship_camp != 'UNIV'
                """,
                (ship_level,)
            ).fetchone()[0]
        finally:
            conn.close()

    # ---------- 数据访问层 ----------

    def testRepositoryDefaultCount(self):
        """默认口径：仅排除已满120级的档位（五阶 / Ⅱ）。"""
        self.assertEqual(self._repository.getRemainingLevelingCount(), EXPECTED_DEFAULT)

    def testFullTechLevelsExcludedFromDefault(self):
        """五阶与Ⅱ都不计入默认口径，而未满120的各档位都计入。"""
        participating_total = sum(
            self._participatingCount(level)
            for level in ('未觉醒', '认知觉醒一阶', '认知觉醒二阶', '认知觉醒三阶', '认知觉醒四阶')
        )

        self.assertEqual(self._repository.getRemainingLevelingCount(), participating_total)
        self.assertGreater(self._participatingCount('认知觉醒五阶'), 0)
        self.assertGreater(self._participatingCount('认知觉醒Ⅱ'), 0)

    def testRepositoryExtraExclusions(self):
        """可选参数可追加排除档位，且默认调用不受影响。"""
        self.assertEqual(
            self._repository.getRemainingLevelingCount(LEVELS_NO_MATERIAL),
            EXPECTED_MATERIAL_PENDING
        )
        self.assertEqual(
            self._repository.getRemainingLevelingCount(LEVELS_EXP_SUFFICIENT),
            EXPECTED_LEVELING_REQUIRED
        )
        self.assertEqual(self._repository.getRemainingLevelingCount(()), EXPECTED_DEFAULT)
        self.assertEqual(self._repository.getRemainingLevelingCount(), EXPECTED_DEFAULT)

    def testSpecialGroupsAndUnivExcluded(self):
        """联动/改造分组与 UNIV 阵营不参与任何口径。"""
        self.assertEqual(self._levelRowCount('认知觉醒一阶'), 3)
        self.assertEqual(self._participatingCount('认知觉醒一阶'), 2)
        self.assertEqual(self._repository.getRemainingLevelingCount(), EXPECTED_DEFAULT)
        self.assertEqual(self._service.getMaterialPendingCount(), EXPECTED_MATERIAL_PENDING)
        self.assertEqual(self._service.getLevelingRequiredCount(), EXPECTED_LEVELING_REQUIRED)

    # ---------- 业务逻辑层 ----------

    def testMaterialPendingCount(self):
        """主值口径：未满120级且仍需消耗心智单元（排除四阶）。"""
        default = self._repository.getRemainingLevelingCount()

        self.assertEqual(self._service.getMaterialPendingCount(), EXPECTED_MATERIAL_PENDING)
        self.assertEqual(
            default - self._participatingCount('认知觉醒四阶'),
            self._service.getMaterialPendingCount()
        )

    def testLevelingRequiredCount(self):
        """括弧口径：未满120级且还需要练级（排除一阶）。"""
        default = self._repository.getRemainingLevelingCount()

        self.assertEqual(self._service.getLevelingRequiredCount(), EXPECTED_LEVELING_REQUIRED)
        self.assertEqual(
            default - self._participatingCount('认知觉醒一阶'),
            self._service.getLevelingRequiredCount()
        )

    def testPhaseFourOnlyInLevelingRequired(self):
        """四阶属于“还需练级”，但不属于“需消耗心智单元”。"""
        self.assertEqual(self._participatingCount('认知觉醒四阶'), 4)
        self.assertNotIn('认知觉醒四阶', LEVELS_EXP_SUFFICIENT)
        self.assertIn('认知觉醒四阶', LEVELS_NO_MATERIAL)

    def testPhaseOneOnlyInMaterialPending(self):
        """一阶属于“需消耗心智单元”，但不属于“还需练级”。"""
        self.assertEqual(self._participatingCount('认知觉醒一阶'), 2)
        self.assertIn('认知觉醒一阶', LEVELS_EXP_SUFFICIENT)
        self.assertNotIn('认知觉醒一阶', LEVELS_NO_MATERIAL)

    def testTwoCriteriaDifferenceEqualsSwappedLevels(self):
        """两口径差值 = 四阶数 - 一阶数（相互交换的两个档位）。"""
        self.assertEqual(
            self._service.getLevelingRequiredCount() - self._service.getMaterialPendingCount(),
            self._participatingCount('认知觉醒四阶') - self._participatingCount('认知觉醒一阶')
        )

    def testGetAllStatisticsKeys(self):
        """聚合统计包含兼容键与两个展示口径键，且均为整数。"""
        stats = self._service.getAllStatistics()

        self.assertEqual(stats['remaining_leveling'], EXPECTED_DEFAULT)
        self.assertEqual(stats['material_pending'], EXPECTED_MATERIAL_PENDING)
        self.assertEqual(stats['leveling_required'], EXPECTED_LEVELING_REQUIRED)
        for key in ('remaining_leveling', 'material_pending', 'leveling_required'):
            self.assertIsInstance(stats[key], int)

    def testUnlockedShipsAreCounted(self):
        """现状口径：未解锁的舰娘同样计入（与心智计算的 codex_unlock='Y' 不同）。"""
        conn = sqlite3.connect(self._test_db_path)
        conn.execute("UPDATE codex_group SET codex_unlock = 'Y' WHERE codex_id = '3'")
        conn.commit()
        conn.close()

        self.assertEqual(self._repository.getRemainingLevelingCount(), EXPECTED_DEFAULT)
        self.assertEqual(self._service.getMaterialPendingCount(), EXPECTED_MATERIAL_PENDING)


class _StubStatisticsService:
    """统计服务桩：返回固定的口径数值。"""

    def getAllStatistics(self):
        """返回预设统计数据。"""
        return {
            'unlock': {
                'total': 5, 'total_excluding_collab': 4,
                'unlocked': 3, 'unlocked_excluding_collab': 2,
                'locked': 2, 'locked_excluding_collab': 2,
                'unlock_rate': 50.0
            },
            'oath': {'total': 5, 'oathed': 1, 'oath_rate': 20.0},
            'tp': {'total_tp': 100, 'unlocked_tp': 40, 'completion_rate': 40.0},
            'bulin': {'universal_bulin': 1, 'trial_bulin_mkii': 2, 'specialized_bulin_mkiii': 3},
            'remaining_leveling': EXPECTED_DEFAULT,
            'material_pending': EXPECTED_MATERIAL_PENDING,
            'leveling_required': EXPECTED_LEVELING_REQUIRED
        }


class _StubUserService:
    """用户服务桩。"""

    def getDutyDaysText(self):
        """返回固定执勤天数文本。"""
        return '100'


class TestRemainingLevelingCard(unittest.TestCase):
    """剩余练级数量卡片展示测试类。"""

    @classmethod
    def setUpClass(cls):
        """初始化 Qt 应用。"""
        from PyQt5.QtWidgets import QApplication
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        """测试初始化。"""
        from views.widgets.statistics_panel import StatisticsPanel

        self._panel = StatisticsPanel(
            statistics_service=_StubStatisticsService(),
            user_service=_StubUserService()
        )

    def tearDown(self):
        """测试清理。"""
        self._panel.deleteLater()

    def testCardShowsMainAndParenthesizedValues(self):
        """卡片按“主值（括弧）”格式展示两个口径。"""
        self.assertEqual(
            self._panel._remainingLevelingCard.value(),
            f'{EXPECTED_MATERIAL_PENDING}（{EXPECTED_LEVELING_REQUIRED}）'
        )

    def testCardKeepsTitleAndTooltip(self):
        """卡片标题不变，并带有两个口径的提示。"""
        card = self._panel._remainingLevelingCard
        tooltip = card.toolTip()

        self.assertEqual(card.title(), '剩余练级数量')
        self.assertIn('心智单元', tooltip)
        self.assertIn('练级', tooltip)
        self.assertIn('四阶', tooltip)
        self.assertIn('一阶', tooltip)

    def testOtherCardsUnaffected(self):
        """其他卡片展示格式保持原样。"""
        self.assertEqual(self._panel._totalTpCard.value(), '100')
        self.assertEqual(self._panel._unlockedTpCard.value(), '40')
        self.assertEqual(self._panel._tpRateCard.value(), '40.0%')
        self.assertEqual(self._panel._totalCard.value(), '4（5）')


if __name__ == "__main__":
    unittest.main()
