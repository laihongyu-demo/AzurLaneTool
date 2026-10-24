"""
心智计算单元测试。

覆盖（对应 issue #13 的确认口径）：

- 等级语义：``认知觉醒一阶`` 表示阶段 1 已完成，只计后续阶段；``未觉醒`` 从阶段 1 开始
- 历史遗留的字符串 ``'null'`` 按未觉醒处理
- 材料只消耗至认知觉醒四阶；四阶、五阶都按阶段 4 处理（四阶升五阶不需要材料）
- ``认知觉醒II`` 按阶段 5 处理
- 稀有度直接对齐基准表：PRY 与 SSR、DR 与 UR 消耗相同（方案舰使用 PRY / DR）
- 统计范围：仅 codex_unlock='Y'，排除 μ兵装 / 小船 / 改造 / 联动 与 UNIV 阵营
- 基准数据全部来自 awakening_of_mind 表（改表即改结果）
"""

import os
import shutil
import sqlite3
import tempfile
import unittest

from repositories.codex_repository import CodexGroupRepository
from services.mental_calculation_service import (
    MentalCalculationService, TARGET_PHASE_FIVE, TARGET_PHASE_II
)
from utils.constants import DEFAULT_DB_PATH
from utils.db_connection import DatabaseConnection

CREATE_SQL = [
    """
    CREATE TABLE codex_group (
        codex_id TEXT NOT NULL PRIMARY KEY,
        ship_name TEXT,
        ship_level TEXT,
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

# 基准表夹具：为了让断言可区分，用 RARITY_PHASE 做系数
#   物资 = 阶段 × 系数，心智单元 = 阶段 × 系数 ÷ 10，心智单元Ⅱ 仅阶段 5 = 系数 ÷ 20
RARITY_FACTOR = {'N': 1, 'R': 2, 'SR': 3, 'SSR': 4, 'PRY': 4, 'UR': 5, 'DR': 5}

# (codex_id, 名称, 等级, 稀有度, 分组, 阵营, 解锁)
SHIP_FIXTURE = [
    ('1', '未觉醒SSR', '未觉醒', 'SSR', '常规', '白鹰联邦', 'Y'),
    ('2', '一阶SSR', '认知觉醒一阶', 'SSR', '常规', '白鹰联邦', 'Y'),
    ('3', '三阶SSR', '认知觉醒三阶', 'SSR', '常规', '白鹰联邦', 'Y'),
    ('4', '四阶SSR', '认知觉醒四阶', 'SSR', '常规', '白鹰联邦', 'Y'),
    ('5', '五阶SSR', '认知觉醒五阶', 'SSR', '常规', '白鹰联邦', 'Y'),
    ('6', '满级SSR', '认知觉醒II', 'SSR', '常规', '白鹰联邦', 'Y'),
    ('7', 'null值SSR', 'null', 'SSR', '常规', '白鹰联邦', 'Y'),
    ('8', '未解锁SSR', '未觉醒', 'SSR', '常规', '白鹰联邦', 'N'),
    ('9', '方案PRY', '未觉醒', 'PRY', '方案', '皇家海军', 'Y'),
    ('10', '方案DR', '未觉醒', 'DR', '方案', '铁血公国', 'Y'),
    ('11', 'UR舰', '未觉醒', 'UR', '常规', '白鹰联邦', 'Y'),
    ('12', 'μ兵装SR', '未觉醒', 'SR', 'μ兵装', '重樱群岛', 'Y'),
    ('13', '小船SR', '未觉醒', 'SR', '小船', '白鹰联邦', 'Y'),
    ('14', '改造SR', '未觉醒', 'SR', '改造', '白鹰联邦', 'Y'),
    ('15', '联动SR', '未觉醒', 'SR', '联动', '哔哩哔哩', 'Y'),
    ('16', '布里UNIV', '未觉醒', 'N', '常规', 'UNIV', 'Y'),
]


def expectedMaterials(rarity: str, from_phase: int, to_phase: int):
    """按夹具规则算出某稀有度、某阶段区间的材料（与 SQL 口径一致）。"""
    factor = RARITY_FACTOR[rarity]
    gc = limit = limit2 = 0
    for phase in range(from_phase, to_phase + 1):
        gc += phase * factor
        limit += phase * factor // 10
        if phase == 5:
            limit2 += factor // 2
    return gc, limit, limit2


class MentalCalculationTestCase(unittest.TestCase):
    """心智计算测试基类。"""

    def setUp(self):
        """创建临时数据库。"""
        self._temp_dir = tempfile.mkdtemp()
        self._db_path = os.path.join(self._temp_dir, 'mental.db')
        DatabaseConnection.setDbPath(self._db_path)
        self._createDatabase()
        self._service = MentalCalculationService()

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
        conn.commit()
        conn.close()
        self._resetFixture()

    def _resetFixture(self):
        """清空并重新写入夹具数据（供需要多轮迭代的用例复位）。"""
        conn = sqlite3.connect(self._db_path)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM codex_group')
        cursor.execute('DELETE FROM awakening_of_mind')

        for rarity, factor in RARITY_FACTOR.items():
            for phase in range(1, 6):
                gc = phase * factor
                limit = phase * factor // 10
                limit2 = factor // 2 if phase == 5 else 0
                cursor.execute(
                    'INSERT INTO awakening_of_mind (ship_rarity, am_phase, expend_gc,'
                    ' expend_limit, expend_limit2) VALUES (?, ?, ?, ?, ?)',
                    (rarity, phase, gc, limit, limit2)
                )

        for codex_id, name, level, rarity, group, camp, unlock in SHIP_FIXTURE:
            cursor.execute(
                'INSERT INTO codex_group (codex_id, ship_name, ship_level, ship_rarity,'
                ' ship_typ, ship_group, ship_aid, ship_camp, codex_unlock)'
                " VALUES (?, ?, ?, ?, '驱逐舰', ?, '2026/01/01', ?, ?)",
                (codex_id, name, level, rarity, group, camp, unlock)
            )
        conn.commit()
        conn.close()

    def _onlyKeep(self, codex_id: str) -> None:
        """重置夹具后只保留指定舰娘（避免多轮迭代互相影响）。"""
        self._resetFixture()
        self._update('DELETE FROM codex_group WHERE codex_id != ?', (codex_id,))

    def _db(self) -> sqlite3.Connection:
        """打开测试库。"""
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _update(self, sql: str, params: tuple = ()) -> None:
        """执行写操作。"""
        conn = self._db()
        try:
            conn.execute(sql, params)
            conn.commit()
        finally:
            conn.close()

    def _calculate(self, include_phase_ii: bool = False):
        """调用心智计算。"""
        result = self._service.calculate(include_phase_ii=include_phase_ii)
        self.assertTrue(result.success, result.message)
        return result


class TestPhaseSemantics(MentalCalculationTestCase):
    """阶段语义与档位处理测试类。"""

    def testOnlySsrShipCostsPhasesOneToFour(self):
        """只留一艘未觉醒 SSR 时，至五阶 = 阶段 1–4；至II = 再加阶段 5。"""
        self._onlyKeep('1')

        result = self._calculate()
        self.assertEqual(
            (result.expend_gc, result.expend_limit, result.expend_limit2),
            expectedMaterials('SSR', 1, 4)
        )

        result = self._calculate(include_phase_ii=True)
        self.assertEqual(
            (result.expend_gc, result.expend_limit, result.expend_limit2),
            expectedMaterials('SSR', 1, 5)
        )

    def testFirstStageShipSkipsPhaseOne(self):
        """一阶表示阶段 1 已完成：只计阶段 2 及以后。"""
        self._onlyKeep('2')

        result = self._calculate()
        self.assertEqual(
            (result.expend_gc, result.expend_limit),
            expectedMaterials('SSR', 2, 4)[:2]
        )

    def testThirdStageShipSkipsPhasesOneToThree(self):
        """三阶表示阶段 1–3 已完成：只计阶段 4。"""
        self._onlyKeep('3')

        result = self._calculate()
        self.assertEqual(
            (result.expend_gc, result.expend_limit),
            expectedMaterials('SSR', 4, 4)[:2]
        )

    def testFourthAndFifthStageNeedNoMoreMaterials(self):
        """四阶升五阶不需要材料：四阶、五阶在“至五阶”口径下都不产生消耗。"""
        for codex_id in ('4', '5'):
            with self.subTest(codex_id=codex_id):
                self._onlyKeep(codex_id)
                result = self._calculate()
                self.assertEqual(
                    (result.expend_gc, result.expend_limit, result.expend_limit2), (0, 0, 0)
                )

    def testFourthAndFifthStageOnlyNeedPhaseFiveForPhaseII(self):
        """四阶 / 五阶舰娘在“至II”口径下只需补阶段 5。"""
        for codex_id in ('4', '5'):
            with self.subTest(codex_id=codex_id):
                self._onlyKeep(codex_id)
                result = self._calculate(include_phase_ii=True)
                self.assertEqual(
                    (result.expend_gc, result.expend_limit, result.expend_limit2),
                    expectedMaterials('SSR', 5, 5)
                )

    def testPhaseIIShipNeedsNothing(self):
        """认知觉醒II（完全满级）不再需要任何材料。"""
        self._onlyKeep('6')

        self.assertEqual(
            (self._calculate().expend_gc, self._calculate(True).expend_gc), (0, 0)
        )

    def testNullStringTreatedAsUnawakened(self):
        """历史遗留的字符串 'null' 按未觉醒处理。"""
        self._onlyKeep('7')

        result = self._calculate()
        self.assertEqual(
            (result.expend_gc, result.expend_limit), expectedMaterials('SSR', 1, 4)[:2]
        )


class TestScopeAndRarity(MentalCalculationTestCase):
    """统计范围与稀有度映射测试类。"""

    def testLockedShipExcluded(self):
        """未解锁舰娘不计入。"""
        self._onlyKeep('8')

        self.assertEqual(self._calculate().expend_gc, 0)

    def testSpecialGroupsAndUnivExcluded(self):
        """μ兵装 / 小船 / 改造 / 联动 与 UNIV 阵营均不计入。"""
        self._resetFixture()
        ids = "','".join(['12', '13', '14', '15', '16'])
        self._update(f"DELETE FROM codex_group WHERE codex_id NOT IN ('{ids}')")

        result = self._calculate()
        self.assertEqual(
            (result.expend_gc, result.expend_limit, result.expend_limit2), (0, 0, 0)
        )

    def testPlanShipRarityMatchesBaselineTable(self):
        """方案舰 PRY / DR 消耗分别等于 SSR / UR（基准表数值决定）。"""
        for codex_id, reference in (('9', 'SSR'), ('10', 'UR')):
            with self.subTest(codex_id=codex_id):
                self._onlyKeep(codex_id)
                result = self._calculate()
                self.assertEqual(
                    (result.expend_gc, result.expend_limit),
                    expectedMaterials(reference, 1, 4)[:2]
                )

    def testUnknownRarityIsDropped(self):
        """稀有度不在基准表中的舰娘被 JOIN 丢弃（不产生消耗）。"""
        self._onlyKeep('1')
        self._update("UPDATE codex_group SET ship_rarity = 'ZZZ'")

        self.assertEqual(self._calculate().expend_gc, 0)

    def testBaselineTableDrivesResult(self):
        """结果完全由基准表决定：改表即改结果。"""
        before = self._calculate()

        self._update('UPDATE awakening_of_mind SET expend_gc = 0')
        after = self._calculate()

        self.assertGreater(before.expend_gc, 0)
        self.assertEqual(after.expend_gc, 0)

    def testTargetPhaseConstants(self):
        """阶段常量语义：4=至五阶（材料终点），5=至II。"""
        self.assertEqual((TARGET_PHASE_FIVE, TARGET_PHASE_II), (4, 5))


class TestMentalCalculationService(MentalCalculationTestCase):
    """服务层测试类。"""

    def testStatusBarMessage(self):
        """状态栏消息包含目标阶段与三项材料。"""
        result = self._calculate()
        message = result.toStatusBarMessage()

        self.assertIn('心智计算完成', message)
        self.assertIn('认知觉醒五阶', message)
        self.assertIn('物资', message)
        self.assertIn('心智单元', message)

    def testRepositoryReturnsDict(self):
        """仓储返回三项材料的字典。"""
        materials = CodexGroupRepository().calculateMentalMaterials(TARGET_PHASE_FIVE)

        self.assertEqual(set(materials.keys()), {'expend_gc', 'expend_limit', 'expend_limit2'})
        self.assertGreater(materials['expend_gc'], 0)


if __name__ == '__main__':
    unittest.main()
