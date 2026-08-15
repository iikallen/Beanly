from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from beanly.core.security.audit import SecurityAuditRecorder
from beanly.modules.fiscal.domain.enums import FiscalComplianceStatus
from beanly.modules.fiscal.domain.exceptions import (
    FiscalVariantNotFound,
    InvalidFiscalVariantProfile,
    InvalidTaxProfile,
    TaxProfileNotFound,
)
from beanly.modules.fiscal.domain.tax import normalize_vat_rate, vat_minor
from beanly.modules.fiscal.infrastructure.db.models import (
    FiscalSaleSnapshotLineModel,
    FiscalSaleSnapshotModel,
    FiscalTaxProfileModel,
    FiscalVariantProfileModel,
)
from beanly.modules.menu.infrastructure.db.models import ProductModel, ProductVariantModel
from beanly.modules.offline_pos.infrastructure.db.models import (
    PosCatalogSnapshotModel,
    PosOfflineSessionModel,
)
from beanly.modules.organizations.domain.entities import TenantContext
from beanly.modules.organizations.infrastructure.db.models import LocationModel, OrganizationModel
from beanly.modules.payments.infrastructure.db.models import PaymentModel
from beanly.modules.sales.infrastructure.db.models import SalesOrderItemModel, SalesOrderModel


class SqlAlchemyFiscalOperations:
    def __init__(self, session: AsyncSession, audit: SecurityAuditRecorder | None = None) -> None:
        self.session = session
        self.audit = audit

    async def get_tax_profile(
        self, organization_id: UUID, *, effective_on: date | None = None
    ) -> FiscalTaxProfileModel:
        day = effective_on or datetime.now(UTC).date()
        value = await self.session.scalar(
            select(FiscalTaxProfileModel)
            .where(
                FiscalTaxProfileModel.organization_id == organization_id,
                FiscalTaxProfileModel.effective_from <= day,
                (FiscalTaxProfileModel.effective_to.is_(None))
                | (FiscalTaxProfileModel.effective_to >= day),
            )
            .order_by(FiscalTaxProfileModel.effective_from.desc())
        )
        if value is None:
            raise TaxProfileNotFound("Tax profile not found")
        return value

    async def set_tax_profile(
        self,
        context: TenantContext,
        *,
        country_code: str,
        tax_regime_code: str,
        vat_registered: bool,
        default_vat_rate: Decimal | None,
        effective_from: date,
    ) -> FiscalTaxProfileModel:
        country = country_code.strip().upper()
        regime = tax_regime_code.strip()
        rate = _rate(default_vat_rate)
        if len(country) != 2 or not regime or (vat_registered and (rate is None or rate <= 0)):
            raise InvalidTaxProfile("Invalid tax profile")
        if not vat_registered:
            rate = None
        current = await self.session.scalar(
            select(OrganizationModel)
            .where(OrganizationModel.id == context.organization_id)
            .with_for_update()
        )
        if current is None:
            raise InvalidTaxProfile("Organization not found")
        current = await self.session.scalar(
            select(FiscalTaxProfileModel)
            .where(
                FiscalTaxProfileModel.organization_id == context.organization_id,
                FiscalTaxProfileModel.effective_to.is_(None),
            )
            .with_for_update()
        )
        if current is not None:
            if effective_from <= current.effective_from:
                raise InvalidTaxProfile("New profile must start after the current profile")
            current.effective_to = effective_from - timedelta(days=1)
        now = datetime.now(UTC)
        value = FiscalTaxProfileModel(
            id=uuid4(),
            organization_id=context.organization_id,
            country_code=country,
            tax_regime_code=regime,
            vat_registered=vat_registered,
            default_vat_rate=rate,
            effective_from=effective_from,
            effective_to=None,
            created_by=context.user_id,
            created_at=now,
        )
        self.session.add(value)
        await self.session.flush()
        if self.audit:
            await self.audit.record(
                action="TAX_PROFILE_CHANGED",
                resource_type="fiscal_tax_profile",
                organization_id=context.organization_id,
                actor_user_id=context.user_id,
                resource_id=value.id,
            )
        await self.session.commit()
        return value

    async def get_variant(
        self, organization_id: UUID, variant_id: UUID
    ) -> FiscalVariantProfileModel:
        await self._variant(organization_id, variant_id)
        value = await self.session.scalar(
            select(FiscalVariantProfileModel).where(
                FiscalVariantProfileModel.organization_id == organization_id,
                FiscalVariantProfileModel.product_variant_id == variant_id,
            )
        )
        if value is None:
            raise FiscalVariantNotFound("Fiscal variant profile not found")
        return value

    async def set_variant(
        self,
        context: TenantContext,
        variant_id: UUID,
        *,
        fiscal_name: str,
        nkt_code: str | None,
        nkt_code_type: str | None,
        fiscal_unit_code: str,
        vat_rate_override: Decimal | None,
        requires_marking: bool,
    ) -> FiscalVariantProfileModel:
        await self._variant(context.organization_id, variant_id)
        name = fiscal_name.strip()
        unit = fiscal_unit_code.strip()
        code = nkt_code.strip() if nkt_code else None
        code_type = nkt_code_type.strip() if nkt_code_type else None
        rate = _rate(vat_rate_override)
        if (
            not name
            or not unit
            or (nkt_code is not None and not code)
            or (rate is not None and rate < 0)
        ):
            raise InvalidFiscalVariantProfile("Invalid fiscal variant profile")
        value = await self.session.scalar(
            select(FiscalVariantProfileModel)
            .where(
                FiscalVariantProfileModel.organization_id == context.organization_id,
                FiscalVariantProfileModel.product_variant_id == variant_id,
            )
            .with_for_update()
        )
        now = datetime.now(UTC)
        if value is None:
            value = FiscalVariantProfileModel(
                id=uuid4(),
                organization_id=context.organization_id,
                product_variant_id=variant_id,
                fiscal_name=name,
                nkt_code=code,
                nkt_code_type=code_type,
                fiscal_unit_code=unit,
                vat_rate_override=rate,
                requires_marking=requires_marking,
                updated_at=now,
            )
            self.session.add(value)
        else:
            if value.nkt_code != code or value.nkt_code_type != code_type:
                value.nkt_verified_at = None
                value.nkt_external_product_id = None
            value.fiscal_name, value.nkt_code, value.nkt_code_type = name, code, code_type
            value.fiscal_unit_code, value.vat_rate_override = unit, rate
            value.requires_marking, value.updated_at = requires_marking, now
        await self.session.flush()
        if self.audit:
            await self.audit.record(
                action="FISCAL_VARIANT_PROFILE_CHANGED",
                resource_type="fiscal_variant_profile",
                organization_id=context.organization_id,
                actor_user_id=context.user_id,
                resource_id=value.id,
                metadata={"variant_id": str(variant_id)},
            )
        await self.session.commit()
        return value

    async def link_variant_nkt(
        self,
        context: TenantContext,
        variant_id: UUID,
        *,
        ntin: str,
        external_product_id: str,
        verified_at: datetime,
    ) -> FiscalVariantProfileModel:
        await self._variant(context.organization_id, variant_id)
        value = await self.session.scalar(
            select(FiscalVariantProfileModel)
            .where(
                FiscalVariantProfileModel.organization_id == context.organization_id,
                FiscalVariantProfileModel.product_variant_id == variant_id,
            )
            .with_for_update()
        )
        if value is None:
            raise FiscalVariantNotFound("Fiscal variant profile not found")
        value.nkt_code = ntin
        value.nkt_code_type = "NTIN"
        value.nkt_external_product_id = external_product_id
        value.nkt_verified_at = verified_at
        value.updated_at = verified_at
        await self.session.flush()
        return value

    async def readiness(self, organization_id: UUID) -> dict[str, object]:
        try:
            await self.get_tax_profile(organization_id)
            tax_status = "COMPLETE"
        except TaxProfileNotFound:
            tax_status = "MISSING"
        rows = await self.session.execute(
            select(ProductVariantModel.id, ProductModel.name, ProductVariantModel.name)
            .join(ProductModel, ProductModel.id == ProductVariantModel.product_id)
            .outerjoin(
                FiscalVariantProfileModel,
                (FiscalVariantProfileModel.product_variant_id == ProductVariantModel.id)
                & (FiscalVariantProfileModel.organization_id == organization_id),
            )
            .where(
                ProductVariantModel.organization_id == organization_id,
                ProductVariantModel.status == "ACTIVE",
                (FiscalVariantProfileModel.id.is_(None))
                | (FiscalVariantProfileModel.nkt_code.is_(None))
                | (FiscalVariantProfileModel.nkt_verified_at.is_(None)),
            )
            .order_by(ProductModel.name, ProductVariantModel.name)
        )
        missing = [
            {
                "variant_id": variant_id,
                "name": f"{product} {variant}".strip(),
                "reason": "NKT_MISSING",
            }
            for variant_id, product, variant in rows
        ]
        total = int(
            await self.session.scalar(
                select(__import__("sqlalchemy").func.count(ProductVariantModel.id)).where(
                    ProductVariantModel.organization_id == organization_id,
                    ProductVariantModel.status == "ACTIVE",
                )
            )
            or 0
        )
        mapped = total - len(missing)
        percent = 100 if not total else int(mapped * 100 / total)
        location_count = int(
            await self.session.scalar(
                select(__import__("sqlalchemy").func.count(LocationModel.id)).where(
                    LocationModel.organization_id == organization_id
                )
            )
            or 0
        )
        location_status = "COMPLETE" if location_count else "MISSING"
        ready = tax_status == "COMPLETE" and location_status == "COMPLETE" and not missing
        return {
            "ready": ready,
            "readiness_percent": percent,
            "tax_profile": tax_status,
            "location": location_status,
            "unmapped_variants": missing,
        }

    async def create_sale_snapshot(
        self, organization_id: UUID, payment_id: UUID
    ) -> FiscalSaleSnapshotModel:
        existing = await self.session.scalar(
            select(FiscalSaleSnapshotModel)
            .options(selectinload(FiscalSaleSnapshotModel.lines))
            .where(
                FiscalSaleSnapshotModel.organization_id == organization_id,
                FiscalSaleSnapshotModel.payment_id == payment_id,
            )
        )
        if existing is not None:
            return existing
        payment = await self.session.scalar(
            select(PaymentModel)
            .where(PaymentModel.organization_id == organization_id, PaymentModel.id == payment_id)
            .with_for_update()
        )
        if payment is None:
            raise TaxProfileNotFound("Payment not found for fiscal snapshot")
        existing = await self.session.scalar(
            select(FiscalSaleSnapshotModel)
            .options(selectinload(FiscalSaleSnapshotModel.lines))
            .where(
                FiscalSaleSnapshotModel.organization_id == organization_id,
                FiscalSaleSnapshotModel.payment_id == payment_id,
            )
        )
        if existing is not None:
            return existing
        order = await self.session.scalar(
            select(SalesOrderModel)
            .options(selectinload(SalesOrderModel.items))
            .where(
                SalesOrderModel.organization_id == organization_id,
                SalesOrderModel.id == payment.order_id,
                SalesOrderModel.status == "PAID",
            )
        )
        if order is None:
            raise TaxProfileNotFound("Paid order not found for fiscal snapshot")
        timezone = await self.session.scalar(
            select(LocationModel.timezone).where(
                LocationModel.organization_id == organization_id,
                LocationModel.id == order.location_id,
            )
        )
        if timezone is None:
            raise TaxProfileNotFound("Payment location not found")
        effective_date = payment.completed_at.astimezone(ZoneInfo(timezone)).date()
        try:
            tax = await self.get_tax_profile(organization_id, effective_on=effective_date)
        except TaxProfileNotFound:
            tax = None
        profiles = {
            value.product_variant_id: value
            for value in await self.session.scalars(
                select(FiscalVariantProfileModel).where(
                    FiscalVariantProfileModel.organization_id == organization_id,
                    FiscalVariantProfileModel.product_variant_id.in_(
                        [item.product_variant_id for item in order.items]
                    ),
                )
            )
        }
        offline_fiscal: dict[str, object] = {}
        if order.offline_session_id is not None:
            payload = await self.session.scalar(
                select(PosCatalogSnapshotModel.private_payload)
                .join(
                    PosOfflineSessionModel,
                    PosOfflineSessionModel.catalog_snapshot_id == PosCatalogSnapshotModel.id,
                )
                .where(
                    PosOfflineSessionModel.organization_id == organization_id,
                    PosOfflineSessionModel.id == order.offline_session_id,
                )
            )
            variants = payload.get("variants") if isinstance(payload, dict) else None
            offline_fiscal = variants if isinstance(variants, dict) else {}
            catalog_tax = payload.get("tax_profiles") if isinstance(payload, dict) else None
            tax = None
            if isinstance(catalog_tax, list):
                for item in catalog_tax:
                    if not isinstance(item, dict):
                        continue
                    start = date.fromisoformat(str(item["effective_from"]))
                    end = (
                        date.fromisoformat(str(item["effective_to"]))
                        if item.get("effective_to")
                        else None
                    )
                    if start <= effective_date and (end is None or end >= effective_date):
                        tax = SimpleNamespace(
                            id=UUID(str(item["id"])),
                            vat_registered=bool(item["vat_registered"]),
                            default_vat_rate=(
                                Decimal(str(item["default_vat_rate"]))
                                if item.get("default_vat_rate") is not None
                                else None
                            ),
                        )
                        break
        now, snapshot_id = datetime.now(UTC), uuid4()
        lines: list[FiscalSaleSnapshotLineModel] = []
        # Delivery fee has no configured NKT/VAT profile yet, so keep the receipt
        # reconcilable but explicitly incomplete instead of claiming tax completeness.
        complete = tax is not None and order.fulfillment_fee_minor == 0
        for item in order.items:
            profile = profiles.get(item.product_variant_id)
            catalog_variant = offline_fiscal.get(str(item.product_variant_id))
            catalog_fiscal = (
                catalog_variant.get("fiscal") if isinstance(catalog_variant, dict) else None
            )
            use_catalog = isinstance(catalog_fiscal, dict)
            catalog_rate = catalog_fiscal.get("vat_rate_override") if use_catalog else None
            rate = (
                Decimal(str(catalog_rate))
                if catalog_rate is not None
                else profile.vat_rate_override
                if profile and profile.vat_rate_override is not None and not offline_fiscal
                else tax.default_vat_rate
                if tax and tax.vat_registered
                else None
            )
            net_total = item.net_line_total_minor
            vat = vat_minor(net_total, rate)
            fiscal_name = (
                str(catalog_fiscal["fiscal_name"])
                if use_catalog
                else profile.fiscal_name
                if profile
                else _item_name(item)
            )
            nkt_code = (
                str(catalog_fiscal["nkt_code"])
                if use_catalog and catalog_fiscal.get("nkt_code") is not None
                else profile.nkt_code
                if profile and not offline_fiscal
                else None
            )
            requires_marking = (
                bool(catalog_fiscal.get("requires_marking", False))
                if use_catalog
                else profile.requires_marking
                if profile and not offline_fiscal
                else False
            )
            complete = complete and bool(nkt_code) and not requires_marking
            lines.append(
                FiscalSaleSnapshotLineModel(
                    id=uuid4(),
                    snapshot_id=snapshot_id,
                    order_item_id=item.id,
                    product_variant_id=item.product_variant_id,
                    fiscal_name=fiscal_name,
                    nkt_code=nkt_code,
                    nkt_code_type=(
                        str(catalog_fiscal["nkt_code_type"])
                        if use_catalog and catalog_fiscal.get("nkt_code_type") is not None
                        else profile.nkt_code_type
                        if profile and not offline_fiscal
                        else None
                    ),
                    unit_code=(
                        str(catalog_fiscal.get("unit_code", "pcs"))
                        if use_catalog
                        else profile.fiscal_unit_code
                        if profile and not offline_fiscal
                        else "pcs"
                    ),
                    quantity=item.quantity,
                    unit_price_minor=item.unit_price_minor,
                    gross_total_minor=item.line_total_minor,
                    discount_minor=item.discount_amount_minor,
                    total_minor=net_total,
                    vat_rate=rate,
                    vat_amount_minor=vat,
                    marking_codes=[],
                    created_at=now,
                )
            )
        snapshot = FiscalSaleSnapshotModel(
            id=snapshot_id,
            organization_id=organization_id,
            location_id=order.location_id,
            order_id=order.id,
            payment_id=payment.id,
            tax_profile_id=tax.id if tax else None,
            occurred_at=payment.completed_at,
            currency_code=payment.currency_code,
            total_minor=payment.amount_minor,
            discount_total_minor=order.discount_total_minor,
            vat_total_minor=sum(line.vat_amount_minor for line in lines),
            compliance_status=(
                FiscalComplianceStatus.COMPLETE.value
                if complete
                else FiscalComplianceStatus.INCOMPLETE.value
            ),
            created_at=now,
            lines=lines,
        )
        self.session.add(snapshot)
        await self.session.flush()
        return snapshot

    async def _variant(self, organization_id: UUID, variant_id: UUID) -> ProductVariantModel:
        value = await self.session.scalar(
            select(ProductVariantModel).where(
                ProductVariantModel.organization_id == organization_id,
                ProductVariantModel.id == variant_id,
            )
        )
        if value is None:
            raise FiscalVariantNotFound("Product variant not found")
        return value


def _rate(value: Decimal | None) -> Decimal | None:
    try:
        return normalize_vat_rate(value)
    except ValueError as exc:
        raise InvalidTaxProfile(str(exc)) from exc


def _item_name(item: SalesOrderItemModel) -> str:
    return f"{item.product_name} - {item.variant_name}" if item.variant_name else item.product_name
