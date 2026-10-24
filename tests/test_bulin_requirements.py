"""
布里（升星材料）需求脚本单元测试。

覆盖 issue 复核确认的口径：

- 升星规则：不论稀有度均可升星 3 次，材料消耗 1 + 1 + 2（最后一次为 2 份）
  → 剩余需求 = 剩余升星次数 + 1
- 满星阈值：N=4、R/SR=5、SSR/UR=6
- 统计范围：已解锁的常规舰娘；排除 改造 / 方案 / META / 联动 / 小船 / μ兵装 与 UNIV（三艘布里）
- 布里种类：N/R/SR→泛用型布里、SSR→试作型布里MKII、UR→特装型布里MKIII；
  方案舰（PRY/DR）不消耗布里
- 稀有度映射为单一来源（utils.codex_options），与 findLimitBreakable / 界限突破服务一致
"""

import os
import shutil
import sqlite3
import tempfile
import unittest

from repositories.codex_repository import CodexGroupRepository
from services.limit_break_service import LimitBreakService
from services.statistics_service import StatisticsService
from utils import codex_options as options
from utils.constants import DEFAULT_DB_PATH
from utils.db_connection import DatabaseConnection

CREATE_SQL = """
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

# 界限突破相关用例需要 TP 表（服务会读取「满星」科技点并置为已解锁）
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

# (codex_id, 名称, 稀有度, 星级, 分组, 阵营, 解锁)
SHIP_FIXTURE = [
    # 范式：各稀有度的初始星（升满均需 4 份）
    ('1', 'N初始', 'N', 1, '常规', '白鹰联邦', 'Y'),
    ('2', 'R初始', 'R', 2, '常规', '白鹰联邦', 'Y'),
    ('3', 'SR初始', 'SR', 2, '常规', '白鹰联邦', 'Y'),
    ('4', 'SSR初始', 'SSR', 3, '常规', '白鹰联邦', 'Y'),
    ('5', 'UR初始', 'UR', 3, '常规', '白鹰联邦', 'Y'),
    # 满星：需求 0
    ('6', 'N满星', 'N', 4, '常规', '白鹰联邦', 'Y'),
    ('7', 'SSR满星', 'SSR', 6, '常规', '白鹰联邦', 'Y'),
    # 中间档位：SSR 4★=3、SSR 5★=2
    ('8', 'SSR四星', 'SSR', 4, '常规', '白鹰联邦', 'Y'),
    ('9', 'SSR五星', 'SSR', 5, '常规', '白鹰联邦', 'Y'),
    # 应被排除
    ('10', '未解锁SSR', 'SSR', 3, '常规', '白鹰联邦', 'N'),
    ('11', '方案PRY', 'PRY', 3, '方案', '皇家海军', 'Y'),
    ('12', '方案DR', 'DR', 3, '方案', '铁血公国', 'Y'),
    ('13', 'META舰', 'SSR', 3, 'META', 'META', 'Y'),
    ('14', '改造舰', 'SSR', 3, '改造', '白鹰联邦', 'Y'),
    ('15', '联动舰', 'SSR', 3, '联动', '哔哩哔哩', 'Y'),
    ('16', '小船舰', 'SR', 2, '小船', '白鹰联邦', 'Y'),
    ('17', 'μ兵装舰', 'SSR', 3, 'μ兵装', '重樱群岛', 'Y'),
    ('18', '泛用型布里', 'SR', 5, '常规', 'UNIV', 'Y'),
    ('19', '试作型布里MKII', 'SSR', 6, '常规', 'UNIV', 'Y'),
    ('20', '特装型布里MKIII', 'UR', 6, '常规', 'UNIV', 'Y'),
    # 异常数据：星级为空 → 不计入
    ('21', '空星级SSR', 'SSR', None, '常规', '白鹰联邦', 'Y'),
]

# 期望：各稀有度初始星升满均 4 份；SSR 4★=3、5★=2；其它 0
EXPECTED_UNIVERSAL = 4 + 4          # N初始 + R初始（SR初始 3 份归泛用型）
EXPECTED_TRIAL = 0
EXPECTED_SPECIALIZED = 0


class BulinRequirementTestCase(unittest.TestCase):
    """布里需求脚本测试基类。"""

    def setUp(self):
        """创建临时数据库。"""
        self._temp_dir = tempfile.mkdtemp()
        self._db_path = os.path.join(self._temp_dir, 'bulin.db')
        DatabaseConnection.setDbPath(self._db_path)
        self._createDatabase()
        self._repository = CodexGroupRepository()

    def tearDown(self):
        """清理临时目录。"""
        DatabaseConnection.setDbPath(DEFAULT_DB_PATH)
        shutil.rmtree(self._temp_dir, ignore_errors=True)

    def _createDatabase(self):
        """建立表结构并写入夹具数据。"""
        conn = sqlite3.connect(self._db_path)
        cursor = conn.cursor()
        cursor.execute(CREATE_SQL)
        cursor.execute(CREATE_TP_SQL)
        conn.commit()
        conn.close()
        self._resetFixture()

    def _resetFixture(self):
        """清空并重新写入夹具数据（供需要多轮迭代的用例复位）。"""
        conn = sqlite3.connect(self._db_path)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM codex_group')
        for codex_id, name, rarity, star, group, camp, unlock in SHIP_FIXTURE:
            cursor.execute(
                'INSERT INTO codex_group (codex_id, ship_name, ship_rarity, ship_star,'
                ' ship_group, ship_camp, codex_unlock, ship_aid)'
                " VALUES (?, ?, ?, ?, ?, ?, ?, '2026/01/01')",
                (codex_id, name, rarity, star, group, camp, unlock)
            )
        conn.commit()
        conn.close()

    def _onlyKeep(self, codex_id: str) -> None:
        """重置夹具后只保留指定舰娘。"""
        self._resetFixture()
        conn = sqlite3.connect(self._db_path)
        conn.execute('DELETE FROM codex_group WHERE codex_id != ?', (codex_id,))
        conn.commit()
        conn.close()

    def _requirements(self) -> dict:
        """调用服务取三类布里需求。"""
        return StatisticsService().getBulinRequirements()


class TestRequirementFormula(BulinRequirementTestCase):
    """升星材料公式测试类。"""

    def testTotalMatchesThreeStarUps(self):
        """各稀有度初始星升满均需 4 份（1+1+2），按布里种类正确归类。"""
        result = self._requirements()

        # 泛用型：N初始(4) + R初始(4) + SR初始(4) = 12；SSR 初始(4)+四星(3)+五星(2)=9 归试作型
        self.assertEqual(result['universal_bulin'], 4 + 4 + 4)
        self.assertEqual(result['trial_bulin_mkii'], 4 + 3 + 2)
        self.assertEqual(result['specialized_bulin_mkiii'], 4)

    def testFullStarShipsNeedNothing(self):
        """满星舰娘需求为 0。"""
        self._resetFixture()
        conn = sqlite3.connect(self._db_path)
        conn.execute("DELETE FROM codex_group WHERE codex_id NOT IN ('6', '7')")
        conn.commit()
        conn.close()

        result = self._requirements()
        self.assertEqual(
            (result['universal_bulin'], result['trial_bulin_mkii'],
             result['specialized_bulin_mkiii']), (0, 0, 0)
        )

    def testRemainingStarUpsPlusOne(self):
        """SSR：3★=4 份、4★=3 份、5★=2 份、6★=0 份。"""
        for codex_id, expected in (('4', 4), ('8', 3), ('9', 2), ('7', 0)):
            with self.subTest(codex_id=codex_id):
                self._onlyKeep(codex_id)

                self.assertEqual(self._requirements()['trial_bulin_mkii'], expected)


class TestRequirementScope(BulinRequirementTestCase):
    """统计范围测试类。"""

    def testOnlyUnlockedConventionalShips(self):
        """未解锁、方案、META、改造、联动、小船、μ兵装 均不计入。"""
        self._resetFixture()
        ids = "','".join([
            '10', '11', '12', '13', '14', '15', '16', '17', '18', '19', '20', '21',
        ])
        conn = sqlite3.connect(self._db_path)
        conn.execute(f"DELETE FROM codex_group WHERE codex_id NOT IN ('{ids}')")
        conn.commit()
        conn.close()

        result = self._requirements()
        self.assertEqual(
            (result['universal_bulin'], result['trial_bulin_mkii'],
             result['specialized_bulin_mkiii']), (0, 0, 0)
        )

    def testUnivBulinShipsExcluded(self):
        """三艘布里（UNIV 阵营）即使未满星也不计入。"""
        conn = sqlite3.connect(self._db_path)
        conn.execute("DELETE FROM codex_group WHERE codex_id != '18'")
        conn.execute("UPDATE codex_group SET ship_rarity = 'SR', ship_star = 2")
        conn.commit()
        conn.close()

        self.assertEqual(self._requirements()['universal_bulin'], 0)

    def testNullStarIgnored(self):
        """星级为空的历史数据不计入（不按 0 星放大需求）。"""
        conn = sqlite3.connect(self._db_path)
        conn.execute("DELETE FROM codex_group WHERE codex_id != '21'")
        conn.commit()
        conn.close()

        self.assertEqual(self._requirements()['trial_bulin_mkii'], 0)

    def testPlanShipRarityHasNoBulinType(self):
        """方案舰的 PRY / DR 不在布里种类映射中。"""
        self.assertNotIn('PRY', options.RARITY_BULIN_TYPE)
        self.assertNotIn('DR', options.RARITY_BULIN_TYPE)


class TestRaritySingleSource(unittest.TestCase):
    """稀有度口径单一来源测试类。"""

    def testMaxStarTable(self):
        """满星阈值：N=4、R/SR=5、SSR/UR=6。"""
        self.assertEqual(options.getMaxStar('N'), 4)
        self.assertEqual(options.getMaxStar('R'), 5)
        self.assertEqual(options.getMaxStar('SR'), 5)
        self.assertEqual(options.getMaxStar('SSR'), 6)
        self.assertEqual(options.getMaxStar('UR'), 6)
        self.assertEqual(options.getMaxStar('未知'), options.DEFAULT_MAX_STAR)

    def testLimitBreakServiceUsesSameTable(self):
        """界限突破服务的满星阈值与 codex_options 一致（修复 N=6 的历史不一致）。"""
        service = LimitBreakService()
        for rarity, expected in options.RARITY_MAX_STAR.items():
            with self.subTest(rarity=rarity):
                self.assertEqual(service._getMaxStar(rarity), expected)

    def testCaseRendering(self):
        """CASE 渲染：数值映射与文字映射均正确。"""
        numeric = options.buildMappingCaseSql('r', {'N': 4, 'SSR': 6}, 6)
        self.assertEqual(numeric, "CASE r WHEN 'N' THEN 4 WHEN 'SSR' THEN 6 ELSE 6 END")

        text = options.buildMappingCaseSql('r', {'N': 'A'}, None, quoteValue=True)
        self.assertEqual(text, "CASE r WHEN 'N' THEN 'A' ELSE NULL END")


class TestLimitBreakBehaviorFix(BulinRequirementTestCase):
    """N 稀有度满星阈值修复的行为验证。"""

    def testLimitBreakMaxStopsAtFourStarsForN(self):
        """N 舰娘「界限突破·MAX」应升到 4★（修复前会写到 6★）。"""
        result = LimitBreakService().limitBreakMax('1')

        self.assertTrue(result.success)
        self.assertEqual(result.new_star, 4)

    def testFindLimitBreakableExcludesFullStarNShip(self):
        """N 舰娘达到 4★ 后不再出现在可突破列表。"""
        ships = CodexGroupRepository().findLimitBreakable()
        ids = {str(ship.codex_id) for ship in ships}

        self.assertIn('1', ids)      # N 1★ 可突破
        self.assertNotIn('6', ids)   # N 4★ 已达满星


if __name__ == '__main__':
    unittest.main()
