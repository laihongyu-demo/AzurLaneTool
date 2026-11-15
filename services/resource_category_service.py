"""
资源类型字典维护服务模块。

承接「设置 → 类型字典」的自助维护（#21）：查询某「资源 + 方向」下的全部类型
（含已停用）、新增、改名（同步历史明细）、上移 / 下移、停用 / 启用。

口径：

- 类型唯一键是 ``(resource_type, direction, name)``，同名可同时存在于收入与支出；
- 改名会同步 ``resource_transaction.category``，避免历史明细变成孤儿；
- 停用只影响录入下拉，历史明细与统计仍按原名保留；
- 每组至少保留一个启用中的类型，避免常规录入的下拉为空。
"""

from dataclasses import dataclass
from typing import List, Optional, Tuple

from models.resource_model import ResourceCategoryModel
from repositories.resource_repository import ResourceRepository
from utils.constants import (
    RESOURCE_DIRECTIONS,
    RESOURCE_DIRECTION_NAMES,
    RESOURCE_DISPLAY_NAMES,
    RESOURCE_TYPES,
)
from utils.db_connection import DatabaseContext
from utils.db_schema import isMissingColumnError, isMissingTableError
from utils.exceptions import DatabaseError, ValidationError

# 类型名称长度上限：够描述玩法来源，又不会把下拉撑破
CATEGORY_NAME_MAX_LENGTH = 20

# 重排时的序号步长：10、20、30……留出插入空间
SORT_ORDER_STEP = 10


@dataclass
class CategoryEntry:
    """
    类型字典维护界面的一行。

    Attributes:
        id: 字典项 ID。
        resource_type: 资源类型。
        direction: 方向。
        name: 类型名称。
        sort_order: 排序序号。
        is_active: 是否启用。
        usage_count: 已关联的明细笔数（用于提示「在用，不能删只能停用」）。
    """

    id: int
    resource_type: str
    direction: str
    name: str
    sort_order: int
    is_active: bool
    usage_count: int = 0

    @property
    def statusText(self) -> str:
        """
        状态文案。

        Returns:
            ``启用`` 或 ``停用``。
        """
        return "启用" if self.is_active else "停用"


@dataclass
class CategoryWriteResult:
    """
    类型字典写操作结果。

    Attributes:
        success: 是否真正发生了写入。
        message: 面向用户的提示文案。
        category_id: 涉及的字典项 ID（用于写入后重新选中）；无对应项时为 0。
    """

    success: bool
    message: str
    category_id: int = 0

    def toStatusBarMessage(self) -> str:
        """
        状态栏文案。

        Returns:
            提示文案。
        """
        return self.message


class ResourceCategoryService:
    """资源类型字典维护服务。"""

    def __init__(self, resource_repository: Optional[ResourceRepository] = None):
        """
        初始化类型字典服务。

        Args:
            resource_repository: 资源仓储实例。
        """
        self._repository = resource_repository or ResourceRepository()

    # ------------------------------------------------------------------ 查询

    def listCategories(self, resource_type: str, direction: str) -> List[CategoryEntry]:
        """
        查询某「资源 + 方向」下的全部类型（含已停用），附带明细笔数。

        表 / 列缺失时降级为空列表，不把数据库异常抛到界面。

        Args:
            resource_type: 资源类型。
            direction: 方向，``income`` 或 ``expense``。

        Returns:
            类型条目列表，按排序序号与名称升序。

        Raises:
            ValidationError: 资源类型或方向非法时抛出。
        """
        self._validatePair(resource_type, direction)
        try:
            records = self._repository.findCategories(
                resource_type, direction, include_inactive=True
            )
            usage = self._repository.countTransactionsByCategories(resource_type)
        except DatabaseError as e:
            if isMissingTableError(e) or isMissingColumnError(e):
                return []
            raise

        return [
            CategoryEntry(
                id=record.id,
                resource_type=record.resource_type,
                direction=record.direction,
                name=record.name,
                sort_order=record.sort_order,
                is_active=bool(record.is_active),
                usage_count=usage.get((record.direction, record.name), 0),
            )
            for record in records
        ]

    # ------------------------------------------------------------------ 写入

    def createCategory(
        self, resource_type: str, direction: str, name: str
    ) -> CategoryWriteResult:
        """
        新增一个类型，排在所属分组末尾。

        Args:
            resource_type: 资源类型。
            direction: 方向。
            name: 类型名称，首尾空白会被去掉。

        Returns:
            写操作结果。

        Raises:
            ValidationError: 名称非法、重名或资源/方向非法时抛出。
        """
        self._validatePair(resource_type, direction)
        clean_name = self._validateName(name)
        self._ensureNameAvailable(resource_type, direction, clean_name)

        records = self._repository.findCategories(
            resource_type, direction, include_inactive=True
        )
        next_order = max((record.sort_order for record in records), default=0) + SORT_ORDER_STEP
        record = ResourceCategoryModel(
            resource_type=resource_type,
            direction=direction,
            name=clean_name,
            sort_order=next_order,
            is_active=1,
        )
        new_id = self._repository.insertCategory(record)
        return CategoryWriteResult(
            True,
            f"已新增：{self._groupLabel(resource_type, direction)} · {clean_name}",
            new_id,
        )

    def renameCategory(self, category_id: int, new_name: str) -> CategoryWriteResult:
        """
        改名，并在同一事务里同步已有关联明细的来源名。

        Args:
            category_id: 字典项 ID。
            new_name: 新名称，首尾空白会被去掉。

        Returns:
            写操作结果；名称未变化时返回 ``success=False`` 的提示，不写库。

        Raises:
            ValidationError: 名称非法、重名或字典项不存在时抛出。
            DatabaseError: 当写入失败时抛出。
        """
        current = self._requireCategory(category_id)
        clean_name = self._validateName(new_name)
        if clean_name == current.name:
            return CategoryWriteResult(False, "名称未变化")
        self._ensureNameAvailable(
            current.resource_type, current.direction, clean_name, exclude_id=category_id
        )

        with DatabaseContext(self._repository.dbPath) as conn:
            updated = self._repository.updateCategoryName(category_id, clean_name, conn)
            if not updated:
                raise ValidationError("类型不存在，可能已被修改，请刷新后重试")
            synced = self._repository.updateTransactionCategory(
                current.resource_type, current.direction, current.name, clean_name, conn
            )

        message = f"已改名：{current.name} → {clean_name}"
        if synced:
            message += f"（同步 {synced} 笔历史明细）"
        return CategoryWriteResult(True, message, category_id)

    def moveCategory(self, category_id: int, offset: int) -> CategoryWriteResult:
        """
        把类型在所属分组内上移（-1）或下移（+1），并整组重排序号。

        Args:
            category_id: 字典项 ID。
            offset: ``-1`` 上移，``1`` 下移。

        Returns:
            写操作结果；已在首 / 末位时返回 ``success=False`` 的提示，不写库。

        Raises:
            ValidationError: 偏移量非法或字典项不存在时抛出。
            DatabaseError: 当写入失败时抛出。
        """
        if offset not in (-1, 1):
            raise ValidationError("排序方向只能是上移或下移")
        current = self._requireCategory(category_id)
        records = self._repository.findCategories(
            current.resource_type, current.direction, include_inactive=True
        )
        index = next((i for i, record in enumerate(records) if record.id == category_id), -1)
        target = index + offset
        if index < 0:
            raise ValidationError("类型不存在，可能已被修改，请刷新后重试")
        if target < 0:
            return CategoryWriteResult(False, f"「{current.name}」已经是最前一项")
        if target >= len(records):
            return CategoryWriteResult(False, f"「{current.name}」已经是最后一项")

        records[index], records[target] = records[target], records[index]
        entries: List[Tuple[int, int]] = [
            (record.id, (position + 1) * SORT_ORDER_STEP)
            for position, record in enumerate(records)
        ]
        self._repository.updateCategorySortOrders(entries)
        action = "上移" if offset < 0 else "下移"
        return CategoryWriteResult(True, f"已{action}：{current.name}", current.id)

    def setCategoryActive(self, category_id: int, is_active: bool) -> CategoryWriteResult:
        """
        启用 / 停用一个类型。

        停用后该类型不再出现在常规录入下拉，历史明细与统计保留原名；
        每组至少保留一个启用中的类型。

        Args:
            category_id: 字典项 ID。
            is_active: True 启用，False 停用。

        Returns:
            写操作结果；状态未变化时返回 ``success=False`` 的提示，不写库。

        Raises:
            ValidationError: 会停用掉最后一个启用类型时抛出。
            DatabaseError: 当写入失败时抛出。
        """
        current = self._requireCategory(category_id)
        if bool(current.is_active) == bool(is_active):
            state = "启用" if is_active else "停用"
            return CategoryWriteResult(False, f"「{current.name}」已经是{state}状态")

        if not is_active:
            records = self._repository.findCategories(
                current.resource_type, current.direction, include_inactive=True
            )
            active_count = sum(1 for record in records if record.is_active)
            if active_count <= 1:
                raise ValidationError("每组至少保留一个启用中的类型，不能全部停用")

        self._repository.updateCategoryActive(category_id, is_active)
        if is_active:
            message = f"已启用：{current.name}"
        else:
            message = f"已停用：{current.name}（历史明细保留，录入下拉不再显示）"
        return CategoryWriteResult(True, message, category_id)

    # ------------------------------------------------------------------ 校验

    def _validatePair(self, resource_type: str, direction: str) -> None:
        """
        校验资源类型与方向。

        Args:
            resource_type: 资源类型。
            direction: 方向。

        Raises:
            ValidationError: 取值非法时抛出。
        """
        if resource_type not in RESOURCE_TYPES:
            raise ValidationError(f"未知的资源类型：{resource_type}")
        if direction not in RESOURCE_DIRECTIONS:
            raise ValidationError(f"未知的收支方向：{direction}")

    def _validateName(self, name: str) -> str:
        """
        校验并规范化类型名称。

        Args:
            name: 原始名称。

        Returns:
            去掉首尾空白后的名称。

        Raises:
            ValidationError: 名称为空或超长时抛出。
        """
        clean_name = (name or "").strip()
        if not clean_name:
            raise ValidationError("类型名称不能为空")
        if len(clean_name) > CATEGORY_NAME_MAX_LENGTH:
            raise ValidationError(f"类型名称不能超过 {CATEGORY_NAME_MAX_LENGTH} 个字符")
        return clean_name

    def _ensureNameAvailable(
        self,
        resource_type: str,
        direction: str,
        name: str,
        exclude_id: Optional[int] = None,
    ) -> None:
        """
        校验同一「资源 + 方向」下名称未被占用（含已停用的类型）。

        Args:
            resource_type: 资源类型。
            direction: 方向。
            name: 待校验名称。
            exclude_id: 改名时排除自身 ID。

        Raises:
            ValidationError: 名称已存在时抛出。
        """
        existing = self._repository.findCategoryByName(resource_type, direction, name)
        if existing is not None and existing.id != exclude_id:
            raise ValidationError(
                f"「{name}」已存在于{self._groupLabel(resource_type, direction)}"
            )

    def _requireCategory(self, category_id: int) -> ResourceCategoryModel:
        """
        读取字典项，不存在时给出可读错误。

        Args:
            category_id: 字典项 ID。

        Returns:
            字典模型。

        Raises:
            ValidationError: 字典项不存在时抛出。
        """
        current = self._repository.findCategoryById(category_id)
        if current is None:
            raise ValidationError("类型不存在，可能已被修改，请刷新后重试")
        return current

    @staticmethod
    def _groupLabel(resource_type: str, direction: str) -> str:
        """
        生成「魔方 · 支出」这类分组标签。

        Args:
            resource_type: 资源类型。
            direction: 方向。

        Returns:
            分组标签。
        """
        resource_name = RESOURCE_DISPLAY_NAMES.get(resource_type, resource_type)
        direction_name = RESOURCE_DIRECTION_NAMES.get(direction, direction)
        return f"{resource_name} · {direction_name}"
