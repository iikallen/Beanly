import hashlib
import secrets
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError

from beanly.core.events import DomainEventSink, NullDomainEventSink
from beanly.core.security.audit import SecurityAuditRecorder
from beanly.modules.offline_pos.domain.events import PosDevicePaired, PosDeviceRevoked
from beanly.modules.offline_pos.domain.exceptions import (
    ActiveDeviceExists,
    OfflinePosNotFound,
)
from beanly.modules.offline_pos.infrastructure.db.models import PosDeviceModel
from beanly.modules.offline_pos.infrastructure.db.repositories import SqlAlchemyOfflinePosRepository
from beanly.modules.organizations.application.services.organization_service import (
    OrganizationService,
)
from beanly.modules.organizations.domain.entities import TenantContext
from beanly.modules.sales.domain.repositories import SalesRepository


class DeviceService:
    def __init__(
        self,
        repository: SqlAlchemyOfflinePosRepository,
        sales: SalesRepository,
        organizations: OrganizationService,
        audit: SecurityAuditRecorder,
        sink: DomainEventSink | None = None,
    ) -> None:
        self.repository = repository
        self.sales = sales
        self.organizations = organizations
        self.audit = audit
        self.sink = sink or NullDomainEventSink()

    async def pair(
        self, context: TenantContext, register_id: UUID, name: str
    ) -> tuple[PosDeviceModel, str]:
        normalized = name.strip()
        if not normalized or len(normalized) > 150:
            raise ValueError("Device name must contain between 1 and 150 characters")
        try:
            register = await self.sales.get_register(context.organization_id, register_id)
            if register is None or not register.is_active:
                raise OfflinePosNotFound("Active register not found")
            await self.organizations.ensure_location_access(context, register.location_id)
            if await self.repository.active_device_for_register(register_id):
                raise ActiveDeviceExists("Register already has an active POS device")
            credential = secrets.token_urlsafe(32)
            now = datetime.now(UTC)
            device = await self.repository.add_device(
                PosDeviceModel(
                    id=uuid4(),
                    organization_id=context.organization_id,
                    location_id=register.location_id,
                    register_id=register.id,
                    name=normalized,
                    status="ACTIVE",
                    credential_hash=credential_hash(credential),
                    last_seen_at=now,
                    created_by=context.user_id,
                    created_at=now,
                    updated_at=now,
                )
            )
            await self.audit.record(
                action="POS_DEVICE_PAIRED",
                resource_type="pos_device",
                organization_id=context.organization_id,
                actor_user_id=context.user_id,
                resource_id=device.id,
            )
            await self.sink.stage(PosDevicePaired(context.organization_id, device.id))
            await self.repository.commit()
            return device, credential
        except IntegrityError as exc:
            await self.repository.rollback()
            if await self.repository.active_device_for_register(register_id):
                raise ActiveDeviceExists("Register already has an active POS device") from exc
            raise
        except Exception:
            await self.repository.rollback()
            raise

    async def list(self, context: TenantContext) -> list[PosDeviceModel]:
        return await self.repository.list_devices(context.organization_id)

    async def revoke(self, context: TenantContext, device_id: UUID) -> PosDeviceModel:
        try:
            device = await self.repository.get_device(context.organization_id, device_id, lock=True)
            if device is None:
                raise OfflinePosNotFound("POS device not found")
            await self.organizations.ensure_location_access(context, device.location_id)
            now = datetime.now(UTC)
            device.status = "REVOKED"
            device.updated_at = now
            current = await self.repository.current_session(device.id)
            if current is not None:
                current.status = "REVOKED"
                current.closed_at = now
            await self.audit.record(
                action="POS_DEVICE_REVOKED",
                resource_type="pos_device",
                organization_id=context.organization_id,
                actor_user_id=context.user_id,
                resource_id=device.id,
            )
            await self.sink.stage(PosDeviceRevoked(context.organization_id, device.id))
            await self.repository.commit()
            return device
        except Exception:
            await self.repository.rollback()
            raise


def credential_hash(credential: str) -> str:
    return hashlib.sha256(credential.encode()).hexdigest()
