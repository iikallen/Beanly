import hashlib
import hmac
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import delete, exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from beanly.core.config.settings import Settings
from beanly.core.events.outbox.repositories import OutboxRepository
from beanly.core.events.outbox.writer import OutboxEventSink
from beanly.modules.organizations.application.services.organization_service import (
    OrganizationService,
)
from beanly.modules.organizations.domain.entities import TenantContext
from beanly.modules.organizations.infrastructure.db.models import LocationModel, OrganizationModel
from beanly.modules.reservations.api.schemas import (
    AvailabilitySlotResponse,
    DiningFloorResponse,
    DiningSectionResponse,
    DiningTableResponse,
    DiningVisitResponse,
    FloorSectionResponse,
    FloorTableResponse,
    GuestReservationCreatedResponse,
    PublicReservationLocationResponse,
    PublicReservationResponse,
    ReservationAvailabilityResponse,
    ReservationResponse,
    ReservationSettingsResponse,
    WaitlistResponse,
)
from beanly.modules.reservations.domain.enums import DiningTableState, ReservationStatus
from beanly.modules.reservations.domain.events import (
    DiningVisitClosed,
    DiningVisitOpened,
    ReservationCancelled,
    ReservationCompleted,
    ReservationCreated,
    ReservationNoShow,
    ReservationSeated,
    WaitlistCancelled,
    WaitlistCreated,
    WaitlistSeated,
)
from beanly.modules.reservations.domain.exceptions import (
    BelowLeadTime,
    InvalidGuestToken,
    InvalidPartySize,
    InvalidReservationTransition,
    LocationClosed,
    NoMatchingTable,
    OutsideBookingHorizon,
    ReservationIdempotencyConflict,
    ReservationNotFound,
    ReservationsDisabled,
    SlotUnavailable,
    TableOccupied,
)
from beanly.modules.reservations.infrastructure.db.models import (
    DiningSectionModel,
    DiningTableModel,
    DiningVisitModel,
    ReservationLocationModel,
    ReservationModel,
    ReservationScheduleModel,
    WaitlistEntryModel,
)
from beanly.modules.sales.application.commands import CreateOrderInput
from beanly.modules.sales.application.order_service import OrderService
from beanly.modules.sales.domain.enums import OrderStatus, OrderType
from beanly.modules.sales.infrastructure.db.models import SalesOrderModel


class ReservationService:
    def __init__(
        self,
        session: AsyncSession,
        organizations: OrganizationService,
        settings: Settings,
        orders: OrderService | None = None,
    ) -> None:
        self.session = session
        self.organizations = organizations
        self.settings = settings
        self.orders = orders
        self.events = OutboxEventSink(OutboxRepository(session))

    async def public_location(self, slug: str) -> PublicReservationLocationResponse:
        config, location, organization = await self._public_scope(slug)
        return PublicReservationLocationResponse(
            slug=config.public_slug,
            organization_name=organization.name,
            location_name=location.name,
            timezone=location.timezone,
            reservations_enabled=config.reservations_enabled,
            minimum_lead_minutes=config.minimum_lead_minutes,
            maximum_advance_days=config.maximum_advance_days,
            maximum_party_size=config.maximum_party_size,
            slot_interval_minutes=config.slot_interval_minutes,
        )

    async def availability(
        self, slug: str, requested_date: date, party_size: int
    ) -> ReservationAvailabilityResponse:
        config, location, _ = await self._public_scope(slug)
        self._validate_party(config, party_size)
        if not config.reservations_enabled:
            raise ReservationsDisabled("Reservations are disabled")
        slots = await self._available_slots(config, location, requested_date, party_size)
        return ReservationAvailabilityResponse(
            timezone=location.timezone,
            date=requested_date,
            party_size=party_size,
            slots=slots,
        )

    async def create_guest(self, slug: str, payload) -> GuestReservationCreatedResponse:
        config, location, _ = await self._public_scope(slug)
        existing = await self.session.scalar(
            select(ReservationModel).where(
                ReservationModel.organization_id == config.organization_id,
                ReservationModel.client_reservation_id == payload.client_reservation_id,
            )
        )
        if existing is not None:
            self._assert_same_reservation(existing, payload, "GUEST", config)
            return await self._guest_response(existing, location, include_token=True)
        reservation = await self._build_reservation(config, location, payload, "GUEST")
        organization_id = config.organization_id
        location_id = config.location_id
        client_reservation_id = payload.client_reservation_id
        try:
            self.session.add(reservation)
            await self.session.flush()
            await self.events.stage(
                ReservationCreated(
                    reservation.id, reservation.organization_id, reservation.location_id
                )
            )
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            existing = await self.session.scalar(
                select(ReservationModel).where(
                    ReservationModel.organization_id == organization_id,
                    ReservationModel.client_reservation_id == client_reservation_id,
                )
            )
            if existing is not None:
                config = await self._config(organization_id, location_id)
                location = await self.session.get(LocationModel, location_id)
                if location is None:
                    raise InvalidGuestToken("Reservation not found") from exc
                self._assert_same_reservation(existing, payload, "GUEST", config)
                return await self._guest_response(existing, location, include_token=True)
            raise SlotUnavailable("The selected slot is no longer available") from exc
        return await self._guest_response(reservation, location, include_token=True)

    async def public_status(self, token: str) -> PublicReservationResponse:
        reservation = await self._token_reservation(token)
        location = await self.session.get(LocationModel, reservation.location_id)
        if location is None:
            raise InvalidGuestToken("Reservation not found")
        return await self._guest_response(reservation, location)

    async def public_cancel(self, token: str) -> PublicReservationResponse:
        reservation = await self._token_reservation(token, lock=True)
        config = await self._config(reservation.organization_id, reservation.location_id)
        location = await self.session.get(LocationModel, reservation.location_id)
        if location is None:
            raise InvalidGuestToken("Reservation not found")
        if reservation.status == ReservationStatus.CANCELLED:
            return await self._guest_response(reservation, location)
        if reservation.status != ReservationStatus.BOOKED:
            raise InvalidReservationTransition("Only a booked reservation can be cancelled")
        if not self._can_guest_cancel(reservation, config):
            raise InvalidReservationTransition("Guest cancellation cutoff has passed")
        now = datetime.now(UTC)
        reservation.status = ReservationStatus.CANCELLED
        reservation.cancelled_at = now
        reservation.updated_at = now
        await self.events.stage(
            ReservationCancelled(
                reservation.id, reservation.organization_id, reservation.location_id
            )
        )
        await self.session.commit()
        return await self._guest_response(reservation, location)

    async def get_settings(
        self, context: TenantContext, location_id: UUID
    ) -> ReservationSettingsResponse:
        await self._access(context, location_id)
        value = await self._config(context.organization_id, location_id)
        return ReservationSettingsResponse.from_model(value)

    async def save_settings(self, context: TenantContext, payload) -> ReservationSettingsResponse:
        await self._access(context, payload.location_id)
        value = await self.session.scalar(
            select(ReservationLocationModel)
            .options(selectinload(ReservationLocationModel.schedules))
            .where(
                ReservationLocationModel.organization_id == context.organization_id,
                ReservationLocationModel.location_id == payload.location_id,
            )
            .with_for_update()
        )
        now = datetime.now(UTC)
        if value is None:
            value = ReservationLocationModel(
                id=uuid4(),
                organization_id=context.organization_id,
                location_id=payload.location_id,
                created_at=now,
                updated_at=now,
                schedules=[],
            )
            self.session.add(value)
        for name in (
            "public_slug",
            "reservations_enabled",
            "default_duration_minutes",
            "cleanup_buffer_minutes",
            "minimum_lead_minutes",
            "maximum_advance_days",
            "guest_cancellation_cutoff_minutes",
            "maximum_party_size",
            "slot_interval_minutes",
        ):
            setattr(value, name, getattr(payload, name))
        value.updated_at = now
        await self.session.flush()
        await self.session.execute(
            delete(ReservationScheduleModel).where(ReservationScheduleModel.settings_id == value.id)
        )
        value.schedules = [
            ReservationScheduleModel(
                id=uuid4(),
                settings_id=value.id,
                organization_id=context.organization_id,
                location_id=payload.location_id,
                weekday=item.weekday,
                opens_at_local=item.opens_at_local,
                closes_at_local=item.closes_at_local,
                created_at=now,
            )
            for item in payload.schedules
        ]
        await self.session.commit()
        await self.session.refresh(value, attribute_names=["schedules"])
        return ReservationSettingsResponse.from_model(value)

    async def list_sections(
        self, context: TenantContext, location_id: UUID
    ) -> list[DiningSectionResponse]:
        await self._access(context, location_id)
        values = await self.session.scalars(
            select(DiningSectionModel)
            .where(
                DiningSectionModel.organization_id == context.organization_id,
                DiningSectionModel.location_id == location_id,
            )
            .order_by(DiningSectionModel.sort_order, DiningSectionModel.name, DiningSectionModel.id)
        )
        return [DiningSectionResponse.model_validate(value) for value in values]

    async def create_section(self, context: TenantContext, payload) -> DiningSectionResponse:
        await self._access(context, payload.location_id)
        now = datetime.now(UTC)
        value = DiningSectionModel(
            id=uuid4(),
            organization_id=context.organization_id,
            location_id=payload.location_id,
            name=_required(payload.name, 120),
            sort_order=payload.sort_order,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        self.session.add(value)
        await self._commit_integrity()
        return DiningSectionResponse.model_validate(value)

    async def patch_section(
        self, context: TenantContext, section_id: UUID, payload
    ) -> DiningSectionResponse:
        value = await self._section(context, section_id, lock=True)
        for name in payload.model_fields_set:
            setattr(value, name, getattr(payload, name))
        if "name" in payload.model_fields_set:
            value.name = _required(value.name, 120)
        value.updated_at = datetime.now(UTC)
        await self._commit_integrity()
        return DiningSectionResponse.model_validate(value)

    async def list_tables(
        self, context: TenantContext, location_id: UUID
    ) -> list[DiningTableResponse]:
        await self._access(context, location_id)
        values = await self.session.scalars(
            select(DiningTableModel)
            .where(
                DiningTableModel.organization_id == context.organization_id,
                DiningTableModel.location_id == location_id,
            )
            .order_by(DiningTableModel.sort_order, DiningTableModel.name, DiningTableModel.id)
        )
        return [DiningTableResponse.model_validate(value) for value in values]

    async def create_table(self, context: TenantContext, payload) -> DiningTableResponse:
        await self._access(context, payload.location_id)
        section = await self._section(context, payload.section_id)
        if section.location_id != payload.location_id:
            raise ReservationNotFound("Section not found")
        now = datetime.now(UTC)
        value = DiningTableModel(
            id=uuid4(),
            organization_id=context.organization_id,
            location_id=payload.location_id,
            section_id=payload.section_id,
            name=_required(payload.name, 100),
            capacity=payload.capacity,
            sort_order=payload.sort_order,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        self.session.add(value)
        await self._commit_integrity()
        return DiningTableResponse.model_validate(value)

    async def patch_table(
        self, context: TenantContext, table_id: UUID, payload
    ) -> DiningTableResponse:
        value = await self._table(context, table_id, lock=True)
        if payload.section_id is not None:
            section = await self._section(context, payload.section_id)
            if section.location_id != value.location_id:
                raise ReservationNotFound("Section not found")
        for name in payload.model_fields_set:
            setattr(value, name, getattr(payload, name))
        if "name" in payload.model_fields_set:
            value.name = _required(value.name, 100)
        value.updated_at = datetime.now(UTC)
        await self._commit_integrity()
        return DiningTableResponse.model_validate(value)

    async def create_staff_reservation(self, context: TenantContext, payload):
        await self._access(context, payload.location_id)
        config = await self._config(context.organization_id, payload.location_id)
        location = await self.session.get(LocationModel, payload.location_id)
        if location is None:
            raise ReservationNotFound("Location not found")
        existing = await self.session.scalar(
            select(ReservationModel).where(
                ReservationModel.organization_id == context.organization_id,
                ReservationModel.client_reservation_id == payload.client_reservation_id,
            )
        )
        if existing is not None:
            self._assert_same_reservation(existing, payload, "STAFF", config)
            return await self._reservation_response(existing)
        value = await self._build_reservation(config, location, payload, "STAFF")
        organization_id = context.organization_id
        location_id = payload.location_id
        client_reservation_id = payload.client_reservation_id
        try:
            self.session.add(value)
            await self.session.flush()
            await self.events.stage(
                ReservationCreated(value.id, value.organization_id, value.location_id)
            )
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            existing = await self.session.scalar(
                select(ReservationModel).where(
                    ReservationModel.organization_id == organization_id,
                    ReservationModel.client_reservation_id == client_reservation_id,
                )
            )
            if existing is not None:
                config = await self._config(organization_id, location_id)
                self._assert_same_reservation(existing, payload, "STAFF", config)
                return await self._reservation_response(existing)
            raise SlotUnavailable("The selected slot is no longer available") from exc
        return await self._reservation_response(value)

    async def list_reservations(
        self, context: TenantContext, location_id: UUID, date_from, date_to, status
    ) -> list[ReservationResponse]:
        await self._access(context, location_id)
        statement = select(ReservationModel).where(
            ReservationModel.organization_id == context.organization_id,
            ReservationModel.location_id == location_id,
        )
        if date_from is not None:
            statement = statement.where(ReservationModel.start_at >= date_from)
        if date_to is not None:
            statement = statement.where(ReservationModel.start_at < date_to)
        if status is not None:
            statement = statement.where(ReservationModel.status == status)
        values = await self.session.scalars(
            statement.order_by(ReservationModel.start_at, ReservationModel.id)
        )
        return [await self._reservation_response(value) for value in values]

    async def get_reservation(self, context: TenantContext, reservation_id: UUID):
        return await self._reservation_response(await self._reservation(context, reservation_id))

    async def cancel_reservation(self, context, reservation_id, client_action_id, reason=None):
        del client_action_id, reason
        value = await self._reservation(context, reservation_id, lock=True)
        if value.status == ReservationStatus.CANCELLED:
            return await self._reservation_response(value)
        if value.status != ReservationStatus.BOOKED:
            raise InvalidReservationTransition("Only a booked reservation can be cancelled")
        now = datetime.now(UTC)
        value.status, value.cancelled_at, value.updated_at = ReservationStatus.CANCELLED, now, now
        await self.events.stage(
            ReservationCancelled(value.id, value.organization_id, value.location_id)
        )
        await self.session.commit()
        return await self._reservation_response(value)

    async def no_show(self, context, reservation_id, client_action_id):
        del client_action_id
        value = await self._reservation(context, reservation_id, lock=True)
        if value.status == ReservationStatus.NO_SHOW:
            return await self._reservation_response(value)
        if value.status != ReservationStatus.BOOKED:
            raise InvalidReservationTransition("Only a booked reservation can be marked no-show")
        now = datetime.now(UTC)
        value.status, value.no_show_at, value.updated_at = ReservationStatus.NO_SHOW, now, now
        await self.events.stage(
            ReservationNoShow(value.id, value.organization_id, value.location_id)
        )
        await self.session.commit()
        return await self._reservation_response(value)

    async def seat_reservation(self, context, reservation_id, client_action_id, table_id=None):
        value = await self._reservation(context, reservation_id, lock=True)
        existing = await self.session.scalar(
            select(DiningVisitModel).where(DiningVisitModel.reservation_id == value.id)
        )
        if existing is not None:
            if existing.client_action_id != client_action_id or (
                table_id is not None and existing.dining_table_id != table_id
            ):
                raise ReservationIdempotencyConflict(
                    "Reservation was seated by a different action"
                )
            return await self._visit_response(existing)
        if value.status != ReservationStatus.BOOKED:
            raise InvalidReservationTransition("Only a booked reservation can be seated")
        if table_id is not None and table_id != value.dining_table_id:
            raise InvalidReservationTransition("Reservation must use its assigned table")
        chosen_id = table_id or value.dining_table_id
        visit, _ = await self._open_visit(
            context,
            client_action_id,
            value.location_id,
            chosen_id,
            value.party_size,
            reservation_id=value.id,
        )
        now = visit.opened_at
        value.status, value.seated_at, value.updated_at = ReservationStatus.SEATED, now, now
        await self.events.stage_many(
            (
                ReservationSeated(value.id, value.organization_id, value.location_id, visit.id),
                DiningVisitOpened(visit.id, visit.organization_id, visit.location_id),
            )
        )
        await self._commit_seating()
        return await self._visit_response(visit)

    async def list_waitlist(self, context, location_id) -> list[WaitlistResponse]:
        await self._access(context, location_id)
        values = await self.session.scalars(
            select(WaitlistEntryModel)
            .where(
                WaitlistEntryModel.organization_id == context.organization_id,
                WaitlistEntryModel.location_id == location_id,
            )
            .order_by(WaitlistEntryModel.created_at, WaitlistEntryModel.id)
        )
        return [WaitlistResponse.model_validate(value) for value in values]

    async def create_waitlist(self, context, payload) -> WaitlistResponse:
        await self._access(context, payload.location_id)
        existing = await self.session.scalar(
            select(WaitlistEntryModel).where(
                WaitlistEntryModel.organization_id == context.organization_id,
                WaitlistEntryModel.client_entry_id == payload.client_entry_id,
            )
        )
        if existing is not None:
            if self._waitlist_fingerprint(existing) != (
                payload.location_id,
                payload.guest_name.strip(),
                _optional(payload.guest_phone, 32),
                str(payload.guest_email) if payload.guest_email else None,
                payload.party_size,
                payload.quoted_wait_minutes,
                _optional(payload.guest_notes, 2000),
            ):
                raise ReservationIdempotencyConflict("client_entry_id was already used")
            return WaitlistResponse.model_validate(existing)
        config = await self._config(context.organization_id, payload.location_id)
        self._validate_party(config, payload.party_size)
        now = datetime.now(UTC)
        value = WaitlistEntryModel(
            id=uuid4(),
            organization_id=context.organization_id,
            location_id=payload.location_id,
            client_entry_id=payload.client_entry_id,
            guest_name=_required(payload.guest_name, 201),
            guest_phone=_optional(payload.guest_phone, 32),
            guest_email=str(payload.guest_email) if payload.guest_email else None,
            party_size=payload.party_size,
            quoted_wait_minutes=payload.quoted_wait_minutes,
            status="WAITING",
            guest_notes=_optional(payload.guest_notes, 2000),
            cancelled_at=None,
            seated_at=None,
            created_at=now,
            updated_at=now,
        )
        try:
            self.session.add(value)
            await self.session.flush()
            await self.events.stage(
                WaitlistCreated(value.id, value.organization_id, value.location_id)
            )
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            existing = await self.session.scalar(
                select(WaitlistEntryModel).where(
                    WaitlistEntryModel.organization_id == context.organization_id,
                    WaitlistEntryModel.client_entry_id == payload.client_entry_id,
                )
            )
            if existing is None or self._waitlist_fingerprint(existing) != (
                payload.location_id,
                payload.guest_name.strip(),
                _optional(payload.guest_phone, 32),
                str(payload.guest_email) if payload.guest_email else None,
                payload.party_size,
                payload.quoted_wait_minutes,
                _optional(payload.guest_notes, 2000),
            ):
                raise ReservationIdempotencyConflict("client_entry_id was already used") from exc
            return WaitlistResponse.model_validate(existing)
        return WaitlistResponse.model_validate(value)

    async def cancel_waitlist(self, context, entry_id, client_action_id):
        del client_action_id
        value = await self._waitlist(context, entry_id, lock=True)
        if value.status == "CANCELLED":
            return WaitlistResponse.model_validate(value)
        if value.status != "WAITING":
            raise InvalidReservationTransition("Only a waiting guest can be cancelled")
        now = datetime.now(UTC)
        value.status, value.cancelled_at, value.updated_at = "CANCELLED", now, now
        await self.events.stage(
            WaitlistCancelled(value.id, value.organization_id, value.location_id)
        )
        await self.session.commit()
        return WaitlistResponse.model_validate(value)

    async def seat_waitlist(self, context, entry_id, client_action_id, table_id):
        value = await self._waitlist(context, entry_id, lock=True)
        existing = await self.session.scalar(
            select(DiningVisitModel).where(DiningVisitModel.waitlist_entry_id == value.id)
        )
        if existing is not None:
            if existing.client_action_id != client_action_id or (
                table_id is not None and existing.dining_table_id != table_id
            ):
                raise ReservationIdempotencyConflict(
                    "Waitlist entry was seated by a different action"
                )
            return await self._visit_response(existing)
        if value.status != "WAITING":
            raise InvalidReservationTransition("Only a waiting guest can be seated")
        action_visit = await self.session.scalar(
            select(DiningVisitModel).where(
                DiningVisitModel.organization_id == context.organization_id,
                DiningVisitModel.client_action_id == client_action_id,
            )
        )
        if action_visit is not None:
            raise ReservationIdempotencyConflict("client_action_id was already used")
        config = await self._config(context.organization_id, value.location_id)
        now = datetime.now(UTC)
        conflict_end = now + timedelta(
            minutes=config.default_duration_minutes + config.cleanup_buffer_minutes
        )
        if table_id is None:
            table = await self._eligible_table(config, value.party_size, now, conflict_end)
            table_id = table.id if table else None
            if table_id is None:
                raise NoMatchingTable("No matching table is available")
        elif (
            await self._eligible_table(config, value.party_size, now, conflict_end, table_id)
            is None
        ):
            raise TableOccupied("Table is reserved or occupied")
        visit, _ = await self._open_visit(
            context,
            client_action_id,
            value.location_id,
            table_id,
            value.party_size,
            waitlist_entry_id=value.id,
        )
        value.status, value.seated_at, value.updated_at = "SEATED", visit.opened_at, visit.opened_at
        await self.events.stage_many(
            (
                WaitlistSeated(value.id, value.organization_id, value.location_id, visit.id),
                DiningVisitOpened(visit.id, visit.organization_id, visit.location_id),
            )
        )
        await self._commit_seating()
        return await self._visit_response(visit)

    async def direct_visit(self, context, payload):
        existing = await self.session.scalar(
            select(DiningVisitModel).where(
                DiningVisitModel.organization_id == context.organization_id,
                DiningVisitModel.client_action_id == payload.client_action_id,
            )
        )
        if existing is not None:
            visit, _ = await self._open_visit(
                context,
                payload.client_action_id,
                payload.location_id,
                payload.dining_table_id,
                payload.party_size,
            )
            return await self._visit_response(visit)
        config = await self._config(context.organization_id, payload.location_id)
        now = datetime.now(UTC)
        if (
            await self._eligible_table(
                config,
                payload.party_size,
                now,
                now
                + timedelta(
                    minutes=config.default_duration_minutes + config.cleanup_buffer_minutes
                ),
                payload.dining_table_id,
            )
            is None
        ):
            raise TableOccupied("Table is reserved or occupied")
        visit, created = await self._open_visit(
            context,
            payload.client_action_id,
            payload.location_id,
            payload.dining_table_id,
            payload.party_size,
        )
        if created:
            await self.events.stage(
                DiningVisitOpened(visit.id, visit.organization_id, visit.location_id)
            )
        await self._commit_seating()
        return await self._visit_response(visit)

    async def get_visit(self, context, visit_id):
        return await self._visit_response(await self._visit(context, visit_id))

    async def open_check(self, context, visit_id, payload):
        visit = await self._visit(context, visit_id, lock=True)
        if visit.closed_at is not None:
            raise InvalidReservationTransition("Closed visits cannot open a check")
        if visit.sales_order_id is not None:
            order = await self.session.get(SalesOrderModel, visit.sales_order_id)
            if order is None or order.client_order_id != payload.client_order_id:
                raise ReservationIdempotencyConflict("Visit already has a different check")
            return await self._visit_response(visit)
        if self.orders is None:
            raise RuntimeError("Order service is unavailable")
        table = await self.session.get(DiningTableModel, visit.dining_table_id)
        if table is None:
            raise ReservationNotFound("Table not found")
        reused_order = await self.session.scalar(
            select(SalesOrderModel.id).where(
                SalesOrderModel.organization_id == context.organization_id,
                SalesOrderModel.client_order_id == payload.client_order_id,
            )
        )
        if reused_order is not None:
            raise ReservationIdempotencyConflict(
                "client_order_id belongs to another check"
            )
        order = await self.orders.create_staged(
            context,
            CreateOrderInput(
                payload.client_order_id,
                payload.shift_id,
                OrderType.DINE_IN,
                visit.party_size,
                table.name,
                None,
            ),
        )
        if order.location_id != visit.location_id:
            raise ReservationNotFound("Shift not found")
        other_visit = await self.session.scalar(
            select(DiningVisitModel.id).where(
                DiningVisitModel.sales_order_id == order.id,
                DiningVisitModel.id != visit.id,
            )
        )
        if other_visit is not None:
            raise ReservationIdempotencyConflict(
                "client_order_id belongs to another check"
            )
        visit.sales_order_id = order.id
        visit.updated_at = datetime.now(UTC)
        await self.session.commit()
        return await self._visit_response(visit)

    async def close_visit(self, context, visit_id, client_action_id):
        del client_action_id
        visit = await self._visit(context, visit_id, lock=True)
        if visit.closed_at is not None:
            return await self._visit_response(visit)
        if visit.sales_order_id is not None:
            order = await self.session.get(SalesOrderModel, visit.sales_order_id)
            if order is None or order.status not in (OrderStatus.PAID, OrderStatus.CANCELLED):
                raise InvalidReservationTransition("The linked check is still open")
        await self._close_visit(visit)
        await self.session.commit()
        return await self._visit_response(visit)

    async def floor(self, context, location_id) -> DiningFloorResponse:
        await self._access(context, location_id)
        location = await self.session.get(LocationModel, location_id)
        if location is None:
            raise ReservationNotFound("Location not found")
        sections = list(
            await self.session.scalars(
                select(DiningSectionModel)
                .where(
                    DiningSectionModel.organization_id == context.organization_id,
                    DiningSectionModel.location_id == location_id,
                )
                .order_by(
                    DiningSectionModel.sort_order, DiningSectionModel.name, DiningSectionModel.id
                )
            )
        )
        tables = list(
            await self.session.scalars(
                select(DiningTableModel)
                .where(
                    DiningTableModel.organization_id == context.organization_id,
                    DiningTableModel.location_id == location_id,
                )
                .order_by(DiningTableModel.sort_order, DiningTableModel.name, DiningTableModel.id)
            )
        )
        now = datetime.now(UTC)
        visits = {
            value.dining_table_id: value
            for value in await self.session.scalars(
                select(DiningVisitModel).where(
                    DiningVisitModel.organization_id == context.organization_id,
                    DiningVisitModel.location_id == location_id,
                    DiningVisitModel.closed_at.is_(None),
                )
            )
        }
        reservations = {}
        for value in await self.session.scalars(
            select(ReservationModel)
            .where(
                ReservationModel.organization_id == context.organization_id,
                ReservationModel.location_id == location_id,
                ReservationModel.status == ReservationStatus.BOOKED,
                ReservationModel.start_at <= now + timedelta(hours=2),
                ReservationModel.conflict_end_at > now,
            )
            .order_by(ReservationModel.start_at, ReservationModel.id)
        ):
            reservations.setdefault(value.dining_table_id, value)
        groups = []
        for section in sections:
            cards = []
            for table in (item for item in tables if item.section_id == section.id):
                visit, reservation = visits.get(table.id), reservations.get(table.id)
                state = (
                    DiningTableState.UNAVAILABLE
                    if not table.is_active
                    else DiningTableState.OCCUPIED
                    if visit
                    else DiningTableState.RESERVED
                    if reservation
                    else DiningTableState.AVAILABLE
                )
                cards.append(
                    FloorTableResponse(
                        id=table.id,
                        name=table.name,
                        capacity=table.capacity,
                        sort_order=table.sort_order,
                        is_active=table.is_active,
                        state=state,
                        reservation=(
                            await self._reservation_response(reservation) if reservation else None
                        ),
                        visit=(await self._visit_response(visit) if visit else None),
                    )
                )
            groups.append(
                FloorSectionResponse(
                    id=section.id, name=section.name, sort_order=section.sort_order, tables=cards
                )
            )
        return DiningFloorResponse(
            location_id=location_id, timezone=location.timezone, sections=groups
        )

    async def apply_payment_completed(self, organization_id: UUID, order_id: UUID) -> None:
        visit = await self.session.scalar(
            select(DiningVisitModel)
            .where(
                DiningVisitModel.organization_id == organization_id,
                DiningVisitModel.sales_order_id == order_id,
            )
            .with_for_update()
        )
        if visit is None or visit.closed_at is not None:
            return
        await self._close_visit(visit)

    async def _close_visit(self, visit: DiningVisitModel) -> None:
        now = datetime.now(UTC)
        visit.closed_at = visit.updated_at = now
        events: list[object] = [
            DiningVisitClosed(visit.id, visit.organization_id, visit.location_id)
        ]
        if visit.reservation_id is not None:
            reservation = await self.session.scalar(
                select(ReservationModel)
                .where(ReservationModel.id == visit.reservation_id)
                .with_for_update()
            )
            if reservation is not None and reservation.status == ReservationStatus.SEATED:
                reservation.status = ReservationStatus.COMPLETED
                reservation.completed_at = reservation.updated_at = now
                events.append(
                    ReservationCompleted(
                        reservation.id,
                        reservation.organization_id,
                        reservation.location_id,
                        visit.id,
                    )
                )
        await self.events.stage_many(tuple(events))

    async def _build_reservation(self, config, location, payload, source):
        self._validate_party(config, payload.party_size)
        if not config.reservations_enabled:
            raise ReservationsDisabled("Reservations are disabled")
        start = _utc(payload.start_at)
        self._validate_time(config, location, start)
        end = start + timedelta(minutes=config.default_duration_minutes)
        conflict_end = end + timedelta(minutes=config.cleanup_buffer_minutes)
        if not _within_schedule(config, location.timezone, start, conflict_end):
            raise LocationClosed("The location is closed for this reservation")
        table_id = getattr(payload, "dining_table_id", None)
        table = await self._eligible_table(
            config, payload.party_size, start, conflict_end, table_id
        )
        if table is None:
            if not await self.session.scalar(
                select(
                    exists().where(
                        DiningTableModel.organization_id == config.organization_id,
                        DiningTableModel.location_id == config.location_id,
                        DiningTableModel.is_active.is_(True),
                        DiningTableModel.capacity >= payload.party_size,
                    )
                )
            ):
                raise NoMatchingTable("No table can seat this party")
            raise SlotUnavailable("The selected slot is no longer available")
        reservation_id, now = uuid4(), datetime.now(UTC)
        return ReservationModel(
            id=reservation_id,
            organization_id=config.organization_id,
            location_id=config.location_id,
            client_reservation_id=payload.client_reservation_id,
            guest_access_token_hash=_sha(self._guest_token(reservation_id)),
            guest_name=_required(payload.guest_name, 201),
            guest_phone=_optional(payload.guest_phone, 32),
            guest_email=str(payload.guest_email) if payload.guest_email else None,
            party_size=payload.party_size,
            start_at=start,
            end_at=end,
            conflict_end_at=conflict_end,
            dining_table_id=table.id,
            status=ReservationStatus.BOOKED,
            source=source,
            guest_notes=_optional(payload.guest_notes, 2000),
            internal_notes=_optional(getattr(payload, "internal_notes", None), 4000),
            cancelled_at=None,
            seated_at=None,
            completed_at=None,
            no_show_at=None,
            created_at=now,
            updated_at=now,
        )

    async def _available_slots(self, config, location, requested_date, party_size):
        zone = ZoneInfo(location.timezone)
        values: list[AvailabilitySlotResponse] = []
        for schedule in config.schedules:
            if schedule.weekday != requested_date.weekday():
                continue
            opened = datetime.combine(requested_date, schedule.opens_at_local, zone)
            closed_date = requested_date + timedelta(
                days=schedule.closes_at_local <= schedule.opens_at_local
            )
            closed = datetime.combine(closed_date, schedule.closes_at_local, zone)
            candidate = opened
            while candidate < closed:
                start = candidate.astimezone(UTC).replace(second=0, microsecond=0)
                end = start + timedelta(minutes=config.default_duration_minutes)
                conflict_end = end + timedelta(minutes=config.cleanup_buffer_minutes)
                try:
                    self._validate_time(config, location, start)
                except (BelowLeadTime, OutsideBookingHorizon):
                    candidate += timedelta(minutes=config.slot_interval_minutes)
                    continue
                if conflict_end <= closed.astimezone(UTC) and await self._eligible_table(
                    config, party_size, start, conflict_end
                ):
                    values.append(
                        AvailabilitySlotResponse(
                            start_at=start.astimezone(zone),
                            end_at=end.astimezone(zone),
                        )
                    )
                candidate += timedelta(minutes=config.slot_interval_minutes)
        return values

    async def _eligible_table(self, config, party_size, start, conflict_end, table_id=None):
        conflict = exists().where(
            ReservationModel.dining_table_id == DiningTableModel.id,
            ReservationModel.status == ReservationStatus.BOOKED,
            ReservationModel.start_at < conflict_end,
            ReservationModel.conflict_end_at > start,
        )
        occupied = exists().where(
            DiningVisitModel.dining_table_id == DiningTableModel.id,
            DiningVisitModel.closed_at.is_(None),
        )
        statement = select(DiningTableModel).where(
            DiningTableModel.organization_id == config.organization_id,
            DiningTableModel.location_id == config.location_id,
            DiningTableModel.is_active.is_(True),
            DiningTableModel.capacity >= party_size,
            ~conflict,
            ~occupied,
        )
        if table_id is not None:
            statement = statement.where(DiningTableModel.id == table_id)
        return await self.session.scalar(
            statement.order_by(
                DiningTableModel.capacity, DiningTableModel.sort_order, DiningTableModel.id
            ).limit(1)
        )

    async def _open_visit(
        self,
        context,
        client_action_id,
        location_id,
        table_id,
        party_size,
        reservation_id=None,
        waitlist_entry_id=None,
    ):
        await self._access(context, location_id)
        existing = await self.session.scalar(
            select(DiningVisitModel).where(
                DiningVisitModel.organization_id == context.organization_id,
                DiningVisitModel.client_action_id == client_action_id,
            )
        )
        if existing is not None:
            if (
                existing.location_id,
                existing.dining_table_id,
                existing.party_size,
                existing.reservation_id,
                existing.waitlist_entry_id,
            ) != (
                location_id,
                table_id,
                party_size,
                reservation_id,
                waitlist_entry_id,
            ):
                raise ReservationIdempotencyConflict("client_action_id was already used")
            return existing, False
        table = await self._table(context, table_id, lock=True)
        if table.location_id != location_id or not table.is_active or table.capacity < party_size:
            raise TableOccupied("Table is unavailable")
        if await self.session.scalar(
            select(
                exists().where(
                    DiningVisitModel.dining_table_id == table.id,
                    DiningVisitModel.closed_at.is_(None),
                )
            )
        ):
            raise TableOccupied("Table is occupied")
        now = datetime.now(UTC)
        value = DiningVisitModel(
            id=uuid4(),
            organization_id=context.organization_id,
            location_id=location_id,
            client_action_id=client_action_id,
            dining_table_id=table.id,
            reservation_id=reservation_id,
            waitlist_entry_id=waitlist_entry_id,
            sales_order_id=None,
            party_size=party_size,
            opened_at=now,
            closed_at=None,
            created_at=now,
            updated_at=now,
        )
        self.session.add(value)
        await self.session.flush()
        return value, True

    async def _public_scope(self, slug):
        row = (
            await self.session.execute(
                select(ReservationLocationModel, LocationModel, OrganizationModel)
                .join(LocationModel, LocationModel.id == ReservationLocationModel.location_id)
                .join(
                    OrganizationModel,
                    OrganizationModel.id == ReservationLocationModel.organization_id,
                )
                .options(selectinload(ReservationLocationModel.schedules))
                .where(
                    ReservationLocationModel.public_slug == slug,
                    LocationModel.is_active.is_(True),
                    OrganizationModel.status == "active",
                )
            )
        ).first()
        if row is None:
            raise ReservationNotFound("Reservation page not found")
        return row

    async def _config(self, organization_id, location_id):
        value = await self.session.scalar(
            select(ReservationLocationModel)
            .options(selectinload(ReservationLocationModel.schedules))
            .where(
                ReservationLocationModel.organization_id == organization_id,
                ReservationLocationModel.location_id == location_id,
            )
        )
        if value is None:
            raise ReservationsDisabled("Reservations are not configured")
        return value

    async def _reservation(self, context, reservation_id, lock=False):
        statement = select(ReservationModel).where(
            ReservationModel.organization_id == context.organization_id,
            ReservationModel.id == reservation_id,
        )
        if lock:
            statement = statement.with_for_update()
        value = await self.session.scalar(statement)
        if value is None:
            raise ReservationNotFound("Reservation not found")
        await self._access(context, value.location_id)
        return value

    async def _waitlist(self, context, entry_id, lock=False):
        statement = select(WaitlistEntryModel).where(
            WaitlistEntryModel.organization_id == context.organization_id,
            WaitlistEntryModel.id == entry_id,
        )
        if lock:
            statement = statement.with_for_update()
        value = await self.session.scalar(statement)
        if value is None:
            raise ReservationNotFound("Waitlist entry not found")
        await self._access(context, value.location_id)
        return value

    async def _visit(self, context, visit_id, lock=False):
        statement = select(DiningVisitModel).where(
            DiningVisitModel.organization_id == context.organization_id,
            DiningVisitModel.id == visit_id,
        )
        if lock:
            statement = statement.with_for_update()
        value = await self.session.scalar(statement)
        if value is None:
            raise ReservationNotFound("Dining visit not found")
        await self._access(context, value.location_id)
        return value

    async def _section(self, context, section_id, lock=False):
        statement = select(DiningSectionModel).where(
            DiningSectionModel.organization_id == context.organization_id,
            DiningSectionModel.id == section_id,
        )
        if lock:
            statement = statement.with_for_update()
        value = await self.session.scalar(statement)
        if value is None:
            raise ReservationNotFound("Section not found")
        await self._access(context, value.location_id)
        return value

    async def _table(self, context, table_id, lock=False):
        statement = select(DiningTableModel).where(
            DiningTableModel.organization_id == context.organization_id,
            DiningTableModel.id == table_id,
        )
        if lock:
            statement = statement.with_for_update()
        value = await self.session.scalar(statement)
        if value is None:
            raise ReservationNotFound("Table not found")
        await self._access(context, value.location_id)
        return value

    async def _token_reservation(self, token, lock=False):
        statement = select(ReservationModel).where(
            ReservationModel.guest_access_token_hash == _sha(token)
        )
        if lock:
            statement = statement.with_for_update()
        value = await self.session.scalar(statement)
        if value is None:
            raise InvalidGuestToken("Reservation not found")
        return value

    async def _reservation_response(self, value):
        table = await self.session.get(DiningTableModel, value.dining_table_id)
        if table is None:
            raise ReservationNotFound("Table not found")
        return ReservationResponse(
            **{
                name: getattr(value, name)
                for name in ReservationResponse.model_fields
                if name != "table_name"
            },
            table_name=table.name,
        )

    async def _visit_response(self, value):
        order_status = None
        if value.sales_order_id is not None:
            order_status = await self.session.scalar(
                select(SalesOrderModel.status).where(SalesOrderModel.id == value.sales_order_id)
            )
        return DiningVisitResponse(
            **{
                name: getattr(value, name)
                for name in DiningVisitResponse.model_fields
                if name != "sales_order_status"
            },
            sales_order_status=order_status,
        )

    async def _guest_response(self, value, location, include_token=False):
        organization_name = await self.session.scalar(
            select(OrganizationModel.name).where(OrganizationModel.id == value.organization_id)
        )
        if organization_name is None:
            raise InvalidGuestToken("Reservation not found")
        zone = ZoneInfo(location.timezone)
        fields = dict(
            organization_name=organization_name,
            location_name=location.name,
            timezone=location.timezone,
            status=value.status,
            guest_name=value.guest_name,
            guest_phone=value.guest_phone,
            guest_email=value.guest_email,
            party_size=value.party_size,
            start_at=_utc(value.start_at).astimezone(zone),
            end_at=_utc(value.end_at).astimezone(zone),
            guest_notes=value.guest_notes,
            can_cancel=self._can_guest_cancel(
                value, await self._config(value.organization_id, value.location_id)
            ),
            cancelled_at=value.cancelled_at,
            seated_at=value.seated_at,
            completed_at=value.completed_at,
            no_show_at=value.no_show_at,
            created_at=value.created_at,
            updated_at=value.updated_at,
        )
        if include_token:
            return GuestReservationCreatedResponse(
                **fields, guest_access_token=self._guest_token(value.id)
            )
        return PublicReservationResponse(**fields)

    def _guest_token(self, reservation_id):
        digest = hmac.new(
            self.settings.jwt_secret.encode(),
            f"reservation:{reservation_id}".encode(),
            hashlib.sha256,
        ).hexdigest()
        return f"{reservation_id.hex}.{digest}"

    def _validate_party(self, config, party_size):
        if not 1 <= party_size <= config.maximum_party_size:
            raise InvalidPartySize("Party size is outside the reservation policy")

    def _validate_time(self, config, location, start):
        now = datetime.now(UTC)
        if start < now + timedelta(minutes=config.minimum_lead_minutes):
            raise BelowLeadTime("Reservation is below the minimum lead time")
        local_now = now.astimezone(ZoneInfo(location.timezone)).date()
        local_start = start.astimezone(ZoneInfo(location.timezone)).date()
        if local_start > local_now + timedelta(days=config.maximum_advance_days):
            raise OutsideBookingHorizon("Reservation is outside the booking horizon")

    def _can_guest_cancel(self, value, config):
        return value.status == ReservationStatus.BOOKED and datetime.now(UTC) < _utc(
            value.start_at
        ) - timedelta(minutes=config.guest_cancellation_cutoff_minutes)

    def _assert_same_reservation(self, existing, payload, source, config):
        start = _utc(payload.start_at)
        end = start + timedelta(minutes=config.default_duration_minutes)
        if (
            existing.source != source
            or _utc(existing.start_at) != start
            or _utc(existing.end_at) != end
            or existing.party_size != payload.party_size
            or existing.guest_name != payload.guest_name.strip()
            or existing.guest_phone != _optional(payload.guest_phone, 32)
            or existing.guest_email != (str(payload.guest_email) if payload.guest_email else None)
            or existing.guest_notes != _optional(payload.guest_notes, 2000)
            or existing.internal_notes != _optional(getattr(payload, "internal_notes", None), 4000)
        ):
            raise ReservationIdempotencyConflict(
                "client_reservation_id was already used with a different request"
            )

    @staticmethod
    def _waitlist_fingerprint(value):
        return (
            value.location_id,
            value.guest_name,
            value.guest_phone,
            value.guest_email,
            value.party_size,
            value.quoted_wait_minutes,
            value.guest_notes,
        )

    async def _access(self, context, location_id):
        await self.organizations.ensure_location_access(context, location_id)

    async def _commit_integrity(self):
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ReservationIdempotencyConflict("The value conflicts with existing data") from exc

    async def _commit_seating(self):
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise TableOccupied("Table was occupied by another request") from exc


def _within_schedule(config, timezone, start, end):
    zone = ZoneInfo(timezone)
    local_start, local_end = start.astimezone(zone), end.astimezone(zone)
    for schedule in config.schedules:
        if schedule.weekday != local_start.weekday():
            continue
        opened = datetime.combine(local_start.date(), schedule.opens_at_local, zone)
        closed_date = local_start.date() + timedelta(
            days=schedule.closes_at_local <= schedule.opens_at_local
        )
        closed = datetime.combine(closed_date, schedule.closes_at_local, zone)
        if opened <= local_start and local_end <= closed:
            return True
    return False


def _required(value, limit):
    normalized = value.strip()
    if not normalized or len(normalized) > limit:
        raise ValueError(f"Text must contain between 1 and {limit} characters")
    return normalized


def _optional(value, limit):
    if value is None:
        return None
    normalized = value.strip()
    if len(normalized) > limit:
        raise ValueError(f"Text cannot exceed {limit} characters")
    return normalized or None


def _sha(value):
    return hashlib.sha256(value.encode()).hexdigest()


def _utc(value):
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
