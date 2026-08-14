from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class FiscalShiftReconciliation:
    job_id: UUID
    organization_id: UUID
    connection_id: UUID
    shift_id: UUID
    external_id: str | None


class FiscalShiftClosePort(Protocol):
    """Looks up an ambiguous Z result; it must never resend the close command."""

    async def reconcile(self, query: FiscalShiftReconciliation) -> bool | None: ...


class UnavailableFiscalShiftClosePort:
    async def reconcile(self, query: FiscalShiftReconciliation) -> bool | None:
        del query
        return None
