from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from beanly.modules.promotions.domain.entities import (
    Promotion,
    PromotionCode,
    PromotionSchedule,
    PromotionTarget,
)
from beanly.modules.promotions.domain.enums import (
    ApplicationMode,
    DiscountKind,
    PromotionChannel,
    PromotionScope,
    PromotionStatus,
    StackingPolicy,
    TargetRole,
    TargetType,
)
from beanly.modules.promotions.infrastructure.db.models import PromotionModel


class SqlAlchemyPromotionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(self, organization_id: UUID) -> list[Promotion]:
        values = await self.session.scalars(
            self._query(organization_id).order_by(PromotionModel.created_at.desc())
        )
        return [_promotion(value) for value in values]

    async def get(
        self, organization_id: UUID, promotion_id: UUID, *, lock: bool = False
    ) -> Promotion | None:
        query = self._query(organization_id).where(PromotionModel.id == promotion_id)
        if lock:
            query = query.with_for_update()
        value = await self.session.scalar(query)
        return _promotion(value) if value else None

    async def save(self, value: Promotion) -> Promotion:
        model = await self.session.scalar(
            self._query(value.organization_id).where(PromotionModel.id == value.id)
        )
        if model is None:
            model = PromotionModel(id=value.id, organization_id=value.organization_id)
            self.session.add(model)
        for field in (
            "name",
            "pos_name",
            "priority",
            "include_modifier_price",
            "minimum_subtotal_minor",
            "maximum_discount_minor",
            "valid_from",
            "valid_to",
            "all_locations",
            "requires_override_permission",
            "created_by",
            "created_at",
            "updated_at",
        ):
            setattr(model, field, getattr(value, field))
        for field in ("status", "application_mode", "discount_kind", "scope", "stacking_policy"):
            setattr(model, field, getattr(value, field).value)
        model.percent_rate = value.percent_rate
        model.amount_minor = value.amount_minor
        model.fixed_price_minor = value.fixed_price_minor
        from beanly.modules.promotions.infrastructure.db.models import (
            PromotionChannelModel,
            PromotionLocationModel,
            PromotionScheduleModel,
            PromotionTargetModel,
        )

        model.channels = [
            PromotionChannelModel(promotion_id=value.id, channel=channel.value)
            for channel in value.channels
        ]

        model.locations = [
            PromotionLocationModel(promotion_id=value.id, location_id=location_id)
            for location_id in value.location_ids
        ]
        model.schedules = [
            PromotionScheduleModel(
                id=item.id,
                promotion_id=value.id,
                weekday=item.weekday,
                start_local_time=item.start_local_time,
                end_local_time=item.end_local_time,
            )
            for item in value.schedules
        ]
        model.targets = [
            PromotionTargetModel(
                id=item.id,
                promotion_id=value.id,
                role=item.role.value,
                target_type=item.target_type.value,
                target_id=item.target_id,
                quantity=item.quantity,
                sort_order=item.sort_order,
            )
            for item in value.targets
        ]
        await self.session.flush()
        saved = await self.get(value.organization_id, value.id)
        assert saved is not None
        return saved

    def _query(self, organization_id: UUID):
        return (
            select(PromotionModel)
            .where(PromotionModel.organization_id == organization_id)
            .options(
                selectinload(PromotionModel.locations),
                selectinload(PromotionModel.schedules),
                selectinload(PromotionModel.targets),
                selectinload(PromotionModel.codes),
                selectinload(PromotionModel.channels),
            )
        )


def _promotion(value: PromotionModel) -> Promotion:
    return Promotion(
        value.id,
        value.organization_id,
        value.name,
        value.pos_name,
        PromotionStatus(value.status),
        ApplicationMode(value.application_mode),
        DiscountKind(value.discount_kind),
        PromotionScope(value.scope),
        value.percent_rate,
        value.amount_minor,
        value.fixed_price_minor,
        value.priority,
        StackingPolicy(value.stacking_policy),
        value.include_modifier_price,
        value.minimum_subtotal_minor,
        value.maximum_discount_minor,
        value.valid_from,
        value.valid_to,
        value.all_locations,
        value.requires_override_permission,
        value.created_by,
        value.created_at,
        value.updated_at,
        tuple(sorted((item.location_id for item in value.locations), key=str)),
        tuple(
            PromotionSchedule(
                item.id, item.promotion_id, item.weekday, item.start_local_time, item.end_local_time
            )
            for item in sorted(
                value.schedules,
                key=lambda item: (item.weekday, item.start_local_time, str(item.id)),
            )
        ),
        tuple(
            PromotionTarget(
                item.id,
                item.promotion_id,
                TargetRole(item.role),
                TargetType(item.target_type),
                item.target_id,
                item.quantity,
                item.sort_order,
            )
            for item in sorted(value.targets, key=lambda item: (item.sort_order, str(item.id)))
        ),
        tuple(
            PromotionCode(
                item.id,
                item.organization_id,
                item.promotion_id,
                item.code_normalized,
                item.is_active,
                item.valid_from,
                item.valid_to,
                item.max_redemptions,
                item.created_at,
            )
            for item in sorted(value.codes, key=lambda item: (item.created_at, str(item.id)))
        ),
        tuple(PromotionChannel(item.channel) for item in value.channels),
    )
