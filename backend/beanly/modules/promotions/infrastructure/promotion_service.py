from dataclasses import replace
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from beanly.core.observability import metrics
from beanly.core.security.audit import SecurityAuditRecorder
from beanly.modules.analytics.infrastructure.db.models import AnalyticsPromotionsDailyModel
from beanly.modules.menu.infrastructure.db.models import (
    MenuCategoryModel,
    ProductModel,
    ProductVariantModel,
)
from beanly.modules.organizations.application.services.organization_service import (
    OrganizationService,
)
from beanly.modules.organizations.domain.entities import TenantContext
from beanly.modules.organizations.domain.exceptions import OrganizationAccessDenied
from beanly.modules.organizations.infrastructure.db.models import LocationModel
from beanly.modules.promotions.application.pricing_engine import SelectedPromotion, price_order
from beanly.modules.promotions.domain.entities import (
    PricingItem,
    Promotion,
    PromotionSchedule,
    PromotionTarget,
)
from beanly.modules.promotions.domain.enums import (
    DiscountSource,
    PromotionStatus,
    TargetType,
)
from beanly.modules.promotions.domain.exceptions import PromotionConflict, PromotionNotFound
from beanly.modules.promotions.infrastructure.db.models import PromotionCodeModel
from beanly.modules.promotions.infrastructure.db.repositories import SqlAlchemyPromotionRepository


class PromotionService:
    def __init__(self, session: AsyncSession, organizations: OrganizationService) -> None:
        self.session = session
        self.organizations = organizations
        self.repository = SqlAlchemyPromotionRepository(session)
        self.audit = SecurityAuditRecorder(session)

    async def list(self, context: TenantContext) -> list[Promotion]:
        values = await self.repository.list(context.organization_id)
        allowed = await self._accessible_location_ids(context)
        return [
            value
            for value in values
            if value.all_locations or bool(allowed.intersection(value.location_ids))
        ]

    async def get(self, context: TenantContext, promotion_id: UUID) -> Promotion:
        value = await self.repository.get(context.organization_id, promotion_id)
        if value is None:
            raise PromotionNotFound("Promotion not found")
        if not value.all_locations and not (
            await self._accessible_location_ids(context)
        ).intersection(value.location_ids):
            raise PromotionNotFound("Promotion not found")
        return value

    async def performance(
        self,
        context: TenantContext,
        date_from: date,
        date_to: date,
        location_id: UUID | None,
    ):
        allowed = await self._accessible_location_ids(context)
        if location_id is not None and location_id not in allowed:
            raise PromotionNotFound("Location not found")
        locations = (location_id,) if location_id else tuple(allowed)
        if not locations:
            return []
        rows = await self.session.execute(
            select(
                AnalyticsPromotionsDailyModel.promotion_id,
                AnalyticsPromotionsDailyModel.promotion_name,
                func.sum(AnalyticsPromotionsDailyModel.orders_count),
                func.sum(AnalyticsPromotionsDailyModel.applications_count),
                func.sum(AnalyticsPromotionsDailyModel.items_count),
                func.sum(AnalyticsPromotionsDailyModel.gross_eligible_amount),
                func.sum(AnalyticsPromotionsDailyModel.discount_amount),
                func.sum(AnalyticsPromotionsDailyModel.net_revenue_amount),
                func.sum(AnalyticsPromotionsDailyModel.refund_amount),
            )
            .where(
                AnalyticsPromotionsDailyModel.organization_id == context.organization_id,
                AnalyticsPromotionsDailyModel.location_id.in_(locations),
                AnalyticsPromotionsDailyModel.local_date >= date_from,
                AnalyticsPromotionsDailyModel.local_date <= date_to,
            )
            .group_by(
                AnalyticsPromotionsDailyModel.promotion_id,
                AnalyticsPromotionsDailyModel.promotion_name,
            )
            .order_by(func.sum(AnalyticsPromotionsDailyModel.discount_amount).desc())
        )
        return list(rows)

    async def create(self, context: TenantContext, payload: Any) -> Promotion:
        await self._validate_payload(context, payload)
        now, promotion_id = datetime.now(UTC), uuid4()
        value = Promotion(
            promotion_id,
            context.organization_id,
            payload.name.strip(),
            payload.pos_name.strip(),
            PromotionStatus.DRAFT,
            payload.application_mode,
            payload.discount_kind,
            payload.scope,
            payload.percent_rate,
            payload.amount_minor,
            payload.fixed_price_minor,
            payload.priority,
            payload.stacking_policy,
            payload.include_modifier_price,
            payload.minimum_subtotal_minor,
            payload.maximum_discount_minor,
            payload.valid_from,
            payload.valid_to,
            payload.all_locations,
            payload.requires_override_permission,
            context.user_id,
            now,
            now,
            tuple(payload.location_ids),
            tuple(
                PromotionSchedule(
                    uuid4(), promotion_id, item.weekday, item.start_local_time, item.end_local_time
                )
                for item in payload.schedules
            ),
            tuple(
                PromotionTarget(
                    uuid4(),
                    promotion_id,
                    item.role,
                    item.target_type,
                    item.target_id,
                    item.quantity,
                    item.sort_order,
                )
                for item in payload.targets
            ),
        )
        return await self._save(context, value, "PROMOTION_CREATED")

    async def update(self, context: TenantContext, promotion_id: UUID, payload: Any) -> Promotion:
        current = await self.get(context, promotion_id)
        if current.status == PromotionStatus.ARCHIVED:
            raise PromotionConflict("Archived promotions are immutable")
        await self._validate_payload(context, payload)
        value = replace(
            current,
            name=payload.name.strip(),
            pos_name=payload.pos_name.strip(),
            application_mode=payload.application_mode,
            discount_kind=payload.discount_kind,
            scope=payload.scope,
            percent_rate=payload.percent_rate,
            amount_minor=payload.amount_minor,
            fixed_price_minor=payload.fixed_price_minor,
            priority=payload.priority,
            stacking_policy=payload.stacking_policy,
            include_modifier_price=payload.include_modifier_price,
            minimum_subtotal_minor=payload.minimum_subtotal_minor,
            maximum_discount_minor=payload.maximum_discount_minor,
            valid_from=payload.valid_from,
            valid_to=payload.valid_to,
            all_locations=payload.all_locations,
            requires_override_permission=payload.requires_override_permission,
            updated_at=datetime.now(UTC),
            location_ids=tuple(payload.location_ids),
            schedules=tuple(
                PromotionSchedule(
                    uuid4(), promotion_id, item.weekday, item.start_local_time, item.end_local_time
                )
                for item in payload.schedules
            ),
            targets=tuple(
                PromotionTarget(
                    uuid4(),
                    promotion_id,
                    item.role,
                    item.target_type,
                    item.target_id,
                    item.quantity,
                    item.sort_order,
                )
                for item in payload.targets
            ),
        )
        return await self._save(context, value, "PROMOTION_UPDATED")

    async def set_status(
        self, context: TenantContext, promotion_id: UUID, status: PromotionStatus
    ) -> Promotion:
        current = await self.get(context, promotion_id)
        if current.status == PromotionStatus.ARCHIVED:
            raise PromotionConflict("Archived promotions are immutable")
        if current.status == status:
            return current
        try:
            saved = await self.repository.save(
                replace(current, status=status, updated_at=datetime.now(UTC))
            )
            action = (
                "PROMOTION_ACTIVATED" if status == PromotionStatus.ACTIVE else "PROMOTION_ARCHIVED"
            )
            await self._audit(context, action, saved.id)
            await self.session.commit()
            if current.status == PromotionStatus.ACTIVE or status == PromotionStatus.ACTIVE:
                metrics.promotions_active.add(1 if status == PromotionStatus.ACTIVE else -1)
            return saved
        except Exception:
            await self.session.rollback()
            raise

    async def preview(self, context: TenantContext, promotion_id: UUID, payload: Any):
        promotion = await self.get(context, promotion_id)
        try:
            await self.organizations.ensure_location_access(context, payload.location_id)
        except OrganizationAccessDenied as exc:
            raise PromotionNotFound("Location not found") from exc
        timezone = await self.session.scalar(
            select(LocationModel.timezone).where(
                LocationModel.organization_id == context.organization_id,
                LocationModel.id == payload.location_id,
            )
        )
        if timezone is None:
            raise PromotionNotFound("Location not found")
        preview = replace(promotion, status=PromotionStatus.ACTIVE)
        return price_order(
            tuple(PricingItem(**item.model_dump()) for item in payload.items),
            (preview,),
            location_id=payload.location_id,
            location_timezone=timezone,
            occurred_at=payload.occurred_at,
            selected=(
                SelectedPromotion(
                    preview, DiscountSource.MANUAL, applied_by_user_id=context.user_id
                ),
            ),
        )

    async def add_code(self, context: TenantContext, promotion_id: UUID, payload: Any) -> Promotion:
        promotion = await self.get(context, promotion_id)
        if promotion.status == PromotionStatus.ARCHIVED:
            raise PromotionConflict("Archived promotions are immutable")
        normalized = "".join(payload.code.upper().split())
        if not normalized:
            raise PromotionConflict("Promo code is empty")
        existing = await self.session.scalar(
            select(PromotionCodeModel.id).where(
                PromotionCodeModel.organization_id == context.organization_id,
                PromotionCodeModel.code_normalized == normalized,
            )
        )
        if existing:
            raise PromotionConflict("Promo code already exists")
        try:
            self.session.add(
                PromotionCodeModel(
                    id=uuid4(),
                    organization_id=context.organization_id,
                    promotion_id=promotion.id,
                    code_normalized=normalized,
                    is_active=True,
                    valid_from=payload.valid_from,
                    valid_to=payload.valid_to,
                    max_redemptions=payload.max_redemptions,
                    created_at=datetime.now(UTC),
                )
            )
            await self.session.commit()
            return await self.get(context, promotion_id)
        except Exception:
            await self.session.rollback()
            raise

    async def delete_code(
        self, context: TenantContext, promotion_id: UUID, code_id: UUID
    ) -> Promotion:
        promotion = await self.get(context, promotion_id)
        if promotion.status == PromotionStatus.ARCHIVED:
            raise PromotionConflict("Archived promotions are immutable")
        try:
            result = await self.session.execute(
                delete(PromotionCodeModel).where(
                    PromotionCodeModel.id == code_id,
                    PromotionCodeModel.promotion_id == promotion_id,
                    PromotionCodeModel.organization_id == context.organization_id,
                )
            )
            if result.rowcount != 1:
                raise PromotionNotFound("Promo code not found")
            await self.session.commit()
            return await self.get(context, promotion_id)
        except Exception:
            await self.session.rollback()
            raise

    async def _save(self, context: TenantContext, value: Promotion, action: str) -> Promotion:
        try:
            saved = await self.repository.save(value)
            await self._audit(context, action, saved.id)
            await self.session.commit()
            return saved
        except Exception:
            await self.session.rollback()
            raise

    async def _accessible_location_ids(self, context: TenantContext) -> set[UUID]:
        membership = await self.organizations.repository.get_membership(
            context.organization_id, context.user_id
        )
        if membership is None:
            return set()
        return {
            value.id
            for value in await self.organizations.repository.list_accessible_locations(membership)
        }

    async def _validate_payload(self, context: TenantContext, payload: Any) -> None:
        for location_id in payload.location_ids:
            try:
                await self.organizations.ensure_location_access(context, location_id)
            except OrganizationAccessDenied as exc:
                raise PromotionNotFound("Location not found") from exc
        for target in payload.targets:
            if target.target_type == TargetType.ALL:
                continue
            model, where = {
                TargetType.CATEGORY: (
                    MenuCategoryModel,
                    MenuCategoryModel.organization_id == context.organization_id,
                ),
                TargetType.PRODUCT: (
                    ProductModel,
                    ProductModel.organization_id == context.organization_id,
                ),
                TargetType.VARIANT: (
                    ProductVariantModel,
                    ProductVariantModel.organization_id == context.organization_id,
                ),
            }[target.target_type]
            found = await self.session.scalar(
                select(model.id).where(model.id == target.target_id, where)
            )
            if found is None:
                raise PromotionNotFound("Promotion target not found")

    async def _audit(self, context: TenantContext, action: str, resource_id: UUID) -> None:
        await self.audit.record(
            action=action,
            resource_type="promotion",
            organization_id=context.organization_id,
            actor_user_id=context.user_id,
            resource_id=resource_id,
        )
