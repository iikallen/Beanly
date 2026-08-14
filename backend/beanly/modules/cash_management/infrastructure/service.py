from __future__ import annotations

import json
from datetime import UTC, date, datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from beanly.core.config.settings import Settings
from beanly.core.events.outbox.repositories import OutboxRepository
from beanly.core.events.outbox.writer import OutboxEventSink
from beanly.core.observability import metrics
from beanly.core.security.audit import SecurityAuditRecorder
from beanly.modules.cash_management.application.ports import (
    FiscalShiftClosePort,
    FiscalShiftReconciliation,
    UnavailableFiscalShiftClosePort,
)
from beanly.modules.cash_management.domain.enums import (
    CashDrawerStatus,
    CashMovementKind,
    FiscalShiftStatus,
)
from beanly.modules.cash_management.domain.events import CashDrawerClosed
from beanly.modules.cash_management.domain.exceptions import (
    CashCloseIdempotencyConflict,
    CashDrawerAlreadyClosed,
    CashDrawerNotFound,
    CashDrawerNotOpen,
    CashMovementIdempotencyConflict,
    CashMovementInvalid,
    CashVarianceApprovalRequired,
    FiscalShiftCloseFailed,
    FiscalShiftReconciliationRequired,
    ShiftCloseSyncPending,
)
from beanly.modules.cash_management.infrastructure.db.models import (
    CashDrawerCloseSnapshotModel,
    CashDrawerFiscalStateModel,
    CashDrawerMovementModel,
    CashDrawerSessionModel,
)
from beanly.modules.fiscal.infrastructure.db.models import FiscalRouteModel
from beanly.modules.identity.infrastructure.db.models import UserModel
from beanly.modules.integrations.infrastructure.crypto import FernetSecretCipher
from beanly.modules.integrations.infrastructure.db.models import (
    IntegrationConnectionModel,
    IntegrationJobModel,
)
from beanly.modules.integrations.infrastructure.providers import build_provider_registry
from beanly.modules.offline_pos.infrastructure.db.models import (
    PosOfflineOrderSyncModel,
    PosOfflineSessionModel,
)
from beanly.modules.organizations.application.services.organization_service import (
    OrganizationService,
)
from beanly.modules.organizations.domain.entities import TenantContext
from beanly.modules.organizations.infrastructure.db.models import (
    LocationModel,
    MembershipLocationModel,
    OrganizationModel,
)
from beanly.modules.payments.infrastructure.db.models import (
    ExternalPaymentAttemptModel,
    PaymentLineModel,
    PaymentModel,
)
from beanly.modules.refunds.infrastructure.db.models import RefundModel, RefundPaymentLineModel
from beanly.modules.sales.domain.entities import RegisterShift
from beanly.modules.sales.infrastructure.db.models import (
    PosRegisterModel,
    RegisterShiftModel,
    SalesOrderModel,
)

MAX_BIGINT = 9_223_372_036_854_775_807


class IntegrationFiscalShiftCloseGateway:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.registry = build_provider_registry(settings)
        self.cipher = FernetSecretCipher(settings.integration_encryption_key_list)

    async def reconcile(self, query: FiscalShiftReconciliation) -> bool | None:
        connection = await self.session.scalar(
            select(IntegrationConnectionModel).where(
                IntegrationConnectionModel.id == query.connection_id,
                IntegrationConnectionModel.organization_id == query.organization_id,
            )
        )
        if connection is None or connection.credentials_ciphertext is None:
            return None
        credentials = json.loads(self.cipher.decrypt(connection.credentials_ciphertext))
        result = await self.registry.adapter(connection.provider_code).lookup_operation(
            query.external_id or str(query.job_id), credentials=credentials
        )
        return True if result is not None else None


class CashDrawerService:
    def __init__(
        self,
        session: AsyncSession,
        organizations: OrganizationService,
        fiscal_close: FiscalShiftClosePort | None = None,
    ) -> None:
        self.session = session
        self.organizations = organizations
        self.events = OutboxEventSink(OutboxRepository(session))
        self.audit = SecurityAuditRecorder(session)
        self.fiscal_close = fiscal_close or UnavailableFiscalShiftClosePort()

    async def existing_shift_id(self, context: TenantContext, client_open_id: UUID) -> UUID | None:
        return await self.session.scalar(
            select(CashDrawerSessionModel.shift_id).where(
                CashDrawerSessionModel.organization_id == context.organization_id,
                CashDrawerSessionModel.client_open_id == client_open_id,
            )
        )

    async def open_for_shift(
        self,
        context: TenantContext,
        shift: RegisterShift,
        starting_cash_minor: int,
        client_open_id: UUID,
    ) -> CashDrawerSessionModel:
        _money(starting_cash_minor, allow_zero=True)
        currency = await self.session.scalar(
            select(OrganizationModel.currency_code).where(
                OrganizationModel.id == context.organization_id
            )
        )
        if currency is None:
            raise CashMovementInvalid("Organization currency not found")
        existing = await self.session.scalar(
            select(CashDrawerSessionModel).where(
                CashDrawerSessionModel.organization_id == context.organization_id,
                CashDrawerSessionModel.client_open_id == client_open_id,
            )
        )
        if existing:
            if existing.shift_id != shift.id or existing.starting_cash_minor != starting_cash_minor:
                raise CashMovementIdempotencyConflict("Opening id already has another payload")
            return existing
        now = datetime.now(UTC)
        drawer = CashDrawerSessionModel(
            id=uuid4(),
            organization_id=context.organization_id,
            location_id=shift.location_id,
            register_id=shift.register_id,
            shift_id=shift.id,
            currency_code=currency,
            status=CashDrawerStatus.OPEN.value,
            starting_cash_minor=starting_cash_minor,
            opened_by_user_id=context.user_id,
            opened_at=now,
            client_open_id=client_open_id,
            created_at=now,
            updated_at=now,
            version=1,
        )
        self.session.add(drawer)
        await self.session.flush()
        self.session.add(
            CashDrawerMovementModel(
                id=uuid4(),
                organization_id=context.organization_id,
                drawer_session_id=drawer.id,
                kind=CashMovementKind.OPENING_FLOAT.value,
                amount_minor=starting_cash_minor,
                source_type="SHIFT_OPEN",
                source_id=shift.id,
                source_line_id=drawer.id,
                client_movement_id=None,
                reason="Opening float",
                note=None,
                created_by_user_id=context.user_id,
                occurred_at=now,
                recorded_at=now,
            )
        )
        await self.session.flush()
        return drawer

    async def current(
        self, context: TenantContext, register_id: UUID
    ) -> CashDrawerSessionModel | None:
        register = await self.session.scalar(
            select(PosRegisterModel).where(
                PosRegisterModel.organization_id == context.organization_id,
                PosRegisterModel.id == register_id,
            )
        )
        if register is None:
            raise CashDrawerNotFound("Register not found")
        await self.organizations.ensure_location_access(context, register.location_id)
        return await self.session.scalar(
            select(CashDrawerSessionModel).where(
                CashDrawerSessionModel.organization_id == context.organization_id,
                CashDrawerSessionModel.register_id == register_id,
                CashDrawerSessionModel.status.in_(("OPEN", "CLOSING")),
            )
        )

    async def get(
        self, context: TenantContext, drawer_id: UUID, *, lock: bool = False
    ) -> CashDrawerSessionModel:
        statement = select(CashDrawerSessionModel).where(
            CashDrawerSessionModel.organization_id == context.organization_id,
            CashDrawerSessionModel.id == drawer_id,
        )
        if lock:
            statement = statement.with_for_update()
        drawer = await self.session.scalar(statement)
        if drawer is None:
            raise CashDrawerNotFound("Cash drawer not found")
        await self.organizations.ensure_location_access(context, drawer.location_id)
        return drawer

    async def movement(
        self,
        context: TenantContext,
        drawer_id: UUID,
        kind: CashMovementKind,
        client_movement_id: UUID,
        amount_minor: int,
        reason: str,
        note: str | None,
    ) -> CashDrawerMovementModel:
        _money(amount_minor)
        reason = reason.strip()
        if not reason or (kind is CashMovementKind.PAY_OUT and not reason):
            raise CashMovementInvalid("Reason is required")
        try:
            drawer = await self.get(context, drawer_id, lock=True)
            existing = await self.session.scalar(
                select(CashDrawerMovementModel).where(
                    CashDrawerMovementModel.organization_id == context.organization_id,
                    CashDrawerMovementModel.client_movement_id == client_movement_id,
                )
            )
            signed = amount_minor if kind is CashMovementKind.PAY_IN else -amount_minor
            if existing:
                if (
                    existing.drawer_session_id != drawer_id
                    or existing.kind != kind.value
                    or existing.amount_minor != signed
                    or existing.reason != reason
                    or existing.note != note
                ):
                    raise CashMovementIdempotencyConflict("Movement id already has another payload")
                return existing
            if drawer.status != CashDrawerStatus.OPEN.value:
                raise CashDrawerNotOpen("Cash drawer is not OPEN")
            now = datetime.now(UTC)
            value = CashDrawerMovementModel(
                id=uuid4(),
                organization_id=context.organization_id,
                drawer_session_id=drawer.id,
                kind=kind.value,
                amount_minor=signed,
                source_type="MANUAL",
                source_id=drawer.id,
                source_line_id=client_movement_id,
                client_movement_id=client_movement_id,
                reason=reason,
                note=note.strip() if note and note.strip() else None,
                created_by_user_id=context.user_id,
                occurred_at=now,
                recorded_at=now,
            )
            self.session.add(value)
            drawer.version += 1
            drawer.updated_at = now
            await self.audit.record(
                action="CASH_PAY_IN" if kind is CashMovementKind.PAY_IN else "CASH_PAY_OUT",
                resource_type="cash_drawer",
                organization_id=context.organization_id,
                actor_user_id=context.user_id,
                resource_id=drawer.id,
                metadata={"movement_id": str(value.id), "amount_minor": abs(signed)},
            )
            await self.session.commit()
            metric = metrics.cash_pay_in_minor if signed > 0 else metrics.cash_pay_out_minor
            metric.add(abs(signed), {"organization.id": str(context.organization_id)})
            return value
        except Exception:
            await self.session.rollback()
            raise

    async def summary(self, context: TenantContext, drawer_id: UUID) -> dict[str, object]:
        drawer = await self.get(context, drawer_id)
        return await self._summary(drawer)

    async def close(
        self,
        context: TenantContext,
        drawer_id: UUID,
        client_close_id: UUID,
        actual_cash_minor: int,
        note: str | None,
        pending_offline_operations: int = 0,
    ) -> dict[str, object]:
        _money(actual_cash_minor, allow_zero=True)
        if pending_offline_operations:
            raise ShiftCloseSyncPending("Offline operations are still pending")
        try:
            drawer = await self.get(context, drawer_id, lock=True)
            if drawer.client_close_id is not None:
                if (
                    drawer.client_close_id != client_close_id
                    or drawer.actual_cash_minor != actual_cash_minor
                    or drawer.close_note != _note(note)
                ):
                    raise CashCloseIdempotencyConflict("Close id already has another payload")
                snapshot = await self.session.scalar(
                    select(CashDrawerCloseSnapshotModel).where(
                        CashDrawerCloseSnapshotModel.drawer_session_id == drawer.id
                    )
                )
                if (
                    snapshot
                    and abs(snapshot.variance_minor) > snapshot.approval_threshold_minor
                    and drawer.approved_at is None
                ):
                    await self.session.rollback()
                    raise CashVarianceApprovalRequired("Manager approval is required")
                replay_drawer_id = drawer.id
                replay_status = drawer.status
                await self.session.rollback()
                return (
                    await self._continue_close(context, replay_drawer_id)
                    if replay_status == "CLOSING"
                    else await self.summary(context, replay_drawer_id)
                )
            if drawer.status == CashDrawerStatus.CLOSED.value:
                raise CashDrawerAlreadyClosed("Cash drawer is already closed")
            if drawer.status != CashDrawerStatus.OPEN.value:
                raise CashDrawerNotOpen("Cash drawer is not OPEN")
            await self._ensure_close_ready(drawer)
            totals = await self._totals(drawer.id)
            expected = sum(totals.values())
            variance = actual_cash_minor - expected
            threshold = int(
                await self.session.scalar(
                    select(LocationModel.cash_variance_approval_threshold_minor).where(
                        LocationModel.id == drawer.location_id
                    )
                )
                or 0
            )
            now = datetime.now(UTC)
            drawer.status = CashDrawerStatus.CLOSING.value
            drawer.expected_cash_minor_snapshot = expected
            drawer.actual_cash_minor = actual_cash_minor
            drawer.variance_minor = variance
            drawer.client_close_id = client_close_id
            drawer.close_note = _note(note)
            drawer.closed_by_user_id = context.user_id
            drawer.updated_at = now
            drawer.version += 1
            shift = await self.session.get(
                RegisterShiftModel, drawer.shift_id, with_for_update=True
            )
            if shift is None or shift.status != "OPEN":
                raise CashDrawerNotOpen("Register shift is not OPEN")
            shift.status = "CLOSING"
            shift.updated_at = now
            active_sessions = list(
                await self.session.scalars(
                    select(PosOfflineSessionModel)
                    .where(
                        PosOfflineSessionModel.shift_id == drawer.shift_id,
                        PosOfflineSessionModel.status == "ACTIVE",
                    )
                    .with_for_update()
                )
            )
            for offline in active_sessions:
                offline.status = "CLOSED"
                offline.closed_at = now
            snapshot = CashDrawerCloseSnapshotModel(
                id=uuid4(),
                organization_id=drawer.organization_id,
                drawer_session_id=drawer.id,
                starting_cash_minor=totals["starting_cash_minor"],
                cash_payments_minor=totals["cash_payments_minor"],
                cash_refunds_minor=totals["cash_refunds_minor"],
                pay_in_minor=totals["pay_in_minor"],
                pay_out_minor=totals["pay_out_minor"],
                expected_cash_minor=expected,
                actual_cash_minor=actual_cash_minor,
                variance_minor=variance,
                approval_threshold_minor=threshold,
                created_at=now,
            )
            self.session.add(snapshot)
            await self.audit.record(
                action="CASH_CLOSE_REQUESTED",
                resource_type="cash_drawer",
                organization_id=context.organization_id,
                actor_user_id=context.user_id,
                resource_id=drawer.id,
                metadata={"actual_cash_minor": actual_cash_minor},
            )
            await self.session.commit()
            if abs(variance) > threshold:
                raise CashVarianceApprovalRequired("Manager approval is required")
            return await self._continue_close(context, drawer.id)
        except CashVarianceApprovalRequired:
            raise
        except Exception:
            await self.session.rollback()
            raise

    async def approve_variance(
        self, context: TenantContext, drawer_id: UUID, reason: str
    ) -> dict[str, object]:
        reason = reason.strip()
        if not reason:
            raise CashMovementInvalid("Approval reason is required")
        try:
            drawer = await self.get(context, drawer_id, lock=True)
            if drawer.status == CashDrawerStatus.CLOSED.value:
                return await self._summary(drawer)
            if drawer.status != CashDrawerStatus.CLOSING.value or drawer.variance_minor is None:
                raise CashDrawerNotOpen("Cash drawer is not awaiting approval")
            now = datetime.now(UTC)
            drawer.approved_by_user_id = context.user_id
            drawer.approved_at = now
            prefix = f"{drawer.close_note}; " if drawer.close_note else ""
            drawer.close_note = f"{prefix}Variance approval: {reason}"
            drawer.updated_at = now
            await self.audit.record(
                action="CASH_VARIANCE_APPROVED",
                resource_type="cash_drawer",
                organization_id=context.organization_id,
                actor_user_id=context.user_id,
                resource_id=drawer.id,
                metadata={"variance_minor": drawer.variance_minor},
            )
            await self.session.commit()
            return await self._continue_close(context, drawer.id)
        except Exception:
            await self.session.rollback()
            raise

    async def _continue_close(self, context: TenantContext, drawer_id: UUID) -> dict[str, object]:
        drawer = await self.get(context, drawer_id, lock=True)
        mode = await self.session.scalar(
            select(LocationModel.fiscal_enforcement_mode).where(
                LocationModel.id == drawer.location_id
            )
        )
        if mode != "LIVE_REQUIRED":
            await self._finalize(drawer, context.user_id)
            await self.session.commit()
            return await self._summary(drawer)
        state = await self.session.scalar(
            select(CashDrawerFiscalStateModel)
            .where(CashDrawerFiscalStateModel.drawer_session_id == drawer.id)
            .with_for_update()
        )
        if state is None:
            state = CashDrawerFiscalStateModel(
                id=uuid4(),
                organization_id=drawer.organization_id,
                drawer_session_id=drawer.id,
                fiscal_job_id=None,
                status=FiscalShiftStatus.NOT_REQUIRED.value,
                updated_at=datetime.now(UTC),
            )
            self.session.add(state)
            await self.session.flush()
        if state.fiscal_job_id is None:
            route = await self.session.scalar(
                select(FiscalRouteModel).where(
                    FiscalRouteModel.organization_id == drawer.organization_id,
                    FiscalRouteModel.register_id == drawer.register_id,
                    FiscalRouteModel.is_active.is_(True),
                )
            )
            if route is None:
                raise FiscalShiftCloseFailed("Active fiscal route not found")
            job = await self._job(drawer, route.provider_connection_id, "FISCAL_SHIFT_Z_REPORT")
            state.fiscal_job_id = job.id
            state.status = FiscalShiftStatus.PENDING.value
            state.updated_at = datetime.now(UTC)
        await self.session.commit()
        return await self._summary(drawer)

    async def fiscal_status(self, context: TenantContext, shift_id: UUID) -> dict[str, object]:
        drawer = await self.session.scalar(
            select(CashDrawerSessionModel).where(
                CashDrawerSessionModel.organization_id == context.organization_id,
                CashDrawerSessionModel.shift_id == shift_id,
            )
        )
        if drawer is None:
            raise CashDrawerNotFound("Cash drawer not found")
        await self.organizations.ensure_location_access(context, drawer.location_id)
        state = await self.session.scalar(
            select(CashDrawerFiscalStateModel).where(
                CashDrawerFiscalStateModel.drawer_session_id == drawer.id
            )
        )
        job = (
            await self.session.get(IntegrationJobModel, state.fiscal_job_id)
            if state and state.fiscal_job_id
            else None
        )
        if job and job.status == "SUCCESS" and drawer.status == "CLOSING":
            drawer = await self.get(context, drawer.id, lock=True)
            await self._finalize(drawer, context.user_id)
            state.status = FiscalShiftStatus.COMPLETED.value
            state.updated_at = datetime.now(UTC)
            await self.session.commit()
        elif job and job.status == "DEAD":
            unknown = job.last_error_code in {"PROVIDER_OUTCOME_UNKNOWN", "OUTCOME_UNKNOWN"}
            state.status = (
                FiscalShiftStatus.UNKNOWN if unknown else FiscalShiftStatus.FAILED
            ).value
            state.updated_at = datetime.now(UTC)
            await self.session.commit()
        status = state.status if state else FiscalShiftStatus.NOT_REQUIRED.value
        if status == FiscalShiftStatus.UNKNOWN.value:
            status = FiscalShiftStatus.RECONCILIATION_REQUIRED.value
        return {
            "shift_id": shift_id,
            "status": status,
            "job_id": job.id if job else None,
            "job_type": job.job_type if job else "FISCAL_SHIFT_Z_REPORT",
            "provider_code": await self.session.scalar(
                select(IntegrationConnectionModel.provider_code).where(
                    IntegrationConnectionModel.id == job.connection_id
                )
            )
            if job
            else None,
            "updated_at": job.updated_at if job else None,
        }

    async def x_report(self, context: TenantContext, shift_id: UUID) -> dict[str, object]:
        drawer = await self.session.scalar(
            select(CashDrawerSessionModel)
            .where(
                CashDrawerSessionModel.organization_id == context.organization_id,
                CashDrawerSessionModel.shift_id == shift_id,
                CashDrawerSessionModel.status.in_(("OPEN", "CLOSING")),
            )
            .with_for_update()
        )
        if drawer is None:
            raise CashDrawerNotFound("Cash drawer not found")
        await self.organizations.ensure_location_access(context, drawer.location_id)
        mode = await self.session.scalar(
            select(LocationModel.fiscal_enforcement_mode).where(
                LocationModel.id == drawer.location_id
            )
        )
        if mode != "LIVE_REQUIRED":
            return {
                "shift_id": shift_id,
                "status": "NOT_REQUIRED",
                "job_id": None,
                "job_type": "FISCAL_SHIFT_X_REPORT",
                "provider_code": None,
                "updated_at": None,
            }
        route = await self.session.scalar(
            select(FiscalRouteModel).where(
                FiscalRouteModel.organization_id == context.organization_id,
                FiscalRouteModel.register_id == drawer.register_id,
                FiscalRouteModel.is_active.is_(True),
            )
        )
        if route is None:
            raise FiscalShiftCloseFailed("Active fiscal route not found")
        job = await self._job(drawer, route.provider_connection_id, "FISCAL_SHIFT_X_REPORT")
        await self.session.commit()
        provider = await self.session.scalar(
            select(IntegrationConnectionModel.provider_code).where(
                IntegrationConnectionModel.id == job.connection_id
            )
        )
        return {
            "shift_id": shift_id,
            "status": _job_status(job.status),
            "job_id": job.id,
            "job_type": job.job_type,
            "provider_code": provider,
            "updated_at": job.updated_at,
        }

    async def reconcile_fiscal(self, context: TenantContext, shift_id: UUID) -> dict[str, object]:
        drawer = await self.session.scalar(
            select(CashDrawerSessionModel)
            .where(
                CashDrawerSessionModel.organization_id == context.organization_id,
                CashDrawerSessionModel.shift_id == shift_id,
            )
            .with_for_update()
        )
        if drawer is None:
            raise CashDrawerNotFound("Cash drawer not found")
        await self.organizations.ensure_location_access(context, drawer.location_id)
        state = await self.session.scalar(
            select(CashDrawerFiscalStateModel)
            .where(CashDrawerFiscalStateModel.drawer_session_id == drawer.id)
            .with_for_update()
        )
        job = (
            await self.session.get(IntegrationJobModel, state.fiscal_job_id, with_for_update=True)
            if state and state.fiscal_job_id
            else None
        )
        if (
            state is None
            or job is None
            or state.status not in {"UNKNOWN", "RECONCILIATION_REQUIRED"}
        ):
            raise FiscalShiftReconciliationRequired("Fiscal shift does not require reconciliation")
        result = await self.fiscal_close.reconcile(
            FiscalShiftReconciliation(
                job.id, job.organization_id, job.connection_id, shift_id, job.external_id
            )
        )
        if result is None:
            raise FiscalShiftReconciliationRequired("Fiscal close result is still unknown")
        if result is False:
            state.status = FiscalShiftStatus.FAILED.value
            state.updated_at = datetime.now(UTC)
            await self.session.commit()
            raise FiscalShiftCloseFailed("Fiscal provider confirmed close failure")
        now = datetime.now(UTC)
        job.status = "SUCCESS"
        job.external_id = job.external_id or f"reconciled:{shift_id}"
        job.completed_at = now
        job.dead_lettered_at = None
        job.last_error_code = None
        job.last_error_message = None
        job.updated_at = now
        state.status = FiscalShiftStatus.COMPLETED.value
        state.updated_at = now
        await self._finalize(drawer, drawer.closed_by_user_id or drawer.opened_by_user_id)
        await self.session.commit()
        return await self.fiscal_status(context, shift_id)

    async def reports(
        self,
        context: TenantContext,
        *,
        location_id: UUID | None,
        date_from: date | None,
        date_to: date | None,
        status: str | None,
    ) -> list[dict[str, object]]:
        statement = (
            select(CashDrawerSessionModel, PosRegisterModel.name)
            .join(PosRegisterModel, PosRegisterModel.id == CashDrawerSessionModel.register_id)
            .where(CashDrawerSessionModel.organization_id == context.organization_id)
        )
        if context.location_access.value != "ALL":
            allowed = select(MembershipLocationModel.location_id).where(
                MembershipLocationModel.membership_id == context.membership_id
            )
            statement = statement.where(CashDrawerSessionModel.location_id.in_(allowed))
        if location_id:
            await self.organizations.ensure_location_access(context, location_id)
            statement = statement.where(CashDrawerSessionModel.location_id == location_id)
        if date_from:
            statement = statement.where(func.date(CashDrawerSessionModel.opened_at) >= date_from)
        if date_to:
            statement = statement.where(func.date(CashDrawerSessionModel.opened_at) <= date_to)
        if status:
            statement = statement.where(CashDrawerSessionModel.status == status)
        rows = (
            await self.session.execute(statement.order_by(CashDrawerSessionModel.opened_at.desc()))
        ).all()
        result = []
        for drawer, register_name in rows:
            location_name = await self.session.scalar(
                select(LocationModel.name).where(LocationModel.id == drawer.location_id)
            )
            cashier = await self.session.get(UserModel, drawer.opened_by_user_id)
            result.append(
                {
                    "id": drawer.id,
                    "location_id": drawer.location_id,
                    "location_name": location_name,
                    "register_id": drawer.register_id,
                    "register_name": register_name,
                    "shift_id": drawer.shift_id,
                    "cashier_user_id": drawer.opened_by_user_id,
                    "cashier_name": (
                        f"{cashier.first_name} {cashier.last_name}".strip()
                        if cashier
                        else str(drawer.opened_by_user_id)
                    ),
                    "status": drawer.status,
                    "opened_at": drawer.opened_at,
                    "closed_at": drawer.closed_at,
                    "starting_cash_minor": str(drawer.starting_cash_minor),
                    "expected_cash_minor": _str(drawer.expected_cash_minor_snapshot),
                    "actual_cash_minor": _str(drawer.actual_cash_minor),
                    "variance_minor": _str(drawer.variance_minor),
                    "currency_code": drawer.currency_code,
                }
            )
        return result

    async def detail(self, context: TenantContext, drawer_id: UUID) -> dict[str, object]:
        summary = await self.summary(context, drawer_id)
        movements = list(
            await self.session.scalars(
                select(CashDrawerMovementModel)
                .where(
                    CashDrawerMovementModel.organization_id == context.organization_id,
                    CashDrawerMovementModel.drawer_session_id == drawer_id,
                )
                .order_by(CashDrawerMovementModel.occurred_at, CashDrawerMovementModel.id)
            )
        )
        return {"summary": summary, "movements": movements}

    async def project_payment(self, organization_id: UUID, payment_id: UUID) -> None:
        payment = await self.session.scalar(
            select(PaymentModel).where(
                PaymentModel.organization_id == organization_id, PaymentModel.id == payment_id
            )
        )
        if payment is None:
            raise CashDrawerNotFound("Payment not found")
        drawer = await self.session.scalar(
            select(CashDrawerSessionModel).where(
                CashDrawerSessionModel.organization_id == organization_id,
                CashDrawerSessionModel.shift_id == payment.shift_id,
            )
        )
        if drawer is None:
            raise CashDrawerNotFound("Payment drawer not found")
        lines = list(
            await self.session.scalars(
                select(PaymentLineModel).where(
                    PaymentLineModel.payment_id == payment.id, PaymentLineModel.method == "CASH"
                )
            )
        )
        for line in lines:
            await self._project(
                drawer,
                CashMovementKind.CASH_PAYMENT,
                line.amount_minor,
                "PAYMENT",
                payment.id,
                line.id,
                payment.completed_at,
            )

    async def project_refund(self, organization_id: UUID, refund_id: UUID) -> None:
        refund = await self.session.scalar(
            select(RefundModel).where(
                RefundModel.organization_id == organization_id,
                RefundModel.id == refund_id,
                RefundModel.status == "COMPLETED",
            )
        )
        if refund is None or refund.completed_at is None:
            raise CashDrawerNotFound("Completed refund not found")
        shift_id = await self.session.scalar(
            select(PaymentModel.shift_id).where(PaymentModel.id == refund.payment_id)
        )
        drawer = await self.session.scalar(
            select(CashDrawerSessionModel).where(
                CashDrawerSessionModel.organization_id == organization_id,
                CashDrawerSessionModel.shift_id == shift_id,
            )
        )
        if drawer is None:
            raise CashDrawerNotFound("Refund drawer not found")
        lines = list(
            await self.session.scalars(
                select(RefundPaymentLineModel).where(
                    RefundPaymentLineModel.refund_id == refund.id,
                    RefundPaymentLineModel.method == "CASH",
                )
            )
        )
        for line in lines:
            await self._project(
                drawer,
                CashMovementKind.CASH_REFUND,
                -line.amount_minor,
                "REFUND",
                refund.id,
                line.id,
                refund.completed_at,
            )

    async def on_integration_job(self, organization_id: UUID, job_id: UUID, *, dead: bool) -> None:
        job = await self.session.scalar(
            select(IntegrationJobModel).where(
                IntegrationJobModel.organization_id == organization_id,
                IntegrationJobModel.id == job_id,
                IntegrationJobModel.job_type == "FISCAL_SHIFT_Z_REPORT",
            )
        )
        if job is None:
            return
        state = await self.session.scalar(
            select(CashDrawerFiscalStateModel).where(
                CashDrawerFiscalStateModel.fiscal_job_id == job.id
            )
        )
        if state is None:
            return
        drawer = await self.session.get(
            CashDrawerSessionModel, state.drawer_session_id, with_for_update=True
        )
        if dead:
            state.status = (
                FiscalShiftStatus.UNKNOWN.value
                if job.last_error_code in {"PROVIDER_OUTCOME_UNKNOWN", "OUTCOME_UNKNOWN"}
                else FiscalShiftStatus.FAILED.value
            )
        elif drawer and drawer.status == "CLOSING":
            await self._finalize(drawer, drawer.closed_by_user_id or drawer.opened_by_user_id)
            state.status = FiscalShiftStatus.COMPLETED.value
        state.updated_at = datetime.now(UTC)

    async def _project(
        self,
        drawer: CashDrawerSessionModel,
        kind: CashMovementKind,
        amount: int,
        source_type: str,
        source_id: UUID,
        line_id: UUID,
        occurred_at: datetime,
    ) -> None:
        existing = await self.session.scalar(
            select(CashDrawerMovementModel.id).where(
                CashDrawerMovementModel.organization_id == drawer.organization_id,
                CashDrawerMovementModel.source_type == source_type,
                CashDrawerMovementModel.source_id == source_id,
                CashDrawerMovementModel.source_line_id == line_id,
            )
        )
        if existing:
            return
        self.session.add(
            CashDrawerMovementModel(
                id=uuid4(),
                organization_id=drawer.organization_id,
                drawer_session_id=drawer.id,
                kind=kind.value,
                amount_minor=amount,
                source_type=source_type,
                source_id=source_id,
                source_line_id=line_id,
                client_movement_id=None,
                reason=None,
                note=None,
                created_by_user_id=None,
                occurred_at=occurred_at,
                recorded_at=datetime.now(UTC),
            )
        )
        await self.session.flush()
        metric = (
            metrics.cash_sales_minor
            if kind is CashMovementKind.CASH_PAYMENT
            else metrics.cash_refunds_minor
        )
        metric.add(abs(amount), {"organization.id": str(drawer.organization_id)})

    async def _totals(self, drawer_id: UUID) -> dict[str, int]:
        rows = (
            await self.session.execute(
                select(
                    CashDrawerMovementModel.kind,
                    func.coalesce(func.sum(CashDrawerMovementModel.amount_minor), 0),
                )
                .where(CashDrawerMovementModel.drawer_session_id == drawer_id)
                .group_by(CashDrawerMovementModel.kind)
            )
        ).all()
        values = dict(rows)
        return {
            "starting_cash_minor": int(values.get("OPENING_FLOAT", 0)),
            "cash_payments_minor": int(values.get("CASH_PAYMENT", 0)),
            "cash_refunds_minor": int(values.get("CASH_REFUND", 0)),
            "pay_in_minor": int(values.get("PAY_IN", 0)),
            "pay_out_minor": int(values.get("PAY_OUT", 0)),
        }

    async def _summary(self, drawer: CashDrawerSessionModel) -> dict[str, object]:
        snapshot = await self.session.scalar(
            select(CashDrawerCloseSnapshotModel).where(
                CashDrawerCloseSnapshotModel.drawer_session_id == drawer.id
            )
        )
        totals = (
            {
                "starting_cash_minor": snapshot.starting_cash_minor,
                "cash_payments_minor": snapshot.cash_payments_minor,
                "cash_refunds_minor": snapshot.cash_refunds_minor,
                "pay_in_minor": snapshot.pay_in_minor,
                "pay_out_minor": snapshot.pay_out_minor,
            }
            if snapshot
            else await self._totals(drawer.id)
        )
        return {
            "drawer": drawer,
            **totals,
            "expected_cash_minor": snapshot.expected_cash_minor
            if snapshot
            else sum(totals.values()),
            "actual_cash_minor": drawer.actual_cash_minor,
            "variance_minor": drawer.variance_minor,
        }

    async def _ensure_close_ready(self, drawer: CashDrawerSessionModel) -> None:
        open_orders = await self.session.scalar(
            select(func.count())
            .select_from(SalesOrderModel)
            .where(
                SalesOrderModel.organization_id == drawer.organization_id,
                SalesOrderModel.shift_id == drawer.shift_id,
                SalesOrderModel.status == "OPEN",
            )
        )
        unresolved_payments = await self.session.scalar(
            select(func.count())
            .select_from(ExternalPaymentAttemptModel)
            .where(
                ExternalPaymentAttemptModel.organization_id == drawer.organization_id,
                ExternalPaymentAttemptModel.register_id == drawer.register_id,
                ExternalPaymentAttemptModel.status.in_(("CREATED", "TERMINAL_PENDING", "UNKNOWN")),
            )
        )
        pending_refunds = await self.session.scalar(
            select(func.count())
            .select_from(RefundModel)
            .join(PaymentModel, PaymentModel.id == RefundModel.payment_id)
            .where(
                RefundModel.organization_id == drawer.organization_id,
                PaymentModel.shift_id == drawer.shift_id,
                RefundModel.status == "PENDING",
            )
        )
        offline_conflicts = await self.session.scalar(
            select(func.count())
            .select_from(PosOfflineOrderSyncModel)
            .join(
                PosOfflineSessionModel,
                PosOfflineSessionModel.id == PosOfflineOrderSyncModel.session_id,
            )
            .where(
                PosOfflineSessionModel.shift_id == drawer.shift_id,
                PosOfflineOrderSyncModel.status == "CONFLICT",
            )
        )
        payment_cash = int(
            await self.session.scalar(
                select(func.coalesce(func.sum(PaymentLineModel.amount_minor), 0))
                .join(PaymentModel, PaymentModel.id == PaymentLineModel.payment_id)
                .where(PaymentModel.shift_id == drawer.shift_id, PaymentLineModel.method == "CASH")
            )
            or 0
        )
        refund_cash = int(
            await self.session.scalar(
                select(func.coalesce(func.sum(RefundPaymentLineModel.amount_minor), 0))
                .join(RefundModel, RefundModel.id == RefundPaymentLineModel.refund_id)
                .join(PaymentModel, PaymentModel.id == RefundModel.payment_id)
                .where(
                    PaymentModel.shift_id == drawer.shift_id,
                    RefundModel.status == "COMPLETED",
                    RefundPaymentLineModel.method == "CASH",
                )
            )
            or 0
        )
        projected = await self._totals(drawer.id)
        if (
            any((open_orders, unresolved_payments, pending_refunds, offline_conflicts))
            or projected["cash_payments_minor"] != payment_cash
            or projected["cash_refunds_minor"] != -refund_cash
        ):
            raise ShiftCloseSyncPending("Shift close prerequisites are not synchronized")

    async def _job(
        self, drawer: CashDrawerSessionModel, connection_id: UUID, job_type: str
    ) -> IntegrationJobModel:
        key = f"{job_type.lower()}:{drawer.shift_id}"
        existing = await self.session.scalar(
            select(IntegrationJobModel).where(
                IntegrationJobModel.connection_id == connection_id,
                IntegrationJobModel.idempotency_key == key,
            )
        )
        if existing:
            return existing
        now = datetime.now(UTC)
        job = IntegrationJobModel(
            id=uuid4(),
            organization_id=drawer.organization_id,
            connection_id=connection_id,
            location_id=drawer.location_id,
            capability="FISCAL",
            job_type=job_type,
            source_event_id=None,
            source_type="REGISTER_SHIFT",
            source_id=drawer.shift_id,
            idempotency_key=key,
            status="PENDING",
            available_at=now,
            attempts=0,
            locked_by=None,
            locked_until=None,
            external_id=None,
            completed_at=None,
            dead_lettered_at=None,
            last_error_code=None,
            last_error_message=None,
            created_at=now,
            updated_at=now,
        )
        self.session.add(job)
        await self.session.flush()
        return job

    async def _finalize(self, drawer: CashDrawerSessionModel, actor_id: UUID) -> None:
        if drawer.status == "CLOSED":
            return
        now = datetime.now(UTC)
        drawer.status = "CLOSED"
        drawer.closed_by_user_id = drawer.closed_by_user_id or actor_id
        drawer.closed_at = now
        drawer.updated_at = now
        drawer.version += 1
        shift = await self.session.get(RegisterShiftModel, drawer.shift_id, with_for_update=True)
        if shift is None:
            raise CashDrawerNotFound("Register shift not found")
        shift.status = "CLOSED"
        shift.closed_by_user_id = actor_id
        shift.closed_at = now
        shift.updated_at = now
        await self.audit.record(
            action="CASH_DRAWER_CLOSED",
            resource_type="cash_drawer",
            organization_id=drawer.organization_id,
            actor_user_id=actor_id,
            resource_id=drawer.id,
            metadata={"variance_minor": drawer.variance_minor or 0},
        )
        await self.events.stage(
            CashDrawerClosed(drawer.id, drawer.organization_id), occurred_at=now
        )
        variance = drawer.variance_minor or 0
        expected = drawer.expected_cash_minor_snapshot or 0
        attributes = {"organization.id": str(drawer.organization_id)}
        metrics.cash_drawer_sessions.add(1, attributes)
        metrics.cash_drawer_variance_minor.record(variance, attributes)
        metrics.cash_drawer_variance_rate.record(
            abs(variance) / expected if expected else 0,
            attributes,
        )


def _money(value: int, *, allow_zero: bool = False) -> None:
    if value < (0 if allow_zero else 1) or value > MAX_BIGINT:
        raise CashMovementInvalid("Cash amount is outside BIGINT range")


def _note(value: str | None) -> str | None:
    return value.strip() if value and value.strip() else None


def _str(value: int | None) -> str | None:
    return str(value) if value is not None else None


def _job_status(value: str) -> str:
    return {"SUCCESS": "COMPLETED", "DEAD": "FAILED"}.get(value, value)
