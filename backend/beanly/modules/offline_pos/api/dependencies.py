from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, status

from beanly.core.config.settings import get_settings
from beanly.core.events.outbox.repositories import OutboxRepository
from beanly.core.events.outbox.writer import OutboxEventSink
from beanly.core.security.audit import SecurityAuditRecorder
from beanly.modules.fiscal.application.service import FiscalService
from beanly.modules.fiscal.infrastructure.operations import SqlAlchemyFiscalOperations
from beanly.modules.fiscal.infrastructure.payment_gateway import FiscalPaymentSnapshotGateway
from beanly.modules.identity.api.dependencies import SessionDep, SettingsDep
from beanly.modules.inventory.application.services import InventoryService
from beanly.modules.inventory.infrastructure.db.repositories import SqlAlchemyInventoryRepository
from beanly.modules.offline_pos.application.device_service import DeviceService, credential_hash
from beanly.modules.offline_pos.application.session_service import SessionService
from beanly.modules.offline_pos.application.sync_service import OfflineSyncService
from beanly.modules.offline_pos.infrastructure.catalog_builder import CatalogSnapshotBuilder
from beanly.modules.offline_pos.infrastructure.db.models import PosDeviceModel
from beanly.modules.offline_pos.infrastructure.db.repositories import SqlAlchemyOfflinePosRepository
from beanly.modules.offline_pos.infrastructure.sales_gateway import OfflineSalesGateway
from beanly.modules.organizations.api.dependencies import TenantContextDep
from beanly.modules.organizations.application.services.organization_service import (
    OrganizationService,
)
from beanly.modules.organizations.domain.entities import TenantContext
from beanly.modules.organizations.domain.permissions import Permission
from beanly.modules.organizations.infrastructure.db.repositories import (
    SqlAlchemyOrganizationRepository,
)
from beanly.modules.payments.api.dependencies import fiscal_checkout_gateway
from beanly.modules.payments.application.payment_service import PaymentService
from beanly.modules.payments.infrastructure.db.repositories import SqlAlchemyPaymentRepository
from beanly.modules.payments.infrastructure.inventory_gateway import (
    InventorySaleGateway,
    SalesOrderReferenceValidator,
)
from beanly.modules.payments.infrastructure.sales_gateway import SalesSettlementGateway
from beanly.modules.sales.infrastructure.db.repositories import SqlAlchemySalesRepository


def _shared(session: SessionDep):
    offline = SqlAlchemyOfflinePosRepository(session)
    sales = SqlAlchemySalesRepository(session)
    organizations = OrganizationService(SqlAlchemyOrganizationRepository(session))
    sink = OutboxEventSink(OutboxRepository(session))
    return offline, sales, organizations, sink


def device_service(session: SessionDep) -> DeviceService:
    offline, sales, organizations, sink = _shared(session)
    return DeviceService(offline, sales, organizations, SecurityAuditRecorder(session), sink)


def session_service(session: SessionDep) -> SessionService:
    offline, sales, organizations, sink = _shared(session)
    return SessionService(
        offline,
        sales,
        organizations,
        CatalogSnapshotBuilder(session),
        SecurityAuditRecorder(session),
        sink,
    )


def sync_service(session: SessionDep, settings: SettingsDep = None) -> OfflineSyncService:
    settings = settings or get_settings()
    offline, sales, organizations, sink = _shared(session)
    inventory = InventoryService(
        SqlAlchemyInventoryRepository(session),
        organizations,
        reference_validator=SalesOrderReferenceValidator(sales),
    )
    payments = PaymentService(
        SqlAlchemyPaymentRepository(session),
        SalesSettlementGateway(sales, organizations),
        InventorySaleGateway(inventory, session),
        sink,
        FiscalPaymentSnapshotGateway(FiscalService(SqlAlchemyFiscalOperations(session))),
        fiscal_checkout_gateway(session, settings),
    )
    return OfflineSyncService(
        session,
        offline,
        organizations,
        OfflineSalesGateway(sales, organizations),
        payments,
        sink,
        SecurityAuditRecorder(session),
    )


DeviceServiceDep = Annotated[DeviceService, Depends(device_service)]
SessionServiceDep = Annotated[SessionService, Depends(session_service)]
SyncServiceDep = Annotated[OfflineSyncService, Depends(sync_service)]


async def active_device(
    session: SessionDep,
    credential: Annotated[str | None, Cookie(alias="beanly_pos_device")] = None,
) -> PosDeviceModel:
    if not credential:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "POS device authentication required")
    value = await SqlAlchemyOfflinePosRepository(session).get_device_by_hash(
        credential_hash(credential)
    )
    if value is None or value.status != "ACTIVE":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "POS device authentication required")
    return value


ActiveDeviceDep = Annotated[PosDeviceModel, Depends(active_device)]


async def device_manage(context: TenantContextDep) -> TenantContext:
    if Permission.POS_DEVICE_MANAGE not in context.permissions:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Permission denied")
    return context


DeviceManageDep = Annotated[TenantContext, Depends(device_manage)]
