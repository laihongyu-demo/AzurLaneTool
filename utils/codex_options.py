"""
舰娘图鉴数据字典模块。

集中定义新增舰娘所需的枚举选项、分组ID规则与字段默认形态，
供界面选项、ID自动生成与科技属性文本校验复用。

科技属性的增益类型（BOOST_TYPS）与属性类型（BUFF_TYPS）是新增录入的
白名单来源：游戏后续新增属性时，只需在下方对应列表中登记一个取值即可，
界面提示与校验错误信息会自动同步。
"""

from typing import Dict, List, Optional

# 舰娘分组（界面下拉顺序）
SHIP_GROUPS: List[str] = ["常规", "META", "方案", "联动", "改造", "小船", "μ兵装"]

# 分组 -> 图鉴ID前缀，None 表示使用纯数字ID
GROUP_ID_PREFIX_MAP: Dict[str, Optional[str]] = {
    "常规": None,
    "META": "META",
    "方案": "Plan",
    "联动": "Collab",
    "改造": "Refit",
    "小船": None,
    "μ兵装": None,
}

# 带前缀ID的数字位数（如 META065、Refit109）
ID_PREFIX_PAD_WIDTH: int = 3

# 无科技点与科技属性记录的分组（新增时跳过 codex_tp / codex_buff 写入）
NO_TP_BUFF_GROUPS: tuple = ("联动", "μ兵装", "小船", "改造")

# 稀有度
SHIP_RARITIES: List[str] = ["UR", "DR", "PRY", "SSR", "SR", "R", "N"]

# 稀有度 -> 新增时的默认星级（改造类型固定为0星）
DEFAULT_STAR_BY_RARITY: Dict[str, int] = {
    "UR": 3, "DR": 3, "PRY": 3, "SSR": 3,
    "SR": 2, "R": 2, "N": 2,
}
DEFAULT_STAR_FOR_REFIT: int = 0

# 舰船类型
SHIP_TYPS: List[str] = [
    "驱逐舰", "轻型巡洋舰", "重型巡洋舰", "超级巡洋舰", "浅水重炮舰",
    "战列舰", "战列巡洋舰", "航空战列舰",
    "航空母舰", "轻型航空母舰",
    "潜艇", "潜水空母",
    "维修舰", "弹药运输舰",
    "风帆S", "风帆M", "风帆V",
]

# 阵营
SHIP_CAMPS: List[str] = [
    "白鹰联邦", "皇家海军", "重樱群岛", "铁血公国", "北方联合",
    "东煌古国", "自由鸢尾", "维希教廷", "撒丁帝国", "郁金王国",
    "晶环联盟", "飓风之海", "META", "UNIV",
]

# 科技属性的增益类型（boost_typ）白名单：新增属性在此登记
BOOST_TYPS: List[str] = [
    "驱逐", "轻巡", "重巡", "重炮", "超巡",
    "战巡", "战列", "航战", "轻航", "正航",
    "潜艇", "潜母", "维修", "运输", "风帆",
]

# 科技属性的属性类型（buff_typ）白名单：新增属性在此登记
BUFF_TYPS: List[str] = ["耐久", "炮击", "雷击", "航空", "防空", "装填", "命中", "机动", "反潜"]

# 科技点解锁条件（固定三档，每档一条记录）
TP_CONDS: List[str] = ["解锁", "满星", "Lv.120"]

# 科技属性解锁条件（固定两档，文本按该顺序录入）
BUFF_CONDS: List[str] = ["解锁", "Lv.120"]

# 舰娘等级选项（改造类型使用字符串 'null'）
SHIP_LEVELS: List[str] = ["未觉醒", "认知觉醒一阶", "认知觉醒二阶", "认知觉醒三阶", "认知觉醒四阶", "认知觉醒五阶", "认知觉醒Ⅱ"]

# 等级分档与游戏等级的对应关系（统计口径依据）
#   未觉醒        : < 100 级
#   认知觉醒一阶   : 105 ~ 110 级（自定义特征：经验一律视为已满足 120 级）
#   认知觉醒二阶/三阶: 中间状态，很少出现
#   认知觉醒四阶   : 116 ~ 119 级（经验未满足，但已不需要消耗心智单元）
#   认知觉醒五阶   : = 120 级（可获得全部科技点与科技属性）
#   认知觉醒Ⅱ     : 完全满级

# 已满 120 级（科技点与科技属性可全部获取）：剩余练级相关的统计口径都排除
LEVELS_FULL_TECH: tuple = ("认知觉醒五阶", "认知觉醒Ⅱ")

# 经验已满足 120 级，不需要再练级：不计入“还需要练级”的数量
LEVELS_EXP_SUFFICIENT: tuple = ("认知觉醒一阶",)

# 已不需要消耗心智单元：不计入“仍需消耗心智单元”的数量
LEVELS_NO_MATERIAL: tuple = ("认知觉醒四阶",)

# 好感度与誓约状态选项（改造类型使用字符串 'null'）
SHIP_LIKINGS: List[str] = ["陌生", "爱", "誓约"]
OATH_STATUSES: List[str] = ["N", "Y"]

# 改造类型固定写入的占位值
NULL_TEXT: str = "null"

# 各分组新增时的默认字段形态
GROUP_FIELD_DEFAULTS: Dict[str, Dict[str, str]] = {
    "常规": {"ship_level": "未觉醒", "ship_liking": "陌生", "oath_status": "N"},
    "META": {"ship_level": "未觉醒", "ship_liking": "陌生", "oath_status": "N"},
    "方案": {"ship_level": "未觉醒", "ship_liking": "陌生", "oath_status": "N"},
    "联动": {"ship_level": "未觉醒", "ship_liking": "陌生", "oath_status": "N"},
    "小船": {"ship_level": "未觉醒", "ship_liking": "陌生", "oath_status": "N"},
    "μ兵装": {"ship_level": "未觉醒", "ship_liking": "陌生", "oath_status": "N"},
    "改造": {"ship_level": NULL_TEXT, "ship_liking": NULL_TEXT, "oath_status": NULL_TEXT},
}

# 日期格式
SHIP_AID_FORMAT: str = "yyyy/MM/dd"
DATE_EDIT_DATE_FORMAT: str = "yyyy-MM-dd"
DATE_EDIT_TIME_FORMAT: str = "HH:mm:ss"

# 科技属性文本录入的格式说明（界面提示与错误信息共用）
BUFF_TEXT_EXAMPLE: str = "战巡/战列/航战 耐久+1"


def getGroupIdPrefix(ship_group: str) -> Optional[str]:
    """
    获取指定分组的图鉴ID前缀。

    Args:
        ship_group: 舰娘分组。

    Returns:
        ID前缀字符串，纯数字分组返回 None。
    """
    return GROUP_ID_PREFIX_MAP.get(ship_group)


def isNoTpBuffGroup(ship_group: str) -> bool:
    """
    判断分组是否不写入科技点与科技属性。

    Args:
        ship_group: 舰娘分组。

    Returns:
        无需写入 codex_tp / codex_buff 时返回 True。
    """
    return ship_group in NO_TP_BUFF_GROUPS


def getDefaultStar(ship_group: str, ship_rarity: str) -> int:
    """
    获取新增舰娘的默认星级。

    Args:
        ship_group: 舰娘分组。
        ship_rarity: 舰娘稀有度。

    Returns:
        默认星级数值。
    """
    if ship_group == "改造":
        return DEFAULT_STAR_FOR_REFIT
    return DEFAULT_STAR_BY_RARITY.get(ship_rarity, 3)


def getGroupFieldDefaults(ship_group: str) -> Dict[str, str]:
    """
    获取分组默认字段形态。

    Args:
        ship_group: 舰娘分组。

    Returns:
        包含 ship_level、ship_liking、oath_status 的字典。
    """
    return dict(GROUP_FIELD_DEFAULTS.get(ship_group, GROUP_FIELD_DEFAULTS["常规"]))
