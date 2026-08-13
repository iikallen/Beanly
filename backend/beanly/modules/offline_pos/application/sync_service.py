import hashlib
import json
from datetime import UTC, datetime, timedelta
from time import monotonic
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from beanly.core.events import DomainEventSink
from beanly.core.observability import metrics
from beanly.core.security.audit import SecurityAuditRecorder
from beanly.modules.inventory.domain.exceptions import InventoryError
from beanly.modules.offline_pos.api.schemas import (
    OfflineOrderRequest,
    OfflineSyncRequest,
    OfflineSyncResultResponse,
)
from beanly.modules.offline_pos.domain.events import OfflineOrderSynced, OfflineSyncConflict
from beanly.modules.offline_pos.domain.exceptions import (
    CatalogSnapshotInvalid,
    OfflinePermissionDenied,
    OfflinePosConflict,
    OfflinePosError,
    OfflinePosNotFound,
    OfflineRevisionConflict,
    OfflineSessionExpired,
)
from beanly.modules.offline_pos.infrastructure.db.models import (
    PosDeviceModel,
    PosOfflineOrderSyncModel,
)
from beanly.modules.offline_pos.infrastructure.db.repositories import SqlAlchemyOfflinePosRepository
from beanly.modules.offline_pos.infrastructure.sales_gateway import OfflineSalesGateway
from beanly.modules.organizations.application.services.organization_service import (
    OrganizationService,
)
from beanly.modules.organizations.domain.exceptions import OrganizationAccessDenied
from beanly.modules.organizations.domain.permissions import Permission
from beanly.modules.payments.application.payment_service import (
    CompletePaymentInput,
    PaymentLineInput,
    PaymentService,
)
from beanly.modules.payments.domain.exceptions import PaymentError
from beanly.modules.sales.domain.exceptions import SalesError

_CLOCK_TOLERANCE = timedelta(minutes=5)
_SYNC_GRACE = timedelta(days=7)


class OfflineSyncService:
    def __init__(
        self,
        session: AsyncSession,
        repository: SqlAlchemyOfflinePosRepository,
        organizations: OrganizationService,
        sales: OfflineSalesGateway,
        payments: PaymentService,
        sink: DomainEventSink,
        audit: SecurityAuditRecorder,
    ) -> None:
        self.session = session
        self.repository = repository
        self.organizations = organizations
        self.sales = sales
        self.payments = payments
        self.sink = sink
        self.audit = audit

    async def sync(
        self, device: PosDeviceModel, request: OfflineSyncRequest
    ) -> list[OfflineSyncResultResponse]:
        started = monotonic()
        metrics.pos_offline_sync.add(1)
        try:
            session = await self.repository.get_session(device.id, request.session_id, lock=True)
            if session is None:
                raise OfflinePosNotFound("Offline session not found")
            now = datetime.now(UTC)
            if now > _utc(session.expires_at) + _SYNC_GRACE:
                raise OfflineSessionExpired("Offline session sync grace has expired")
            context = await self.organizations.tenant_context(
                session.actor_user_id, session.organization_id
            )
            results: list[OfflineSyncResultResponse] = []
            for order in request.orders:
                result = await self._one(device, session, context, order, now)
                results.append(result)
            session.last_sync_at = now
            await self.repository.touch_device(device.id, now)
            await self.repository.commit()
            return results
        except Exception:
            await self.repository.rollback()
            raise
        finally:
            metrics.pos_offline_sync_duration.record(monotonic() - started)

    async def _one(self, device, session, context, request, now):
        payload_hash = _hash(request)
        receipt = await self.repository.get_sync(session.id, request.client_order_id, lock=True)
        if receipt is not None and request.revision == receipt.last_client_revision:
            if payload_hash != receipt.payload_hash:
                metrics.pos_offline_conflicts.add(1, {"code": OfflineRevisionConflict.code})
                return OfflineSyncResultResponse(
                    client_order_id=request.client_order_id,
                    revision=request.revision,
                    status="CONFLICT",
                    code=OfflineRevisionConflict.code,
                    server_order_id=receipt.server_order_id,
                    server_order_number=receipt.server_order_number,
                    server_version=receipt.last_server_version,
                    payment_id=receipt.payment_id,
                )
            return _response(receipt)
        if receipt is not None and request.revision < receipt.last_client_revision:
            metrics.pos_offline_conflicts.add(1, {"code": OfflineRevisionConflict.code})
            return OfflineSyncResultResponse(
                client_order_id=request.client_order_id,
                revision=request.revision,
                status="CONFLICT",
                code=OfflineRevisionConflict.code,
                server_order_id=receipt.server_order_id,
                server_order_number=receipt.server_order_number,
                server_version=receipt.last_server_version,
                payment_id=receipt.payment_id,
            )
        required = {Permission.SALES_CREATE}
        if request.payment is not None:
            required.add(Permission.PAYMENTS_CREATE)
        if request.status == "CANCELLED":
            required.add(Permission.SALES_CANCEL)
        if request.manual_promotion_ids:
            required.add(Permission.DISCOUNTS_APPLY)
        if not required <= context.permissions:
            return await self._conflict(
                session,
                request,
                OfflinePermissionDenied("Current role cannot sync this order"),
                receipt,
                payload_hash,
            )
        try:
            await self.organizations.ensure_location_access(context, session.location_id)
        except OrganizationAccessDenied:
            return await self._conflict(
                session,
                request,
                OfflinePermissionDenied("Current role cannot access this location"),
                receipt,
                payload_hash,
            )
        session_started = _utc(session.started_at)
        session_expires = _utc(session.expires_at)
        if request.created_at < session_started - _CLOCK_TOLERANCE:
            return await self._conflict(
                session, request, OfflinePosConflict("Order predates offline session"), receipt
            )
        if request.created_at > session_expires + _CLOCK_TOLERANCE:
            return await self._conflict(
                session,
                request,
                OfflineSessionExpired("Order was created after session expiry"),
                receipt,
            )
        if (
            request.updated_at < request.created_at
            or request.updated_at < session_started - _CLOCK_TOLERANCE
            or request.updated_at > session_expires + _CLOCK_TOLERANCE
        ):
            return await self._conflict(
                session,
                request,
                OfflinePosConflict("Order updated_at is outside session bounds"),
                receipt,
            )
        if request.payment is not None and (
            request.payment.completed_at < request.updated_at
            or request.payment.completed_at < session_started - _CLOCK_TOLERANCE
            or request.payment.completed_at > session_expires + _CLOCK_TOLERANCE
        ):
            return await self._conflict(
                session,
                request,
                OfflinePosConflict("Payment completed_at is outside session bounds"),
                receipt,
            )
        snapshot = await self.repository.get_snapshot(
            session.organization_id, request.catalog_snapshot_id
        )
        if (
            snapshot is None
            or snapshot.location_id != session.location_id
            or snapshot.warehouse_id != session.warehouse_id
            or _utc(snapshot.created_at) < session_started - _CLOCK_TOLERANCE
            or _utc(snapshot.created_at) > session_expires + _CLOCK_TOLERANCE
        ):
            return await self._conflict(
                session,
                request,
                CatalogSnapshotInvalid("Catalog snapshot does not belong to session"),
                receipt,
            )
        was_conflict = receipt is not None and receipt.status == "CONFLICT"
        try:
            async with self.session.begin_nested():
                order = await self.sales.reconcile_staged(
                    context, device, session, snapshot, request
                )
                payment = None
                if request.payment is not None:
                    if any(
                        line.method.value == "CARD" and not line.external_settlement_confirmed
                        for line in request.payment.lines
                    ):
                        raise OfflinePosConflict(
                            "Offline CARD requires confirmed external settlement"
                        )
                    payment = await self.payments.complete_staged(
                        context,
                        order.id,
                        CompletePaymentInput(
                            request.payment.client_payment_id,
                            tuple(
                                PaymentLineInput(
                                    line.method,
                                    int(line.amount_minor),
                                    (
                                        int(line.cash_received_minor)
                                        if line.cash_received_minor is not None
                                        else None
                                    ),
                                    line.reference,
                                )
                                for line in request.payment.lines
                            ),
                            request.payment.completed_at,
                            session.id,
                        ),
                    )
                if receipt is None:
                    receipt = PosOfflineOrderSyncModel(
                        id=uuid4(),
                        session_id=session.id,
                        client_order_id=request.client_order_id,
                        server_order_id=order.id,
                        payment_id=payment.id if payment else None,
                        server_order_number=order.number,
                        last_client_revision=request.revision,
                        last_server_version=order.version + (1 if payment else 0),
                        payload_hash=payload_hash,
                        status="SYNCED",
                        last_error_code=None,
                        synced_at=now,
                    )
                else:
                    receipt.server_order_id = order.id
                    receipt.payment_id = payment.id if payment else None
                    receipt.server_order_number = order.number
                    receipt.last_client_revision = request.revision
                    receipt.last_server_version = order.version + (1 if payment else 0)
                    receipt.payload_hash = payload_hash
                    receipt.status = "SYNCED"
                    receipt.last_error_code = None
                    receipt.synced_at = now
                await self.repository.save_sync(receipt)
                await self.sink.stage(
                    OfflineOrderSynced(session.organization_id, session.id, order.id)
                )
                if was_conflict:
                    await self.audit.record(
                        action="OFFLINE_CONFLICT_RESOLVED",
                        resource_type="pos_offline_order_sync",
                        organization_id=session.organization_id,
                        actor_user_id=session.actor_user_id,
                        resource_id=receipt.id,
                    )
            metrics.pos_offline_orders_synced.add(1)
            if payment is not None:
                metrics.pos_offline_payments_synced.add(1)
                delay = max(0.0, (now - request.payment.completed_at).total_seconds())
                metrics.pos_offline_payment_delay.record(delay)
            return _response(receipt)
        except (OfflinePosError, PaymentError, SalesError, InventoryError, ValueError) as exc:
            return await self._conflict(session, request, exc, receipt, payload_hash)

    async def _conflict(
        self, session, request, exc, receipt=None, payload_hash=None
    ) -> OfflineSyncResultResponse:
        code = getattr(exc, "code", "OFFLINE_SYNC_FAILED")
        metrics.pos_offline_conflicts.add(1, {"code": code})
        if receipt is None:
            receipt = PosOfflineOrderSyncModel(
                id=uuid4(),
                session_id=session.id,
                client_order_id=request.client_order_id,
                server_order_id=None,
                payment_id=None,
                server_order_number=None,
                last_client_revision=request.revision,
                last_server_version=None,
                payload_hash=payload_hash or _hash(request),
                status="CONFLICT",
                last_error_code=code,
                synced_at=datetime.now(UTC),
            )
            await self.repository.save_sync(receipt)
        elif request.revision >= receipt.last_client_revision:
            receipt.last_client_revision = request.revision
            receipt.payload_hash = payload_hash or _hash(request)
            receipt.status = "CONFLICT"
            receipt.last_error_code = code
            receipt.synced_at = datetime.now(UTC)
            await self.repository.save_sync(receipt)
        else:
            return OfflineSyncResultResponse(
                client_order_id=request.client_order_id,
                revision=request.revision,
                status="CONFLICT",
                code=code,
                server_order_id=receipt.server_order_id,
                server_order_number=receipt.server_order_number,
                server_version=receipt.last_server_version,
                payment_id=receipt.payment_id,
            )
        await self.sink.stage(
            OfflineSyncConflict(
                session.organization_id,
                session.id,
                request.client_order_id,
                code,
            )
        )
        return OfflineSyncResultResponse(
            client_order_id=request.client_order_id,
            revision=request.revision,
            status="CONFLICT",
            code=code,
            server_order_id=receipt.server_order_id,
            server_order_number=receipt.server_order_number,
            server_version=receipt.last_server_version,
            payment_id=receipt.payment_id,
        )


def _hash(value: OfflineOrderRequest) -> str:
    payload = value.model_dump(mode="json")
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _response(value: PosOfflineOrderSyncModel) -> OfflineSyncResultResponse:
    return OfflineSyncResultResponse(
        client_order_id=value.client_order_id,
        revision=value.last_client_revision,
        status="SYNCED" if value.status == "SYNCED" else "CONFLICT",
        code=value.last_error_code,
        server_order_id=value.server_order_id,
        server_order_number=value.server_order_number,
        server_version=value.last_server_version,
        payment_id=value.payment_id,
    )


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
