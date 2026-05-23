"""
工具层模块单元测试。
"""

import unittest
import os
import tempfile

from utils.helpers import (
    generateId, formatDatetime, parseDatetime,
    safeGet, truncateString, formatNumber, formatCurrency
)
from utils.sql_loader import loadSqlFile
from utils.unit_formatter import formatValue
from utils.exceptions import DatabaseError


class TestHelpers(unittest.TestCase):
    """辅助函数测试类。"""

    def testGenerateId(self):
        """测试 ID 生成。"""
        id1 = generateId()
        id2 = generateId()
        self.assertIsInstance(id1, str)
        self.assertNotEqual(id1, id2)

    def testFormatDatetime(self):
        """测试日期格式化。"""
        from datetime import datetime
        dt = datetime(2024, 1, 15, 10, 30, 0)
        result = formatDatetime(dt)
        self.assertEqual(result, "2024-01-15 10:30:00")

    def testParseDatetime(self):
        """测试日期解析。"""
        result = parseDatetime("2024-01-15 10:30:00")
        self.assertEqual(result.year, 2024)
        self.assertEqual(result.month, 1)
        self.assertEqual(result.day, 15)

    def testSafeGet(self):
        """测试安全获取字典值。"""
        data = {"name": "test", "value": 123}
        self.assertEqual(safeGet(data, "name"), "test")
        self.assertEqual(safeGet(data, "missing", "default"), "default")

    def testTruncateString(self):
        """测试字符串截断。"""
        text = "这是一个很长的测试字符串"
        result = truncateString(text, 10)
        self.assertTrue(len(result) <= 13)

    def testFormatNumber(self):
        """测试数字格式化。"""
        self.assertEqual(formatNumber(3.14159, 2), "3.14")
        self.assertEqual(formatNumber(100.0, 0), "100")

    def testFormatCurrency(self):
        """测试货币格式化。"""
        self.assertEqual(formatCurrency(1234.5), "¥1,234.50")


class TestSqlLoader(unittest.TestCase):
    """SQL 加载器测试类。"""

    def testLoadSqlFileNotFound(self):
        """测试加载不存在的 SQL 文件。"""
        with self.assertRaises(DatabaseError):
            loadSqlFile("nonexistent.sql")


class TestUnitFormatter(unittest.TestCase):
    """数值单位换算测试类。"""

    def testZero(self):
        """测试零值。"""
        self.assertEqual(formatValue(0), "0")

    def testBelowKilo(self):
        """测试小于1000的数值。"""
        self.assertEqual(formatValue(1), "1")
        self.assertEqual(formatValue(999), "999")
        self.assertEqual(formatValue(500), "500")

    def testKiloRange(self):
        """测试 K 单位范围（1000~999999）。"""
        self.assertEqual(formatValue(1000), "1.0K")
        self.assertEqual(formatValue(1500), "1.5K")
        self.assertEqual(formatValue(1550), "1.6K")
        self.assertEqual(formatValue(10000), "10.0K")
        self.assertEqual(formatValue(999900), "999.9K")
        self.assertEqual(formatValue(999999), "1000.0K")

    def testMegaRange(self):
        """测试 M 单位范围（1000000~999999999）。"""
        self.assertEqual(formatValue(1000000), "1.0M")
        self.assertEqual(formatValue(2500000), "2.5M")
        self.assertEqual(formatValue(999900000), "999.9M")
        self.assertEqual(formatValue(999999999), "1000.0M")

    def testGigaRange(self):
        """测试 B 单位范围（1000000000~999999999999）。"""
        self.assertEqual(formatValue(1000000000), "1.0B")
        self.assertEqual(formatValue(1500000000), "1.5B")
        self.assertEqual(formatValue(999999999999), "1000.0B")

    def testTeraRange(self):
        """测试 T 单位范围（>=1000000000000）。"""
        self.assertEqual(formatValue(1000000000000), "1.0T")
        self.assertEqual(formatValue(2500000000000), "2.5T")
        self.assertEqual(formatValue(9999900000000000), "9999.9T")

    def testNegativeValues(self):
        """测试负数值。"""
        self.assertEqual(formatValue(-500), "-500")
        self.assertEqual(formatValue(-1500), "-1.5K")
        self.assertEqual(formatValue(-1000000), "-1.0M")

    def testFloatInputs(self):
        """测试浮点数输入。"""
        self.assertEqual(formatValue(1.0), "1")
        self.assertEqual(formatValue(1500.0), "1.5K")
        self.assertEqual(formatValue(1500.9), "1.5K")

    def testEdgeCases(self):
        """测试边界值。"""
        self.assertEqual(formatValue(999), "999")
        self.assertEqual(formatValue(1000), "1.0K")
        self.assertEqual(formatValue(999999), "1000.0K")
        self.assertEqual(formatValue(1000000), "1.0M")
        self.assertEqual(formatValue(999999999), "1000.0M")
        self.assertEqual(formatValue(1000000000), "1.0B")


if __name__ == "__main__":
    unittest.main()
