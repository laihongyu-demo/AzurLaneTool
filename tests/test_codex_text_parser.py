"""
科技属性文本解析模块单元测试。

测试覆盖：
- 单条与多条解析、多个增益类型展开
- 分隔符与全角符号容错、空行与注释忽略
- 按条件顺序拼接
- 格式错误、未登记增益类型/属性、非正整数数值的错误定位
"""

import unittest

from utils import codex_options as options
from utils.codex_text_parser import parseBuffText, parseBuffTextBlock
from utils.exceptions import ValidationError


class TestParseBuffText(unittest.TestCase):
    """科技属性文本解析测试类。"""

    def testParseSingleBoostTyp(self):
        """单个增益类型解析为一行。"""
        rows = parseBuffText("战巡 耐久+1", "解锁")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].boost_typ, "战巡")
        self.assertEqual(rows[0].buff_cond, "解锁")
        self.assertEqual(rows[0].buff_typ, "耐久")
        self.assertEqual(rows[0].buff_value, 1)

    def testParseMultipleBoostTyps(self):
        """一行内多个增益类型展开为多行。"""
        rows = parseBuffText("战巡/战列/航战 耐久+2", "解锁")

        self.assertEqual([row.boost_typ for row in rows], ["战巡", "战列", "航战"])
        self.assertTrue(all(row.buff_typ == "耐久" for row in rows))
        self.assertTrue(all(row.buff_value == 2 for row in rows))
        self.assertTrue(all(row.buff_cond == "解锁" for row in rows))

    def testParseSeparatorVariants(self):
        """支持 /、、、逗号与空格作为增益类型分隔符。"""
        for text in ("战巡、战列，航战 耐久+1", "战巡,战列,航战 耐久+1", "战巡 战列 航战 耐久+1"):
            with self.subTest(text=text):
                rows = parseBuffText(text, "解锁")
                self.assertEqual([row.boost_typ for row in rows], ["战巡", "战列", "航战"])

    def testParseSymbolVariants(self):
        """支持全角加号与符号前空格。"""
        for text in ("战巡 耐久＋1", "战巡 耐久 +1", "战巡  耐久+1"):
            with self.subTest(text=text):
                rows = parseBuffText(text, "解锁")
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0].buff_value, 1)

    def testParseMultipleLinesWithBlankAndComment(self):
        """多行解析：空行、整行注释与行尾注释均被忽略。"""
        text = "\n".join([
            "# 下面是原始数据",
            "战巡/战列/航战 耐久+1",
            "",
            "   ",
            "// 另一段",
            "轻巡 防空+2   # 行尾注释",
        ])

        rows = parseBuffText(text, "解锁")

        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0].boost_typ, "战巡")
        self.assertEqual(rows[3].boost_typ, "轻巡")
        self.assertEqual(rows[3].buff_typ, "防空")
        self.assertEqual(rows[3].buff_value, 2)

    def testParseDuplicateLineKeepsAllRows(self):
        """重复行不去重，按录入内容原样展开。"""
        rows = parseBuffText("战巡 装填+1\n战巡 装填+1", "Lv.120")

        self.assertEqual(len(rows), 2)

    def testParseBuffTextBlockOrder(self):
        """按解锁条件顺序拼接全部行。"""
        rows = parseBuffTextBlock({
            "Lv.120": "战巡/战列/航战 炮击+1",
            "解锁": "战巡/战列/航战 耐久+2",
        })

        self.assertEqual(len(rows), 6)
        self.assertEqual([row.buff_cond for row in rows[:3]], ["解锁"] * 3)
        self.assertEqual([row.buff_cond for row in rows[3:]], ["Lv.120"] * 3)

    def testParseBuffTextBlockEmpty(self):
        """空文本返回空列表。"""
        self.assertEqual(parseBuffTextBlock({}), [])
        self.assertEqual(parseBuffTextBlock(None), [])
        self.assertEqual(parseBuffTextBlock({"解锁": "   "}), [])

    def testParseFormatErrorReportsLineNumber(self):
        """格式错误时按行号报错。"""
        text = "战巡/战列/航战 耐久+1\n战巡 耐久"

        with self.assertRaises(ValidationError) as ctx:
            parseBuffText(text, "解锁")

        self.assertIn("第 2 行", str(ctx.exception))
        self.assertIn("格式错误", str(ctx.exception))
        self.assertIn(options.BUFF_TEXT_EXAMPLE, str(ctx.exception))

    def testParseMissingBoostTyp(self):
        """缺少增益类型时按格式错误报错。"""
        with self.assertRaises(ValidationError) as ctx:
            parseBuffText("耐久+1", "解锁")

        self.assertIn("格式错误", str(ctx.exception))

    def testParseUnknownBoostTyp(self):
        """未登记的增益类型被拒绝，并提示登记位置。"""
        with self.assertRaises(ValidationError) as ctx:
            parseBuffText("战巡/战巡舰 耐久+1", "解锁")

        message = str(ctx.exception)
        self.assertIn("增益类型「战巡舰」未登记", message)
        self.assertIn("BOOST_TYPS", message)
        self.assertIn("战巡", message)

    def testParseUnknownBuffTyp(self):
        """未登记的属性被拒绝，并提示登记位置。"""
        with self.assertRaises(ValidationError) as ctx:
            parseBuffText("战巡 耐九+1", "解锁")

        message = str(ctx.exception)
        self.assertIn("属性「耐九」未登记", message)
        self.assertIn("BUFF_TYPS", message)
        self.assertIn("耐久", message)

    def testParseNonPositiveValue(self):
        """数值必须为正整数。"""
        with self.assertRaises(ValidationError) as ctx:
            parseBuffText("战巡 耐久+0", "解锁")

        self.assertIn("正整数", str(ctx.exception))

    def testParseUnknownCondition(self):
        """未知解锁条件被拒绝。"""
        with self.assertRaises(ValidationError):
            parseBuffText("战巡 耐久+1", "满星")

    def testWhitelistCoversAllCurrentData(self):
        """白名单与现有图鉴数据取值一致（新增属性时本用例会提示同步登记）。"""
        self.assertEqual(len(options.BOOST_TYPS), len(set(options.BOOST_TYPS)))
        self.assertEqual(len(options.BUFF_TYPS), len(set(options.BUFF_TYPS)))
        self.assertEqual(
            set(options.BOOST_TYPS),
            {"驱逐", "轻巡", "重巡", "重炮", "超巡", "战巡", "战列", "航战",
             "轻航", "正航", "潜艇", "潜母", "维修", "运输", "风帆"}
        )
        self.assertEqual(
            set(options.BUFF_TYPS),
            {"耐久", "炮击", "雷击", "航空", "防空", "装填", "命中", "机动", "反潜"}
        )


if __name__ == "__main__":
    unittest.main()
