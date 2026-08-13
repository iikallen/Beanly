from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from beanly.core.observability import metrics
from beanly.core.security.audit import SecurityAuditRecorder
from beanly.modules.menu.infrastructure.db.models import ProductModel
from beanly.modules.organizations.infrastructure.db.models import LocationModel
from beanly.modules.promotions.application.pricing_engine import (
    CustomDiscount,
    SelectedPromotion,
    price_order,
)
from beanly.modules.promotions.domain.entities import PricingItem
from beanly.modules.promotions.domain.enums import (
    DiscountKind,
    DiscountSource,
    PromotionScope,
    PromotionStatus,
)
from beanly.modules.promotions.domain.exceptions import (
    DiscountIdempotencyConflict,
    PromotionCodeUnavailable,
    PromotionNotFound,
)
from beanly.modules.promotions.infrastructure.db.models import (
    PromotionCodeModel,
    SalesOrderDiscountAllocationModel,
    SalesOrderDiscountModel,
)
from beanly.modules.promotions.infrastructure.db.repositories import SqlAlchemyPromotionRepository
from beanly.modules.sales.domain.enums import OrderStatus
from beanly.modules.sales.infrastructure.db.models import SalesOrderItemModel, SalesOrderModel


async def reprice_order(
    session: AsyncSession,
    organization_id: UUID,
    order_id: UUID,
    *,
    occurred_at: datetime | None = None,
    promotion_snapshot: tuple | None = None,
    manual_promotion_ids: tuple[UUID, ...] = (),
):
    started = datetime.now(UTC)
    metrics.promotion_evaluations_total.add(1)
    order = await session.scalar(
        select(SalesOrderModel)
        .where(SalesOrderModel.id == order_id, SalesOrderModel.organization_id == organization_id)
        .with_for_update()
    )
    if order is None:
        raise PromotionNotFound("Order not found")
    if order.status != OrderStatus.OPEN.value:
        return order
    item_rows = list(
        await session.scalars(
            select(SalesOrderItemModel)
            .where(SalesOrderItemModel.order_id == order_id)
            .order_by(SalesOrderItemModel.created_at, SalesOrderItemModel.id)
        )
    )
    product_ids = {item.product_id for item in item_rows}
    categories = (
        dict(
            (
                await session.execute(
                    select(ProductModel.id, ProductModel.category_id).where(
                        ProductModel.id.in_(product_ids)
                    )
                )
            ).all()
        )
        if product_ids
        else {}
    )
    location_timezone = await session.scalar(
        select(LocationModel.timezone).where(LocationModel.id == order.location_id)
    )
    if not location_timezone:
        raise ValueError("Order location timezone is missing")
    previous = list(
        await session.scalars(
            select(SalesOrderDiscountModel)
            .where(SalesOrderDiscountModel.order_id == order_id)
            .order_by(SalesOrderDiscountModel.sort_order)
        )
    )
    for intent in previous:
        if intent.source != DiscountSource.PROMO_CODE.value or not intent.promo_code_snapshot:
            continue
        code = await session.scalar(
            select(PromotionCodeModel)
            .where(
                PromotionCodeModel.organization_id == organization_id,
                PromotionCodeModel.code_normalized == intent.promo_code_snapshot,
                PromotionCodeModel.is_active.is_(True),
            )
            .with_for_update()
        )
        if code is None:
            raise PromotionCodeUnavailable("Promo code is unavailable")
        if code.max_redemptions is not None:
            paid = await session.scalar(
                select(func.count())
                .select_from(SalesOrderDiscountModel)
                .join(SalesOrderModel, SalesOrderModel.id == SalesOrderDiscountModel.order_id)
                .where(
                    SalesOrderDiscountModel.promo_code_snapshot == code.code_normalized,
                    SalesOrderModel.status == OrderStatus.PAID.value,
                )
            )
            if int(paid or 0) >= code.max_redemptions:
                raise PromotionCodeUnavailable("Promo code redemption limit reached")
    repo = SqlAlchemyPromotionRepository(session)
    promotions = promotion_snapshot or tuple(
        value
        for value in await repo.list(organization_id)
        if value.status == PromotionStatus.ACTIVE
    )
    by_id = {value.id: value for value in promotions}
    selected = tuple(
        SelectedPromotion(
            by_id[value.promotion_id],
            DiscountSource(value.source),
            value.client_discount_id,
            value.promo_code_snapshot,
            value.applied_by_user_id,
        )
        for value in previous
        if value.source in {DiscountSource.MANUAL.value, DiscountSource.PROMO_CODE.value}
        and value.promotion_id in by_id
    )
    selected += tuple(
        SelectedPromotion(by_id[promotion_id], DiscountSource.MANUAL)
        for promotion_id in manual_promotion_ids
        if promotion_id in by_id
    )
    custom = tuple(
        CustomDiscount(
            value.client_discount_id,
            DiscountKind(value.discount_kind),
            value.percent_rate,
            value.configured_amount_minor,
            value.reason or "",
            value.applied_by_user_id,
        )
        for value in previous
        if value.source == DiscountSource.CUSTOM.value
        and value.client_discount_id
        and value.applied_by_user_id
    )
    now = occurred_at or datetime.now(UTC)
    result = price_order(
        tuple(
            PricingItem(
                item.id,
                categories.get(item.product_id),
                item.product_id,
                item.product_variant_id,
                item.quantity,
                item.base_price_minor,
                item.modifier_price_minor,
            )
            for item in item_rows
        ),
        promotions,
        location_id=order.location_id,
        location_timezone=location_timezone,
        occurred_at=now,
        selected=selected,
        custom=custom,
    )
    await session.execute(
        delete(SalesOrderDiscountModel).where(SalesOrderDiscountModel.order_id == order_id)
    )
    for value in result.discounts:
        model = SalesOrderDiscountModel(
            id=value.id,
            order_id=order_id,
            client_discount_id=value.client_discount_id,
            promotion_id=value.promotion_id,
            source=value.source.value,
            promotion_name=value.promotion_name,
            discount_kind=value.discount_kind.value,
            scope=value.scope.value,
            percent_rate=value.percent_rate,
            configured_amount_minor=value.configured_amount_minor,
            promo_code_snapshot=value.promo_code_snapshot,
            reason=value.reason,
            applied_by_user_id=value.applied_by_user_id,
            applied_at=value.applied_at or now,
            discount_total_minor=value.discount_total_minor,
            promotion_config_hash=value.promotion_config_hash,
            sort_order=value.sort_order,
        )
        model.allocations = [
            SalesOrderDiscountAllocationModel(
                id=uuid4(),
                order_discount_id=value.id,
                order_item_id=item.order_item_id,
                eligible_amount_minor=item.eligible_amount_minor,
                discount_amount_minor=item.discount_amount_minor,
                sort_order=item.sort_order,
            )
            for item in value.allocations
        ]
        session.add(model)
    for item in item_rows:
        discount = result.item_discount_minor.get(item.id, 0)
        item.discount_amount_minor = discount
        item.net_line_total_minor = item.line_total_minor - discount
    order.subtotal_minor = result.subtotal_minor
    order.discount_total_minor = result.discount_total_minor
    order.total_minor = result.total_minor
    order.pricing_revision += 1
    order.priced_at = result.priced_at
    order.version += 1
    order.updated_at = now
    await session.flush()
    metrics.promotion_matches_total.add(len(result.discounts))
    metrics.discount_applications_total.add(len(result.discounts))
    metrics.discount_amount_total.add(result.discount_total_minor)
    metrics.pricing_duration_seconds.record((datetime.now(UTC) - started).total_seconds())
    return order


class OrderDiscountService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.audit = SecurityAuditRecorder(session)

    async def manual(
        self,
        organization_id: UUID,
        user_id: UUID,
        order_id: UUID,
        client_id: UUID,
        promotion_id: UUID,
    ):
        if await self._idempotency(order_id, client_id, promotion_id=promotion_id):
            return order_id
        promotion = await SqlAlchemyPromotionRepository(self.session).get(
            organization_id, promotion_id
        )
        if promotion is None or promotion.status != PromotionStatus.ACTIVE:
            raise PromotionNotFound("Active promotion not found")
        self._intent(
            order_id,
            client_id,
            promotion_id,
            DiscountSource.MANUAL,
            promotion.name,
            promotion.discount_kind,
            promotion.scope,
            promotion.percent_rate,
            promotion.amount_minor or promotion.fixed_price_minor,
            user_id,
        )
        await self._audit(organization_id, user_id, order_id, "MANUAL_DISCOUNT_APPLIED")
        return await self._finish(organization_id, order_id)

    async def code(
        self, organization_id: UUID, user_id: UUID, order_id: UUID, client_id: UUID, code: str
    ):
        metrics.promo_code_attempts_total.add(1)
        normalized = "".join(code.upper().split())
        if await self._idempotency(order_id, client_id, code=normalized):
            return order_id
        row = await self.session.scalar(
            select(PromotionCodeModel)
            .where(
                PromotionCodeModel.organization_id == organization_id,
                PromotionCodeModel.code_normalized == normalized,
                PromotionCodeModel.is_active.is_(True),
            )
            .with_for_update()
        )
        now = datetime.now(UTC)
        if (
            row is None
            or (row.valid_from and now < row.valid_from)
            or (row.valid_to and now >= row.valid_to)
        ):
            raise PromotionCodeUnavailable("Promo code is unavailable")
        if row.max_redemptions is not None:
            count = await self.session.scalar(
                select(func.count())
                .select_from(SalesOrderDiscountModel)
                .join(SalesOrderModel, SalesOrderModel.id == SalesOrderDiscountModel.order_id)
                .where(
                    SalesOrderDiscountModel.promo_code_snapshot == normalized,
                    SalesOrderModel.status == OrderStatus.PAID.value,
                )
            )
            if int(count or 0) >= row.max_redemptions:
                raise PromotionCodeUnavailable("Promo code redemption limit reached")
        promotion = await SqlAlchemyPromotionRepository(self.session).get(
            organization_id, row.promotion_id
        )
        if promotion is None or promotion.status != PromotionStatus.ACTIVE:
            raise PromotionCodeUnavailable("Promo code promotion is unavailable")
        self._intent(
            order_id,
            client_id,
            promotion.id,
            DiscountSource.PROMO_CODE,
            promotion.name,
            promotion.discount_kind,
            promotion.scope,
            promotion.percent_rate,
            promotion.amount_minor or promotion.fixed_price_minor,
            user_id,
            code=normalized,
        )
        await self._audit(organization_id, user_id, order_id, "PROMO_CODE_APPLIED")
        return await self._finish(organization_id, order_id)

    async def custom(
        self,
        organization_id: UUID,
        user_id: UUID,
        order_id: UUID,
        client_id: UUID,
        kind: DiscountKind,
        percent: Decimal | None,
        amount: int | None,
        reason: str,
    ):
        if await self._idempotency(
            order_id, client_id, kind=kind.value, percent=percent, amount=amount, reason=reason
        ):
            return order_id
        self._intent(
            order_id,
            client_id,
            None,
            DiscountSource.CUSTOM,
            "Custom discount",
            kind,
            PromotionScope.ORDER,
            percent,
            amount,
            user_id,
            reason=reason,
        )
        metrics.custom_discount_total.add(amount or 0)
        await self._audit(
            organization_id,
            user_id,
            order_id,
            "CUSTOM_DISCOUNT_APPLIED",
            {"reason": reason, "configured_amount_minor": amount or 0},
        )
        return await self._finish(organization_id, order_id)

    async def remove(self, organization_id: UUID, order_id: UUID, discount_id: UUID):
        await self.session.execute(
            delete(SalesOrderDiscountModel).where(
                SalesOrderDiscountModel.id == discount_id,
                SalesOrderDiscountModel.order_id == order_id,
            )
        )
        await self.audit.record(
            action="DISCOUNT_REMOVED",
            resource_type="sales_order",
            organization_id=organization_id,
            resource_id=order_id,
            metadata={"discount_id": str(discount_id)},
        )
        return await self._finish(organization_id, order_id)

    async def _audit(
        self,
        organization_id: UUID,
        user_id: UUID,
        order_id: UUID,
        action: str,
        metadata: dict[str, object] | None = None,
    ) -> None:
        await self.audit.record(
            action=action,
            resource_type="sales_order",
            organization_id=organization_id,
            actor_user_id=user_id,
            resource_id=order_id,
            metadata=metadata,
        )

    async def _idempotency(self, order_id: UUID, client_id: UUID, **payload):
        existing = await self.session.scalar(
            select(SalesOrderDiscountModel).where(
                SalesOrderDiscountModel.order_id == order_id,
                SalesOrderDiscountModel.client_discount_id == client_id,
            )
        )
        if existing is None:
            return False
        same = all(
            getattr(
                existing,
                {
                    "promotion_id": "promotion_id",
                    "code": "promo_code_snapshot",
                    "kind": "discount_kind",
                    "percent": "percent_rate",
                    "amount": "configured_amount_minor",
                    "reason": "reason",
                }[key],
            )
            == value
            for key, value in payload.items()
        )
        if same:
            return True
        raise DiscountIdempotencyConflict("client_discount_id was used with a different payload")

    def _intent(
        self,
        order_id,
        client_id,
        promotion_id,
        source,
        name,
        kind,
        scope,
        percent,
        amount,
        user_id,
        *,
        code=None,
        reason=None,
    ):
        self.session.add(
            SalesOrderDiscountModel(
                id=uuid4(),
                order_id=order_id,
                client_discount_id=client_id,
                promotion_id=promotion_id,
                source=source.value,
                promotion_name=name,
                discount_kind=kind.value,
                scope=scope.value,
                percent_rate=percent,
                configured_amount_minor=amount,
                promo_code_snapshot=code,
                reason=reason,
                applied_by_user_id=user_id,
                applied_at=datetime.now(UTC),
                discount_total_minor=0,
                promotion_config_hash="intent",
                sort_order=999,
            )
        )

    async def _finish(self, organization_id, order_id):
        try:
            await reprice_order(self.session, organization_id, order_id)
            await self.session.commit()
            return order_id
        except Exception:
            await self.session.rollback()
            raise
