import re
from datetime import UTC, date, datetime
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from beanly.core.security.audit import SecurityAuditRecorder
from beanly.modules.customers.domain.exceptions import (
    CustomerInvalid,
    CustomerNotFound,
    CustomerPhoneConflict,
    LoyaltyIdempotencyConflict,
    LoyaltyInsufficientBalance,
    LoyaltyInvalid,
    LoyaltyOrderImmutable,
)
from beanly.modules.customers.infrastructure.db.models import (
    CustomerModel,
    LoyaltyAccountModel,
    LoyaltyLedgerEntryModel,
    LoyaltyProgramModel,
    LoyaltyRedemptionModel,
    LoyaltyTierModel,
    PromotionAudienceCustomerModel,
    PromotionAudienceModel,
)
from beanly.modules.organizations.application.services.organization_service import (
    OrganizationService,
)
from beanly.modules.organizations.domain.entities import TenantContext
from beanly.modules.organizations.domain.exceptions import OrganizationAccessDenied
from beanly.modules.organizations.infrastructure.db.models import LocationModel
from beanly.modules.payments.infrastructure.db.models import PaymentModel
from beanly.modules.promotions.infrastructure.db.models import SalesOrderDiscountModel
from beanly.modules.refunds.infrastructure.db.models import RefundModel
from beanly.modules.sales.infrastructure.db.models import SalesOrderModel

MAX_BIGINT = 9_223_372_036_854_775_807


class CustomerService:
    def __init__(self, session: AsyncSession, organizations: OrganizationService) -> None:
        self.session = session
        self.organizations = organizations
        self.audit = SecurityAuditRecorder(session)

    async def list(self, context: TenantContext, search: str | None, limit: int, offset: int):
        query = select(CustomerModel).where(
            CustomerModel.organization_id == context.organization_id,
            CustomerModel.deleted_at.is_(None),
        )
        if search and (term := search.strip()):
            digits = re.sub(r"\D", "", term)
            filters = [
                CustomerModel.first_name.ilike(f"%{term}%"),
                CustomerModel.last_name.ilike(f"%{term}%"),
                CustomerModel.email.ilike(f"%{term}%"),
            ]
            if digits:
                filters.append(CustomerModel.phone_normalized.contains(digits))
            query = query.where(or_(*filters))
        values = await self.session.scalars(
            query.order_by(CustomerModel.updated_at.desc(), CustomerModel.id)
            .limit(limit)
            .offset(offset)
        )
        return [await self._view(value) for value in values]

    async def create(self, context: TenantContext, payload):
        now = datetime.now(UTC)
        phone = normalize_phone(payload.phone)
        value = CustomerModel(
            id=uuid4(),
            organization_id=context.organization_id,
            phone_normalized=phone,
            phone_display=phone,
            first_name=_optional(payload.first_name, 100),
            last_name=_optional(payload.last_name, 100),
            email=_email(payload.email),
            birth_date=_birth_date(payload.birth_date),
            note=_optional(payload.note, 4000),
            marketing_consent=payload.marketing_consent,
            created_by_user_id=context.user_id,
            created_at=now,
            updated_at=now,
        )
        try:
            self.session.add(value)
            self.session.add(
                LoyaltyAccountModel(
                    id=uuid4(),
                    organization_id=context.organization_id,
                    customer_id=value.id,
                    points_balance=0,
                    lifetime_earned_points=0,
                    updated_at=now,
                )
            )
            await self._program(context.organization_id, context.user_id)
            await self.audit.record(
                action="CUSTOMER_CREATED",
                resource_type="customer",
                organization_id=context.organization_id,
                actor_user_id=context.user_id,
                resource_id=value.id,
            )
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise CustomerPhoneConflict("Phone already belongs to a customer") from exc
        return await self.get(context, value.id)

    async def get(self, context: TenantContext, customer_id: UUID):
        return await self._view(await self._customer(context.organization_id, customer_id))

    async def update(self, context: TenantContext, customer_id: UUID, payload):
        value = await self._customer(context.organization_id, customer_id, lock=True)
        fields = payload.model_fields_set
        if not fields:
            raise CustomerInvalid("No fields supplied")
        if "phone" in fields:
            if payload.phone is None:
                raise CustomerInvalid("Phone cannot be removed")
            value.phone_normalized = value.phone_display = normalize_phone(payload.phone)
        for field, limit in (("first_name", 100), ("last_name", 100), ("note", 4000)):
            if field in fields:
                setattr(value, field, _optional(getattr(payload, field), limit))
        if "email" in fields:
            value.email = _email(payload.email)
        if "birth_date" in fields:
            value.birth_date = _birth_date(payload.birth_date)
        if "marketing_consent" in fields:
            if payload.marketing_consent is None:
                raise CustomerInvalid("marketing_consent cannot be null")
            value.marketing_consent = payload.marketing_consent
        value.updated_at = datetime.now(UTC)
        try:
            await self.audit.record(
                action="CUSTOMER_UPDATED",
                resource_type="customer",
                organization_id=context.organization_id,
                actor_user_id=context.user_id,
                resource_id=value.id,
            )
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise CustomerPhoneConflict("Phone already belongs to a customer") from exc
        return await self.get(context, value.id)

    async def soft_delete(self, context: TenantContext, customer_id: UUID) -> None:
        value = await self._customer(context.organization_id, customer_id, lock=True)
        attached = await self.session.scalar(
            select(func.count())
            .select_from(SalesOrderModel)
            .where(
                SalesOrderModel.organization_id == context.organization_id,
                SalesOrderModel.customer_id == customer_id,
                SalesOrderModel.status == "OPEN",
            )
        )
        if attached:
            raise CustomerInvalid("Customer is attached to an OPEN order")
        value.deleted_at = value.updated_at = datetime.now(UTC)
        await self.audit.record(
            action="CUSTOMER_ARCHIVED",
            resource_type="customer",
            organization_id=context.organization_id,
            actor_user_id=context.user_id,
            resource_id=value.id,
        )
        await self.session.commit()

    async def orders(self, context: TenantContext, customer_id: UUID, limit: int, offset: int):
        await self._customer(context.organization_id, customer_id)
        refunds = (
            select(
                RefundModel.order_id.label("order_id"),
                func.coalesce(func.sum(RefundModel.total_amount_minor), 0).label("refunded"),
            )
            .where(
                RefundModel.organization_id == context.organization_id,
                RefundModel.status == "COMPLETED",
            )
            .group_by(RefundModel.order_id)
            .subquery()
        )
        rows = await self.session.execute(
            select(SalesOrderModel, func.coalesce(refunds.c.refunded, 0))
            .outerjoin(refunds, refunds.c.order_id == SalesOrderModel.id)
            .where(
                SalesOrderModel.organization_id == context.organization_id,
                SalesOrderModel.customer_id == customer_id,
            )
            .order_by(SalesOrderModel.created_at.desc(), SalesOrderModel.id)
            .limit(limit)
            .offset(offset)
        )
        return [
            {
                "id": order.id,
                "location_id": order.location_id,
                "number": str(order.number),
                "status": order.status,
                "total_minor": str(order.total_minor),
                "refunded_minor": str(int(refunded)),
                "net_minor": str(order.total_minor - int(refunded)),
                "paid_at": order.paid_at,
            }
            for order, refunded in rows
        ]

    async def loyalty(self, context: TenantContext, customer_id: UUID):
        await self._customer(context.organization_id, customer_id)
        program = await self._program(context.organization_id, context.user_id)
        account = await self._account(context.organization_id, customer_id)
        tier = (
            await self.session.get(LoyaltyTierModel, account.tier_id) if account.tier_id else None
        )
        entries = list(
            await self.session.scalars(
                select(LoyaltyLedgerEntryModel)
                .where(
                    LoyaltyLedgerEntryModel.organization_id == context.organization_id,
                    LoyaltyLedgerEntryModel.customer_id == customer_id,
                )
                .order_by(LoyaltyLedgerEntryModel.occurred_at.desc(), LoyaltyLedgerEntryModel.id)
                .limit(100)
            )
        )
        reserved = await self._reserved_points(context.organization_id, customer_id)
        return {
            "customer_id": customer_id,
            "points_balance": str(account.points_balance),
            "available_points": str(max(0, account.points_balance - reserved)),
            "lifetime_earned_points": str(account.lifetime_earned_points),
            "point_value_minor": str(program.point_value_minor),
            "earn_rate_bps": program.earn_rate_bps,
            "tier": _tier_ref(tier),
            "entries": [
                {
                    "id": item.id,
                    "points_delta": str(item.points_delta),
                    "kind": item.kind,
                    "source_type": item.source_type,
                    "source_id": item.source_id,
                    "related_source_id": item.related_source_id,
                    "reason": item.reason,
                    "occurred_at": item.occurred_at,
                }
                for item in entries
            ],
        }

    async def program(self, context: TenantContext):
        value = await self._program(context.organization_id, context.user_id)
        await self.session.commit()
        return _program_view(value)

    async def configure_program(self, context: TenantContext, payload):
        value = await self._program(context.organization_id, context.user_id, lock=True)
        point_value = _bigint(payload.point_value_minor, positive=True)
        birthday = _bigint(payload.birthday_reward_points)
        value.earn_rate_bps = payload.earn_rate_bps
        value.point_value_minor = point_value
        value.birthday_reward_points = birthday
        value.is_active = payload.is_active
        value.updated_by_user_id = context.user_id
        value.updated_at = datetime.now(UTC)
        await self.audit.record(
            action="LOYALTY_PROGRAM_CONFIGURED",
            resource_type="loyalty_program",
            organization_id=context.organization_id,
            actor_user_id=context.user_id,
            resource_id=value.id,
            metadata={
                "earn_rate_bps": value.earn_rate_bps,
                "point_value_minor": value.point_value_minor,
                "birthday_reward_points": value.birthday_reward_points,
                "is_active": value.is_active,
            },
        )
        await self.session.commit()
        return _program_view(value)

    async def tiers(self, context: TenantContext):
        return [
            _tier_view(value)
            for value in await self.session.scalars(
                select(LoyaltyTierModel)
                .where(LoyaltyTierModel.organization_id == context.organization_id)
                .order_by(LoyaltyTierModel.threshold_lifetime_points, LoyaltyTierModel.id)
            )
        ]

    async def create_tier(self, context: TenantContext, payload):
        now = datetime.now(UTC)
        value = LoyaltyTierModel(
            id=uuid4(),
            organization_id=context.organization_id,
            name=_required(payload.name, 100),
            threshold_lifetime_points=_bigint(payload.threshold_lifetime_points),
            earn_multiplier_bps=payload.earn_multiplier_bps,
            created_at=now,
            updated_at=now,
        )
        self.session.add(value)
        try:
            await self.session.flush()
            await self._recompute_tiers(context.organization_id)
            await self.audit.record(
                action="LOYALTY_TIER_CREATED",
                resource_type="loyalty_tier",
                organization_id=context.organization_id,
                actor_user_id=context.user_id,
                resource_id=value.id,
            )
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise LoyaltyInvalid("Tier name and threshold must be unique") from exc
        return _tier_view(value)

    async def update_tier(self, context: TenantContext, tier_id: UUID, payload):
        value = await self.session.scalar(
            select(LoyaltyTierModel)
            .where(
                LoyaltyTierModel.id == tier_id,
                LoyaltyTierModel.organization_id == context.organization_id,
            )
            .with_for_update()
        )
        if value is None:
            raise CustomerNotFound("Loyalty tier not found")
        value.name = _required(payload.name, 100)
        value.threshold_lifetime_points = _bigint(payload.threshold_lifetime_points)
        value.earn_multiplier_bps = payload.earn_multiplier_bps
        value.updated_at = datetime.now(UTC)
        try:
            await self.session.flush()
            await self._recompute_tiers(context.organization_id)
            await self.audit.record(
                action="LOYALTY_TIER_UPDATED",
                resource_type="loyalty_tier",
                organization_id=context.organization_id,
                actor_user_id=context.user_id,
                resource_id=value.id,
            )
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise LoyaltyInvalid("Tier name and threshold must be unique") from exc
        return _tier_view(value)

    async def adjust(self, context: TenantContext, customer_id: UUID, payload):
        await self._customer(context.organization_id, customer_id)
        delta = _bigint(payload.points_delta, signed=True)
        reason = _required(payload.reason, 1000)
        source_id = str(payload.client_adjustment_id)
        try:
            created = await self._entry(
                context.organization_id,
                customer_id,
                delta,
                "ADJUSTMENT",
                "CLIENT_ADJUSTMENT",
                source_id,
                reason,
                context.user_id,
                datetime.now(UTC),
            )
            if created:
                await self.audit.record(
                    action="LOYALTY_ADJUSTED",
                    resource_type="customer",
                    organization_id=context.organization_id,
                    actor_user_id=context.user_id,
                    resource_id=customer_id,
                    metadata={"points_delta": delta, "reason": reason},
                )
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            existing = await self._adjustment(context.organization_id, source_id)
            if existing is None or (
                existing.customer_id != customer_id
                or existing.points_delta != delta
                or existing.reason != reason
            ):
                raise LoyaltyIdempotencyConflict(
                    "client_adjustment_id was used with a different payload"
                ) from exc
        return await self.loyalty(context, customer_id)

    async def attach(self, context: TenantContext, order_id: UUID, customer_id: UUID | None):
        order = await self._open_order(context, order_id)
        await self._ensure_no_reservation(context.organization_id, order_id)
        if customer_id is not None:
            customer = await self._customer(context.organization_id, customer_id)
            await self._birthday_reward(context, customer, order.location_id)
            order.customer_name_snapshot = _customer_name(customer)
            order.customer_phone_snapshot = customer.phone_normalized
        else:
            order.customer_name_snapshot = None
            order.customer_phone_snapshot = None
        order.customer_id = customer_id
        order.version += 1
        order.updated_at = datetime.now(UTC)
        from beanly.modules.promotions.infrastructure.pricing_service import reprice_order

        await reprice_order(self.session, context.organization_id, order_id)
        await self.session.commit()
        return order_id

    async def quote(self, context: TenantContext, order_id: UUID, points_value: str):
        order = await self._open_order(context, order_id)
        if order.customer_id is None:
            raise LoyaltyInvalid("Order has no customer")
        points = _bigint(points_value, positive=True)
        program = await self._program(context.organization_id, context.user_id)
        if not program.is_active:
            raise LoyaltyInvalid("Loyalty program is inactive")
        account = await self._account(context.organization_id, order.customer_id, lock=True)
        available = account.points_balance - await self._reserved_points(
            context.organization_id, order.customer_id
        )
        usable = min(points, available, order.total_minor // program.point_value_minor)
        if usable <= 0:
            raise LoyaltyInsufficientBalance("No redeemable points")
        return {
            "points": str(usable),
            "discount_minor": str(usable * program.point_value_minor),
            "balance_points": str(available),
        }

    async def redeem(self, context: TenantContext, order_id: UUID, payload):
        order = await self._open_order(context, order_id)
        if order.customer_id is None:
            raise LoyaltyInvalid("Order has no customer")
        customer_id = order.customer_id
        requested = _bigint(payload.points, positive=True)
        existing = await self.session.scalar(
            select(LoyaltyRedemptionModel).where(
                LoyaltyRedemptionModel.organization_id == context.organization_id,
                LoyaltyRedemptionModel.client_redemption_id == payload.client_redemption_id,
            )
        )
        if existing is not None:
            if (
                existing.order_id != order_id
                or existing.customer_id != order.customer_id
                or existing.points_requested != requested
            ):
                raise LoyaltyIdempotencyConflict(
                    "client_redemption_id was used with a different payload"
                )
            return order_id
        if await self.session.scalar(
            select(LoyaltyRedemptionModel.id).where(
                LoyaltyRedemptionModel.order_id == order_id,
                LoyaltyRedemptionModel.status != "REVERSED",
            )
        ):
            raise LoyaltyInvalid("Order already has a loyalty redemption")
        quote = await self.quote(context, order_id, str(requested))
        points, discount = int(quote["points"]), int(quote["discount_minor"])
        now = datetime.now(UTC)
        redemption_id = uuid4()
        self.session.add(
            LoyaltyRedemptionModel(
                id=redemption_id,
                organization_id=context.organization_id,
                customer_id=customer_id,
                order_id=order_id,
                client_redemption_id=payload.client_redemption_id,
                points_requested=requested,
                points_applied=points,
                discount_minor=discount,
                status="RESERVED",
                created_by_user_id=context.user_id,
                created_at=now,
            )
        )
        self.session.add(
            SalesOrderDiscountModel(
                id=uuid4(),
                order_id=order_id,
                client_discount_id=payload.client_redemption_id,
                promotion_id=None,
                source="CUSTOM",
                promotion_name="Loyalty redemption",
                discount_kind="FIXED_AMOUNT",
                scope="ORDER",
                percent_rate=None,
                configured_amount_minor=discount,
                promo_code_snapshot=None,
                reason="LOYALTY_REDEMPTION",
                applied_by_user_id=context.user_id,
                applied_at=now,
                discount_total_minor=0,
                promotion_config_hash="loyalty-redemption-v1",
                sort_order=998,
                audience_kind=None,
            )
        )
        from beanly.modules.promotions.infrastructure.pricing_service import reprice_order

        try:
            await reprice_order(self.session, context.organization_id, order_id)
            await self.audit.record(
                action="LOYALTY_REDEMPTION_RESERVED",
                resource_type="sales_order",
                organization_id=context.organization_id,
                actor_user_id=context.user_id,
                resource_id=order_id,
                metadata={"points": points, "discount_minor": discount},
            )
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            existing = await self.session.scalar(
                select(LoyaltyRedemptionModel).where(
                    LoyaltyRedemptionModel.organization_id == context.organization_id,
                    LoyaltyRedemptionModel.client_redemption_id == payload.client_redemption_id,
                )
            )
            if existing is not None and (
                existing.order_id == order_id
                and existing.customer_id == customer_id
                and existing.points_requested == requested
            ):
                return order_id
            raise LoyaltyIdempotencyConflict("Concurrent loyalty redemption") from exc
        return order_id

    async def release(self, context: TenantContext, order_id: UUID):
        await self._open_order(context, order_id)
        value = await self.session.scalar(
            select(LoyaltyRedemptionModel)
            .where(
                LoyaltyRedemptionModel.organization_id == context.organization_id,
                LoyaltyRedemptionModel.order_id == order_id,
                LoyaltyRedemptionModel.status == "RESERVED",
            )
            .with_for_update()
        )
        if value is None:
            raise CustomerNotFound("Reserved loyalty redemption not found")
        await self.session.execute(
            delete(SalesOrderDiscountModel).where(
                SalesOrderDiscountModel.order_id == order_id,
                SalesOrderDiscountModel.client_discount_id == value.client_redemption_id,
            )
        )
        await self.session.delete(value)
        from beanly.modules.promotions.infrastructure.pricing_service import reprice_order

        await reprice_order(self.session, context.organization_id, order_id)
        await self.audit.record(
            action="LOYALTY_REDEMPTION_RELEASED",
            resource_type="sales_order",
            organization_id=context.organization_id,
            actor_user_id=context.user_id,
            resource_id=order_id,
        )
        await self.session.commit()
        return order_id

    async def get_audience(self, context: TenantContext, promotion_id: UUID):
        await self._promotion(context.organization_id, promotion_id)
        audience = await self.session.get(PromotionAudienceModel, promotion_id)
        if audience is None:
            return {
                "promotion_id": promotion_id,
                "kind": "ALL",
                "tier_id": None,
                "customer_ids": [],
            }
        customers = list(
            await self.session.scalars(
                select(PromotionAudienceCustomerModel.customer_id)
                .where(PromotionAudienceCustomerModel.promotion_id == promotion_id)
                .order_by(PromotionAudienceCustomerModel.customer_id)
            )
        )
        return {
            "promotion_id": promotion_id,
            "kind": audience.kind,
            "tier_id": audience.tier_id,
            "customer_ids": customers,
        }

    async def set_audience(self, context: TenantContext, promotion_id: UUID, payload):
        await self._promotion(context.organization_id, promotion_id)
        customer_ids = tuple(dict.fromkeys(payload.customer_ids))
        if payload.kind == "CUSTOMER":
            if payload.tier_id is not None or not customer_ids:
                raise LoyaltyInvalid("CUSTOMER audience requires customer_ids only")
            count = await self.session.scalar(
                select(func.count())
                .select_from(CustomerModel)
                .where(
                    CustomerModel.organization_id == context.organization_id,
                    CustomerModel.id.in_(customer_ids),
                    CustomerModel.deleted_at.is_(None),
                )
            )
            if count != len(customer_ids):
                raise CustomerNotFound("Audience customer not found")
        elif payload.kind == "TIER":
            if payload.tier_id is None or customer_ids:
                raise LoyaltyInvalid("TIER audience requires tier_id only")
            tier = await self.session.scalar(
                select(LoyaltyTierModel.id).where(
                    LoyaltyTierModel.organization_id == context.organization_id,
                    LoyaltyTierModel.id == payload.tier_id,
                )
            )
            if tier is None:
                raise CustomerNotFound("Audience tier not found")
        elif payload.tier_id is not None or customer_ids:
            raise LoyaltyInvalid(f"{payload.kind} audience cannot have targets")
        audience = await self.session.get(PromotionAudienceModel, promotion_id)
        if audience is None:
            audience = PromotionAudienceModel(
                promotion_id=promotion_id,
                organization_id=context.organization_id,
                kind=payload.kind,
                tier_id=payload.tier_id,
            )
            self.session.add(audience)
        else:
            audience.kind, audience.tier_id = payload.kind, payload.tier_id
        await self.session.execute(
            delete(PromotionAudienceCustomerModel).where(
                PromotionAudienceCustomerModel.promotion_id == promotion_id
            )
        )
        self.session.add_all(
            [
                PromotionAudienceCustomerModel(promotion_id=promotion_id, customer_id=customer_id)
                for customer_id in customer_ids
            ]
        )
        await self.audit.record(
            action="PROMOTION_AUDIENCE_CONFIGURED",
            resource_type="promotion",
            organization_id=context.organization_id,
            actor_user_id=context.user_id,
            resource_id=promotion_id,
            metadata={
                "kind": payload.kind,
                "tier_id": str(payload.tier_id) if payload.tier_id else None,
                "customer_count": len(customer_ids),
            },
        )
        await self.session.commit()
        return await self.get_audience(context, promotion_id)

    async def _view(self, value: CustomerModel):
        account = await self._account(value.organization_id, value.id)
        tier = (
            await self.session.get(LoyaltyTierModel, account.tier_id) if account.tier_id else None
        )
        paid = await self.session.execute(
            select(
                func.count(SalesOrderModel.id),
                func.coalesce(func.sum(SalesOrderModel.total_minor), 0),
                func.max(SalesOrderModel.paid_at),
            ).where(
                SalesOrderModel.organization_id == value.organization_id,
                SalesOrderModel.customer_id == value.id,
                SalesOrderModel.status == "PAID",
            )
        )
        visits, gross, last = paid.one()
        refunded = await self.session.scalar(
            select(func.coalesce(func.sum(RefundModel.total_amount_minor), 0))
            .join(SalesOrderModel, SalesOrderModel.id == RefundModel.order_id)
            .where(
                RefundModel.organization_id == value.organization_id,
                RefundModel.status == "COMPLETED",
                SalesOrderModel.customer_id == value.id,
            )
        )
        return {
            "id": value.id,
            "organization_id": value.organization_id,
            "phone": value.phone_normalized,
            "first_name": value.first_name,
            "last_name": value.last_name,
            "email": value.email,
            "birth_date": value.birth_date,
            "note": value.note,
            "marketing_consent": value.marketing_consent,
            "visit_count": int(visits or 0),
            "lifetime_value_minor": str(int(gross or 0) - int(refunded or 0)),
            "last_visit_at": last,
            "loyalty_points_balance": str(account.points_balance),
            "tier": _tier_ref(tier),
            "created_at": value.created_at,
            "updated_at": value.updated_at,
        }

    async def _birthday_reward(
        self, context: TenantContext, customer: CustomerModel, location_id: UUID
    ) -> None:
        timezone = await self.session.scalar(
            select(LocationModel.timezone).where(
                LocationModel.organization_id == context.organization_id,
                LocationModel.id == location_id,
            )
        )
        try:
            today = datetime.now(ZoneInfo(timezone or "")).date()
        except ZoneInfoNotFoundError as exc:
            raise CustomerInvalid("Location timezone is invalid") from exc
        program = await self._program(context.organization_id, context.user_id)
        if (
            program.is_active
            and program.birthday_reward_points > 0
            and customer.birth_date
            and (customer.birth_date.month, customer.birth_date.day) == (today.month, today.day)
        ):
            await self._entry(
                context.organization_id,
                customer.id,
                program.birthday_reward_points,
                "BIRTHDAY_REWARD",
                "BIRTHDAY_YEAR",
                str(today.year),
                "Birthday reward",
                context.user_id,
                datetime.now(UTC),
            )

    async def _customer(self, organization_id: UUID, customer_id: UUID, *, lock: bool = False):
        query = select(CustomerModel).where(
            CustomerModel.organization_id == organization_id,
            CustomerModel.id == customer_id,
            CustomerModel.deleted_at.is_(None),
        )
        if lock:
            query = query.with_for_update()
        value = await self.session.scalar(query)
        if value is None:
            raise CustomerNotFound("Customer not found")
        return value

    async def _account(self, organization_id: UUID, customer_id: UUID, *, lock: bool = False):
        query = select(LoyaltyAccountModel).where(
            LoyaltyAccountModel.organization_id == organization_id,
            LoyaltyAccountModel.customer_id == customer_id,
        )
        if lock:
            query = query.with_for_update()
        value = await self.session.scalar(query)
        if value is None:
            raise CustomerNotFound("Customer loyalty account not found")
        return value

    async def _program(self, organization_id: UUID, actor_id: UUID, *, lock: bool = False):
        query = select(LoyaltyProgramModel).where(
            LoyaltyProgramModel.organization_id == organization_id
        )
        if lock:
            query = query.with_for_update()
        value = await self.session.scalar(query)
        if value is None:
            now = datetime.now(UTC)
            values = {
                "id": uuid4(),
                "organization_id": organization_id,
                "earn_rate_bps": 0,
                "point_value_minor": 100,
                "birthday_reward_points": 0,
                "is_active": True,
                "updated_by_user_id": actor_id,
                "created_at": now,
                "updated_at": now,
            }
            dialect = self.session.get_bind().dialect.name
            if dialect == "postgresql":
                from sqlalchemy.dialects.postgresql import insert
            elif dialect == "sqlite":
                from sqlalchemy.dialects.sqlite import insert
            else:
                self.session.add(LoyaltyProgramModel(**values))
                await self.session.flush()
                return await self.session.scalar(query)
            await self.session.execute(
                insert(LoyaltyProgramModel)
                .values(**values)
                .on_conflict_do_nothing(index_elements=["organization_id"])
            )
            value = await self.session.scalar(query)
            if value is None:
                raise LoyaltyInvalid("Loyalty program could not be initialized")
        return value

    async def _open_order(self, context: TenantContext, order_id: UUID):
        value = await self.session.scalar(
            select(SalesOrderModel)
            .where(
                SalesOrderModel.organization_id == context.organization_id,
                SalesOrderModel.id == order_id,
            )
            .with_for_update()
        )
        if value is None:
            raise CustomerNotFound("Order not found")
        try:
            await self.organizations.ensure_location_access(context, value.location_id)
        except OrganizationAccessDenied as exc:
            raise CustomerNotFound("Order not found") from exc
        if value.status != "OPEN":
            raise LoyaltyOrderImmutable("Order is immutable")
        return value

    async def _reserved_points(self, organization_id: UUID, customer_id: UUID) -> int:
        value = await self.session.scalar(
            select(
                func.coalesce(
                    func.sum(
                        func.coalesce(
                            LoyaltyRedemptionModel.points_applied,
                            LoyaltyRedemptionModel.points_requested,
                        )
                    ),
                    0,
                )
            )
            .join(SalesOrderModel, SalesOrderModel.id == LoyaltyRedemptionModel.order_id)
            .where(
                LoyaltyRedemptionModel.organization_id == organization_id,
                LoyaltyRedemptionModel.customer_id == customer_id,
                LoyaltyRedemptionModel.status == "RESERVED",
                SalesOrderModel.status == "OPEN",
            )
        )
        return int(value or 0)

    async def _ensure_no_reservation(self, organization_id: UUID, order_id: UUID) -> None:
        if await self.session.scalar(
            select(LoyaltyRedemptionModel.id).where(
                LoyaltyRedemptionModel.organization_id == organization_id,
                LoyaltyRedemptionModel.order_id == order_id,
                LoyaltyRedemptionModel.status == "RESERVED",
            )
        ):
            raise LoyaltyOrderImmutable("Release loyalty redemption before changing this order")

    async def _promotion(self, organization_id: UUID, promotion_id: UUID) -> None:
        from beanly.modules.promotions.infrastructure.db.models import PromotionModel

        if not await self.session.scalar(
            select(PromotionModel.id).where(
                PromotionModel.organization_id == organization_id,
                PromotionModel.id == promotion_id,
            )
        ):
            raise CustomerNotFound("Promotion not found")

    async def _recompute_tiers(self, organization_id: UUID) -> None:
        tiers = list(
            await self.session.scalars(
                select(LoyaltyTierModel)
                .where(LoyaltyTierModel.organization_id == organization_id)
                .order_by(LoyaltyTierModel.threshold_lifetime_points.desc())
            )
        )
        accounts = await self.session.scalars(
            select(LoyaltyAccountModel)
            .where(LoyaltyAccountModel.organization_id == organization_id)
            .with_for_update()
        )
        for account in accounts:
            account.tier_id = next(
                (
                    tier.id
                    for tier in tiers
                    if tier.threshold_lifetime_points <= account.lifetime_earned_points
                ),
                None,
            )

    async def _entry(
        self,
        organization_id: UUID,
        customer_id: UUID,
        points_delta: int,
        kind: str,
        source_type: str,
        source_id: str,
        reason: str | None,
        actor_id: UUID | None,
        occurred_at: datetime,
    ) -> bool:
        account = await self._account(organization_id, customer_id, lock=True)
        row = (
            await self._adjustment(organization_id, source_id)
            if kind == "ADJUSTMENT" and source_type == "CLIENT_ADJUSTMENT"
            else await self.session.scalar(
                select(LoyaltyLedgerEntryModel).where(
                    LoyaltyLedgerEntryModel.organization_id == organization_id,
                    LoyaltyLedgerEntryModel.customer_id == customer_id,
                    LoyaltyLedgerEntryModel.kind == kind,
                    LoyaltyLedgerEntryModel.source_type == source_type,
                    LoyaltyLedgerEntryModel.source_id == source_id,
                )
            )
        )
        if row is not None:
            if (
                kind == "ADJUSTMENT"
                and (
                    row.customer_id != customer_id
                    or row.points_delta != points_delta
                    or row.reason != reason
                )
            ):
                raise LoyaltyIdempotencyConflict(
                    "client_adjustment_id was used with a different payload"
                )
            return False
        if points_delta == 0:
            return False
        balance = account.points_balance + points_delta
        if points_delta < 0 and balance < 0:
            raise LoyaltyInsufficientBalance("Loyalty points balance is insufficient")
        if abs(balance) > MAX_BIGINT:
            raise LoyaltyInvalid("Loyalty points are outside BIGINT")
        now = datetime.now(UTC)
        self.session.add(
            LoyaltyLedgerEntryModel(
                id=uuid4(),
                organization_id=organization_id,
                customer_id=customer_id,
                points_delta=points_delta,
                kind=kind,
                source_type=source_type,
                source_id=source_id,
                related_source_id=None,
                reason=reason,
                created_by_user_id=actor_id,
                occurred_at=occurred_at,
                recorded_at=now,
            )
        )
        account.points_balance = balance
        if points_delta > 0 and kind in {"EARN", "BIRTHDAY_REWARD"}:
            next_lifetime = account.lifetime_earned_points + points_delta
            if next_lifetime > MAX_BIGINT:
                raise LoyaltyInvalid("Lifetime loyalty points are outside BIGINT")
            account.lifetime_earned_points = next_lifetime
            tiers = list(
                await self.session.scalars(
                    select(LoyaltyTierModel)
                    .where(
                        LoyaltyTierModel.organization_id == organization_id,
                        LoyaltyTierModel.threshold_lifetime_points
                        <= account.lifetime_earned_points,
                    )
                    .order_by(LoyaltyTierModel.threshold_lifetime_points.desc())
                    .limit(1)
                )
            )
            account.tier_id = tiers[0].id if tiers else None
        account.updated_at = now
        await self.session.flush()
        return True

    async def _adjustment(
        self, organization_id: UUID, source_id: str
    ) -> LoyaltyLedgerEntryModel | None:
        return await self.session.scalar(
            select(LoyaltyLedgerEntryModel).where(
                LoyaltyLedgerEntryModel.organization_id == organization_id,
                LoyaltyLedgerEntryModel.kind == "ADJUSTMENT",
                LoyaltyLedgerEntryModel.source_type == "CLIENT_ADJUSTMENT",
                LoyaltyLedgerEntryModel.source_id == source_id,
            )
        )


class CustomerProjectionService:
    """Idempotent payment/refund projector; session commit is owned by the caller."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def apply_payment(
        self,
        payment_id: UUID,
        organization_id: UUID,
        order_id: UUID,
        amount_minor: int,
        occurred_at: datetime,
    ) -> None:
        order = await self.session.scalar(
            select(SalesOrderModel)
            .where(
                SalesOrderModel.organization_id == organization_id,
                SalesOrderModel.id == order_id,
            )
            .with_for_update()
        )
        if order is None or order.customer_id is None or order.status != "OPEN":
            return
        customer = await self.session.scalar(
            select(CustomerModel)
            .where(
                CustomerModel.organization_id == organization_id,
                CustomerModel.id == order.customer_id,
                CustomerModel.deleted_at.is_(None),
            )
            .with_for_update()
        )
        if customer is None:
            raise LoyaltyInvalid("Payment customer is unavailable")
        order.customer_name_snapshot = _customer_name(customer)
        order.customer_phone_snapshot = customer.phone_normalized
        helper = _ProjectionLedger(self.session)
        program = await self.session.scalar(
            select(LoyaltyProgramModel).where(
                LoyaltyProgramModel.organization_id == organization_id
            )
        )
        account = await helper.account(organization_id, customer.id)
        redemption = await self.session.scalar(
            select(LoyaltyRedemptionModel)
            .where(
                LoyaltyRedemptionModel.organization_id == organization_id,
                LoyaltyRedemptionModel.order_id == order_id,
                LoyaltyRedemptionModel.status == "RESERVED",
            )
            .with_for_update()
        )
        if redemption is not None:
            if program is None or not program.is_active:
                raise LoyaltyInvalid("Loyalty program changed; release and redeem again")
            applied_points = redemption.points_applied or redemption.points_requested
            discount = await self.session.scalar(
                select(SalesOrderDiscountModel.discount_total_minor).where(
                    SalesOrderDiscountModel.order_id == order_id,
                    SalesOrderDiscountModel.client_discount_id == redemption.client_redemption_id,
                )
            )
            expected = applied_points * program.point_value_minor
            if discount != expected or account.points_balance < applied_points:
                raise LoyaltyInvalid("Loyalty redemption changed before payment")
            await helper.entry(
                organization_id,
                customer.id,
                -applied_points,
                "REDEEM",
                "PAYMENT",
                str(payment_id),
                "Order loyalty redemption",
                occurred_at,
            )
            redemption.status = "APPLIED"
            redemption.points_applied = applied_points
            redemption.applied_at = occurred_at
        if program is None or not program.is_active:
            return
        tier = (
            await self.session.get(LoyaltyTierModel, account.tier_id) if account.tier_id else None
        )
        multiplier = tier.earn_multiplier_bps if tier else 10000
        earned = (
            amount_minor
            * program.earn_rate_bps
            * multiplier
            // (10000 * 10000 * program.point_value_minor)
        )
        if earned:
            await helper.entry(
                organization_id,
                customer.id,
                earned,
                "EARN",
                "PAYMENT",
                str(payment_id),
                "Payment loyalty earn",
                occurred_at,
                lifetime=True,
            )

    async def apply_refund(
        self, refund_id: UUID, organization_id: UUID, occurred_at: datetime
    ) -> None:
        refund = await self.session.scalar(
            select(RefundModel).where(
                RefundModel.organization_id == organization_id,
                RefundModel.id == refund_id,
                RefundModel.status == "COMPLETED",
            )
        )
        if refund is None:
            raise LoyaltyInvalid("Completed refund not found")
        payment = await self.session.scalar(
            select(PaymentModel).where(
                PaymentModel.organization_id == organization_id,
                PaymentModel.id == refund.payment_id,
            )
        )
        order = await self.session.scalar(
            select(SalesOrderModel).where(
                SalesOrderModel.organization_id == organization_id,
                SalesOrderModel.id == refund.order_id,
            )
        )
        if payment is None or order is None or order.customer_id is None:
            return
        helper = _ProjectionLedger(self.session)
        # Serialize all refund projections for this customer before reading cumulative state.
        await helper.account(organization_id, order.customer_id)
        cumulative = int(
            await self.session.scalar(
                select(func.coalesce(func.sum(RefundModel.total_amount_minor), 0)).where(
                    RefundModel.organization_id == organization_id,
                    RefundModel.payment_id == payment.id,
                    RefundModel.status == "COMPLETED",
                )
            )
            or 0
        )
        full = cumulative >= payment.amount_minor
        earned = await helper.source_points(
            organization_id, order.customer_id, "EARN", "PAYMENT", str(payment.id)
        )
        if earned > 0:
            target = earned if full else earned * cumulative // payment.amount_minor
            prior = -await helper.kind_sum(
                organization_id, order.customer_id, "REFUND_REVERSAL", "PAYMENT", str(payment.id)
            )
            if target > prior:
                await helper.entry(
                    organization_id,
                    order.customer_id,
                    -(target - prior),
                    "REFUND_REVERSAL",
                    "REFUND",
                    str(refund.id),
                    "Refund loyalty earn reversal",
                    occurred_at,
                    lifetime=True,
                    related_source_id=str(payment.id),
                )
        redeemed = -await helper.source_points(
            organization_id, order.customer_id, "REDEEM", "PAYMENT", str(payment.id)
        )
        if redeemed > 0:
            target = redeemed if full else redeemed * cumulative // payment.amount_minor
            prior = await helper.kind_sum(
                organization_id,
                order.customer_id,
                "REDEMPTION_REVERSAL",
                "PAYMENT",
                str(payment.id),
            )
            if target > prior:
                await helper.entry(
                    organization_id,
                    order.customer_id,
                    target - prior,
                    "REDEMPTION_REVERSAL",
                    "REFUND",
                    str(refund.id),
                    "Refund loyalty redemption return",
                    occurred_at,
                    related_source_id=str(payment.id),
                )
            if full:
                redemption = await self.session.scalar(
                    select(LoyaltyRedemptionModel)
                    .where(
                        LoyaltyRedemptionModel.organization_id == organization_id,
                        LoyaltyRedemptionModel.order_id == order.id,
                        LoyaltyRedemptionModel.status == "APPLIED",
                    )
                    .with_for_update()
                )
                if redemption is not None:
                    redemption.status = "REVERSED"
                    redemption.reversed_at = occurred_at


class _ProjectionLedger:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def account(self, organization_id: UUID, customer_id: UUID):
        value = await self.session.scalar(
            select(LoyaltyAccountModel)
            .where(
                LoyaltyAccountModel.organization_id == organization_id,
                LoyaltyAccountModel.customer_id == customer_id,
            )
            .with_for_update()
        )
        if value is None:
            raise LoyaltyInvalid("Loyalty account not found")
        return value

    async def entry(
        self,
        organization_id: UUID,
        customer_id: UUID,
        delta: int,
        kind: str,
        source_type: str,
        source_id: str,
        reason: str,
        occurred_at: datetime,
        *,
        lifetime: bool = False,
        related_source_id: str | None = None,
    ) -> None:
        account = await self.account(organization_id, customer_id)
        if await self.session.scalar(
            select(LoyaltyLedgerEntryModel.id).where(
                LoyaltyLedgerEntryModel.organization_id == organization_id,
                LoyaltyLedgerEntryModel.customer_id == customer_id,
                LoyaltyLedgerEntryModel.kind == kind,
                LoyaltyLedgerEntryModel.source_type == source_type,
                LoyaltyLedgerEntryModel.source_id == source_id,
            )
        ):
            return
        next_balance = account.points_balance + delta
        if delta < 0 and next_balance < 0 and kind != "REFUND_REVERSAL":
            raise LoyaltyInsufficientBalance("Loyalty points balance is insufficient")
        if abs(next_balance) > MAX_BIGINT:
            raise LoyaltyInvalid("Loyalty points are outside BIGINT")
        self.session.add(
            LoyaltyLedgerEntryModel(
                id=uuid4(),
                organization_id=organization_id,
                customer_id=customer_id,
                points_delta=delta,
                kind=kind,
                source_type=source_type,
                source_id=source_id,
                related_source_id=related_source_id,
                reason=reason,
                created_by_user_id=None,
                occurred_at=occurred_at,
                recorded_at=datetime.now(UTC),
            )
        )
        account.points_balance = next_balance
        if lifetime:
            next_lifetime = account.lifetime_earned_points + delta
            if not 0 <= next_lifetime <= MAX_BIGINT:
                raise LoyaltyInvalid("Lifetime loyalty points are outside BIGINT")
            account.lifetime_earned_points = next_lifetime
            tier = await self.session.scalar(
                select(LoyaltyTierModel)
                .where(
                    LoyaltyTierModel.organization_id == organization_id,
                    LoyaltyTierModel.threshold_lifetime_points <= next_lifetime,
                )
                .order_by(LoyaltyTierModel.threshold_lifetime_points.desc())
                .limit(1)
            )
            account.tier_id = tier.id if tier else None
        account.updated_at = datetime.now(UTC)
        await self.session.flush()

    async def source_points(
        self, organization_id: UUID, customer_id: UUID, kind: str, source_type: str, source_id: str
    ) -> int:
        return int(
            await self.session.scalar(
                select(func.coalesce(func.sum(LoyaltyLedgerEntryModel.points_delta), 0)).where(
                    LoyaltyLedgerEntryModel.organization_id == organization_id,
                    LoyaltyLedgerEntryModel.customer_id == customer_id,
                    LoyaltyLedgerEntryModel.kind == kind,
                    LoyaltyLedgerEntryModel.source_type == source_type,
                    LoyaltyLedgerEntryModel.source_id == source_id,
                )
            )
            or 0
        )

    async def kind_sum(
        self,
        organization_id: UUID,
        customer_id: UUID,
        kind: str,
        original_source_type: str,
        original_source_id: str,
    ) -> int:
        return int(
            await self.session.scalar(
                select(func.coalesce(func.sum(LoyaltyLedgerEntryModel.points_delta), 0)).where(
                    LoyaltyLedgerEntryModel.organization_id == organization_id,
                    LoyaltyLedgerEntryModel.customer_id == customer_id,
                    LoyaltyLedgerEntryModel.kind == kind,
                    LoyaltyLedgerEntryModel.related_source_id == original_source_id,
                )
            )
            or 0
        )


def normalize_phone(value: str) -> str:
    digits = re.sub(r"\D", "", value)
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    elif len(digits) == 10:
        digits = "7" + digits
    if not 10 <= len(digits) <= 15:
        raise CustomerInvalid("Phone must contain 10 to 15 digits")
    return "+" + digits


def _bigint(value: str | int, *, positive: bool = False, signed: bool = False) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise LoyaltyInvalid("Value must be an integer") from exc
    if abs(number) > MAX_BIGINT or (positive and number <= 0) or (not signed and number < 0):
        raise LoyaltyInvalid("Value is outside BIGINT")
    if signed and number == 0:
        raise LoyaltyInvalid("points_delta cannot be zero")
    return number


def _optional(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    result = value.strip()
    if len(result) > limit:
        raise CustomerInvalid(f"Text cannot exceed {limit} characters")
    return result or None


def _required(value: str, limit: int) -> str:
    result = value.strip()
    if not result or len(result) > limit:
        raise CustomerInvalid(f"Text must contain between 1 and {limit} characters")
    return result


def _email(value: str | None) -> str | None:
    result = _optional(value, 320)
    if result and ("@" not in result or result.startswith("@") or result.endswith("@")):
        raise CustomerInvalid("Email is invalid")
    return result.lower() if result else None


def _birth_date(value: date | None) -> date | None:
    if value and value > date.today():
        raise CustomerInvalid("birth_date cannot be in the future")
    return value


def _tier_ref(value: LoyaltyTierModel | None):
    return {"id": value.id, "name": value.name} if value else None


def _tier_view(value: LoyaltyTierModel):
    return {
        "id": value.id,
        "organization_id": value.organization_id,
        "name": value.name,
        "threshold_lifetime_points": str(value.threshold_lifetime_points),
        "earn_multiplier_bps": value.earn_multiplier_bps,
        "created_at": value.created_at,
        "updated_at": value.updated_at,
    }


def _customer_name(value: CustomerModel) -> str | None:
    return " ".join(part for part in (value.first_name, value.last_name) if part) or None


def _program_view(value: LoyaltyProgramModel):
    return {
        "earn_rate_bps": value.earn_rate_bps,
        "point_value_minor": str(value.point_value_minor),
        "birthday_reward_points": str(value.birthday_reward_points),
        "is_active": value.is_active,
    }
