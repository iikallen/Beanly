from datetime import datetime
from typing import Protocol
from uuid import UUID

from beanly.modules.organizations.domain.entities import OrganizationInvitation
from beanly.modules.organizations.domain.enums import MembershipRole
from beanly.modules.organizations.domain.repositories import OrganizationRepository


class InvitationRepository(Protocol):
    async def add(self, invitation: OrganizationInvitation) -> OrganizationInvitation: ...

    async def update(self, invitation: OrganizationInvitation) -> OrganizationInvitation: ...

    async def list_for_organization(
        self, organization_id: UUID
    ) -> list[OrganizationInvitation]: ...

    async def get_for_organization(
        self, organization_id: UUID, invitation_id: UUID, *, lock: bool = False
    ) -> OrganizationInvitation | None: ...

    async def get_by_token_hash(
        self, token_hash: str, *, lock: bool = False
    ) -> OrganizationInvitation | None: ...

    async def pending_exists(self, organization_id: UUID, email: str) -> bool: ...

    async def expire_pending(self, organization_id: UUID, email: str, now: datetime) -> None: ...

    async def member_exists_for_email(self, organization_id: UUID, email: str) -> bool: ...

    async def organization_name(self, organization_id: UUID) -> str | None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


class EmailSender(Protocol):
    async def send_invitation(
        self, email: str, organization_name: str, role: MembershipRole, invite_url: str
    ) -> None: ...


__all__ = ["EmailSender", "InvitationRepository", "OrganizationRepository"]
