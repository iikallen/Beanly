from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from beanly.modules.integrations.infrastructure.db.models import IntegrationConnectionModel
from beanly.modules.offline_pos.infrastructure.db.models import PosDeviceModel
from beanly.modules.payments.domain.entities import (
    ExternalPaymentAttempt,
    Payment,
    PaymentMethodTotal,
    ShiftPaymentSummary,
    TerminalBinding,
)
from beanly.modules.payments.domain.enums import PaymentMethod
from beanly.modules.payments.domain.exceptions import (
    PaymentConflict,
    TerminalBindingConflict,
    TerminalBindingNotFound,
)
from beanly.modules.payments.infrastructure.db.mappers import (
    to_external_attempt,
    to_payment,
    to_terminal_binding,
)
from beanly.modules.payments.infrastructure.db.models import (
    ExternalPaymentAttemptModel,
    PaymentLineModel,
    PaymentModel,
    TerminalBindingModel,
)
from beanly.modules.sales.infrastructure.db.models import PosRegisterModel, RegisterShiftModel


class SqlAlchemyPaymentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, value: Payment) -> Payment:
        model = PaymentModel(**_payment_values(value))
        model.lines = [PaymentLineModel(**_line_values(line)) for line in value.lines]
        self.session.add(model)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            raise PaymentConflict("Payment already exists") from exc
        return to_payment(model)

    async def list_terminal_bindings(
        self, organization_id: UUID, register_id: UUID
    ) -> list[TerminalBinding]:
        values = await self.session.scalars(
            select(TerminalBindingModel)
            .where(
                TerminalBindingModel.organization_id == organization_id,
                TerminalBindingModel.register_id == register_id,
            )
            .order_by(TerminalBindingModel.created_at, TerminalBindingModel.id)
        )
        return [to_terminal_binding(value) for value in values]

    async def add_terminal_binding(self, context, **values: object) -> TerminalBinding:
        organization_id = context.organization_id
        location_id = UUID(str(values["location_id"]))
        register_id = UUID(str(values["register_id"]))
        connection_id = UUID(str(values["connection_id"]))
        provider_code = str(values["provider_code"])
        valid = await self.session.scalar(
            select(IntegrationConnectionModel.id)
            .join(PosRegisterModel, PosRegisterModel.id == register_id)
            .where(
                IntegrationConnectionModel.organization_id == organization_id,
                IntegrationConnectionModel.id == connection_id,
                IntegrationConnectionModel.provider_code == provider_code,
                IntegrationConnectionModel.status == "ACTIVE",
                PosRegisterModel.organization_id == organization_id,
                PosRegisterModel.location_id == location_id,
                PosRegisterModel.is_active.is_(True),
            )
        )
        if valid is None:
            raise TerminalBindingNotFound("Active connection or register not found")
        now = datetime.now(UTC)
        model = TerminalBindingModel(
            id=uuid4(),
            organization_id=organization_id,
            connection_id=connection_id,
            location_id=location_id,
            register_id=register_id,
            provider_code=provider_code,
            external_terminal_id=values.get("external_terminal_id"),
            transport_config={},
            is_active=bool(values.get("is_active", True)),
            created_at=now,
            updated_at=now,
        )
        try:
            async with self.session.begin_nested():
                self.session.add(model)
                await self.session.flush()
        except IntegrityError as exc:
            raise TerminalBindingConflict("Terminal binding already exists") from exc
        return to_terminal_binding(model)

    async def update_terminal_binding(
        self, context, binding_id: UUID, **values: object
    ) -> TerminalBinding:
        model = await self.session.scalar(
            select(TerminalBindingModel)
            .where(
                TerminalBindingModel.organization_id == context.organization_id,
                TerminalBindingModel.id == binding_id,
            )
            .with_for_update()
        )
        if model is None:
            raise TerminalBindingNotFound("Terminal binding not found")
        if "external_terminal_id" in values:
            model.external_terminal_id = values["external_terminal_id"]
        if "is_active" in values:
            model.is_active = bool(values["is_active"])
        model.transport_config = {}
        model.updated_at = datetime.now(UTC)
        await self.session.flush()
        return to_terminal_binding(model)

    async def get_external_attempt(
        self, organization_id: UUID, attempt_id: UUID
    ) -> ExternalPaymentAttempt | None:
        model = await self.session.scalar(
            select(ExternalPaymentAttemptModel).where(
                ExternalPaymentAttemptModel.organization_id == organization_id,
                ExternalPaymentAttemptModel.id == attempt_id,
            )
        )
        return to_external_attempt(model) if model else None

    async def get_external_attempt_by_client_id(
        self, organization_id: UUID, client_attempt_id: UUID
    ) -> ExternalPaymentAttempt | None:
        model = await self.session.scalar(
            select(ExternalPaymentAttemptModel).where(
                ExternalPaymentAttemptModel.organization_id == organization_id,
                ExternalPaymentAttemptModel.client_attempt_id == client_attempt_id,
            )
        )
        return to_external_attempt(model) if model else None

    async def validate_terminal_binding(
        self,
        organization_id: UUID,
        *,
        location_id: UUID,
        shift_id: UUID,
        register_id: UUID,
        connection_id: UUID,
        provider_code: str,
        pos_device_id: UUID | None,
    ) -> None:
        value = await self.session.scalar(
            select(TerminalBindingModel.id)
            .join(
                RegisterShiftModel,
                RegisterShiftModel.register_id == TerminalBindingModel.register_id,
            )
            .join(
                IntegrationConnectionModel,
                IntegrationConnectionModel.id == TerminalBindingModel.connection_id,
            )
            .where(
                TerminalBindingModel.organization_id == organization_id,
                TerminalBindingModel.location_id == location_id,
                TerminalBindingModel.register_id == register_id,
                TerminalBindingModel.connection_id == connection_id,
                TerminalBindingModel.provider_code == provider_code,
                TerminalBindingModel.is_active.is_(True),
                RegisterShiftModel.id == shift_id,
                RegisterShiftModel.status == "OPEN",
                IntegrationConnectionModel.status == "ACTIVE",
            )
        )
        if value is None:
            raise TerminalBindingNotFound("Active terminal binding not found")
        if pos_device_id is not None:
            device_id = await self.session.scalar(
                select(PosDeviceModel.id).where(
                    PosDeviceModel.organization_id == organization_id,
                    PosDeviceModel.location_id == location_id,
                    PosDeviceModel.register_id == register_id,
                    PosDeviceModel.id == pos_device_id,
                    PosDeviceModel.status == "ACTIVE",
                )
            )
            if device_id is None:
                raise TerminalBindingNotFound("Active POS device not found")

    async def add_external_attempt(self, value: ExternalPaymentAttempt) -> ExternalPaymentAttempt:
        model = ExternalPaymentAttemptModel(
            id=value.id,
            organization_id=value.organization_id,
            location_id=value.location_id,
            order_id=value.order_id,
            register_id=value.register_id,
            pos_device_id=value.pos_device_id,
            connection_id=value.connection_id,
            client_attempt_id=value.client_attempt_id,
            provider_code=value.provider_code,
            method=value.method.value,
            amount_minor=value.amount_minor,
            currency_code=value.currency_code,
            status=value.status.value,
            provider_operation_id=value.provider_operation_id,
            provider_reference=value.provider_reference,
            request_hash=value.request_hash,
            created_by_user_id=value.created_by_user_id,
            payment_id=value.payment_id,
            created_at=value.created_at,
            approved_at=value.approved_at,
            failed_at=value.failed_at,
            failure_code=value.failure_code,
            order_pricing_revision=value.order_pricing_revision,
        )
        try:
            async with self.session.begin_nested():
                self.session.add(model)
                await self.session.flush()
        except IntegrityError as exc:
            raise PaymentConflict("External payment attempt already exists") from exc
        return to_external_attempt(model)

    async def get(self, organization_id: UUID, payment_id: UUID) -> Payment | None:
        model = await self.session.scalar(
            _payment_query(organization_id).where(PaymentModel.id == payment_id)
        )
        return to_payment(model) if model else None

    async def get_by_order(self, organization_id: UUID, order_id: UUID) -> Payment | None:
        model = await self.session.scalar(
            _payment_query(organization_id).where(PaymentModel.order_id == order_id)
        )
        return to_payment(model) if model else None

    async def get_by_client_id(
        self, organization_id: UUID, client_payment_id: UUID
    ) -> Payment | None:
        model = await self.session.scalar(
            _payment_query(organization_id).where(
                PaymentModel.client_payment_id == client_payment_id
            )
        )
        return to_payment(model) if model else None

    async def list(
        self,
        organization_id: UUID,
        location_ids: tuple[UUID, ...],
        *,
        shift_id: UUID | None,
        date_from: datetime | None,
        date_to: datetime | None,
        method: PaymentMethod | None,
    ) -> list[Payment]:
        if not location_ids:
            return []
        statement = _payment_query(organization_id).where(
            PaymentModel.location_id.in_(location_ids)
        )
        if shift_id is not None:
            statement = statement.where(PaymentModel.shift_id == shift_id)
        if date_from is not None:
            statement = statement.where(PaymentModel.completed_at >= date_from)
        if date_to is not None:
            statement = statement.where(PaymentModel.completed_at <= date_to)
        if method is not None:
            statement = statement.where(
                PaymentModel.id.in_(
                    select(PaymentLineModel.payment_id).where(
                        PaymentLineModel.method == method.value
                    )
                )
            )
        models = await self.session.scalars(
            statement.order_by(PaymentModel.completed_at.desc(), PaymentModel.id)
        )
        return [to_payment(model) for model in models]

    async def shift_summary(self, organization_id: UUID, shift_id: UUID) -> ShiftPaymentSummary:
        totals = await self.session.execute(
            select(
                func.count(PaymentModel.id),
                func.coalesce(func.sum(PaymentModel.amount_minor), 0),
            ).where(
                PaymentModel.organization_id == organization_id,
                PaymentModel.shift_id == shift_id,
            )
        )
        orders_paid, gross_amount_minor = totals.one()
        method_rows = await self.session.execute(
            select(
                PaymentLineModel.method,
                func.coalesce(func.sum(PaymentLineModel.amount_minor), 0),
            )
            .join(PaymentModel, PaymentModel.id == PaymentLineModel.payment_id)
            .where(
                PaymentModel.organization_id == organization_id,
                PaymentModel.shift_id == shift_id,
            )
            .group_by(PaymentLineModel.method)
        )
        by_method = {PaymentMethod(method): int(amount) for method, amount in method_rows}
        return ShiftPaymentSummary(
            int(orders_paid),
            int(gross_amount_minor),
            tuple(
                PaymentMethodTotal(method, by_method[method])
                for method in PaymentMethod
                if method in by_method
            ),
        )

    async def dashboard_summary(
        self,
        organization_id: UUID,
        location_ids: tuple[UUID, ...],
        date_from: datetime,
        date_to: datetime,
    ) -> tuple[int, int]:
        if not location_ids:
            return 0, 0
        amount, orders = (
            await self.session.execute(
                select(
                    func.coalesce(func.sum(PaymentModel.amount_minor), 0),
                    func.count(PaymentModel.id),
                ).where(
                    PaymentModel.organization_id == organization_id,
                    PaymentModel.location_id.in_(location_ids),
                    PaymentModel.completed_at >= date_from,
                    PaymentModel.completed_at < date_to,
                )
            )
        ).one()
        return int(amount), int(orders)

    async def dashboard_trend(
        self,
        organization_id: UUID,
        location_ids: tuple[UUID, ...],
        buckets: tuple[tuple[datetime, datetime], ...],
    ) -> tuple[tuple[int, int], ...]:
        if not location_ids or not buckets:
            return tuple((0, 0) for _ in buckets)
        columns = []
        for date_from, date_to in buckets:
            condition = (PaymentModel.completed_at >= date_from) & (
                PaymentModel.completed_at < date_to
            )
            columns.extend(
                (
                    func.coalesce(
                        func.sum(case((condition, PaymentModel.amount_minor), else_=0)),
                        0,
                    ),
                    func.coalesce(func.sum(case((condition, 1), else_=0)), 0),
                )
            )
        row = (
            await self.session.execute(
                select(*columns).where(
                    PaymentModel.organization_id == organization_id,
                    PaymentModel.location_id.in_(location_ids),
                    PaymentModel.completed_at >= buckets[0][0],
                    PaymentModel.completed_at < buckets[-1][1],
                )
            )
        ).one()
        return tuple((int(row[index]), int(row[index + 1])) for index in range(0, len(row), 2))

    async def dashboard_locations(
        self,
        organization_id: UUID,
        location_ids: tuple[UUID, ...],
        date_from: datetime,
        date_to: datetime,
    ) -> tuple[tuple[UUID, int, int], ...]:
        if not location_ids:
            return ()
        rows = await self.session.execute(
            select(
                PaymentModel.location_id,
                func.coalesce(func.sum(PaymentModel.amount_minor), 0),
                func.count(PaymentModel.id),
            )
            .where(
                PaymentModel.organization_id == organization_id,
                PaymentModel.location_id.in_(location_ids),
                PaymentModel.completed_at >= date_from,
                PaymentModel.completed_at < date_to,
            )
            .group_by(PaymentModel.location_id)
        )
        return tuple(
            (location_id, int(amount), int(orders)) for location_id, amount, orders in rows
        )

    async def dashboard_mix(
        self,
        organization_id: UUID,
        location_ids: tuple[UUID, ...],
        date_from: datetime,
        date_to: datetime,
    ) -> tuple[tuple[str, int], ...]:
        if not location_ids:
            return ()
        rows = await self.session.execute(
            select(
                PaymentLineModel.method,
                func.coalesce(func.sum(PaymentLineModel.amount_minor), 0),
            )
            .join(PaymentModel, PaymentModel.id == PaymentLineModel.payment_id)
            .where(
                PaymentModel.organization_id == organization_id,
                PaymentModel.location_id.in_(location_ids),
                PaymentModel.completed_at >= date_from,
                PaymentModel.completed_at < date_to,
            )
            .group_by(PaymentLineModel.method)
            .order_by(PaymentLineModel.method)
        )
        return tuple((method, int(amount)) for method, amount in rows)

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()


def _payment_query(organization_id: UUID):
    return (
        select(PaymentModel)
        .where(PaymentModel.organization_id == organization_id)
        .options(selectinload(PaymentModel.lines))
        .execution_options(populate_existing=True)
    )


def _payment_values(value: Payment) -> dict[str, object]:
    return {
        "id": value.id,
        "organization_id": value.organization_id,
        "location_id": value.location_id,
        "order_id": value.order_id,
        "shift_id": value.shift_id,
        "offline_session_id": value.offline_session_id,
        "client_payment_id": value.client_payment_id,
        "currency_code": value.currency_code,
        "amount_minor": value.amount_minor,
        "created_by_user_id": value.created_by_user_id,
        "completed_at": value.completed_at,
        "created_at": value.created_at,
        "updated_at": value.updated_at,
    }


def _line_values(value) -> dict[str, object]:
    return {
        "id": value.id,
        "payment_id": value.payment_id,
        "method": value.method.value,
        "amount_minor": value.amount_minor,
        "cash_received_minor": value.cash_received_minor,
        "change_minor": value.change_minor,
        "reference": value.reference,
        "external_payment_attempt_id": value.external_payment_attempt_id,
        "provider_code": value.provider_code,
        "provider_transaction_id": value.provider_transaction_id,
        "sort_order": value.sort_order,
        "created_at": value.created_at,
    }
