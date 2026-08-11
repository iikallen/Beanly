from datetime import UTC, datetime, time
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from beanly.core.observability import metrics
from beanly.core.security.audit import SecurityAuditRecorder
from beanly.modules.fiscal.domain.enums import (
    FiscalReceiptStatus,
    FiscalRouteSourceMode,
)
from beanly.modules.fiscal.domain.exceptions import (
    FiscalReceiptNotFound,
    FiscalReceiptStateConflict,
    FiscalRouteAlreadyConfigured,
    FiscalRouteNotFound,
)
from beanly.modules.fiscal.infrastructure.db.models import (
    FiscalReceiptModel,
    FiscalRouteModel,
    FiscalTaxProfileModel,
    FiscalVariantProfileModel,
)
from beanly.modules.integrations.application.dto import FiscalReceiptResult
from beanly.modules.integrations.domain.enums import IntegrationConnectionStatus
from beanly.modules.integrations.infrastructure.db.mappers import to_connection
from beanly.modules.integrations.infrastructure.db.models import (
    IntegrationConnectionModel,
    IntegrationJobModel,
    IntegrationLocationBindingModel,
)
from beanly.modules.menu.infrastructure.db.models import ProductVariantModel
from beanly.modules.organizations.application.queries.list_locations import ListLocationsQuery
from beanly.modules.organizations.application.services.organization_service import (
    OrganizationService,
)
from beanly.modules.organizations.domain.entities import TenantContext
from beanly.modules.organizations.domain.exceptions import OrganizationAccessDenied
from beanly.modules.organizations.infrastructure.db.models import LocationModel
from beanly.modules.payments.infrastructure.db.models import PaymentModel, TerminalBindingModel
from beanly.modules.refunds.infrastructure.db.models import RefundModel
from beanly.modules.sales.infrastructure.db.models import (
    PosRegisterModel,
    RegisterShiftModel,
    SalesOrderModel,
)


class SqlAlchemyFiscalLiveRepository:
    def __init__(
        self,
        session: AsyncSession,
        organizations: OrganizationService,
        audit: SecurityAuditRecorder | None = None,
    ) -> None:
        self.session = session
        self.organizations = organizations
        self.audit = audit

    async def get_receipt(self, context: TenantContext, receipt_id: UUID) -> FiscalReceiptModel:
        value = await self.session.scalar(
            select(FiscalReceiptModel).where(
                FiscalReceiptModel.organization_id == context.organization_id,
                FiscalReceiptModel.id == receipt_id,
            )
        )
        if value is None:
            raise FiscalReceiptNotFound("Fiscal receipt not found")
        await self._location(context, value.location_id)
        return value

    async def list_receipts(
        self,
        context: TenantContext,
        *,
        location_id: UUID | None,
        status: FiscalReceiptStatus | None,
        limit: int,
        offset: int,
    ) -> tuple[list[FiscalReceiptModel], int]:
        location_ids = await self._locations(context, location_id)
        if not location_ids:
            return [], 0
        filters = [
            FiscalReceiptModel.organization_id == context.organization_id,
            FiscalReceiptModel.location_id.in_(location_ids),
        ]
        if status is not None:
            filters.append(FiscalReceiptModel.status == status.value)
        total = int(
            await self.session.scalar(select(func.count(FiscalReceiptModel.id)).where(*filters))
            or 0
        )
        values = list(
            await self.session.scalars(
                select(FiscalReceiptModel)
                .where(*filters)
                .order_by(FiscalReceiptModel.created_at.desc(), FiscalReceiptModel.id)
                .limit(limit)
                .offset(offset)
            )
        )
        return values, total

    async def operations(self, context: TenantContext, location_id: UUID) -> dict[str, object]:
        location = await self._location(context, location_id)
        local_now = datetime.now(UTC).astimezone(ZoneInfo(location.timezone))
        start = datetime.combine(
            local_now.date(), time.min, ZoneInfo(location.timezone)
        ).astimezone(UTC)
        pending_statuses = ("PENDING", "PROCESSING", "RETRYING")
        row = (
            await self.session.execute(
                select(
                    func.count(FiscalReceiptModel.id),
                    func.coalesce(
                        func.sum(case((FiscalReceiptModel.status == "SUCCEEDED", 1), else_=0)), 0
                    ),
                    func.coalesce(
                        func.sum(
                            case((FiscalReceiptModel.status.in_(pending_statuses), 1), else_=0)
                        ),
                        0,
                    ),
                    func.coalesce(
                        func.sum(case((FiscalReceiptModel.status == "DEAD", 1), else_=0)), 0
                    ),
                    func.coalesce(
                        func.sum(case((FiscalReceiptModel.status == "UNKNOWN", 1), else_=0)), 0
                    ),
                    func.min(
                        case(
                            (
                                FiscalReceiptModel.status.in_(pending_statuses),
                                FiscalReceiptModel.created_at,
                            )
                        )
                    ),
                ).where(
                    FiscalReceiptModel.organization_id == context.organization_id,
                    FiscalReceiptModel.location_id == location_id,
                    FiscalReceiptModel.created_at >= start,
                )
            )
        ).one()
        route = await self.session.execute(
            select(IntegrationConnectionModel.provider_code, IntegrationConnectionModel.status)
            .join(
                FiscalRouteModel,
                FiscalRouteModel.provider_connection_id == IntegrationConnectionModel.id,
            )
            .where(
                FiscalRouteModel.organization_id == context.organization_id,
                FiscalRouteModel.location_id == location_id,
                FiscalRouteModel.is_active.is_(True),
            )
            .limit(1)
        )
        provider = route.first()
        oldest = _utc(row[5]) if row[5] else None
        return {
            "provider_code": provider[0] if provider else None,
            "connected": bool(provider and provider[1] == IntegrationConnectionStatus.ACTIVE.value),
            "receipts_today": int(row[0]),
            "successful_today": int(row[1]),
            "pending": int(row[2]),
            "failed": int(row[3]),
            "unknown": int(row[4]),
            "oldest_pending_seconds": (
                max(0, int((datetime.now(UTC) - oldest).total_seconds())) if oldest else None
            ),
        }

    async def retry_receipt(self, context: TenantContext, receipt_id: UUID) -> FiscalReceiptModel:
        value = await self._locked_receipt(context, receipt_id)
        if value.status == FiscalReceiptStatus.UNKNOWN.value:
            raise FiscalReceiptStateConflict("UNKNOWN receipt must be reconciled, never retried")
        if value.status not in {
            FiscalReceiptStatus.DEAD.value,
            FiscalReceiptStatus.RETRYING.value,
        }:
            raise FiscalReceiptStateConflict("Receipt is not retryable")
        job = await self.session.scalar(
            select(IntegrationJobModel)
            .where(
                IntegrationJobModel.organization_id == context.organization_id,
                IntegrationJobModel.connection_id == value.connection_id,
                IntegrationJobModel.source_id == value.source_id,
                IntegrationJobModel.source_type
                == ("PAYMENT" if value.source_type == "SALE" else "REFUND"),
            )
            .with_for_update()
        )
        if job is None:
            raise FiscalReceiptNotFound("Fiscalization job not found")
        now = datetime.now(UTC)
        job.status = "RETRYING"
        job.available_at = now
        job.dead_lettered_at = None
        job.locked_by = None
        job.locked_until = None
        job.updated_at = now
        value.status = FiscalReceiptStatus.RETRYING.value
        value.last_error_code = None
        value.last_error_message = None
        value.updated_at = now
        await self._audit(context, "FISCAL_RECEIPT_MANUAL_RETRY", "fiscal_receipt", value.id)
        await self.session.commit()
        return value

    async def finish_reconciliation(
        self,
        context: TenantContext,
        receipt_id: UUID,
        result: FiscalReceiptResult,
    ) -> FiscalReceiptModel:
        value = await self._locked_receipt(context, receipt_id)
        if value.status != FiscalReceiptStatus.UNKNOWN.value:
            raise FiscalReceiptStateConflict("Receipt is no longer UNKNOWN")
        now = datetime.now(UTC)
        _success(value, result, now)
        await self._audit(context, "FISCAL_RECEIPT_RECONCILED", "fiscal_receipt", value.id)
        await self.session.commit()
        metrics.fiscal_receipt_success.add(1, {"provider.code": value.provider_code})
        return value

    async def enforcement(self, context: TenantContext, location_id: UUID) -> LocationModel:
        return await self._location(context, location_id)

    async def set_enforcement(
        self, context: TenantContext, location_id: UUID, mode: str
    ) -> LocationModel:
        await self._location(context, location_id)
        value = await self.session.scalar(
            select(LocationModel)
            .where(
                LocationModel.organization_id == context.organization_id,
                LocationModel.id == location_id,
            )
            .with_for_update()
        )
        assert value is not None
        value.fiscal_enforcement_mode = mode
        value.updated_at = datetime.now(UTC)
        await self._audit(context, "FISCAL_ENFORCEMENT_CHANGED", "location", value.id)
        await self.session.commit()
        return value

    async def list_routes(
        self, context: TenantContext, location_id: UUID | None
    ) -> list[FiscalRouteModel]:
        location_ids = await self._locations(context, location_id)
        if not location_ids:
            return []
        return list(
            await self.session.scalars(
                select(FiscalRouteModel)
                .where(
                    FiscalRouteModel.organization_id == context.organization_id,
                    FiscalRouteModel.location_id.in_(location_ids),
                )
                .order_by(FiscalRouteModel.created_at, FiscalRouteModel.id)
            )
        )

    async def create_route(self, context: TenantContext, **values: object) -> FiscalRouteModel:
        location_id = UUID(str(values["location_id"]))
        register_id = UUID(str(values["register_id"]))
        connection_id = UUID(str(values["provider_connection_id"]))
        source_mode = FiscalRouteSourceMode(str(values["source_mode"]))
        await self._location(context, location_id)
        register = await self.session.scalar(
            select(PosRegisterModel).where(
                PosRegisterModel.organization_id == context.organization_id,
                PosRegisterModel.location_id == location_id,
                PosRegisterModel.id == register_id,
            )
        )
        if register is None:
            raise FiscalRouteNotFound("Register not found")
        connection = await self.session.scalar(
            select(IntegrationConnectionModel).where(
                IntegrationConnectionModel.organization_id == context.organization_id,
                IntegrationConnectionModel.id == connection_id,
                IntegrationConnectionModel.status == IntegrationConnectionStatus.ACTIVE.value,
            )
        )
        if connection is None:
            raise FiscalRouteNotFound("Active integration connection not found")
        if source_mode is FiscalRouteSourceMode.EXTERNAL_KKM:
            valid = await self.session.scalar(
                select(IntegrationLocationBindingModel.id).where(
                    IntegrationLocationBindingModel.organization_id == context.organization_id,
                    IntegrationLocationBindingModel.connection_id == connection_id,
                    IntegrationLocationBindingModel.location_id == location_id,
                    IntegrationLocationBindingModel.capability == "FISCAL",
                    IntegrationLocationBindingModel.is_active.is_(True),
                )
            )
        else:
            valid = await self.session.scalar(
                select(TerminalBindingModel.id).where(
                    TerminalBindingModel.organization_id == context.organization_id,
                    TerminalBindingModel.connection_id == connection_id,
                    TerminalBindingModel.location_id == location_id,
                    TerminalBindingModel.register_id == register_id,
                    TerminalBindingModel.is_active.is_(True),
                )
            )
        if valid is None:
            raise FiscalRouteNotFound("Active provider binding not found")
        requested_active = bool(values.get("is_active", True))
        if requested_active:
            existing = await self.session.scalar(
                select(FiscalRouteModel.id).where(
                    FiscalRouteModel.register_id == register_id,
                    FiscalRouteModel.is_active.is_(True),
                )
            )
            if existing is not None:
                raise FiscalRouteAlreadyConfigured("Register already has an active fiscal route")
        now = datetime.now(UTC)
        value = FiscalRouteModel(
            id=uuid4(),
            organization_id=context.organization_id,
            location_id=location_id,
            register_id=register_id,
            provider_connection_id=connection_id,
            source_mode=source_mode.value,
            is_active=requested_active,
            created_at=now,
            updated_at=now,
        )
        self.session.add(value)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise FiscalRouteAlreadyConfigured(
                "Register already has an active fiscal route"
            ) from exc
        await self._audit(context, "FISCAL_ROUTE_CHANGED", "fiscal_route", value.id)
        await self.session.commit()
        return value

    async def set_route_active(
        self, context: TenantContext, route_id: UUID, active: bool
    ) -> FiscalRouteModel:
        value = await self.session.scalar(
            select(FiscalRouteModel)
            .where(
                FiscalRouteModel.organization_id == context.organization_id,
                FiscalRouteModel.id == route_id,
            )
            .with_for_update()
        )
        if value is None:
            raise FiscalRouteNotFound("Fiscal route not found")
        await self._location(context, value.location_id)
        if active:
            connection = await self.session.scalar(
                select(IntegrationConnectionModel).where(
                    IntegrationConnectionModel.organization_id == context.organization_id,
                    IntegrationConnectionModel.id == value.provider_connection_id,
                    IntegrationConnectionModel.status
                    == IntegrationConnectionStatus.ACTIVE.value,
                )
            )
            if connection is None:
                raise FiscalRouteNotFound("Active integration connection not found")
            if value.source_mode == FiscalRouteSourceMode.EXTERNAL_KKM.value:
                binding_id = await self.session.scalar(
                    select(IntegrationLocationBindingModel.id).where(
                        IntegrationLocationBindingModel.organization_id
                        == context.organization_id,
                        IntegrationLocationBindingModel.connection_id
                        == value.provider_connection_id,
                        IntegrationLocationBindingModel.location_id == value.location_id,
                        IntegrationLocationBindingModel.capability == "FISCAL",
                        IntegrationLocationBindingModel.is_active.is_(True),
                    )
                )
            else:
                binding_id = await self.session.scalar(
                    select(TerminalBindingModel.id).where(
                        TerminalBindingModel.organization_id == context.organization_id,
                        TerminalBindingModel.connection_id == value.provider_connection_id,
                        TerminalBindingModel.location_id == value.location_id,
                        TerminalBindingModel.register_id == value.register_id,
                        TerminalBindingModel.is_active.is_(True),
                    )
                )
            if binding_id is None:
                raise FiscalRouteNotFound("Active provider binding not found")
            existing = await self.session.scalar(
                select(FiscalRouteModel.id).where(
                    FiscalRouteModel.register_id == value.register_id,
                    FiscalRouteModel.id != value.id,
                    FiscalRouteModel.is_active.is_(True),
                )
            )
            if existing:
                raise FiscalRouteAlreadyConfigured("Register already has an active fiscal route")
        value.is_active = active
        value.updated_at = datetime.now(UTC)
        await self._audit(context, "FISCAL_ROUTE_CHANGED", "fiscal_route", value.id)
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise FiscalRouteAlreadyConfigured(
                "Register already has an active fiscal route"
            ) from exc
        return value

    async def go_live_readiness(
        self,
        context: TenantContext,
        location_id: UUID,
        *,
        live_transport_enabled: bool,
        real_provider_codes: frozenset[str],
        nkt_configured: bool,
    ) -> dict[str, object]:
        await self._location(context, location_id)
        tax = bool(
            await self.session.scalar(
                select(FiscalTaxProfileModel.id).where(
                    FiscalTaxProfileModel.organization_id == context.organization_id,
                    FiscalTaxProfileModel.effective_to.is_(None),
                )
            )
        )
        variant_total = int(
            await self.session.scalar(
                select(func.count(ProductVariantModel.id)).where(
                    ProductVariantModel.organization_id == context.organization_id,
                    ProductVariantModel.status == "ACTIVE",
                )
            )
            or 0
        )
        nkt_total = int(
            await self.session.scalar(
                select(func.count(FiscalVariantProfileModel.id))
                .join(
                    ProductVariantModel,
                    ProductVariantModel.id == FiscalVariantProfileModel.product_variant_id,
                )
                .where(
                    FiscalVariantProfileModel.organization_id == context.organization_id,
                    ProductVariantModel.status == "ACTIVE",
                    FiscalVariantProfileModel.nkt_verified_at.is_not(None),
                )
            )
            or 0
        )
        route_row = (
            await self.session.execute(
                select(
                    FiscalRouteModel,
                    IntegrationConnectionModel.provider_code,
                    IntegrationConnectionModel.status,
                )
                .join(
                    IntegrationConnectionModel,
                    IntegrationConnectionModel.id == FiscalRouteModel.provider_connection_id,
                )
                .where(
                    FiscalRouteModel.organization_id == context.organization_id,
                    FiscalRouteModel.location_id == location_id,
                    FiscalRouteModel.is_active.is_(True),
                )
                .limit(1)
            )
        ).first()
        provider_ok = bool(
            route_row
            and route_row[1] in real_provider_codes
            and route_row[2] == IntegrationConnectionStatus.ACTIVE.value
        )
        cashbox = False
        if route_row and route_row[0].source_mode == FiscalRouteSourceMode.EXTERNAL_KKM.value:
            cashbox = bool(
                await self.session.scalar(
                    select(IntegrationLocationBindingModel.id).where(
                        IntegrationLocationBindingModel.connection_id
                        == route_row[0].provider_connection_id,
                        IntegrationLocationBindingModel.location_id == location_id,
                        IntegrationLocationBindingModel.capability == "FISCAL",
                        IntegrationLocationBindingModel.is_active.is_(True),
                        IntegrationLocationBindingModel.external_location_id.is_not(None),
                    )
                )
            )
        checks = {
            "tax_profile": tax,
            "fiscal_variants": variant_total > 0 and nkt_total == variant_total,
            "nkt": nkt_configured and variant_total > 0 and nkt_total == variant_total,
            "fiscal_connection": provider_ok,
            "cashbox": cashbox,
            "route": route_row is not None,
            "live_transport": live_transport_enabled and provider_ok,
        }
        return {"ready": all(checks.values()), "checks": checks}

    async def resolve_fiscal_connection(
        self,
        organization_id: UUID,
        source_type: str,
        source_id: UUID,
    ):
        if source_type == "REFUND":
            refund = await self.session.execute(
                select(RefundModel.location_id, RefundModel.payment_id).where(
                    RefundModel.organization_id == organization_id,
                    RefundModel.id == source_id,
                )
            )
            row = refund.first()
            if row is None:
                return None
            connection = await self.session.scalar(
                select(IntegrationConnectionModel)
                .join(
                    FiscalReceiptModel,
                    FiscalReceiptModel.connection_id == IntegrationConnectionModel.id,
                )
                .where(
                    FiscalReceiptModel.organization_id == organization_id,
                    FiscalReceiptModel.source_type == "SALE",
                    FiscalReceiptModel.source_id == row[1],
                )
            )
            if connection is None:
                raise FiscalReceiptNotFound("Original fiscal sale receipt not found")
            return to_connection(connection), row[0]

        row = (
            await self.session.execute(
                select(PaymentModel.location_id, RegisterShiftModel.register_id)
                .join(SalesOrderModel, SalesOrderModel.id == PaymentModel.order_id)
                .join(RegisterShiftModel, RegisterShiftModel.id == SalesOrderModel.shift_id)
                .where(
                    PaymentModel.organization_id == organization_id,
                    PaymentModel.id == source_id,
                )
            )
        ).first()
        if row is None:
            return None
        connection = await self.session.scalar(
            select(IntegrationConnectionModel)
            .join(
                FiscalRouteModel,
                FiscalRouteModel.provider_connection_id == IntegrationConnectionModel.id,
            )
            .where(
                FiscalRouteModel.organization_id == organization_id,
                FiscalRouteModel.location_id == row[0],
                FiscalRouteModel.register_id == row[1],
                FiscalRouteModel.is_active.is_(True),
                IntegrationConnectionModel.status
                == IntegrationConnectionStatus.ACTIVE.value,
            )
        )
        return (to_connection(connection), row[0]) if connection else None

    async def ensure_pending_receipt(
        self,
        *,
        organization_id: UUID,
        location_id: UUID,
        connection_id: UUID,
        provider_code: str,
        source_type: str,
        source_id: UUID,
    ) -> FiscalReceiptModel:
        existing = await self.session.scalar(
            select(FiscalReceiptModel).where(
                FiscalReceiptModel.organization_id == organization_id,
                FiscalReceiptModel.source_type == source_type,
                FiscalReceiptModel.source_id == source_id,
            )
        )
        if existing:
            return existing
        now = datetime.now(UTC)
        value = FiscalReceiptModel(
            id=uuid4(),
            organization_id=organization_id,
            location_id=location_id,
            connection_id=connection_id,
            source_type=source_type,
            source_id=source_id,
            provider_code=provider_code,
            status=FiscalReceiptStatus.PENDING.value,
            provider_correlation_id=(
                f"beanly:{organization_id}:{source_type.casefold()}:{source_id}"
            ),
            created_at=now,
            updated_at=now,
        )
        try:
            async with self.session.begin_nested():
                self.session.add(value)
                await self.session.flush()
        except IntegrityError:
            existing = await self.session.scalar(
                select(FiscalReceiptModel).where(
                    FiscalReceiptModel.organization_id == organization_id,
                    FiscalReceiptModel.source_type == source_type,
                    FiscalReceiptModel.source_id == source_id,
                )
            )
            if existing is None:
                raise
            return existing
        metrics.fiscal_receipts.add(1, {"provider.code": provider_code})
        return value

    async def mark_receipt_processing(
        self, organization_id: UUID, source_type: str, source_id: UUID
    ) -> None:
        value = await self._source_receipt(organization_id, source_type, source_id)
        if value.status in {"SUCCEEDED", "UNKNOWN", "DEAD"}:
            raise FiscalReceiptStateConflict("Terminal fiscal receipt cannot be processed again")
        value.status = FiscalReceiptStatus.PROCESSING.value
        value.updated_at = datetime.now(UTC)
        await self.session.flush()

    async def mark_receipt_succeeded(
        self,
        organization_id: UUID,
        source_type: str,
        source_id: UUID,
        result: FiscalReceiptResult,
    ) -> None:
        value = await self._source_receipt(organization_id, source_type, source_id)
        if value.status == FiscalReceiptStatus.SUCCEEDED.value:
            return
        now = datetime.now(UTC)
        _success(value, result, now)
        await self.session.flush()
        metrics.fiscal_receipt_success.add(1, {"provider.code": value.provider_code})

    async def mark_receipt_failed(
        self,
        organization_id: UUID,
        source_type: str,
        source_id: UUID,
        error: BaseException,
        *,
        temporary: bool,
        unknown: bool,
    ) -> None:
        value = await self._source_receipt(organization_id, source_type, source_id)
        if value.status == FiscalReceiptStatus.SUCCEEDED.value:
            return
        value.status = (
            FiscalReceiptStatus.UNKNOWN.value
            if unknown
            else (
                FiscalReceiptStatus.RETRYING.value if temporary else FiscalReceiptStatus.DEAD.value
            )
        )
        value.last_error_code = str(getattr(error, "code", type(error).__name__))[:100]
        value.last_error_message = str(getattr(error, "public_message", "Fiscalization failed"))[
            :1000
        ]
        value.updated_at = datetime.now(UTC)
        await self.session.flush()
        if unknown:
            metrics.fiscal_receipt_unknown.add(1, {"provider.code": value.provider_code})
        else:
            metrics.fiscal_receipt_failed.add(1, {"provider.code": value.provider_code})

    async def _source_receipt(
        self, organization_id: UUID, source_type: str, source_id: UUID
    ) -> FiscalReceiptModel:
        value = await self.session.scalar(
            select(FiscalReceiptModel)
            .where(
                FiscalReceiptModel.organization_id == organization_id,
                FiscalReceiptModel.source_type == source_type,
                FiscalReceiptModel.source_id == source_id,
            )
            .with_for_update()
        )
        if value is None:
            raise FiscalReceiptNotFound("Fiscal receipt not found")
        return value

    async def _locked_receipt(self, context: TenantContext, receipt_id: UUID) -> FiscalReceiptModel:
        value = await self.session.scalar(
            select(FiscalReceiptModel)
            .where(
                FiscalReceiptModel.organization_id == context.organization_id,
                FiscalReceiptModel.id == receipt_id,
            )
            .with_for_update()
        )
        if value is None:
            raise FiscalReceiptNotFound("Fiscal receipt not found")
        await self._location(context, value.location_id)
        return value

    async def _locations(
        self, context: TenantContext, location_id: UUID | None
    ) -> tuple[UUID, ...]:
        if location_id is not None:
            await self._location(context, location_id)
            return (location_id,)
        values = await self.organizations.list_locations(
            ListLocationsQuery(context.user_id, context.organization_id)
        )
        return tuple(value.id for value in values)

    async def _location(self, context: TenantContext, location_id: UUID) -> LocationModel:
        value = await self.session.scalar(
            select(LocationModel).where(
                LocationModel.organization_id == context.organization_id,
                LocationModel.id == location_id,
            )
        )
        if value is None:
            raise FiscalRouteNotFound("Location not found")
        try:
            await self.organizations.ensure_location_access(context, location_id)
        except OrganizationAccessDenied as exc:
            raise FiscalRouteNotFound("Location not found") from exc
        return value

    async def _audit(
        self, context: TenantContext, action: str, resource_type: str, resource_id: UUID
    ) -> None:
        if self.audit:
            await self.audit.record(
                action=action,
                resource_type=resource_type,
                organization_id=context.organization_id,
                actor_user_id=context.user_id,
                resource_id=resource_id,
            )


def _success(value: FiscalReceiptModel, result: FiscalReceiptResult, now: datetime) -> None:
    value.status = FiscalReceiptStatus.SUCCEEDED.value
    value.external_receipt_id = result.external_receipt_id
    value.receipt_number = result.receipt_number
    value.receipt_url = result.receipt_url
    value.provider_request_id = result.provider_request_id
    value.fiscalized_at = now
    value.last_error_code = None
    value.last_error_message = None
    value.updated_at = now


def _utc(value: datetime) -> datetime:
    return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
