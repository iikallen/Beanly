from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status

from beanly.modules.employees.domain.exceptions import EmployeeNotFound
from beanly.modules.identity.api.dependencies import CurrentUserDep
from beanly.modules.organizations.api.dependencies import (
    InvitationServiceDep,
    OrganizationServiceDep,
    ensure_location_scope,
    require_permission,
)
from beanly.modules.organizations.api.team_schemas import (
    CreateInvitationRequest,
    InvitationResponse,
    PublicInvitationResponse,
    TeamMemberResponse,
    TeamResponse,
)
from beanly.modules.organizations.application.commands.accept_invitation import (
    AcceptInvitationCommand,
)
from beanly.modules.organizations.application.commands.create_invitation import (
    CreateInvitationCommand,
)
from beanly.modules.organizations.application.commands.revoke_invitation import (
    RevokeInvitationCommand,
)
from beanly.modules.organizations.domain.entities import TenantContext
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
from beanly.modules.organizations.domain.permissions import Permission

router = APIRouter(tags=["team"])

TeamReadDep = Annotated[TenantContext, Depends(require_permission(Permission.TEAM_READ))]
TeamInviteDep = Annotated[TenantContext, Depends(require_permission(Permission.TEAM_INVITE))]
TeamRemoveDep = Annotated[TenantContext, Depends(require_permission(Permission.TEAM_REMOVE))]


@router.post(
    "/team/invitations",
    response_model=InvitationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_invitation(
    payload: CreateInvitationRequest,
    user: CurrentUserDep,
    context: TeamInviteDep,
    service: InvitationServiceDep,
    organizations: OrganizationServiceDep,
) -> InvitationResponse:
    await ensure_location_scope(context, tuple(payload.location_ids), organizations)
    try:
        invitation = await service.create(
            CreateInvitationCommand(
                organization_id=context.organization_id,
                invited_by=user.id,
                inviter_email=user.email,
                inviter_role=context.role,
                email=str(payload.email),
                role=payload.role,
                location_ids=tuple(payload.location_ids),
                employee_id=payload.employee_id,
            )
        )
    except (DuplicateInvitation, DuplicateMembership) as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "Invitation conflicts") from exc
    except (InvalidLocationAccess, InvalidRoleAssignment) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Invalid invitation") from exc
    except EmployeeNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Employee not found") from exc
    except InvitationNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organization not found") from exc
    return InvitationResponse.model_validate(invitation)


@router.get("/team/invitations", response_model=list[InvitationResponse])
async def list_invitations(
    context: TeamReadDep, service: InvitationServiceDep
) -> list[InvitationResponse]:
    invitations = await service.list(context.organization_id)
    return [InvitationResponse.model_validate(invitation) for invitation in invitations]


@router.post(
    "/team/invitations/{invitation_id}/revoke",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_invitation(
    invitation_id: UUID,
    context: TeamRemoveDep,
    service: InvitationServiceDep,
) -> Response:
    try:
        await service.revoke(RevokeInvitationCommand(context.organization_id, invitation_id))
    except InvitationNotFound as exc:
        raise _not_found() from exc
    except InvitationGone as exc:
        raise _gone() from exc
    except InvitationAlreadyAccepted as exc:
        raise _conflict() from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/team", response_model=TeamResponse)
async def list_team(context: TeamReadDep, service: InvitationServiceDep) -> TeamResponse:
    members = await service.team(context.organization_id)
    invitations = await service.list(context.organization_id)
    return TeamResponse(
        members=[TeamMemberResponse.model_validate(member) for member in members],
        invitations=[InvitationResponse.model_validate(invitation) for invitation in invitations],
        permissions=sorted(permission.value for permission in context.permissions),
    )


@router.get("/invitations/{token}", response_model=PublicInvitationResponse)
async def inspect_invitation(token: str, service: InvitationServiceDep) -> PublicInvitationResponse:
    try:
        invitation, organization_name = await service.inspect(token)
    except InvitationNotFound as exc:
        raise _not_found() from exc
    except InvitationGone as exc:
        raise _gone() from exc
    except InvitationAlreadyAccepted as exc:
        raise _conflict() from exc
    return PublicInvitationResponse(
        organization_name=organization_name,
        email=invitation.email,
        role=invitation.role,
        expires_at=invitation.expires_at,
    )


@router.post("/invitations/{token}/accept", status_code=status.HTTP_204_NO_CONTENT)
async def accept_invitation(
    token: str,
    user: CurrentUserDep,
    service: InvitationServiceDep,
) -> Response:
    try:
        await service.accept(
            AcceptInvitationCommand(
                token=token,
                user_id=user.id,
                user_email=user.email,
                first_name=user.first_name,
                last_name=user.last_name,
            )
        )
    except InvitationNotFound as exc:
        raise _not_found() from exc
    except InvitationGone as exc:
        raise _gone() from exc
    except (InvitationAlreadyAccepted, DuplicateMembership) as exc:
        raise _conflict() from exc
    except InvitationEmailMismatch as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invitation email mismatch") from exc
    except InvalidLocationAccess as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "Invitation is no longer valid") from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "Invitation not found")


def _gone() -> HTTPException:
    return HTTPException(status.HTTP_410_GONE, "Invitation expired or revoked")


def _conflict() -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, "Invitation already accepted")
