"""
贸易许可证数据模型模块。

定义购买 / 续约记录与当前状态结果对象。
"""

from dataclasses import dataclass
from datetime import date
from typing import Optional

from models.base_model import BaseModel
from utils.constants import TRADE_LICENSE_RENEWAL_WINDOW_DAYS


@dataclass
class TradeLicensePurchaseModel(BaseModel):
    """
    贸易许可证购买 / 续约记录。

    对应 ``trade_license_purchase`` 表。

    Attributes:
        id: 记录 ID。
        purchase_time: 购买 / 续约时刻 ``yyyy-MM-dd HH:mm:ss``。
        start_date: 生效日 ``yyyy-MM-dd``（含当天）。
        end_date: 到期日 ``yyyy-MM-dd``（含当天）。
        days: 本次时长（天）。
        amount: 本次记入的红尖尖数量；期初登记为 0。
        transaction_id: 关联的 500 红尖尖明细 ID；期初登记为空。
        note: 备注。
        created_at: 创建时间。
    """

    id: Optional[int] = None
    purchase_time: str = ""
    start_date: str = ""
    end_date: str = ""
    days: int = 30
    amount: int = 500
    transaction_id: Optional[int] = None
    note: str = ""
    created_at: Optional[str] = None


@dataclass
class TradeLicenseStatus:
    """
    贸易许可证当前状态。

    Attributes:
        has_purchase: 是否存在购买 / 期初登记记录。
        remaining_days: 剩余天数（含今天；无记录或过期时为 0）。
        expire_date: 到期日 ``yyyy-MM-dd``；无记录时为 None。
        can_renew: 是否允许购买 / 续约。
        last_purchase_time: 最近一次购买 / 续约时刻。
    """

    has_purchase: bool
    remaining_days: int
    expire_date: Optional[str]
    can_renew: bool
    last_purchase_time: Optional[str] = None

    def recalculate(self, today: date) -> "TradeLicenseStatus":
        """
        按指定日期重算剩余天数与续约状态（不查库）。

        Args:
            today: 今天。

        Returns:
            新的状态对象。
        """
        if not self.has_purchase or not self.expire_date:
            return TradeLicenseStatus(
                has_purchase=False,
                remaining_days=0,
                expire_date=None,
                can_renew=True,
                last_purchase_time=self.last_purchase_time,
            )

        end = date.fromisoformat(self.expire_date)
        remaining = max(0, (end - today).days + 1)
        return TradeLicenseStatus(
            has_purchase=True,
            remaining_days=remaining,
            expire_date=self.expire_date,
            can_renew=remaining <= TRADE_LICENSE_RENEWAL_WINDOW_DAYS,
            last_purchase_time=self.last_purchase_time,
        )


@dataclass
class TradeLicenseResult:
    """
    贸易许可证写操作结果。

    Attributes:
        success: 是否成功。
        message: 面向用户的提示文案。
        status: 操作后的状态。
    """

    success: bool
    message: str
    status: Optional[TradeLicenseStatus] = None

    def toStatusBarMessage(self) -> str:
        """
        状态栏文案。

        Returns:
            提示文案。
        """
        return self.message
