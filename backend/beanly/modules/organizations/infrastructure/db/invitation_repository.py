from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from beanly.modules.identity.infrastructure.db.models import UserModel
from beanly.modules.organizations.domain.entities import OrganizationInvitation
from beanly.modules.organizations.domain.enums import InvitationStatus, MembershipStatus
from beanly.modules.organizations.domain.exceptions import DuplicateInvitation
from beanly.modules.organizations.infrastructure.db.mappers import to_invitation
from beanly.modules.organizations.infrastructure.db.models import (
    InvitationLocationModel,
    OrganizationInvitationModel,
    OrganizationMembershipModel,
    OrganizationModel,
)


class SqlAlchemyInvitationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, invitation: OrganizationInvitation) -> OrganizationInvitation:
        model = OrganizationInvitationModel(
            id=invitation.id,
            organization_id=invitation.organization_id,
            employee_id=invitation.employee_id,
            email=invitation.email,
            role=invitation.role.value,
            token_hash=invitation.token_hash,
            status=invitation.status.value,
            expires_at=invitation.expires_at,
            invited_by=invitation.invited_by,
            accepted_by=invitation.accepted_by,
            accepted_at=invitation.accepted_at,
            created_at=invitation.created_at,
        )
        self.session.add(model)
        try:
            await self.session.flush()
            self.session.add_all(
                InvitationLocationModel(
                    invitation_id=invitation.id,
                    location_id=location_id,
                    created_at=invitation.created_at,
                )
                for location_id in invitation.location_ids
            )
            await self.session.flush()
        except IntegrityError as exc:
            raise DuplicateInvitation from exc
        return to_invitation(model, invitation.location_ids)

    async def update(self, invitation: OrganizationInvitation) -> OrganizationInvitation:
        model = await self.session.get(OrganizationInvitationModel, invitation.id)
        if model is None:
            return invitation
        model.status = invitation.status.value
        model.accepted_by = invitation.accepted_by
        model.accepted_at = invitation.accepted_at
        model.employee_id = invitation.employee_id
        await self.session.flush()
        return to_invitation(model, invitation.location_ids)

    async def list_for_organization(self, organization_id: UUID) -> list[OrganizationInvitation]:
        models = list(
            await self.session.scalars(
                select(OrganizationInvitationModel)
                .where(OrganizationInvitationModel.organization_id == organization_id)
                .order_by(OrganizationInvitationModel.created_at.desc())
            )
        )
        locations = await self._location_map([model.id for model in models])
        return [to_invitation(model, locations.get(model.id, ())) for model in models]

    async def get_for_organization(
        self, organization_id: UUID, invitation_id: UUID, *, lock: bool = False
    ) -> OrganizationInvitation | None:
        statement = select(OrganizationInvitationModel).where(
            OrganizationInvitationModel.id == invitation_id,
            OrganizationInvitationModel.organization_id == organization_id,
        )
        if lock:
            statement = statement.with_for_update()
        model = await self.session.scalar(statement)
        if model is None:
            return None
        locations = await self._location_map([model.id])
        return to_invitation(model, locations.get(model.id, ()))

    async def get_by_token_hash(
        self, token_hash: str, *, lock: bool = False
    ) -> OrganizationInvitation | None:
        statement = select(OrganizationInvitationModel).where(
            OrganizationInvitationModel.token_hash == token_hash
        )
        if lock:
            statement = statement.with_for_update()
        model = await self.session.scalar(statement)
        if model is None:
            return None
        locations = await self._location_map([model.id])
        return to_invitation(model, locations.get(model.id, ()))

    async def pending_exists(self, organization_id: UUID, email: str) -> bool:
        invitation_id = await self.session.scalar(
            select(OrganizationInvitationModel.id).where(
                OrganizationInvitationModel.organization_id == organization_id,
                OrganizationInvitationModel.email == email,
                OrganizationInvitationModel.status == InvitationStatus.PENDING.value,
                OrganizationInvitationModel.expires_at > datetime.now(UTC),
            )
        )
        return invitation_id is not None

    async def expire_pending(self, organization_id: UUID, email: str, now: datetime) -> None:
        await self.session.execute(
            update(OrganizationInvitationModel)
            .where(
                OrganizationInvitationModel.organization_id == organization_id,
                OrganizationInvitationModel.email == email,
                OrganizationInvitationModel.status == InvitationStatus.PENDING.value,
                OrganizationInvitationModel.expires_at <= now,
            )
            .values(status=InvitationStatus.EXPIRED.value)
        )
        await self.session.flush()

    async def member_exists_for_email(self, organization_id: UUID, email: str) -> bool:
        membership_id = await self.session.scalar(
            select(OrganizationMembershipModel.id)
            .join(UserModel, UserModel.id == OrganizationMembershipModel.user_id)
            .where(
                OrganizationMembershipModel.organization_id == organization_id,
                UserModel.email == email,
                OrganizationMembershipModel.status.in_(
                    {
                        MembershipStatus.ACTIVE.value,
                        MembershipStatus.SUSPENDED.value,
                        MembershipStatus.REVOKED.value,
                    }
                ),
            )
        )
        return membership_id is not None

    async def organization_name(self, organization_id: UUID) -> str | None:
        return await self.session.scalar(
            select(OrganizationModel.name).where(OrganizationModel.id == organization_id)
        )

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()

    async def _location_map(self, invitation_ids: list[UUID]) -> dict[UUID, tuple[UUID, ...]]:
        if not invitation_ids:
            return {}
        rows = await self.session.execute(
            select(
                InvitationLocationModel.invitation_id,
                InvitationLocationModel.location_id,
            )
            .where(InvitationLocationModel.invitation_id.in_(invitation_ids))
            .order_by(InvitationLocationModel.created_at)
        )
        result: dict[UUID, list[UUID]] = {}
        for invitation_id, location_id in rows:
            result.setdefault(invitation_id, []).append(location_id)
        return {
            invitation_id: tuple(location_ids) for invitation_id, location_ids in result.items()
        }
