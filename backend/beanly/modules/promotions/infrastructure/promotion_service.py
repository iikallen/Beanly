from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from beanly.core.observability import metrics
from beanly.core.security.audit import SecurityAuditRecorder
from beanly.modules.organizations.domain.entities import TenantContext
from beanly.modules.promotions.domain.entities import Promotion, PromotionSchedule, PromotionTarget
from beanly.modules.promotions.domain.enums import PromotionStatus
from beanly.modules.promotions.domain.exceptions import PromotionConflict, PromotionNotFound
from beanly.modules.promotions.infrastructure.db.models import PromotionCodeModel
from beanly.modules.promotions.infrastructure.db.repositories import SqlAlchemyPromotionRepository


class PromotionService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = SqlAlchemyPromotionRepository(session)
        self.audit = SecurityAuditRecorder(session)

    async def list(self, context: TenantContext) -> list[Promotion]:
        return await self.repository.list(context.organization_id)

    async def get(self, context: TenantContext, promotion_id: UUID) -> Promotion:
        value = await self.repository.get(context.organization_id, promotion_id)
        if value is None:
            raise PromotionNotFound("Promotion not found")
        return value

    async def create(self, context: TenantContext, payload: Any) -> Promotion:
        now = datetime.now(UTC)
        promotion_id = uuid4()
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
        saved = await self.repository.save(value)
        await self._audit(context, "PROMOTION_CREATED", saved.id)
        await self.session.commit()
        return saved

    async def update(self, context: TenantContext, promotion_id: UUID, payload: Any) -> Promotion:
        current = await self.get(context, promotion_id)
        if current.status == PromotionStatus.ARCHIVED:
            raise PromotionConflict("Archived promotions are immutable")
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
        saved = await self.repository.save(value)
        await self._audit(context, "PROMOTION_UPDATED", saved.id)
        await self.session.commit()
        return saved

    async def set_status(
        self, context: TenantContext, promotion_id: UUID, status: PromotionStatus
    ) -> Promotion:
        current = await self.get(context, promotion_id)
        if current.status == PromotionStatus.ARCHIVED:
            raise PromotionConflict("Archived promotions are immutable")
        saved = await self.repository.save(
            replace(current, status=status, updated_at=datetime.now(UTC))
        )
        action = "PROMOTION_ACTIVATED" if status == PromotionStatus.ACTIVE else "PROMOTION_ARCHIVED"
        await self._audit(context, action, saved.id)
        metrics.promotions_active.add(1 if status == PromotionStatus.ACTIVE else -1)
        await self.session.commit()
        return saved

    async def add_code(self, context: TenantContext, promotion_id: UUID, payload: Any) -> Promotion:
        promotion = await self.get(context, promotion_id)
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

    async def delete_code(
        self, context: TenantContext, promotion_id: UUID, code_id: UUID
    ) -> Promotion:
        await self.get(context, promotion_id)
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

    async def _commit(self, operation):
        try:
            value = await operation
            await self.session.commit()
            return value
        except Exception:
            await self.session.rollback()
            raise

    async def _audit(self, context: TenantContext, action: str, resource_id: UUID) -> None:
        await self.audit.record(
            action=action,
            resource_type="promotion",
            organization_id=context.organization_id,
            actor_user_id=context.user_id,
            resource_id=resource_id,
        )
