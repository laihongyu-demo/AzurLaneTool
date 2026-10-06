"""
科技属性文本解析模块。

将界面录入的原始数据文本解析为 codex_buff 明细行。

文本格式（每行一条，行内可写多个增益类型）::

    战巡/战列/航战 耐久+1

含义：战巡、战列、航战三个增益类型各写入一条“耐久+1”记录。
增益类型分隔符支持 ``/``、``、``、``,``、``，``与空格；
以 ``#`` 或 ``//`` 开头的行视为注释，空行忽略。
"""

import re
from dataclasses import dataclass
from typing import Dict, List, Optional

from utils import codex_options as options
from utils.exceptions import ValidationError

# 增益类型之间的分隔符
BOOST_SEPARATOR_PATTERN = re.compile(r"[/、,，\s]+")

# 单行格式：<增益类型列表> <属性><+|＋><数值>
BUFF_LINE_PATTERN = re.compile(
    r"^(?P<boosts>.+?)\s+(?P<stat>[^\s+＋]+)\s*[+＋]\s*(?P<value>\d+)$"
)


@dataclass
class BuffTextRow:
    """
    科技属性明细行。

    Attributes:
        boost_typ: 增益类型。
        buff_cond: 解锁条件。
        buff_typ: 属性类型。
        buff_value: 属性数值。
    """

    boost_typ: str
    buff_cond: str
    buff_typ: str
    buff_value: int

    def toDict(self) -> Dict:
        """转换为字典。"""
        return {
            "boost_typ": self.boost_typ,
            "buff_cond": self.buff_cond,
            "buff_typ": self.buff_typ,
            "buff_value": self.buff_value
        }


def parseBuffText(text: str, buff_cond: str) -> List[BuffTextRow]:
    """
    解析单个解锁条件下的科技属性文本。

    Args:
        text: 原始数据文本，每行形如“战巡/战列/航战 耐久+1”。
        buff_cond: 解锁条件（解锁 / Lv.120）。

    Returns:
        解析后的科技属性明细行列表。

    Raises:
        ValidationError: 当某行格式错误、增益类型或属性未登记时抛出，
            错误信息中包含行号与可选取值。
    """
    if buff_cond not in options.BUFF_CONDS:
        raise ValidationError(f"未知的科技属性解锁条件: {buff_cond}")

    rows: List[BuffTextRow] = []

    for line_no, raw_line in enumerate(str(text or "").splitlines(), start=1):
        # 支持整行注释与行尾注释
        line = raw_line.split("#")[0].strip()
        if not line or line.startswith("//"):
            continue

        match = BUFF_LINE_PATTERN.match(line)
        if match is None:
            raise ValidationError(
                f"科技属性（{buff_cond}）第 {line_no} 行格式错误：{line}；"
                f"正确格式如「{options.BUFF_TEXT_EXAMPLE}」"
            )

        boost_typs = [
            item for item in BOOST_SEPARATOR_PATTERN.split(match.group("boosts").strip()) if item
        ]
        if not boost_typs:
            raise ValidationError(
                f"科技属性（{buff_cond}）第 {line_no} 行缺少增益类型：{line}；"
                f"正确格式如「{options.BUFF_TEXT_EXAMPLE}」"
            )

        buff_typ = match.group("stat").strip()
        buff_value = int(match.group("value"))

        _validateBuffTyp(buff_typ, buff_cond, line_no)

        if buff_value <= 0:
            raise ValidationError(
                f"科技属性（{buff_cond}）第 {line_no} 行的数值应为正整数：{line}"
            )

        for boost_typ in boost_typs:
            _validateBoostTyp(boost_typ, buff_cond, line_no)

            rows.append(BuffTextRow(
                boost_typ=boost_typ,
                buff_cond=buff_cond,
                buff_typ=buff_typ,
                buff_value=buff_value
            ))

    return rows


def parseBuffTextBlock(buff_text: Optional[Dict[str, str]]) -> List[BuffTextRow]:
    """
    按解锁条件顺序解析全部科技属性文本。

    Args:
        buff_text: 解锁条件 -> 原始数据文本的映射。

    Returns:
        解析后的科技属性明细行列表（按 BUFF_CONDS 顺序拼接）。

    Raises:
        ValidationError: 当文本不合法时抛出。
    """
    buff_text = buff_text or {}
    rows: List[BuffTextRow] = []

    for buff_cond in options.BUFF_CONDS:
        rows.extend(parseBuffText(buff_text.get(buff_cond, ""), buff_cond))

    return rows


def _validateBoostTyp(boost_typ: str, buff_cond: str, line_no: int) -> None:
    """校验增益类型是否已登记。"""
    if boost_typ in options.BOOST_TYPS:
        return

    raise ValidationError(
        f"科技属性（{buff_cond}）第 {line_no} 行的增益类型「{boost_typ}」未登记；"
        f"可用增益类型：{'/'.join(options.BOOST_TYPS)}。"
        f"若为游戏新增类型，请在 utils/codex_options.py 的 BOOST_TYPS 中登记后再录入。"
    )


def _validateBuffTyp(buff_typ: str, buff_cond: str, line_no: int) -> None:
    """校验属性类型是否已登记。"""
    if buff_typ in options.BUFF_TYPS:
        return

    raise ValidationError(
        f"科技属性（{buff_cond}）第 {line_no} 行的属性「{buff_typ}」未登记；"
        f"可用属性：{'/'.join(options.BUFF_TYPS)}。"
        f"若为游戏新增属性，请在 utils/codex_options.py 的 BUFF_TYPS 中登记后再录入。"
    )
