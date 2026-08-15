import base64
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from beanly.core.config.settings import Settings
from beanly.core.events.outbox.repositories import OutboxRepository
from beanly.core.events.outbox.writer import OutboxEventSink
from beanly.core.observability.metrics import metrics
from beanly.modules.customers.infrastructure.db.models import PromotionAudienceModel
from beanly.modules.offline_pos.infrastructure.catalog_builder import CatalogSnapshotBuilder
from beanly.modules.online_ordering.api.schemas import (
    AvailabilityResponse,
    ChannelReportRow,
    LocationSettingsResponse,
    OnlineOrderItemResponse,
    OnlineOrderResponse,
    PublicMenuResponse,
    PublicOrderingResponse,
    QuoteLineResponse,
    QuoteRequest,
    QuoteResponse,
    ReadinessResponse,
    StationResponse,
)
from beanly.modules.online_ordering.domain.enums import (
    OnlineOrderSource,
    OnlineOrderStatus,
)
from beanly.modules.online_ordering.domain.events import (
    OnlineOrderAccepted,
    OnlineOrderCancelled,
    OnlineOrderRejected,
    OnlineOrderSubmitted,
)
from beanly.modules.online_ordering.domain.exceptions import (
    OnlineOrderAlreadyAccepted,
    OnlineOrderCartInvalid,
    OnlineOrderIdempotencyConflict,
    OnlineOrderingNotFound,
    OnlineOrderingUnavailable,
    OnlineOrderInvalidState,
    OnlineOrderInvalidStation,
    OnlineOrderQuoteChanged,
)
from beanly.modules.online_ordering.infrastructure.db.models import (
    OnlineOrderActionModel,
    OnlineOrderingLocationModel,
    OnlineOrderingScheduleModel,
    OnlineOrderModel,
    OrderingStationModel,
)
from beanly.modules.organizations.application.services.organization_service import (
    OrganizationService,
)
from beanly.modules.organizations.domain.entities import TenantContext
from beanly.modules.organizations.domain.exceptions import OrganizationAccessDenied
from beanly.modules.organizations.infrastructure.db.models import (
    LocationModel,
    OrganizationModel,
)
from beanly.modules.payments.infrastructure.db.models import PaymentModel
from beanly.modules.promotions.application.pricing_engine import (
    SelectedPromotion,
    price_order,
)
from beanly.modules.promotions.domain.entities import PricingItem
from beanly.modules.promotions.domain.enums import (
    DiscountSource,
    PromotionChannel,
    PromotionStatus,
)
from beanly.modules.promotions.infrastructure.db.models import (
    PromotionCodeModel,
    SalesOrderDiscountModel,
)
from beanly.modules.promotions.infrastructure.db.repositories import SqlAlchemyPromotionRepository
from beanly.modules.promotions.infrastructure.pricing_service import reprice_order
from beanly.modules.refunds.infrastructure.db.models import RefundModel
from beanly.modules.sales.domain.enums import OrderStatus, OrderType, RegisterShiftStatus
from beanly.modules.sales.infrastructure.db.models import (
    PosRegisterModel,
    RegisterShiftModel,
    SalesOrderItemComponentModel,
    SalesOrderItemModel,
    SalesOrderItemModifierModel,
    SalesOrderModel,
)

_MAX_BIGINT = 9_223_372_036_854_775_807
_QUOTE_TTL = 300


@dataclass(frozen=True, slots=True)
class _ResolvedLine:
    request: object
    item_id: UUID
    category_id: UUID
    product_id: UUID
    product_name: str
    variant_name: str
    base_price: int
    modifier_price: int
    modifiers: tuple[dict[str, object], ...]
    components: tuple[dict[str, object], ...]

    @property
    def unit_price(self) -> int:
        return self.base_price + self.modifier_price


class OnlineOrderingService:
    def __init__(
        self,
        session: AsyncSession,
        organizations: OrganizationService,
        settings: Settings,
    ) -> None:
        self.session = session
        self.organizations = organizations
        self.settings = settings
        self.events = OutboxEventSink(OutboxRepository(session))

    async def public_location(
        self, slug: str, station_token: str | None
    ) -> PublicOrderingResponse:
        config, location, organization = await self._public_scope(slug)
        station = await self._station_token(config, station_token) if station_token else None
        availability = await self._availability(config, location, station)
        return PublicOrderingResponse(
            slug=config.public_slug,
            location_id=location.id,
            location_name=location.name,
            timezone=location.timezone,
            currency_code=organization.currency_code,
            enabled=config.enabled,
            pickup_enabled=config.pickup_enabled,
            qr_dine_in_enabled=config.qr_dine_in_enabled,
            accepting_orders=availability.available,
            unavailable_reason=availability.reasons[0] if availability.reasons else None,
            guest_name_required=station is None or config.guest_name_required,
            guest_phone_required_pickup=True,
            station=(
                {"kind": station.kind, "label": station.label} if station is not None else None
            ),
        )

    async def public_menu(self, slug: str) -> PublicMenuResponse:
        config, location, organization = await self._public_scope(slug)
        shift = await self._catalog_shift(config)
        if shift is None:
            raise OnlineOrderingUnavailable("Online ordering has no register catalog")
        snapshot = await CatalogSnapshotBuilder(self.session).build(
            config.organization_id, config.location_id, shift.warehouse_id
        )
        return PublicMenuResponse(
            location_id=location.id,
            currency_code=organization.currency_code,
            categories=_public_categories(snapshot.public_payload),
        )

    async def availability(
        self, slug: str, station_token: str | None
    ) -> AvailabilityResponse:
        config, location, _ = await self._public_scope(slug)
        station = await self._station_token(config, station_token) if station_token else None
        return await self._availability(config, location, station)

    async def quote(self, slug: str, payload: QuoteRequest) -> QuoteResponse:
        config, location, _ = await self._public_scope(slug)
        station = await self._station_token(config, payload.station_token)
        await self._require_available(config, location, station)
        return await self._quote(config, location, payload)

    async def submit(self, slug: str, payload) -> OnlineOrderResponse:
        config, location, organization = await self._public_scope(slug)
        stable_hash = _payload_hash(slug, payload)
        await self._lock_organization(config.organization_id)
        existing = await self.session.scalar(
            select(OnlineOrderModel).where(
                OnlineOrderModel.organization_id == config.organization_id,
                OnlineOrderModel.client_order_id == payload.client_order_id,
            )
        )
        if existing is not None:
            if existing.payload_hash != stable_hash:
                raise OnlineOrderIdempotencyConflict(
                    "client_order_id was used with a different order"
                )
            return await self._response(existing, include_token=True)

        station = await self._station_token(config, payload.station_token)
        shift = await self._require_available(config, location, station)
        self._guest(config, station, payload.guest_name, payload.guest_phone)
        quote_payload = QuoteRequest(
            client_order_id=payload.client_order_id,
            station_token=payload.station_token,
            promo_code=payload.promo_code,
            items=payload.items,
        )
        try:
            issued = int(payload.quote_revision.split(":", 1)[0])
        except (ValueError, IndexError) as exc:
            raise await self._quote_changed(config, location, quote_payload) from exc
        now = datetime.now(UTC)
        if issued > int(now.timestamp()) or int(now.timestamp()) - issued > _QUOTE_TTL:
            raise await self._quote_changed(
                config, location, quote_payload, "The quote expired"
            )
        try:
            authoritative = await self._quote(config, location, quote_payload, issued=issued)
        except OnlineOrderCartInvalid as exc:
            raise await self._quote_changed(config, location, quote_payload) from exc
        if not hmac.compare_digest(authoritative.quote_revision, payload.quote_revision):
            raise await self._quote_changed(config, location, quote_payload)

        lines, pricing, selected = await self._resolve_and_price(
            config, location, shift, quote_payload
        )
        online_id = uuid4()
        sales_id = uuid4()
        source = OnlineOrderSource.QR if station else OnlineOrderSource.ONLINE
        sales = SalesOrderModel(
            id=sales_id,
            organization_id=config.organization_id,
            location_id=config.location_id,
            shift_id=shift.id,
            warehouse_id=shift.warehouse_id,
            number=await self._next_order_number(),
            client_order_id=payload.client_order_id,
            order_source=source.value,
            order_type=(OrderType.DINE_IN.value if station else OrderType.TAKEAWAY.value),
            status=OrderStatus.OPEN.value,
            currency_code=organization.currency_code,
            guest_count=1 if station else None,
            table_label=station.label if station else None,
            note=None,
            customer_name_snapshot=_text(payload.guest_name),
            customer_phone_snapshot=_phone(payload.guest_phone),
            subtotal_minor=pricing.subtotal_minor,
            discount_total_minor=0,
            total_minor=pricing.subtotal_minor,
            pricing_revision=1,
            created_by_user_id=None,
            created_at=now,
            updated_at=now,
            version=1,
        )
        sales.items = [_sales_item(sales_id, line, now) for line in lines]
        self.session.add(sales)
        await self.session.flush()
        if selected is not None:
            self.session.add(
                SalesOrderDiscountModel(
                    id=uuid4(),
                    order_id=sales_id,
                    client_discount_id=uuid5(
                        NAMESPACE_URL, f"beanly:online-code:{sales_id}:{selected.code}"
                    ),
                    promotion_id=selected.promotion.id,
                    source=DiscountSource.PROMO_CODE.value,
                    promotion_name=selected.promotion.name,
                    discount_kind=selected.promotion.discount_kind.value,
                    scope=selected.promotion.scope.value,
                    percent_rate=selected.promotion.percent_rate,
                    configured_amount_minor=(
                        selected.promotion.amount_minor or selected.promotion.fixed_price_minor
                    ),
                    promo_code_snapshot=selected.code,
                    reason=None,
                    applied_by_user_id=None,
                    applied_at=now,
                    discount_total_minor=0,
                    promotion_config_hash="intent",
                    sort_order=999,
                )
            )
            await self.session.flush()
        await reprice_order(
            self.session,
            config.organization_id,
            sales_id,
            occurred_at=now,
            channel=PromotionChannel.QR if station else PromotionChannel.ONLINE,
        )
        await self.session.refresh(sales)
        if (
            sales.subtotal_minor,
            sales.discount_total_minor,
            sales.total_minor,
        ) != (pricing.subtotal_minor, pricing.discount_total_minor, pricing.total_minor):
            raise await self._quote_changed(config, location, quote_payload)
        auto_accept = bool(station and config.qr_auto_accept)
        online = OnlineOrderModel(
            id=online_id,
            organization_id=config.organization_id,
            location_id=config.location_id,
            sales_order_id=sales_id,
            station_id=station.id if station else None,
            client_order_id=payload.client_order_id,
            payload_hash=stable_hash,
            source=source.value,
            status=(
                OnlineOrderStatus.AWAITING_PAYMENT.value
                if auto_accept
                else OnlineOrderStatus.PENDING.value
            ),
            guest_name_snapshot=_text(payload.guest_name),
            guest_phone_snapshot=_phone(payload.guest_phone),
            station_label_snapshot=station.label if station else None,
            subtotal_minor=sales.subtotal_minor,
            discount_minor=sales.discount_total_minor,
            total_minor=sales.total_minor,
            quote_revision=payload.quote_revision,
            status_token_hash=_sha(self._status_token(online_id)),
            accepted_at=now if auto_accept else None,
            created_at=now,
            updated_at=now,
        )
        self.session.add(online)
        self._action(online, "SUBMIT", None, online.status, None, None)
        await self.events.stage(
            OnlineOrderSubmitted(config.organization_id, online.id, sales.id), occurred_at=now
        )
        if auto_accept:
            await self.events.stage(
                OnlineOrderAccepted(config.organization_id, online.id, sales.id), occurred_at=now
            )
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            existing = await self.session.scalar(
                select(OnlineOrderModel).where(
                    OnlineOrderModel.organization_id == config.organization_id,
                    OnlineOrderModel.client_order_id == payload.client_order_id,
                )
            )
            if existing is None or existing.payload_hash != stable_hash:
                raise OnlineOrderIdempotencyConflict(
                    "client_order_id was used with a different order"
                ) from exc
            return await self._response(existing, include_token=True)
        metrics.online_orders_submitted.add(1, {"source": source.value})
        if auto_accept:
            metrics.online_orders_accepted.add(1, {"source": source.value})
            metrics.online_acceptance_seconds.record(0, {"source": source.value})
        return await self._response(online, include_token=True)

    async def public_status(self, token: str) -> OnlineOrderResponse:
        order = await self._by_status_token(token)
        return await self._response(order)

    async def public_cancel(self, token: str) -> OnlineOrderResponse:
        order = await self._by_status_token(token, lock=True)
        if order.status != OnlineOrderStatus.PENDING.value:
            raise OnlineOrderAlreadyAccepted("Only a pending order can be cancelled by the guest")
        await self._cancel_sales(order, None, "Cancelled by guest")
        previous = order.status
        order.status = OnlineOrderStatus.CANCELLED.value
        order.cancelled_at = order.updated_at = datetime.now(UTC)
        order.cancel_reason = "Cancelled by guest"
        self._action(order, "GUEST_CANCEL", previous, order.status, None, None)
        await self.events.stage(
            OnlineOrderCancelled(order.organization_id, order.id, order.sales_order_id),
            occurred_at=order.cancelled_at,
        )
        await self.session.commit()
        metrics.online_orders_cancelled.add(1, {"source": order.source})
        return await self._response(order)

    async def list_orders(
        self,
        context: TenantContext,
        *,
        location_id: UUID | None,
        status: OnlineOrderStatus | None,
    ) -> list[OnlineOrderResponse]:
        allowed = await self._allowed_locations(context)
        if location_id is not None:
            if location_id not in allowed:
                raise OnlineOrderingNotFound("Location not found")
            allowed = {location_id}
        query = select(OnlineOrderModel).where(
            OnlineOrderModel.organization_id == context.organization_id,
            OnlineOrderModel.location_id.in_(allowed),
        )
        if status is not None:
            query = query.where(OnlineOrderModel.status == status.value)
        values = await self.session.scalars(
            query.order_by(OnlineOrderModel.created_at.desc()).limit(250)
        )
        return [await self._response(value) for value in values]

    async def get_order(self, context: TenantContext, order_id: UUID) -> OnlineOrderResponse:
        order = await self._staff_order(context, order_id)
        return await self._response(order)

    async def accept(
        self, context: TenantContext, order_id: UUID, client_action_id: UUID
    ) -> OnlineOrderResponse:
        order = await self._staff_order(context, order_id, lock=True)
        if await self._replay(
            context.organization_id, client_action_id, order.id, "ACCEPT"
        ):
            return await self._response(order)
        if order.status != OnlineOrderStatus.PENDING.value:
            raise OnlineOrderInvalidState("Only pending online orders can be accepted")
        previous = order.status
        now = datetime.now(UTC)
        order.status = OnlineOrderStatus.AWAITING_PAYMENT.value
        order.accepted_by_user_id = context.user_id
        order.accepted_at = order.updated_at = now
        self._action(order, "ACCEPT", previous, order.status, context.user_id, client_action_id)
        await self.events.stage(
            OnlineOrderAccepted(order.organization_id, order.id, order.sales_order_id),
            occurred_at=now,
        )
        await self.session.commit()
        metrics.online_orders_accepted.add(1, {"source": order.source})
        metrics.online_acceptance_seconds.record(
            max(0, (now - _utc(order.created_at)).total_seconds()), {"source": order.source}
        )
        return await self._response(order)

    async def reject(
        self, context: TenantContext, order_id: UUID, client_action_id: UUID, reason: str
    ) -> OnlineOrderResponse:
        order = await self._staff_order(context, order_id, lock=True)
        if await self._replay(
            context.organization_id, client_action_id, order.id, "REJECT", reason
        ):
            return await self._response(order)
        if order.status != OnlineOrderStatus.PENDING.value:
            raise OnlineOrderInvalidState("Only pending online orders can be rejected")
        await self._cancel_sales(order, context.user_id, reason)
        previous = order.status
        now = datetime.now(UTC)
        order.status = OnlineOrderStatus.REJECTED.value
        order.rejected_by_user_id = context.user_id
        order.rejected_at = order.updated_at = now
        order.rejection_reason = reason.strip()
        self._action(
            order, "REJECT", previous, order.status, context.user_id, client_action_id, reason
        )
        await self.events.stage(
            OnlineOrderRejected(order.organization_id, order.id, order.sales_order_id),
            occurred_at=now,
        )
        await self.session.commit()
        metrics.online_orders_rejected.add(1, {"source": order.source})
        return await self._response(order)

    async def cancel(
        self, context: TenantContext, order_id: UUID, client_action_id: UUID, reason: str
    ) -> OnlineOrderResponse:
        order = await self._staff_order(context, order_id, lock=True)
        if await self._replay(
            context.organization_id, client_action_id, order.id, "CANCEL", reason
        ):
            return await self._response(order)
        if order.status not in {
            OnlineOrderStatus.PENDING.value,
            OnlineOrderStatus.AWAITING_PAYMENT.value,
        }:
            raise OnlineOrderInvalidState("Paid online orders require a refund")
        await self._cancel_sales(order, context.user_id, reason)
        previous = order.status
        now = datetime.now(UTC)
        order.status = OnlineOrderStatus.CANCELLED.value
        order.cancelled_by_user_id = context.user_id
        order.cancelled_at = order.updated_at = now
        order.cancel_reason = reason.strip()
        self._action(
            order, "CANCEL", previous, order.status, context.user_id, client_action_id, reason
        )
        await self.events.stage(
            OnlineOrderCancelled(order.organization_id, order.id, order.sales_order_id),
            occurred_at=now,
        )
        await self.session.commit()
        metrics.online_orders_cancelled.add(1, {"source": order.source})
        return await self._response(order)

    async def get_settings(
        self, context: TenantContext, location_id: UUID
    ) -> LocationSettingsResponse:
        await self._location_access(context, location_id)
        value = await self._config(context.organization_id, location_id)
        if value is None:
            raise OnlineOrderingNotFound("Online ordering settings not found")
        return LocationSettingsResponse.from_model(value)

    async def save_settings(self, context: TenantContext, payload) -> LocationSettingsResponse:
        await self._location_access(context, payload.location_id)
        if payload.register_id is not None:
            valid_register = await self.session.scalar(
                select(PosRegisterModel.id).where(
                    PosRegisterModel.id == payload.register_id,
                    PosRegisterModel.organization_id == context.organization_id,
                    PosRegisterModel.location_id == payload.location_id,
                    PosRegisterModel.is_active.is_(True),
                )
            )
            if valid_register is None:
                raise OnlineOrderingNotFound("Register not found")
        model = await self._config(context.organization_id, payload.location_id, lock=True)
        now = datetime.now(UTC)
        if model is None:
            model = OnlineOrderingLocationModel(
                id=uuid4(),
                organization_id=context.organization_id,
                location_id=payload.location_id,
                created_at=now,
            )
            self.session.add(model)
        for field in (
            "public_slug",
            "enabled",
            "pickup_enabled",
            "qr_dine_in_enabled",
            "qr_auto_accept",
            "register_id",
            "accepting_orders",
            "guest_name_required",
            "guest_phone_required_pickup",
        ):
            setattr(model, field, getattr(payload, field))
        model.minimum_order_minor = int(payload.minimum_order_minor)
        model.maximum_order_minor = (
            int(payload.maximum_order_minor) if payload.maximum_order_minor is not None else None
        )
        model.updated_at = now
        await self.session.flush()
        await self.session.execute(
            delete(OnlineOrderingScheduleModel).where(
                OnlineOrderingScheduleModel.location_id == payload.location_id
            )
        )
        self.session.add_all([
            OnlineOrderingScheduleModel(
                id=uuid4(),
                location_config_id=model.id,
                organization_id=context.organization_id,
                location_id=payload.location_id,
                weekday=item.weekday,
                opens_at_local=item.opens_at_local,
                closes_at_local=item.closes_at_local,
            )
            for item in payload.schedules
        ])
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise OnlineOrderCartInvalid("Public slug or schedule is already in use") from exc
        saved = await self._config(context.organization_id, payload.location_id)
        assert saved is not None
        return LocationSettingsResponse.from_model(saved)

    async def pause(self, context: TenantContext, payload) -> LocationSettingsResponse:
        model = await self._managed_config(context, payload.location_id, lock=True)
        location = await self.session.scalar(
            select(LocationModel).where(
                LocationModel.id == payload.location_id,
                LocationModel.organization_id == context.organization_id,
            )
        )
        if location is None:
            raise OnlineOrderingNotFound("Location not found")
        now = datetime.now(UTC)
        model.accepting_orders = False
        model.manual_pause_reason = payload.reason.strip()
        model.paused_until = (
            now + timedelta(minutes=payload.minutes) if payload.minutes else None
        )
        model.closed_date = (
            now.astimezone(ZoneInfo(location.timezone)).date()
            if payload.closed_today
            else None
        )
        model.updated_at = now
        await self.session.commit()
        return LocationSettingsResponse.from_model(model)

    async def resume(self, context: TenantContext, location_id: UUID) -> LocationSettingsResponse:
        model = await self._managed_config(context, location_id, lock=True)
        model.accepting_orders = True
        model.manual_pause_reason = None
        model.paused_until = None
        model.closed_date = None
        model.updated_at = datetime.now(UTC)
        await self.session.commit()
        return LocationSettingsResponse.from_model(model)

    async def list_stations(
        self, context: TenantContext, location_id: UUID | None
    ) -> list[StationResponse]:
        allowed = await self._allowed_locations(context)
        if location_id is not None:
            if location_id not in allowed:
                raise OnlineOrderingNotFound("Location not found")
            allowed = {location_id}
        values = await self.session.scalars(
            select(OrderingStationModel)
            .where(
                OrderingStationModel.organization_id == context.organization_id,
                OrderingStationModel.location_id.in_(allowed),
            )
            .order_by(OrderingStationModel.label, OrderingStationModel.id)
        )
        return [StationResponse.from_model(value) for value in values]

    async def create_station(self, context: TenantContext, payload) -> StationResponse:
        await self._location_access(context, payload.location_id)
        token = secrets.token_urlsafe(32)
        model = OrderingStationModel(
            id=uuid4(),
            organization_id=context.organization_id,
            location_id=payload.location_id,
            kind=payload.kind.value,
            label=payload.label.strip(),
            public_token_hash=_sha(token),
            is_active=True,
        )
        self.session.add(model)
        await self.session.commit()
        return StationResponse.from_model(model, token)

    async def patch_station(self, context: TenantContext, station_id: UUID, payload):
        model = await self._staff_station(context, station_id, lock=True)
        if payload.kind is not None:
            model.kind = payload.kind.value
        if payload.label is not None:
            model.label = payload.label.strip()
        if payload.is_active is not None:
            model.is_active = payload.is_active
        model.updated_at = datetime.now(UTC)
        await self.session.commit()
        return StationResponse.from_model(model)

    async def rotate_station(self, context: TenantContext, station_id: UUID):
        model = await self._staff_station(context, station_id, lock=True)
        token = secrets.token_urlsafe(32)
        model.public_token_hash = _sha(token)
        model.is_active = True
        model.updated_at = datetime.now(UTC)
        await self.session.commit()
        return StationResponse.from_model(model, token)

    async def readiness(self, context: TenantContext, location_id: UUID) -> ReadinessResponse:
        await self._location_access(context, location_id)
        config = await self._config(context.organization_id, location_id)
        reasons: list[str] = []
        register = bool(config and config.register_id)
        open_shift = await self._open_shift(config) if config else None
        shift = bool(open_shift)
        location = await self.session.scalar(
            select(LocationModel).where(
                LocationModel.id == location_id,
                LocationModel.organization_id == context.organization_id,
            )
        )
        schedule = bool(config and location and _schedule_open(config, location.timezone))
        catalog_shift = await self._catalog_shift(config) if config else None
        menu = False
        if config and catalog_shift:
            snapshot = await CatalogSnapshotBuilder(self.session).build(
                config.organization_id, config.location_id, catalog_shift.warehouse_id
            )
            menu = any(
                product.get("is_available", True) and product.get("variants")
                for category in snapshot.public_payload.get("categories", [])
                for product in category.get("products", [])
            )
        now = datetime.now(UTC)
        accepting = bool(
            config
            and (
                config.accepting_orders
                or (config.paused_until and _utc(config.paused_until) <= now)
                or (
                    location
                    and config.closed_date
                    and config.closed_date
                    != now.astimezone(ZoneInfo(location.timezone)).date()
                )
            )
        )
        if config is None or not config.enabled:
            reasons.append("ONLINE_ORDERING_DISABLED")
        if config and not config.pickup_enabled and not config.qr_dine_in_enabled:
            reasons.append("NO_ORDERING_CHANNEL_ENABLED")
        if not menu:
            reasons.append("MENU_NOT_READY")
        if not register:
            reasons.append("REGISTER_NOT_CONFIGURED")
        if register and not shift:
            reasons.append("SHIFT_NOT_OPEN")
        if not schedule:
            reasons.append("SCHEDULE_CLOSED")
        closed_today = bool(
            config
            and location
            and config.closed_date == now.astimezone(ZoneInfo(location.timezone)).date()
        )
        if not accepting and not closed_today:
            reasons.append("TEMPORARILY_PAUSED")
        if location is None or not location.is_active:
            reasons.append("LOCATION_UNAVAILABLE")
        if closed_today:
            reasons.append("CLOSED_TODAY")
        return ReadinessResponse(
            ready=not reasons,
            menu_ready=menu,
            register_configured=register,
            shift_open=shift,
            schedule_open=schedule,
            default_location_available=bool(location and location.is_active),
            reasons=reasons,
        )

    async def channel_report(
        self, context: TenantContext, date_from: date | None, date_to: date | None
    ) -> list[ChannelReportRow]:
        allowed = await self._allowed_locations(context)
        where = [
            SalesOrderModel.organization_id == context.organization_id,
            SalesOrderModel.location_id.in_(allowed),
            SalesOrderModel.status == OrderStatus.PAID.value,
        ]
        if date_from:
            where.append(
                PaymentModel.completed_at
                >= datetime.combine(date_from, datetime.min.time(), UTC)
            )
        if date_to:
            where.append(
                PaymentModel.completed_at
                < datetime.combine(date_to + timedelta(days=1), datetime.min.time(), UTC)
            )
        refunds = (
            select(
                RefundModel.order_id.label("order_id"),
                func.sum(RefundModel.total_amount_minor).label("refunded"),
            )
            .where(RefundModel.status == "COMPLETED")
            .group_by(RefundModel.order_id)
            .subquery()
        )
        revenue_rows = (
            await self.session.execute(
            select(
                SalesOrderModel.order_source,
                func.count(PaymentModel.id),
                func.sum(PaymentModel.amount_minor),
                func.coalesce(func.sum(refunds.c.refunded), 0),
            )
            .join(PaymentModel, PaymentModel.order_id == SalesOrderModel.id)
            .outerjoin(refunds, refunds.c.order_id == SalesOrderModel.id)
            .where(*where)
            .group_by(SalesOrderModel.order_source)
            )
        ).all()
        activity_where = [
            OnlineOrderModel.organization_id == context.organization_id,
            OnlineOrderModel.location_id.in_(allowed),
        ]
        if date_from:
            activity_where.append(
                OnlineOrderModel.created_at
                >= datetime.combine(date_from, datetime.min.time(), UTC)
            )
        if date_to:
            activity_where.append(
                OnlineOrderModel.created_at
                < datetime.combine(date_to + timedelta(days=1), datetime.min.time(), UTC)
            )
        activity_rows = (
            await self.session.execute(
                select(
                    OnlineOrderModel.source,
                    func.count(OnlineOrderModel.id),
                    func.count(OnlineOrderModel.id).filter(
                        OnlineOrderModel.accepted_at.is_not(None)
                    ),
                    func.count(OnlineOrderModel.id).filter(
                        OnlineOrderModel.rejected_at.is_not(None)
                    ),
                )
                .where(*activity_where)
                .group_by(OnlineOrderModel.source)
            )
        ).all()
        revenue = {
            source: (int(count), int(gross or 0), int(refunded or 0))
            for source, count, gross, refunded in revenue_rows
        }
        activity = {
            source: (int(submitted), int(accepted), int(rejected))
            for source, submitted, accepted, rejected in activity_rows
        }
        return [
            ChannelReportRow(
                order_source=source,
                orders_count=revenue.get(source, (0, 0, 0))[0],
                gross_sales_minor=str(revenue.get(source, (0, 0, 0))[1]),
                refunds_minor=str(revenue.get(source, (0, 0, 0))[2]),
                net_revenue_minor=str(
                    revenue.get(source, (0, 0, 0))[1]
                    - revenue.get(source, (0, 0, 0))[2]
                ),
                average_order_value_minor=str(
                    revenue.get(source, (0, 0, 0))[1]
                    // max(1, revenue.get(source, (0, 0, 0))[0])
                ),
                acceptance_rate_percent=_rate(activity.get(source), 1),
                reject_rate_percent=_rate(activity.get(source), 2),
            )
            for source in sorted(revenue.keys() | activity.keys())
        ]

    async def apply_event(
        self,
        organization_id: UUID,
        event_id: UUID,
        event_type: str,
        order_id: UUID | None,
        ticket_id: UUID | None,
        occurred_at: datetime,
    ) -> None:
        if await self.session.scalar(
            select(OnlineOrderActionModel.id).where(
                OnlineOrderActionModel.organization_id == organization_id,
                OnlineOrderActionModel.source_event_id == event_id,
            )
        ):
            return
        if order_id is None and ticket_id is not None:
            from beanly.modules.kitchen.infrastructure.db.models import KitchenTicketModel

            order_id = await self.session.scalar(
                select(KitchenTicketModel.order_id).where(KitchenTicketModel.id == ticket_id)
            )
        if order_id is None:
            return
        online = await self.session.scalar(
            select(OnlineOrderModel)
            .where(
                OnlineOrderModel.organization_id == organization_id,
                OnlineOrderModel.sales_order_id == order_id,
            )
            .with_for_update()
        )
        if online is None:
            return
        target, timestamp = {
            "payment.completed": (OnlineOrderStatus.PAID, "paid_at"),
            "kitchen.work_started": (OnlineOrderStatus.PREPARING, "preparing_at"),
            "kitchen.ticket_ready": (OnlineOrderStatus.READY, "ready_at"),
            "kitchen.ticket_completed": (OnlineOrderStatus.COMPLETED, "completed_at"),
        }[event_type]
        ranks = {
            OnlineOrderStatus.PENDING.value: 0,
            OnlineOrderStatus.AWAITING_PAYMENT.value: 1,
            OnlineOrderStatus.PAID.value: 2,
            OnlineOrderStatus.PREPARING.value: 3,
            OnlineOrderStatus.READY.value: 4,
            OnlineOrderStatus.COMPLETED.value: 5,
        }
        if online.status not in ranks or ranks[online.status] >= ranks[target.value]:
            self._action(
                online,
                event_type,
                online.status,
                online.status,
                None,
                None,
                event_id=event_id,
            )
            return
        previous = online.status
        online.status = target.value
        setattr(online, timestamp, occurred_at)
        online.updated_at = occurred_at
        self._action(online, event_type, previous, target.value, None, None, event_id=event_id)
        if target == OnlineOrderStatus.PAID:
            metrics.online_orders_paid.add(1, {"source": online.source})
        elif target == OnlineOrderStatus.COMPLETED:
            metrics.online_orders_completed.add(1, {"source": online.source})
        elif target == OnlineOrderStatus.READY and online.preparing_at:
            metrics.online_ready_seconds.record(
                max(0, (occurred_at - _utc(online.preparing_at)).total_seconds()),
                {"source": online.source},
            )

    async def _quote(
        self,
        config: OnlineOrderingLocationModel,
        location: LocationModel,
        payload: QuoteRequest,
        *,
        issued: int | None = None,
    ) -> QuoteResponse:
        shift = await self._open_shift(config)
        if shift is None:
            raise OnlineOrderingUnavailable("Online ordering requires an open register shift")
        lines, pricing, _ = await self._resolve_and_price(config, location, shift, payload)
        issued = issued if issued is not None else int(datetime.now(UTC).timestamp())
        expires = datetime.fromtimestamp(issued + _QUOTE_TTL, UTC)
        body = {
            "client_order_id": str(payload.client_order_id),
            "station": _sha(payload.station_token) if payload.station_token else None,
            "promo": _promo(payload.promo_code),
            "items": [item.model_dump(mode="json") for item in payload.items],
            "subtotal": pricing.subtotal_minor,
            "discount": pricing.discount_total_minor,
            "total": pricing.total_minor,
            "issued": issued,
        }
        revision = f"{issued}:{hashlib.sha256(_canonical(body)).hexdigest()}"
        return QuoteResponse(
            source=OnlineOrderSource.QR if payload.station_token else OnlineOrderSource.ONLINE,
            subtotal_minor=str(pricing.subtotal_minor),
            discount_minor=str(pricing.discount_total_minor),
            total_minor=str(pricing.total_minor),
            lines=[
                QuoteLineResponse(
                    client_item_id=line.request.client_item_id,
                    variant_id=line.request.variant_id,
                    product_name=line.product_name,
                    variant_name=line.variant_name,
                    quantity=line.request.quantity,
                    base_price_minor=str(line.base_price),
                    modifier_price_minor=str(line.modifier_price),
                    unit_price_minor=str(line.unit_price),
                    subtotal_minor=str(line.unit_price * line.request.quantity),
                    discount_minor=str(pricing.item_discount_minor.get(line.item_id, 0)),
                    total_minor=str(
                        line.unit_price * line.request.quantity
                        - pricing.item_discount_minor.get(line.item_id, 0)
                    ),
                    modifiers=[
                        {
                            "id": value["id"],
                            "name": value["name"],
                            "price_delta_minor": str(value["price_delta_minor"]),
                        }
                        for value in line.modifiers
                    ],
                )
                for line in lines
            ],
            applied_promotions=[
                {
                    "promotion_id": value.promotion_id,
                    "name": value.promotion_name,
                    "discount_minor": str(value.discount_total_minor),
                }
                for value in pricing.discounts
            ],
            quote_revision=revision,
            expires_at=expires,
        )

    async def _quote_changed(self, config, location, payload, message="The quote changed"):
        try:
            quote = await self._quote(config, location, payload)
        except OnlineOrderCartInvalid:
            quote = None
        return OnlineOrderQuoteChanged(message, quote)

    async def _resolve_and_price(self, config, location, shift, payload):
        snapshot = await CatalogSnapshotBuilder(self.session).build(
            config.organization_id, config.location_id, shift.warehouse_id
        )
        lines = _resolve_lines(snapshot.public_payload, snapshot.private_payload, payload)
        subtotal = sum(line.unit_price * line.request.quantity for line in lines)
        if subtotal > _MAX_BIGINT:
            raise OnlineOrderCartInvalid("Order total exceeds the supported range")
        repo = SqlAlchemyPromotionRepository(self.session)
        channel = PromotionChannel.QR if payload.station_token else PromotionChannel.ONLINE
        promotions = tuple(
            value
            for value in await repo.list(config.organization_id)
            if value.status == PromotionStatus.ACTIVE and channel in value.channels
        )
        if promotions:
            public_ids = set(
                await self.session.scalars(
                    select(PromotionAudienceModel.promotion_id).where(
                        PromotionAudienceModel.organization_id == config.organization_id,
                        PromotionAudienceModel.promotion_id.in_(tuple(x.id for x in promotions)),
                        PromotionAudienceModel.kind == "ALL",
                    )
                )
            )
            targeted = set(
                await self.session.scalars(
                    select(PromotionAudienceModel.promotion_id).where(
                        PromotionAudienceModel.organization_id == config.organization_id,
                        PromotionAudienceModel.promotion_id.in_(tuple(x.id for x in promotions)),
                        PromotionAudienceModel.kind != "ALL",
                    )
                )
            )
            promotions = tuple(
                value for value in promotions if value.id not in targeted or value.id in public_ids
            )
        selected = await self._promo_selection(
            config.organization_id, payload.promo_code, promotions
        )
        pricing = price_order(
            tuple(
                PricingItem(
                    line.item_id,
                    line.category_id,
                    line.product_id,
                    line.request.variant_id,
                    line.request.quantity,
                    line.base_price,
                    line.modifier_price,
                )
                for line in lines
            ),
            promotions,
            location_id=config.location_id,
            location_timezone=location.timezone,
            occurred_at=datetime.now(UTC),
            selected=(selected,) if selected else (),
        )
        if pricing.total_minor < config.minimum_order_minor:
            raise OnlineOrderCartInvalid("Order is below the configured minimum")
        if (
            config.maximum_order_minor is not None
            and pricing.total_minor > config.maximum_order_minor
        ):
            raise OnlineOrderCartInvalid("Order exceeds the configured maximum")
        return lines, pricing, selected

    async def _promo_selection(self, organization_id, code, promotions):
        normalized = _promo(code)
        if normalized is None:
            return None
        row = await self.session.scalar(
            select(PromotionCodeModel).where(
                PromotionCodeModel.organization_id == organization_id,
                PromotionCodeModel.code_normalized == normalized,
                PromotionCodeModel.is_active.is_(True),
            )
        )
        now = datetime.now(UTC)
        if row is None or (row.valid_from and now < _utc(row.valid_from)) or (
            row.valid_to and now >= _utc(row.valid_to)
        ):
            raise OnlineOrderCartInvalid("Promo code is unavailable")
        promotion = next((value for value in promotions if value.id == row.promotion_id), None)
        if promotion is None:
            raise OnlineOrderCartInvalid("Promo code is unavailable for this channel")
        return SelectedPromotion(promotion, DiscountSource.PROMO_CODE, code=normalized)

    async def _public_scope(self, slug: str):
        row = await self.session.execute(
            select(OnlineOrderingLocationModel, LocationModel, OrganizationModel)
            .join(LocationModel, LocationModel.id == OnlineOrderingLocationModel.location_id)
            .join(
                OrganizationModel,
                OrganizationModel.id == OnlineOrderingLocationModel.organization_id,
            )
            .options(selectinload(OnlineOrderingLocationModel.schedules))
            .where(
                OnlineOrderingLocationModel.public_slug == slug,
                LocationModel.is_active.is_(True),
                OrganizationModel.status == "active",
            )
        )
        value = row.first()
        if value is None:
            raise OnlineOrderingNotFound("Ordering page not found")
        return value

    async def _availability(self, config, location, station):
        now = datetime.now(UTC)
        schedule_open = _schedule_open(config, location.timezone, now)
        shift_open = await self._open_shift(config) is not None
        local_date = now.astimezone(ZoneInfo(location.timezone)).date()
        accepting = config.accepting_orders or bool(
            config.paused_until and _utc(config.paused_until) <= now
        ) or bool(
            config.closed_date and config.closed_date != local_date
        )
        reasons: list[str] = []
        if not config.enabled:
            reasons.append("ONLINE_ORDERING_DISABLED")
        if station and not config.qr_dine_in_enabled:
            reasons.append("QR_DINE_IN_DISABLED")
        if station is None and not config.pickup_enabled:
            reasons.append("PICKUP_DISABLED")
        closed_today = config.closed_date == local_date
        if not accepting and not closed_today:
            reasons.append("TEMPORARILY_PAUSED")
        if closed_today:
            reasons.append("CLOSED_TODAY")
        if not schedule_open:
            reasons.append("SCHEDULE_CLOSED")
        if not shift_open:
            reasons.append("SHIFT_NOT_OPEN")
        return AvailabilityResponse(
            available=not reasons,
            schedule_open=schedule_open,
            shift_open=shift_open,
            accepting_orders=accepting,
            reasons=reasons,
        )

    async def _require_available(self, config, location, station):
        availability = await self._availability(config, location, station)
        if not availability.available:
            raise OnlineOrderingUnavailable(availability.reasons[0])
        shift = await self._open_shift(config, lock=True)
        if shift is None:
            raise OnlineOrderingUnavailable("SHIFT_NOT_OPEN")
        return shift

    async def _open_shift(self, config, *, lock=False):
        if config.register_id is None:
            return None
        query = select(RegisterShiftModel).where(
            RegisterShiftModel.organization_id == config.organization_id,
            RegisterShiftModel.location_id == config.location_id,
            RegisterShiftModel.register_id == config.register_id,
            RegisterShiftModel.status == RegisterShiftStatus.OPEN.value,
        )
        return await self.session.scalar(query.with_for_update() if lock else query)

    async def _catalog_shift(self, config):
        if config.register_id is None:
            return None
        return await self.session.scalar(
            select(RegisterShiftModel)
            .where(
                RegisterShiftModel.organization_id == config.organization_id,
                RegisterShiftModel.location_id == config.location_id,
                RegisterShiftModel.register_id == config.register_id,
            )
            .order_by(RegisterShiftModel.opened_at.desc())
            .limit(1)
        )

    async def _station_token(self, config, token):
        if token is None:
            return None
        value = await self.session.scalar(
            select(OrderingStationModel).where(
                OrderingStationModel.organization_id == config.organization_id,
                OrderingStationModel.location_id == config.location_id,
                OrderingStationModel.public_token_hash == _sha(token),
                OrderingStationModel.is_active.is_(True),
            )
        )
        if value is None:
            raise OnlineOrderInvalidStation("Ordering station not found")
        return value

    async def _by_status_token(self, token: str, *, lock=False):
        query = select(OnlineOrderModel).where(OnlineOrderModel.status_token_hash == _sha(token))
        value = await self.session.scalar(query.with_for_update() if lock else query)
        if value is None:
            raise OnlineOrderingNotFound("Online order not found")
        return value

    async def _response(self, value, *, include_token=False):
        sales = await self.session.scalar(
            select(SalesOrderModel)
            .options(
                selectinload(SalesOrderModel.items).selectinload(
                    SalesOrderItemModel.modifiers
                )
            )
            .where(SalesOrderModel.id == value.sales_order_id)
        )
        if sales is None:
            raise OnlineOrderingNotFound("Online order not found")
        return OnlineOrderResponse(
            id=value.id,
            organization_id=value.organization_id,
            location_id=value.location_id,
            sales_order_id=value.sales_order_id,
            order_number=sales.number,
            station_id=value.station_id,
            client_order_id=value.client_order_id,
            source=value.source,
            status=value.status,
            guest_name=value.guest_name_snapshot,
            guest_phone=value.guest_phone_snapshot,
            station_label=value.station_label_snapshot,
            currency_code=sales.currency_code,
            subtotal_minor=str(value.subtotal_minor),
            discount_minor=str(value.discount_minor),
            total_minor=str(value.total_minor),
            accepted_at=value.accepted_at,
            rejected_at=value.rejected_at,
            rejection_reason=value.rejection_reason,
            cancelled_at=value.cancelled_at,
            cancel_reason=value.cancel_reason,
            paid_at=value.paid_at,
            preparing_at=value.preparing_at,
            ready_at=value.ready_at,
            completed_at=value.completed_at,
            created_at=value.created_at,
            updated_at=value.updated_at,
            items=[
                OnlineOrderItemResponse(
                    product_name=item.product_name,
                    variant_name=item.variant_name,
                    quantity=item.quantity,
                    note=item.note,
                    unit_price_minor=str(item.unit_price_minor),
                    total_minor=str(item.net_line_total_minor),
                    modifiers=[modifier.modifier_option_name for modifier in item.modifiers],
                )
                for item in sorted(sales.items, key=lambda item: (item.created_at, item.id))
            ],
            status_token=self._status_token(value.id) if include_token else None,
        )

    async def _staff_order(self, context, order_id, *, lock=False):
        query = select(OnlineOrderModel).where(
            OnlineOrderModel.id == order_id,
            OnlineOrderModel.organization_id == context.organization_id,
        )
        value = await self.session.scalar(query.with_for_update() if lock else query)
        if value is None:
            raise OnlineOrderingNotFound("Online order not found")
        await self._location_access(context, value.location_id)
        return value

    async def _cancel_sales(self, online, user_id, reason):
        now = datetime.now(UTC)
        result = await self.session.execute(
            update(SalesOrderModel)
            .where(
                SalesOrderModel.id == online.sales_order_id,
                SalesOrderModel.organization_id == online.organization_id,
                SalesOrderModel.status == OrderStatus.OPEN.value,
            )
            .values(
                status=OrderStatus.CANCELLED.value,
                cancelled_by_user_id=user_id,
                cancelled_at=now,
                cancel_reason=reason.strip(),
                updated_at=now,
                version=SalesOrderModel.version + 1,
            )
        )
        if result.rowcount != 1:
            raise OnlineOrderInvalidState("Paid online orders require a refund")

    async def _replay(
        self,
        organization_id,
        client_action_id,
        order_id,
        action_type,
        note=None,
    ):
        value = await self.session.scalar(
            select(OnlineOrderActionModel).where(
                OnlineOrderActionModel.organization_id == organization_id,
                OnlineOrderActionModel.client_action_id == client_action_id,
            )
        )
        if value is None:
            return False
        if (
            value.online_order_id != order_id
            or value.action_type != action_type
            or (value.note or None) != (_text(note) or None)
        ):
            raise OnlineOrderIdempotencyConflict("client_action_id was already used")
        return True

    def _action(
        self,
        order,
        action,
        previous,
        target,
        actor,
        client_action,
        note=None,
        *,
        event_id=None,
    ):
        self.session.add(
            OnlineOrderActionModel(
                id=uuid4(),
                organization_id=order.organization_id,
                online_order_id=order.id,
                action_type=action,
                from_status=previous,
                to_status=target,
                actor_user_id=actor,
                client_action_id=client_action,
                source_event_id=event_id,
                note=_text(note),
            )
        )

    async def _staff_station(self, context, station_id, *, lock=False):
        query = select(OrderingStationModel).where(
            OrderingStationModel.id == station_id,
            OrderingStationModel.organization_id == context.organization_id,
        )
        value = await self.session.scalar(query.with_for_update() if lock else query)
        if value is None:
            raise OnlineOrderingNotFound("Ordering station not found")
        await self._location_access(context, value.location_id)
        return value

    async def _managed_config(self, context, location_id, *, lock=False):
        await self._location_access(context, location_id)
        value = await self._config(context.organization_id, location_id, lock=lock)
        if value is None:
            raise OnlineOrderingNotFound("Online ordering settings not found")
        return value

    async def _config(self, organization_id, location_id, *, lock=False):
        query = (
            select(OnlineOrderingLocationModel)
            .options(selectinload(OnlineOrderingLocationModel.schedules))
            .where(
                OnlineOrderingLocationModel.organization_id == organization_id,
                OnlineOrderingLocationModel.location_id == location_id,
            )
        )
        return await self.session.scalar(query.with_for_update() if lock else query)

    async def _allowed_locations(self, context):
        membership = await self.organizations.repository.get_membership(
            context.organization_id, context.user_id
        )
        if membership is None:
            return set()
        return {
            value.id
            for value in await self.organizations.repository.list_accessible_locations(membership)
        }

    async def _location_access(self, context, location_id):
        try:
            await self.organizations.ensure_location_access(context, location_id)
        except OrganizationAccessDenied as exc:
            raise OnlineOrderingNotFound("Location not found") from exc

    async def _lock_organization(self, organization_id):
        await self.session.scalar(
            select(OrganizationModel.id)
            .where(OrganizationModel.id == organization_id)
            .with_for_update()
        )

    async def _next_order_number(self):
        if self.session.get_bind().dialect.name == "postgresql":
            return int(await self.session.scalar(select(func.nextval("sales_order_number_seq"))))
        return int(await self.session.scalar(select(func.count(SalesOrderModel.id))) or 0) + 1

    def _status_token(self, online_order_id: UUID) -> str:
        digest = hmac.new(
            self.settings.jwt_secret.encode(),
            f"beanly:online-order-status:{online_order_id}".encode(),
            hashlib.sha256,
        ).digest()
        return base64.urlsafe_b64encode(digest).decode().rstrip("=")

    @staticmethod
    def _guest(config, station, name, phone):
        normalized_name = _text(name)
        normalized_phone = _phone(phone)
        if (station is None or config.guest_name_required) and not normalized_name:
            raise OnlineOrderCartInvalid("Guest name is required")
        if station is None and not normalized_phone:
            raise OnlineOrderCartInvalid("Pickup phone is required")


def _rate(activity: tuple[int, int, int] | None, index: int) -> str | None:
    if activity is None or activity[0] == 0:
        return None
    return str((Decimal(activity[index]) * 100 / Decimal(activity[0])).quantize(Decimal("0.01")))


def _resolve_lines(public_payload, private_payload, payload) -> tuple[_ResolvedLine, ...]:
    if len({item.client_item_id for item in payload.items}) != len(payload.items):
        raise OnlineOrderCartInvalid("Cart item identifiers must be unique")
    public_variants: dict[str, tuple[dict, dict]] = {}
    for category in public_payload.get("categories", []):
        for product in category.get("products", []):
            for variant in product.get("variants", []):
                public_variants[str(variant["id"])] = (category, product)
    private_variants = private_payload.get("variants", {})
    lines: list[_ResolvedLine] = []
    for item in payload.items:
        public = public_variants.get(str(item.variant_id))
        private = private_variants.get(str(item.variant_id))
        if public is None or private is None or not private.get("is_available", True):
            raise OnlineOrderCartInvalid("Product is unavailable")
        category, product = public
        selected_ids = [str(value) for value in item.modifier_option_ids]
        if len(selected_ids) != len(set(selected_ids)):
            raise OnlineOrderCartInvalid("Modifier options must be unique")
        selected: list[dict] = []
        for group in private.get("modifier_groups", []):
            options = {str(value["id"]): value for value in group.get("options", [])}
            group_selected = [
                {
                    **options[value],
                    "modifier_group_id": group["id"],
                    "modifier_group_name": group["name"],
                }
                for value in selected_ids
                if value in options
            ]
            count = len(group_selected)
            if count < int(group["min_selections"]) or count > int(group["max_selections"]):
                raise OnlineOrderCartInvalid("Modifier selection is invalid")
            selected.extend(group_selected)
        if {str(value["id"]) for value in selected} != set(selected_ids):
            raise OnlineOrderCartInvalid("Modifier option is invalid")
        if any(not value.get("is_available", True) for value in selected):
            raise OnlineOrderCartInvalid("Modifier option is unavailable")
        components: dict[str, dict[str, object]] = {}
        for value in private.get("components", []):
            components[str(value["inventory_item_id"])] = dict(value)
        for option in selected:
            for value in option.get("components", []):
                key = str(value["inventory_item_id"])
                current = components.get(key, dict(value))
                current["quantity"] = str(
                    Decimal(str(current.get("quantity", "0")))
                    + Decimal(str(value.get("quantity", "0")))
                )
                components[key] = current
        if any(Decimal(str(value["quantity"])) < 0 for value in components.values()):
            raise OnlineOrderCartInvalid("Modifier selection produces invalid recipe")
        lines.append(
            _ResolvedLine(
                request=item,
                item_id=uuid5(
                    NAMESPACE_URL,
                    f"beanly:online-item:{payload.client_order_id}:{item.client_item_id}",
                ),
                category_id=UUID(str(category["id"])),
                product_id=UUID(str(product["id"])),
                product_name=str(private["product_name"]),
                variant_name=str(private["variant_name"]),
                base_price=int(private["base_price_minor"]),
                modifier_price=sum(int(value["price_delta_minor"]) for value in selected),
                modifiers=tuple(selected),
                components=tuple(
                    value
                    for value in components.values()
                    if Decimal(str(value["quantity"])) > 0
                ),
            )
        )
    return tuple(lines)


def _sales_item(order_id: UUID, line: _ResolvedLine, now: datetime):
    model = SalesOrderItemModel(
        id=line.item_id,
        order_id=order_id,
        client_item_id=line.request.client_item_id,
        product_id=line.product_id,
        product_variant_id=line.request.variant_id,
        product_name=line.product_name,
        variant_name=line.variant_name,
        quantity=line.request.quantity,
        base_price_minor=line.base_price,
        modifier_price_minor=line.modifier_price,
        unit_price_minor=line.unit_price,
        line_total_minor=line.unit_price * line.request.quantity,
        discount_amount_minor=0,
        net_line_total_minor=line.unit_price * line.request.quantity,
        note=_text(line.request.note),
        created_at=now,
        updated_at=now,
    )
    model.modifiers = [
        SalesOrderItemModifierModel(
            id=uuid4(),
            order_item_id=line.item_id,
            modifier_group_id=UUID(str(value.get("modifier_group_id") or value.get("group_id"))),
            modifier_group_name=str(value.get("modifier_group_name") or "Modifier"),
            modifier_option_id=UUID(str(value["id"])),
            modifier_option_name=str(value["name"]),
            price_delta_minor=int(value["price_delta_minor"]),
            sort_order=int(value.get("sort_order", 0)),
        )
        for value in line.modifiers
    ]
    model.components = [
        SalesOrderItemComponentModel(
            id=uuid4(),
            order_item_id=line.item_id,
            inventory_item_id=UUID(str(value["inventory_item_id"])),
            inventory_item_name=str(value["inventory_item_name"]),
            base_unit=str(value["base_unit"]),
            quantity_per_unit=Decimal(str(value["quantity"])),
            created_at=now,
        )
        for value in line.components
    ]
    return model


def _public_categories(payload: dict) -> list[dict[str, object]]:
    return [
        {
            "id": category["id"],
            "name": category["name"],
            "sort_order": category["sort_order"],
            "products": [
                {
                    "id": product["id"],
                    "name": product["name"],
                    "description": product.get("description"),
                    "image_url": product.get("image_url"),
                    "is_available": product.get("is_available", True),
                    "variants": [
                        {
                            "id": variant["id"],
                            "name": variant["name"],
                            "price_minor": variant["effective_price_minor"],
                            "is_default": variant["is_default"],
                            "sort_order": variant["sort_order"],
                            "modifier_groups": [
                                {
                                    "id": group["id"],
                                    "name": group["name"],
                                    "selection_type": group["selection_type"],
                                    "min_selections": group["min_selections"],
                                    "max_selections": group["max_selections"],
                                    "options": [
                                        {
                                            "id": option["id"],
                                            "name": option["name"],
                                            "price_delta_minor": option[
                                                "effective_price_delta_minor"
                                            ],
                                            "is_default": option["is_default"],
                                            "is_available": option["is_available"],
                                        }
                                        for option in group["options"]
                                    ],
                                }
                                for group in variant["modifier_groups"]
                            ],
                        }
                        for variant in product["variants"]
                    ],
                }
                for product in category["products"]
            ],
        }
        for category in payload.get("categories", [])
    ]


def _schedule_open(config, timezone: str, now: datetime | None = None) -> bool:
    local = (now or datetime.now(UTC)).astimezone(ZoneInfo(timezone))
    weekday, current = local.weekday(), local.time().replace(tzinfo=None)
    for value in config.schedules:
        if value.opens_at_local < value.closes_at_local:
            if value.weekday == weekday and value.opens_at_local <= current < value.closes_at_local:
                return True
        elif (value.weekday == weekday and current >= value.opens_at_local) or (
            value.weekday == (weekday - 1) % 7 and current < value.closes_at_local
        ):
            return True
    return False


def _payload_hash(slug: str, payload) -> str:
    body = payload.model_dump(mode="json", exclude={"quote_revision"})
    body["slug"] = slug
    if body.get("station_token"):
        body["station_token"] = _sha(body["station_token"])
    return hashlib.sha256(_canonical(body)).hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _promo(value: str | None) -> str | None:
    normalized = "".join((value or "").upper().split())
    return normalized or None


def _text(value: str | None) -> str | None:
    normalized = (value or "").strip()
    return normalized or None


def _phone(value: str | None) -> str | None:
    normalized = "".join(character for character in (value or "") if character.isdigit())
    if not normalized:
        return None
    if not 7 <= len(normalized) <= 15:
        raise OnlineOrderCartInvalid("Phone must contain 7 to 15 digits")
    return f"+{normalized}"


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
