from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from beanly.modules.fiscal.application.live_ports import UnavailableFiscalReconciler
from beanly.modules.fiscal.application.live_service import FiscalLiveService
from beanly.modules.fiscal.infrastructure.live_repository import SqlAlchemyFiscalLiveRepository
from beanly.modules.inventory.infrastructure.db.models import InventoryItemModel, WarehouseModel
from beanly.modules.menu.infrastructure.db.models import (
    MenuCategoryModel,
    ProductLocationSettingModel,
    ProductModel,
    ProductVariantModel,
)
from beanly.modules.onboarding.application.ports import BootstrapResult
from beanly.modules.organizations.application.services.organization_service import (
    OrganizationService,
)
from beanly.modules.organizations.domain.entities import TenantContext
from beanly.modules.organizations.infrastructure.db.models import LocationModel, OrganizationModel
from beanly.modules.organizations.infrastructure.db.repositories import (
    SqlAlchemyOrganizationRepository,
)
from beanly.modules.sales.infrastructure.db.models import PosRegisterModel


@dataclass(frozen=True, slots=True)
class SqlAlchemyBootstrapResult(BootstrapResult):
    location_id: UUID
    warehouse_id: UUID
    register_id: UUID
    warehouse_created: bool
    register_created: bool


class SqlAlchemyOnboardingGateway:
    def __init__(
        self,
        session: AsyncSession,
        *,
        live_transport_enabled: bool,
        nkt_configured: bool,
    ) -> None:
        self.session = session
        self.fiscal = FiscalLiveService(
            SqlAlchemyFiscalLiveRepository(
                session,
                OrganizationService(SqlAlchemyOrganizationRepository(session)),
            ),
            UnavailableFiscalReconciler(),
            live_transport_enabled=live_transport_enabled,
            real_provider_codes=frozenset({"webkassa"}),
            nkt_configured=nkt_configured,
        )

    async def bootstrap(
        self,
        context: TenantContext,
        warehouse_name: str,
        register_name: str,
        now: datetime,
    ) -> SqlAlchemyBootstrapResult:
        organization = await self.session.scalar(
            select(OrganizationModel)
            .where(OrganizationModel.id == context.organization_id)
            .with_for_update()
        )
        if organization is None:
            raise ValueError("Organization not found")
        location = await self.session.scalar(
            select(LocationModel)
            .where(
                LocationModel.organization_id == context.organization_id,
                LocationModel.is_primary.is_(True),
                LocationModel.is_active.is_(True),
            )
            .order_by(LocationModel.created_at, LocationModel.id)
        )
        if location is None:
            raise ValueError("Primary active location is required")
        warehouse = await self.session.scalar(
            select(WarehouseModel)
            .where(
                WarehouseModel.organization_id == context.organization_id,
                WarehouseModel.location_id == location.id,
                WarehouseModel.is_active.is_(True),
            )
            .order_by(
                (WarehouseModel.name == warehouse_name).desc(),
                WarehouseModel.created_at,
                WarehouseModel.id,
            )
        )
        warehouse_created = warehouse is None
        if warehouse is None:
            warehouse = WarehouseModel(
                id=uuid4(),
                organization_id=context.organization_id,
                location_id=location.id,
                name=warehouse_name,
                is_active=True,
                created_at=now,
                updated_at=now,
            )
            self.session.add(warehouse)
        register = await self.session.scalar(
            select(PosRegisterModel)
            .where(
                PosRegisterModel.organization_id == context.organization_id,
                PosRegisterModel.location_id == location.id,
                PosRegisterModel.is_active.is_(True),
            )
            .order_by(
                (PosRegisterModel.name == register_name).desc(),
                PosRegisterModel.created_at,
                PosRegisterModel.id,
            )
        )
        register_created = register is None
        if register is None:
            register = PosRegisterModel(
                id=uuid4(),
                organization_id=context.organization_id,
                location_id=location.id,
                name=register_name,
                is_active=True,
                created_by_user_id=context.user_id,
                created_at=now,
                updated_at=now,
            )
            self.session.add(register)
        await self.session.flush()
        return SqlAlchemyBootstrapResult(
            location.id,
            warehouse.id,
            register.id,
            warehouse_created,
            register_created,
        )

    async def readiness(self, context: TenantContext) -> dict[str, object]:
        location = await self.session.scalar(
            select(LocationModel).where(
                LocationModel.organization_id == context.organization_id,
                LocationModel.is_primary.is_(True),
                LocationModel.is_active.is_(True),
            )
        )
        location_id = location.id if location else None
        warehouse_count = (
            await self._count(
                WarehouseModel,
                WarehouseModel.organization_id == context.organization_id,
                WarehouseModel.location_id == location_id,
                WarehouseModel.is_active.is_(True),
            )
            if location_id
            else 0
        )
        register_count = (
            await self._count(
                PosRegisterModel,
                PosRegisterModel.organization_id == context.organization_id,
                PosRegisterModel.location_id == location_id,
                PosRegisterModel.is_active.is_(True),
            )
            if location_id
            else 0
        )
        product_count = 0
        inventory_count = await self._count(
            InventoryItemModel,
            InventoryItemModel.organization_id == context.organization_id,
            InventoryItemModel.is_active.is_(True),
        )
        if location_id:
            product_count = int(
                await self.session.scalar(
                    select(func.count(func.distinct(ProductModel.id)))
                    .select_from(ProductModel)
                    .join(MenuCategoryModel, MenuCategoryModel.id == ProductModel.category_id)
                    .join(ProductVariantModel, ProductVariantModel.product_id == ProductModel.id)
                    .outerjoin(
                        ProductLocationSettingModel,
                        and_(
                            ProductLocationSettingModel.product_id == ProductModel.id,
                            ProductLocationSettingModel.location_id == location_id,
                        ),
                    )
                    .where(
                        ProductModel.organization_id == context.organization_id,
                        ProductModel.status == "ACTIVE",
                        ProductVariantModel.status == "ACTIVE",
                        MenuCategoryModel.is_active.is_(True),
                        or_(
                            ProductLocationSettingModel.id.is_(None),
                            and_(
                                ProductLocationSettingModel.is_available.is_(True),
                                ProductLocationSettingModel.is_visible.is_(True),
                            ),
                        ),
                    )
                )
                or 0
            )
        fiscal_ready = True
        fiscal_optional = location is None or location.fiscal_enforcement_mode != "LIVE_REQUIRED"
        fiscal_details: list[str] = []
        if location and location.fiscal_enforcement_mode == "LIVE_REQUIRED":
            fiscal = await self.fiscal.go_live_readiness(context, location.id)
            fiscal_ready = bool(fiscal["ready"])
            fiscal_details = [str(value) for value in fiscal.get("blockers", [])]
        steps = {
            "workspace": _step(True, 1),
            "location": _step(bool(location), 1 if location else 0),
            "warehouse": _step(warehouse_count > 0, warehouse_count),
            "inventory": _step(
                inventory_count > 0,
                inventory_count,
                status="COMPLETE" if inventory_count else "NEEDS_ATTENTION",
            ),
            "register": _step(register_count > 0, register_count),
            "menu": _step(
                product_count > 0,
                product_count,
                [f"products={product_count}", f"ready_products={product_count}"],
            ),
            "fiscal": _step(
                fiscal_ready,
                1 if fiscal_ready else 0,
                fiscal_details,
                status="OPTIONAL" if fiscal_optional else None,
            ),
        }
        return {
            "steps": steps,
            "pos_ready": bool(
                location and warehouse_count and register_count and product_count and fiscal_ready
            ),
        }

    async def organization_origin(self, organization_id: UUID) -> tuple[UUID, datetime] | None:
        row = (
            await self.session.execute(
                select(OrganizationModel.created_by, OrganizationModel.created_at).where(
                    OrganizationModel.id == organization_id
                )
            )
        ).one_or_none()
        return (row.created_by, row.created_at) if row else None

    async def _count(self, model, *filters: object) -> int:
        return int(
            await self.session.scalar(select(func.count()).select_from(model).where(*filters)) or 0
        )


def _step(
    ready: bool,
    count: int,
    details: list[str] | None = None,
    *,
    status: str | None = None,
) -> dict[str, object]:
    return {
        "status": status or ("COMPLETE" if ready else "MISSING"),
        "count": count,
        "details": details or [],
    }
