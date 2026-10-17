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
SHIP_LEVELS: List[str] = ["未觉醒", "认知觉醒一阶", "认知觉醒二阶", "认知觉醒三阶", "认知觉醒四阶", "认知觉醒五阶", "认知觉醒II"]

# 等级分档与游戏等级的对应关系（统计口径依据）
#   未觉醒        : < 100 级
#   认知觉醒一阶   : 105 ~ 110 级（自定义特征：经验一律视为已满足 120 级）
#   认知觉醒二阶/三阶: 中间状态，很少出现
#   认知觉醒四阶   : 116 ~ 119 级（经验未满足，但已不需要消耗心智单元）
#   认知觉醒五阶   : = 120 级（可获得全部科技点与科技属性）
#   认知觉醒II     : 完全满级

# 已满 120 级（科技点与科技属性可全部获取）：剩余练级相关的统计口径都排除
LEVELS_FULL_TECH: tuple = ("认知觉醒五阶", "认知觉醒II")

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

# 等级 → 已完成的觉醒阶段号（唯一口径来源，心智计算与觉醒消耗共用）
#   一阶/二阶/三阶/四阶 = 对应阶段已完成；四阶升五阶不需要材料，故五阶与四阶同为 4；
#   认知觉醒II = 完全满级（阶段 5）；未觉醒与改造占位值 'null' 为 0
LEVEL_PHASE_MAP: Dict[str, int] = {
    "认知觉醒一阶": 1,
    "认知觉醒二阶": 2,
    "认知觉醒三阶": 3,
    "认知觉醒四阶": 4,
    "认知觉醒五阶": 4,
    "认知觉醒II": 5,
}

# 未登记的等级（含未觉醒、'null'）按阶段 0 处理
DEFAULT_PHASE: int = 0


def getPhaseOfLevel(ship_level) -> int:
    """
    获取某等级对应的“已完成觉醒阶段号”。

    Args:
        ship_level: 舰娘等级字符串（未觉醒 / 认知觉醒一阶 … / 认知觉醒II / 'null'）。

    Returns:
        阶段号（0–5）；未登记的取值返回 :data:`DEFAULT_PHASE`。

    Examples:
        >>> getPhaseOfLevel("认知觉醒一阶")
        1
        >>> getPhaseOfLevel("认知觉醒五阶")
        4
        >>> getPhaseOfLevel("未觉醒")
        0
    """
    return LEVEL_PHASE_MAP.get(str(ship_level or "").strip(), DEFAULT_PHASE)


def buildPhaseCaseSql(column: str) -> str:
    """
    生成与 :data:`LEVEL_PHASE_MAP` 一致的 SQL CASE 片段。

    供聚合查询（心智计算）复用同一份阶段口径，避免出现第二套映射。

    Args:
        column: 等级字段表达式（如 ``cg.ship_level`` 或占位符 ``?``）。

    Returns:
        形如 ``CASE cg.ship_level WHEN '认知觉醒一阶' THEN 1 … ELSE 0 END`` 的 SQL 片段。
    """
    whens = " ".join(
        f"WHEN '{level}' THEN {phase}" for level, phase in LEVEL_PHASE_MAP.items()
    )
    return f"CASE {column} {whens} ELSE {DEFAULT_PHASE} END"


# 稀有度 → 满星阈值
# 各稀有度均可升星 3 次（初始星不同）：N 1→4、R/SR 2→5、SSR/UR 3→6；
# 方案舰固定使用 PRY / DR（PRY 同 SSR、DR 同 UR），另有历史值 PR / E
RARITY_MAX_STAR: Dict[str, int] = {
    "N": 4,
    "R": 5,
    "SR": 5,
    "SSR": 6,
    "UR": 6,
    "PRY": 6,
    "DR": 6,
    "PR": 3,
    "E": 3,
}

# 未登记稀有度的兜底满星阈值
DEFAULT_MAX_STAR: int = 6

# 稀有度 → 升星所需布里种类（方案舰的 PRY / DR 不在此表，即不消耗布里）
RARITY_BULIN_TYPE: Dict[str, str] = {
    "N": "Universal Bulin",
    "R": "Universal Bulin",
    "SR": "Universal Bulin",
    "SSR": "Trial Bulin MKII",
    "UR": "Specialized Bulin MKIII",
}

# 单次升星的基础消耗与最后一次升星的额外消耗（合计 1 + 1 + 2 = 4）
BULIN_PER_STAR: int = 1
BULIN_LAST_STAR_EXTRA: int = 1


def getMaxStar(ship_rarity) -> int:
    """
    获取某稀有度的满星阈值。

    Args:
        ship_rarity: 稀有度（N / R / SR / SSR / UR / PRY / DR / PR / E）。

    Returns:
        满星阈值；未登记时返回 :data:`DEFAULT_MAX_STAR`。

    Examples:
        >>> getMaxStar("N")
        4
        >>> getMaxStar("SSR")
        6
    """
    return RARITY_MAX_STAR.get(str(ship_rarity or "").strip(), DEFAULT_MAX_STAR)


def buildMappingCaseSql(column: str, mapping: Dict, default, quoteValue: bool = False) -> str:
    """
    按映射字典生成 SQL CASE 片段（把口径下沉为单一来源，供 SQL 模板注入）。

    Args:
        column: 字段表达式（如 ``ship_rarity``）。
        mapping: 取值映射，如 ``{"N": 4, "SSR": 6}``。
        default: 未命中时的返回值（``None`` 生成 ``ELSE NULL``）。
        quoteValue: 映射值是否按字符串加引号（文字类型映射时为 True）。

    Returns:
        形如 ``CASE ship_rarity WHEN 'N' THEN 4 … ELSE 6 END`` 的 SQL 片段。
    """
    def render(value) -> str:
        if value is None:
            return "NULL"
        if quoteValue:
            return f"'{value}'"
        return str(value)

    whens = " ".join(
        f"WHEN '{key}' THEN {render(value)}" for key, value in mapping.items()
    )
    return f"CASE {column} {whens} ELSE {render(default)} END"


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
