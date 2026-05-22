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


if __name__ == "__main__":
    unittest.main()
