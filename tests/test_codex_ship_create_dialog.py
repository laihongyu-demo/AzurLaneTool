"""新增舰娘对话框布局与科技属性单行录入单元测试。

覆盖：科技属性两个输入框为单行控件、窗体高度随之下降、单行文本仍能解析出
codex_buff 明细并给出写入条数提示，以及采集结果与输入一致。
"""

import os
import shutil
import sqlite3
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication, QLineEdit, QPlainTextEdit  # noqa: E402

from utils.db_connection import DatabaseConnection  # noqa: E402
from views.dialogs.codex_ship_create_dialog import CodexShipCreateDialog  # noqa: E402

CREATE_SQL = """
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
    date_edit NUMERIC,
    fleet_position TEXT
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

# 单行输入框的高度上限：一行文字 + 内边距，远小于原来的 88px 多行框
MAX_SINGLE_LINE_HEIGHT = 40


class CodexShipCreateDialogLayoutTest(unittest.TestCase):
    """新增舰娘对话框的科技属性录入与窗体尺寸。"""

    @classmethod
    def setUpClass(cls):
        """创建 QApplication（offscreen）。"""
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        """每个用例使用独立临时库。"""
        self._temp_dir = tempfile.mkdtemp()
        self._db_path = os.path.join(self._temp_dir, "test_create_dialog.db")
        self._original_path = DatabaseConnection.getDbPath()
        conn = sqlite3.connect(self._db_path)
        for sql in (CREATE_SQL, CREATE_TP_SQL, CREATE_BUFF_SQL):
            conn.executescript(sql)
        conn.commit()
        conn.close()
        DatabaseConnection.setDbPath(self._db_path)

    def tearDown(self):
        """恢复数据库路径并清理。"""
        DatabaseConnection.setDbPath(self._original_path)
        if os.path.exists(self._temp_dir):
            shutil.rmtree(self._temp_dir)

    def _createDialog(self):
        """在当前临时库上创建对话框。"""
        return CodexShipCreateDialog()

    def testBuffEditorsAreSingleLine(self):
        """科技属性两个输入框都是单行控件，高度不超过一行。"""
        dialog = self._createDialog()
        try:
            self.assertEqual(set(dialog._buffEdits), {"解锁", "Lv.120"})
            for cond, edit in dialog._buffEdits.items():
                self.assertIsInstance(edit, QLineEdit, cond)
                self.assertNotIsInstance(edit, QPlainTextEdit, cond)
                self.assertLessEqual(edit.sizeHint().height(), MAX_SINGLE_LINE_HEIGHT, cond)
        finally:
            dialog.close()

    def testDialogHeightShrinks(self):
        """窗体最小高度下调，且不低于内容所需高度。"""
        dialog = self._createDialog()
        try:
            self.assertLessEqual(dialog.minimumSize().height(), 570)
            self.assertGreater(dialog.minimumSize().height(), 400)
            self.assertLessEqual(
                dialog.minimumSizeHint().height(),
                dialog.minimumSize().height(),
                "内容所需高度不应超过窗体最小高度",
            )
        finally:
            dialog.close()

    def testSingleLineTextStillParses(self):
        """单行文本仍可解析出多条增益明细，并给出写入条数提示。"""
        dialog = self._createDialog()
        try:
            dialog._buffEdits["解锁"].setText("战巡/战列/航战 耐久+1")
            dialog._buffEdits["Lv.120"].setText("战巡/战列/航战 炮击+1")
            self._app.processEvents()

            rows = dialog._create_service.parseBuffRows(dialog._collectBuffText())
            self.assertEqual(len(rows), 6)
            self.assertEqual(
                dialog._collectBuffText()["解锁"], "战巡/战列/航战 耐久+1"
            )
            self.assertIn("codex_buff 6 条", dialog._buffHintLabel.text())
        finally:
            dialog.close()

    def testInvalidTextShowsHint(self):
        """格式错误的单行文本在提示标签里报错，不抛异常。"""
        dialog = self._createDialog()
        try:
            dialog._buffEdits["解锁"].setText("耐久1")
            self._app.processEvents()
            self.assertIn("格式错误", dialog._buffHintLabel.text())
        finally:
            dialog.close()


if __name__ == "__main__":
    unittest.main()
