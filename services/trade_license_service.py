"""
贸易许可证业务逻辑层模块。

负责剩余天数计算、购买 / 续约、期初登记与最近一条记录的修正 / 删除。
每次购买 / 续约写入 500 红尖尖收入，并与购买记录放在同一事务。
"""

from datetime import date, datetime, timedelta
from typing import Optional

from models.resource_model import ResourceTransactionModel
from models.trade_license_model import (
    TradeLicensePurchaseModel, TradeLicenseResult, TradeLicenseStatus,
)
from repositories.resource_repository import ResourceRepository
from repositories.trade_license_repository import TradeLicenseRepository
from utils import time_source
from utils.constants import (
    RECORD_DATE_FORMAT, RECORD_TIME_FORMAT, RESOURCE_DIRECTION_INCOME,
    RESOURCE_TYPE_RED_GEM, TRADE_LICENSE_CATEGORY, TRADE_LICENSE_DAYS,
    TRADE_LICENSE_RENEWAL_WINDOW_DAYS, TRADE_LICENSE_REWARD,
)
from utils.db_connection import DatabaseContext
from utils.db_schema import isMissingColumnError, isMissingTableError
from utils.exceptions import DatabaseError, ValidationError


class TradeLicenseService:
    """贸易许可证服务类。"""

    def __init__(
        self,
        repository: Optional[TradeLicenseRepository] = None,
        resource_repository: Optional[ResourceRepository] = None,
    ):
        """
        初始化贸易许可证服务。

        Args:
            repository: 购买记录数据访问实例。
            resource_repository: 资源明细数据访问实例。
        """
        self._repository = repository or TradeLicenseRepository()
        self._resource_repository = resource_repository or ResourceRepository()

    # ------------------------------------------------------------- 查询

    def getStatus(self, today: Optional[date] = None) -> TradeLicenseStatus:
        """
        获取当前贸易许可证状态。

        Args:
            today: 今天；默认取时间源。

        Returns:
            当前状态；表缺失时按未购买降级。
        """
        try:
            latest = self._repository.findLatest()
        except DatabaseError as e:
            if isMissingTableError(e) or isMissingColumnError(e):
                return TradeLicenseStatus(False, 0, None, True)
            raise
        return self._buildStatus(latest, today or time_source.today())

    def _buildStatus(
        self, latest: Optional[TradeLicensePurchaseModel], today: date
    ) -> TradeLicenseStatus:
        """
        由最近一条记录构造状态。

        Args:
            latest: 最近购买记录。
            today: 今天。

        Returns:
            状态对象。
        """
        if latest is None:
            return TradeLicenseStatus(False, 0, None, True)
        end = date.fromisoformat(latest.end_date)
        remaining = max(0, (end - today).days + 1)
        return TradeLicenseStatus(
            has_purchase=True,
            remaining_days=remaining,
            expire_date=latest.end_date,
            can_renew=remaining <= TRADE_LICENSE_RENEWAL_WINDOW_DAYS,
            last_purchase_time=latest.purchase_time,
        )

    # ------------------------------------------------------------- 写操作

    def renew(self, at: Optional[datetime] = None) -> TradeLicenseResult:
        """
        购买 / 续约一次：写入 500 红尖尖并顺延 30 天。

        Args:
            at: 操作时刻，默认当前时间；测试可传固定时刻。

        Returns:
            操作结果。

        Raises:
            ValidationError: 剩余天数大于 7、尚未到续约窗口时抛出。
            DatabaseError: 数据库写入失败时抛出。
        """
        moment = at or time_source.now()
        today = moment.date()
        status = self.getStatus(today)
        if not status.can_renew:
            raise ValidationError(
                f"当前剩余 {status.remaining_days} 天，"
                f"剩余 {TRADE_LICENSE_RENEWAL_WINDOW_DAYS} 天及以下才可续约"
            )

        if status.has_purchase and status.expire_date:
            current_end = date.fromisoformat(status.expire_date)
            start = current_end + timedelta(days=1) if current_end >= today else today
        else:
            start = today
        end = start + timedelta(days=TRADE_LICENSE_DAYS - 1)

        record_time_text = moment.strftime(RECORD_TIME_FORMAT)
        transaction = ResourceTransactionModel(
            resource_type=RESOURCE_TYPE_RED_GEM,
            direction=RESOURCE_DIRECTION_INCOME,
            record_time=record_time_text,
            category=TRADE_LICENSE_CATEGORY,
            amount=TRADE_LICENSE_REWARD,
            note=f"贸易许可证（{TRADE_LICENSE_DAYS} 天，至 {end:%Y-%m-%d}）",
        )
        purchase = TradeLicensePurchaseModel(
            purchase_time=record_time_text,
            start_date=start.strftime(RECORD_DATE_FORMAT),
            end_date=end.strftime(RECORD_DATE_FORMAT),
            days=TRADE_LICENSE_DAYS,
            amount=TRADE_LICENSE_REWARD,
            note="贸易许可证购买 / 续约",
        )

        with DatabaseContext(self._repository.dbPath) as conn:
            transaction_id = self._resource_repository.insertTransaction(transaction, conn)
            self._resource_repository.upsertDetailDaily(
                RESOURCE_TYPE_RED_GEM, today.strftime(RECORD_DATE_FORMAT),
                record_time_text, conn,
            )
            self._resource_repository.recomputeLastRecordTime(
                RESOURCE_TYPE_RED_GEM, today.strftime(RECORD_DATE_FORMAT), conn
            )
            purchase.transaction_id = transaction_id
            self._repository.insert(purchase, conn)

        new_status = self.getStatus(today)
        return TradeLicenseResult(
            success=True,
            message=(
                f"贸易许可证已续约：+{TRADE_LICENSE_REWARD} 红尖尖，"
                f"到期日 {end:%Y-%m-%d}"
            ),
            status=new_status,
        )

    def registerInitialExpiry(
        self, expire_date: date, at: Optional[datetime] = None
    ) -> TradeLicenseResult:
        """
        登记当前已在使用的月卡到期日（不产生 500 红尖尖）。

        Args:
            expire_date: 当前到期日。
            at: 登记时刻，默认当前时间。

        Returns:
            操作结果。

        Raises:
            ValidationError: 已有记录，或到期日早于今天时抛出。
            DatabaseError: 数据库写入失败时抛出。
        """
        if self._repository.findLatest() is not None:
            raise ValidationError("已有贸易许可证记录，请使用「修正到期日」")
        moment = at or time_source.now()
        today = moment.date()
        if expire_date < today:
            raise ValidationError("到期日不能早于今天")

        start = expire_date - timedelta(days=TRADE_LICENSE_DAYS - 1)
        purchase = TradeLicensePurchaseModel(
            purchase_time=moment.strftime(RECORD_TIME_FORMAT),
            start_date=start.strftime(RECORD_DATE_FORMAT),
            end_date=expire_date.strftime(RECORD_DATE_FORMAT),
            days=TRADE_LICENSE_DAYS,
            amount=0,
            transaction_id=None,
            note="期初登记",
        )
        self._repository.insert(purchase)
        new_status = self.getStatus(today)
        return TradeLicenseResult(
            success=True,
            message=f"已登记贸易许可证到期日：{expire_date:%Y-%m-%d}",
            status=new_status,
        )

    def updateLatestEndDate(
        self, new_end_date: date, at: Optional[datetime] = None
    ) -> TradeLicenseResult:
        """
        修正最近一条记录的到期日。

        Args:
            new_end_date: 新到期日。
            at: 操作时刻，默认当前时间。

        Returns:
            操作结果。

        Raises:
            ValidationError: 无记录或到期日早于生效日时抛出。
            DatabaseError: 数据库写入失败时抛出。
        """
        latest = self._repository.findLatest()
        if latest is None:
            raise ValidationError("暂无贸易许可证记录")
        start = date.fromisoformat(latest.start_date)
        if latest.amount == 0:
            # 期初登记按 30 天卡处理，改到期日时同步反推生效日
            start = new_end_date - timedelta(days=TRADE_LICENSE_DAYS - 1)
        if new_end_date < start:
            raise ValidationError("到期日不能早于生效日")

        days = (new_end_date - start).days + 1
        self._repository.updateDates(
            latest.id,
            start.strftime(RECORD_DATE_FORMAT),
            new_end_date.strftime(RECORD_DATE_FORMAT),
            days,
        )
        moment = at or time_source.now()
        new_status = self.getStatus(moment.date())
        return TradeLicenseResult(
            success=True,
            message=f"贸易许可证到期日已修正为 {new_end_date:%Y-%m-%d}",
            status=new_status,
        )

    def deleteLatest(self) -> TradeLicenseResult:
        """
        删除最近一条记录；若关联 500 红尖尖明细，一并回滚。

        Returns:
            操作结果。

        Raises:
            ValidationError: 无记录时抛出。
            DatabaseError: 数据库写入失败时抛出。
        """
        latest = self._repository.findLatest()
        if latest is None:
            raise ValidationError("暂无贸易许可证记录")

        transaction = None
        if latest.transaction_id is not None:
            transaction = self._resource_repository.findTransactionById(latest.transaction_id)
        target_date = (
            transaction.record_time[:10] if transaction is not None
            else latest.start_date
        )

        with DatabaseContext(self._repository.dbPath) as conn:
            if transaction is not None:
                self._resource_repository.deleteTransaction(transaction.id, conn)
                self._resource_repository.recomputeLastRecordTime(
                    RESOURCE_TYPE_RED_GEM, target_date, conn
                )
            self._repository.delete(latest.id, conn)

        new_status = self.getStatus()
        message = "已删除最近一条贸易许可证记录"
        if transaction is not None:
            message += f"，并回滚 {transaction.amount} 红尖尖"
        return TradeLicenseResult(success=True, message=message, status=new_status)
