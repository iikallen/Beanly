from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError

from beanly.core.events import DomainEventSink, NullDomainEventSink
from beanly.core.observability import metrics
from beanly.core.security.audit import SecurityAuditRecorder
from beanly.modules.offline_pos.domain.events import OfflineSessionClosed, OfflineSessionStarted
from beanly.modules.offline_pos.domain.exceptions import (
    OfflinePosConflict,
    OfflinePosNotFound,
)
from beanly.modules.offline_pos.infrastructure.catalog_builder import CatalogSnapshotBuilder
from beanly.modules.offline_pos.infrastructure.db.models import (
    PosCatalogSnapshotModel,
    PosDeviceModel,
    PosOfflineSessionModel,
)
from beanly.modules.offline_pos.infrastructure.db.repositories import SqlAlchemyOfflinePosRepository
from beanly.modules.organizations.application.services.organization_service import (
    OrganizationService,
)
from beanly.modules.organizations.domain.entities import TenantContext
from beanly.modules.sales.domain.enums import RegisterShiftStatus
from beanly.modules.sales.domain.repositories import SalesRepository


class SessionService:
    def __init__(
        self,
        repository: SqlAlchemyOfflinePosRepository,
        sales: SalesRepository,
        organizations: OrganizationService,
        catalog: CatalogSnapshotBuilder,
        audit: SecurityAuditRecorder,
        sink: DomainEventSink | None = None,
    ) -> None:
        self.repository = repository
        self.sales = sales
        self.organizations = organizations
        self.catalog = catalog
        self.audit = audit
        self.sink = sink or NullDomainEventSink()

    async def start(
        self, context: TenantContext, device: PosDeviceModel, shift_id: UUID
    ) -> tuple[PosOfflineSessionModel, PosCatalogSnapshotModel]:
        try:
            if device.status != "ACTIVE" or device.organization_id != context.organization_id:
                raise OfflinePosNotFound("POS device not found")
            await self.organizations.ensure_location_access(context, device.location_id)
            shift = await self.sales.get_shift(context.organization_id, shift_id, lock=True)
            if (
                shift is None
                or shift.status != RegisterShiftStatus.OPEN
                or shift.register_id != device.register_id
                or shift.location_id != device.location_id
            ):
                raise OfflinePosConflict("Offline session requires this device's OPEN shift")
            current = await self.repository.current_session(device.id)
            now = datetime.now(UTC)
            if current is not None and now > _utc(current.expires_at):
                current.status = "EXPIRED"
                current.closed_at = now
                await self.repository.commit()
                current = None
            if current is not None:
                snapshot = await self.repository.get_snapshot(
                    current.organization_id, current.catalog_snapshot_id
                )
                if snapshot is None:
                    raise OfflinePosNotFound("Catalog snapshot not found")
                await self.repository.commit()
                return current, snapshot
            snapshot = await self.catalog.build(
                context.organization_id,
                shift.location_id,
                shift.warehouse_id,
            )
            await self.repository.add_snapshot(snapshot)
            value = await self.repository.add_session(
                PosOfflineSessionModel(
                    id=uuid4(),
                    device_id=device.id,
                    organization_id=context.organization_id,
                    location_id=shift.location_id,
                    register_id=device.register_id,
                    shift_id=shift.id,
                    warehouse_id=shift.warehouse_id,
                    actor_user_id=context.user_id,
                    catalog_snapshot_id=snapshot.id,
                    status="ACTIVE",
                    started_at=now,
                    expires_at=now + timedelta(hours=24),
                    last_sync_at=None,
                    closed_at=None,
                )
            )
            await self.audit.record(
                action="OFFLINE_SESSION_STARTED",
                resource_type="pos_offline_session",
                organization_id=context.organization_id,
                actor_user_id=context.user_id,
                resource_id=value.id,
            )
            await self.sink.stage(OfflineSessionStarted(context.organization_id, value.id))
            await self.repository.commit()
            metrics.pos_offline_sessions_started.add(1)
            return value, snapshot
        except IntegrityError as exc:
            await self.repository.rollback()
            current = await self.repository.current_session(device.id)
            if current is None:
                raise
            snapshot = await self.repository.get_snapshot(
                current.organization_id, current.catalog_snapshot_id
            )
            if snapshot is None:
                raise OfflinePosNotFound("Catalog snapshot not found") from exc
            return current, snapshot
        except Exception:
            await self.repository.rollback()
            raise

    async def current(
        self, device: PosDeviceModel
    ) -> tuple[PosOfflineSessionModel, PosCatalogSnapshotModel] | None:
        value = await self.repository.current_session(device.id)
        if value is None:
            return None
        snapshot = await self.repository.get_snapshot(
            value.organization_id, value.catalog_snapshot_id
        )
        if snapshot is None:
            raise OfflinePosNotFound("Catalog snapshot not found")
        if datetime.now(UTC) > _utc(value.expires_at):
            value.status = "EXPIRED"
            value.closed_at = datetime.now(UTC)
            await self.repository.commit()
        return value, snapshot

    async def refresh(
        self, device: PosDeviceModel, session_id: UUID
    ) -> tuple[PosOfflineSessionModel, PosCatalogSnapshotModel]:
        try:
            value = await self.repository.get_session(device.id, session_id, lock=True)
            if value is None or value.status != "ACTIVE":
                raise OfflinePosNotFound("Active offline session not found")
            if datetime.now(UTC) > _utc(value.expires_at):
                value.status = "EXPIRED"
                value.closed_at = datetime.now(UTC)
                await self.repository.commit()
                raise OfflinePosConflict("Offline session has expired")
            shift = await self.sales.get_shift(value.organization_id, value.shift_id)
            if shift is None or shift.status != RegisterShiftStatus.OPEN:
                raise OfflinePosConflict("Offline session shift is not OPEN")
            current = await self.repository.get_snapshot(
                value.organization_id, value.catalog_snapshot_id
            )
            if current is None:
                raise OfflinePosNotFound("Catalog snapshot not found")
            fresh = await self.catalog.build(
                value.organization_id, value.location_id, value.warehouse_id
            )
            if fresh.payload_hash != current.payload_hash:
                await self.repository.add_snapshot(fresh)
                value.catalog_snapshot_id = fresh.id
                current = fresh
            await self.repository.touch_device(device.id, datetime.now(UTC))
            await self.repository.commit()
            return value, current
        except Exception:
            await self.repository.rollback()
            raise

    async def close(
        self, device: PosDeviceModel, session_id: UUID
    ) -> tuple[PosOfflineSessionModel, PosCatalogSnapshotModel]:
        try:
            value = await self.repository.get_session(device.id, session_id, lock=True)
            if value is None or value.status != "ACTIVE":
                raise OfflinePosNotFound("Active offline session not found")
            if await self.repository.pending_for_shift(value.shift_id):
                raise OfflinePosConflict("Resolve offline sync conflicts before closing")
            now = datetime.now(UTC)
            value.status = "CLOSED"
            value.closed_at = now
            snapshot = await self.repository.get_snapshot(
                value.organization_id, value.catalog_snapshot_id
            )
            if snapshot is None:
                raise OfflinePosNotFound("Catalog snapshot not found")
            await self.audit.record(
                action="OFFLINE_SESSION_CLOSED",
                resource_type="pos_offline_session",
                organization_id=value.organization_id,
                actor_user_id=value.actor_user_id,
                resource_id=value.id,
            )
            await self.sink.stage(OfflineSessionClosed(value.organization_id, value.id))
            await self.repository.commit()
            return value, snapshot
        except Exception:
            await self.repository.rollback()
            raise


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
