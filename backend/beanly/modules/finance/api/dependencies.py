from typing import Annotated

from fastapi import Depends

from beanly.core.events.outbox.repositories import OutboxRepository
from beanly.core.events.outbox.writer import OutboxEventSink
from beanly.core.security.audit import SecurityAuditRecorder
from beanly.modules.finance.application.cash_service import CashService
from beanly.modules.finance.application.expense_service import ExpenseService
from beanly.modules.finance.application.finance_query_service import FinanceQueryService
from beanly.modules.finance.infrastructure.db.repositories import SqlAlchemyFinanceRepository
from beanly.modules.identity.api.dependencies import SessionDep, SettingsDep
from beanly.modules.organizations.api.dependencies import require_permission
from beanly.modules.organizations.application.services.organization_service import (
    OrganizationService,
)
from beanly.modules.organizations.domain.entities import TenantContext
from beanly.modules.organizations.domain.permissions import Permission
from beanly.modules.organizations.infrastructure.db.repositories import (
    SqlAlchemyOrganizationRepository,
)


def expense_service(session: SessionDep, settings: SettingsDep) -> ExpenseService:
    return ExpenseService(
        SqlAlchemyFinanceRepository(session),
        OutboxEventSink(OutboxRepository(session)),
        OrganizationService(SqlAlchemyOrganizationRepository(session)),
        SecurityAuditRecorder(session) if settings.audit_enabled else None,
    )


def cash_service(session: SessionDep) -> CashService:
    return CashService(
        SqlAlchemyFinanceRepository(session),
        OutboxEventSink(OutboxRepository(session)),
        OrganizationService(SqlAlchemyOrganizationRepository(session)),
    )


def query_service(session: SessionDep) -> FinanceQueryService:
    return FinanceQueryService(
        SqlAlchemyFinanceRepository(session),
        OrganizationService(SqlAlchemyOrganizationRepository(session)),
    )


ExpenseServiceDep = Annotated[ExpenseService, Depends(expense_service)]
CashServiceDep = Annotated[CashService, Depends(cash_service)]
FinanceQueryServiceDep = Annotated[FinanceQueryService, Depends(query_service)]
FinanceReadDep = Annotated[
    TenantContext, Depends(require_permission(Permission.FINANCE_READ))
]
FinanceWriteDep = Annotated[
    TenantContext, Depends(require_permission(Permission.FINANCE_WRITE))
]
