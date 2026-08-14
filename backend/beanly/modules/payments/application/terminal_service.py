import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from beanly.modules.organizations.domain.entities import TenantContext
from beanly.modules.payments.application.ports import SalesSettlementPort
from beanly.modules.payments.domain.entities import ExternalPaymentAttempt, TerminalBinding
from beanly.modules.payments.domain.enums import (
    ExternalPaymentAttemptStatus,
    ExternalPaymentMethod,
)
from beanly.modules.payments.domain.exceptions import (
    ExternalPaymentAttemptAmountMismatch,
    ExternalPaymentAttemptIdempotencyConflict,
    ExternalPaymentAttemptNotFound,
    ExternalPaymentUnsupportedAmount,
    ExternalPaymentUnsupportedCurrency,
    ExternalTerminalUnavailable,
    OrderNotPayable,
    TerminalBindingConflict,
)
from beanly.modules.sales.domain.enums import OrderStatus


class TerminalRepositoryPort(Protocol):
    async def list_terminal_bindings(
        self, organization_id: UUID, register_id: UUID
    ) -> list[TerminalBinding]: ...

    async def add_terminal_binding(
        self, context: TenantContext, **values: object
    ) -> TerminalBinding: ...

    async def update_terminal_binding(
        self, context: TenantContext, binding_id: UUID, **values: object
    ) -> TerminalBinding: ...

    async def get_external_attempt(
        self, organization_id: UUID, attempt_id: UUID
    ) -> ExternalPaymentAttempt | None: ...

    async def get_external_attempt_by_client_id(
        self, organization_id: UUID, client_attempt_id: UUID
    ) -> ExternalPaymentAttempt | None: ...

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
    ) -> None: ...

    async def add_external_attempt(
        self, value: ExternalPaymentAttempt
    ) -> ExternalPaymentAttempt: ...

    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...


@dataclass(frozen=True, slots=True)
class ExternalAttemptInput:
    client_attempt_id: UUID
    order_id: UUID
    register_id: UUID
    pos_device_id: UUID | None
    connection_id: UUID
    provider_code: str
    method: ExternalPaymentMethod
    amount_minor: int
    currency_code: str


class TerminalPaymentService:
    def __init__(self, repository: TerminalRepositoryPort, sales: SalesSettlementPort) -> None:
        self.repository = repository
        self.sales = sales

    async def list_bindings(
        self, context: TenantContext, register_id: UUID
    ) -> list[TerminalBinding]:
        values = await self.repository.list_terminal_bindings(context.organization_id, register_id)
        for value in values:
            await self.sales.ensure_location_access(context, value.location_id)
        return values

    async def create_binding(self, context: TenantContext, **values: object) -> TerminalBinding:
        location_id = UUID(str(values["location_id"]))
        await self.sales.ensure_location_access(context, location_id)
        if values.get("provider_code") != "kaspi_smart_pos":
            raise TerminalBindingConflict("Unsupported interactive terminal provider")
        if values.get("transport_config") not in (None, {}):
            raise TerminalBindingConflict("Terminal transport configuration is bridge-managed")
        try:
            result = await self.repository.add_terminal_binding(
                context, **values, transport_config={}
            )
            await self.repository.commit()
            return result
        except Exception:
            await self.repository.rollback()
            raise

    async def update_binding(
        self, context: TenantContext, binding_id: UUID, **values: object
    ) -> TerminalBinding:
        if values.get("transport_config") not in (None, {}):
            raise TerminalBindingConflict("Terminal transport configuration is bridge-managed")
        try:
            result = await self.repository.update_terminal_binding(context, binding_id, **values)
            await self.sales.ensure_location_access(context, result.location_id)
            await self.repository.commit()
            return result
        except Exception:
            await self.repository.rollback()
            raise

    async def create_attempt(
        self, context: TenantContext, value: ExternalAttemptInput
    ) -> ExternalPaymentAttempt:
        request_hash = _request_hash(value)
        existing = await self.repository.get_external_attempt_by_client_id(
            context.organization_id, value.client_attempt_id
        )
        if existing is not None:
            await self.sales.ensure_location_access(context, existing.location_id)
            return _idempotent(existing, value, request_hash)

        order = await self.sales.lock_order_for_payment(context, value.order_id)
        if order.status != OrderStatus.OPEN or not order.shift_is_open or not order.has_items:
            raise OrderNotPayable("Order is not payable")
        if value.currency_code != "KZT" or order.currency_code != "KZT":
            raise ExternalPaymentUnsupportedCurrency("Smart POS supports KZT only")
        if value.provider_code != "kaspi_smart_pos":
            raise ExternalTerminalUnavailable("Unsupported interactive terminal provider")
        if value.amount_minor <= 0 or value.amount_minor % 100:
            raise ExternalPaymentUnsupportedAmount(
                "Smart POS amount must be a positive whole-tenge value"
            )
        if value.amount_minor != order.total_minor:
            raise ExternalPaymentAttemptAmountMismatch("Attempt must equal the order total")

        await self.repository.validate_terminal_binding(
            context.organization_id,
            location_id=order.location_id,
            shift_id=order.shift_id,
            register_id=value.register_id,
            connection_id=value.connection_id,
            provider_code=value.provider_code,
            pos_device_id=value.pos_device_id,
        )
        now = datetime.now(UTC)
        attempt = ExternalPaymentAttempt(
            uuid4(),
            context.organization_id,
            order.location_id,
            order.id,
            value.register_id,
            value.pos_device_id,
            value.connection_id,
            value.client_attempt_id,
            value.provider_code,
            value.method,
            value.amount_minor,
            value.currency_code,
            ExternalPaymentAttemptStatus.CREATED,
            None,
            None,
            request_hash,
            context.user_id,
            None,
            now,
            None,
            None,
            None,
            order.pricing_revision,
        )
        try:
            saved = await self.repository.add_external_attempt(attempt)
            await self.repository.commit()
            return saved
        except Exception:
            await self.repository.rollback()
            existing = await self.repository.get_external_attempt_by_client_id(
                context.organization_id, value.client_attempt_id
            )
            if existing is not None:
                return _idempotent(existing, value, request_hash)
            raise

    async def get_attempt(self, context: TenantContext, attempt_id: UUID) -> ExternalPaymentAttempt:
        value = await self.repository.get_external_attempt(context.organization_id, attempt_id)
        if value is None:
            raise ExternalPaymentAttemptNotFound("External payment attempt not found")
        await self.sales.ensure_location_access(context, value.location_id)
        return value

    async def start(self, context: TenantContext, attempt_id: UUID) -> ExternalPaymentAttempt:
        value = await self.get_attempt(context, attempt_id)
        if value.status is not ExternalPaymentAttemptStatus.CREATED:
            return value
        raise ExternalTerminalUnavailable(
            "Smart POS local bridge and test device are not configured"
        )

    async def reconcile(self, context: TenantContext, attempt_id: UUID) -> ExternalPaymentAttempt:
        value = await self.get_attempt(context, attempt_id)
        if value.status not in {
            ExternalPaymentAttemptStatus.UNKNOWN,
            ExternalPaymentAttemptStatus.TERMINAL_PENDING,
        }:
            return value
        raise ExternalTerminalUnavailable(
            "Smart POS local bridge and test device are not configured"
        )


def _request_hash(value: ExternalAttemptInput) -> str:
    payload = {
        "amount_minor": value.amount_minor,
        "connection_id": str(value.connection_id),
        "currency_code": value.currency_code,
        "method": value.method.value,
        "order_id": str(value.order_id),
        "pos_device_id": str(value.pos_device_id) if value.pos_device_id else None,
        "provider_code": value.provider_code,
        "register_id": str(value.register_id),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _idempotent(
    existing: ExternalPaymentAttempt,
    requested: ExternalAttemptInput,
    request_hash: str,
) -> ExternalPaymentAttempt:
    if existing.request_hash != request_hash or existing.order_id != requested.order_id:
        raise ExternalPaymentAttemptIdempotencyConflict(
            "client_attempt_id was already used with a different request"
        )
    return existing
