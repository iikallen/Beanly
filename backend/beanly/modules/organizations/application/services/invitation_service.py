from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from beanly.core.config.settings import Settings
from beanly.core.security.tokens import create_invitation_token, hash_invitation_token
from beanly.modules.employees.domain.entities import Employee
from beanly.modules.employees.domain.enums import EmployeeStatus
from beanly.modules.employees.domain.exceptions import EmployeeNotFound
from beanly.modules.employees.domain.repositories import EmployeeRepository
from beanly.modules.organizations.application.commands.accept_invitation import (
    AcceptInvitationCommand,
)
from beanly.modules.organizations.application.commands.create_invitation import (
    CreateInvitationCommand,
)
from beanly.modules.organizations.application.commands.revoke_invitation import (
    RevokeInvitationCommand,
)
from beanly.modules.organizations.application.ports import (
    EmailSender,
    InvitationRepository,
)
from beanly.modules.organizations.domain.entities import (
    MembershipLocation,
    OrganizationInvitation,
    OrganizationMembership,
    TeamMember,
)
from beanly.modules.organizations.domain.enums import (
    InvitationStatus,
    LocationAccess,
    MembershipRole,
    MembershipStatus,
)
from beanly.modules.organizations.domain.exceptions import (
    DuplicateInvitation,
    DuplicateMembership,
    InvalidLocationAccess,
    InvalidRoleAssignment,
    InvitationAlreadyAccepted,
    InvitationEmailMismatch,
    InvitationGone,
    InvitationNotFound,
)
from beanly.modules.organizations.domain.repositories import OrganizationRepository


class InvitationService:
    def __init__(
        self,
        invitations: InvitationRepository,
        organizations: OrganizationRepository,
        employees: EmployeeRepository,
        email_sender: EmailSender,
        settings: Settings,
    ) -> None:
        self.invitations = invitations
        self.organizations = organizations
        self.employees = employees
        self.email_sender = email_sender
        self.settings = settings

    async def create(self, command: CreateInvitationCommand) -> OrganizationInvitation:
        email = command.email.strip().casefold()
        now = datetime.now(UTC)
        locations = tuple(dict.fromkeys(command.location_ids))
        if not locations or not await self.organizations.locations_belong_to_organization(
            command.organization_id, locations
        ):
            raise InvalidLocationAccess
        if not _can_assign(command.inviter_role, command.role):
            raise InvalidRoleAssignment
        if email == command.inviter_email.strip().casefold():
            raise DuplicateInvitation
        if await self.invitations.member_exists_for_email(command.organization_id, email):
            raise DuplicateMembership
        await self.invitations.expire_pending(command.organization_id, email, now)
        if await self.invitations.pending_exists(command.organization_id, email):
            raise DuplicateInvitation
        if command.employee_id is not None:
            employee = await self.employees.get(command.organization_id, command.employee_id)
            if employee is None or employee.user_id is not None:
                raise EmployeeNotFound

        organization_name = await self.invitations.organization_name(command.organization_id)
        if organization_name is None:
            raise InvitationNotFound
        token, token_hash = create_invitation_token()
        invitation = OrganizationInvitation(
            id=uuid4(),
            organization_id=command.organization_id,
            employee_id=command.employee_id,
            email=email,
            role=command.role,
            token_hash=token_hash,
            status=InvitationStatus.PENDING,
            expires_at=now + timedelta(days=self.settings.invitation_days),
            invited_by=command.invited_by,
            accepted_by=None,
            accepted_at=None,
            location_ids=locations,
            created_at=now,
        )
        try:
            await self.invitations.add(invitation)
            await self.invitations.commit()
        except Exception:
            await self.invitations.rollback()
            raise
        invite_url = f"{self.settings.frontend_url.rstrip('/')}/invite/{token}"
        await self.email_sender.send_invitation(email, organization_name, command.role, invite_url)
        return invitation

    async def list(self, organization_id: UUID) -> list[OrganizationInvitation]:
        now = datetime.now(UTC)
        invitations = await self.invitations.list_for_organization(organization_id)
        return [_effective(invitation, now) for invitation in invitations]

    async def inspect(self, token: str) -> tuple[OrganizationInvitation, str]:
        invitation = await self.invitations.get_by_token_hash(hash_invitation_token(token))
        if invitation is None:
            raise InvitationNotFound
        invitation = _effective(invitation, datetime.now(UTC))
        if invitation.status in {InvitationStatus.EXPIRED, InvitationStatus.REVOKED}:
            raise InvitationGone
        if invitation.status is InvitationStatus.ACCEPTED:
            raise InvitationAlreadyAccepted
        organization_name = await self.invitations.organization_name(invitation.organization_id)
        if organization_name is None:
            raise InvitationNotFound
        return invitation, organization_name

    async def accept(self, command: AcceptInvitationCommand) -> OrganizationMembership:
        invitation = await self.invitations.get_by_token_hash(
            hash_invitation_token(command.token), lock=True
        )
        if invitation is None:
            raise InvitationNotFound
        now = datetime.now(UTC)
        effective = _effective(invitation, now)
        if effective.status in {InvitationStatus.EXPIRED, InvitationStatus.REVOKED}:
            raise InvitationGone
        if effective.status is InvitationStatus.ACCEPTED:
            raise InvitationAlreadyAccepted
        if command.user_email.strip().casefold() != invitation.email:
            raise InvitationEmailMismatch
        if await self.organizations.get_membership_any_status(
            invitation.organization_id, command.user_id
        ):
            raise DuplicateMembership
        if not await self.organizations.locations_belong_to_organization(
            invitation.organization_id, invitation.location_ids
        ):
            raise InvalidLocationAccess

        membership = OrganizationMembership(
            id=uuid4(),
            organization_id=invitation.organization_id,
            user_id=command.user_id,
            role=invitation.role,
            status=MembershipStatus.ACTIVE,
            location_access=LocationAccess.SELECTED,
            created_at=now,
            updated_at=now,
        )
        try:
            await self.organizations.add_membership(membership)
            await self.organizations.add_membership_locations(
                tuple(
                    MembershipLocation(membership.id, location_id, now)
                    for location_id in invitation.location_ids
                )
            )
            employee = await self._link_employee(invitation, command, now)
            await self.invitations.update(
                replace(
                    invitation,
                    employee_id=employee.id,
                    status=InvitationStatus.ACCEPTED,
                    accepted_by=command.user_id,
                    accepted_at=now,
                )
            )
            await self.invitations.commit()
        except Exception:
            await self.invitations.rollback()
            raise
        return membership

    async def revoke(self, command: RevokeInvitationCommand) -> None:
        invitation = await self.invitations.get_for_organization(
            command.organization_id, command.invitation_id, lock=True
        )
        if invitation is None:
            raise InvitationNotFound
        effective = _effective(invitation, datetime.now(UTC))
        if effective.status is InvitationStatus.ACCEPTED:
            raise InvitationAlreadyAccepted
        if effective.status is InvitationStatus.EXPIRED:
            raise InvitationGone
        if effective.status is InvitationStatus.REVOKED:
            return
        await self.invitations.update(replace(invitation, status=InvitationStatus.REVOKED))
        await self.invitations.commit()

    async def team(self, organization_id) -> list[TeamMember]:
        return await self.employees.list_team_members(organization_id)

    async def _link_employee(
        self,
        invitation: OrganizationInvitation,
        command: AcceptInvitationCommand,
        now: datetime,
    ) -> Employee:
        employee = (
            await self.employees.get(invitation.organization_id, invitation.employee_id)
            if invitation.employee_id is not None
            else await self.employees.get_by_user(invitation.organization_id, command.user_id)
        )
        if employee is None:
            employee = Employee(
                id=uuid4(),
                organization_id=invitation.organization_id,
                user_id=command.user_id,
                first_name=command.first_name,
                last_name=command.last_name,
                phone=None,
                position=invitation.role.value.title(),
                status=EmployeeStatus.ACTIVE,
                location_ids=invitation.location_ids,
                created_at=now,
                updated_at=now,
            )
            await self.employees.add(employee)
        else:
            employee = replace(
                employee,
                user_id=command.user_id,
                location_ids=invitation.location_ids,
                updated_at=now,
            )
            await self.employees.update(employee)
        await self.employees.replace_locations(employee.id, invitation.location_ids)
        return employee


def _effective(invitation: OrganizationInvitation, now: datetime) -> OrganizationInvitation:
    if invitation.status is InvitationStatus.PENDING and invitation.expires_at <= now:
        return replace(invitation, status=InvitationStatus.EXPIRED)
    return invitation


def _can_assign(inviter: MembershipRole, target: MembershipRole) -> bool:
    if inviter is MembershipRole.OWNER:
        return target is not MembershipRole.OWNER
    if inviter is MembershipRole.ADMIN:
        return target not in {MembershipRole.OWNER, MembershipRole.ADMIN}
    return False
