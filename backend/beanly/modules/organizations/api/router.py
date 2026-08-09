from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from beanly.modules.identity.api.dependencies import CurrentUserDep
from beanly.modules.organizations.api.dependencies import (
    OrganizationServiceDep,
    TenantContextDep,
)
from beanly.modules.organizations.api.schemas import (
    CreatedWorkspaceResponse,
    CreateLocationRequest,
    CreateOrganizationRequest,
    LocationResponse,
    MembershipResponse,
    OrganizationResponse,
    TenantContextResponse,
    UpdateLocationRequest,
    UpdateOrganizationRequest,
)
from beanly.modules.organizations.application.commands.create_location import (
    CreateLocationCommand,
)
from beanly.modules.organizations.application.commands.create_organization import (
    CreateOrganizationCommand,
)
from beanly.modules.organizations.application.commands.update_location import (
    UpdateLocationCommand,
)
from beanly.modules.organizations.application.commands.update_organization import (
    UpdateOrganizationCommand,
)
from beanly.modules.organizations.application.queries.get_organization import (
    GetOrganizationQuery,
)
from beanly.modules.organizations.application.queries.list_locations import ListLocationsQuery
from beanly.modules.organizations.application.queries.list_user_organizations import (
    ListUserOrganizationsQuery,
)
from beanly.modules.organizations.domain.exceptions import (
    CurrencyLocked,
    DuplicateMembership,
    LocationNotFound,
    OrganizationNotFound,
    PermissionDenied,
)

router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.post("", response_model=CreatedWorkspaceResponse, status_code=status.HTTP_201_CREATED)
async def create_organization(
    payload: CreateOrganizationRequest,
    user: CurrentUserDep,
    service: OrganizationServiceDep,
) -> CreatedWorkspaceResponse:
    try:
        created = await service.create_workspace(
            CreateOrganizationCommand(
                user_id=user.id,
                name=payload.name,
                country_code=payload.country_code,
                currency_code=payload.currency_code,
                location_name=payload.first_location.name,
                timezone=payload.first_location.timezone,
                address=payload.first_location.address,
            )
        )
    except DuplicateMembership as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "Duplicate membership") from exc
    return CreatedWorkspaceResponse(
        organization=OrganizationResponse.model_validate(created.organization),
        location=LocationResponse.model_validate(created.location),
        membership=MembershipResponse(role=created.membership.role.value),
    )


@router.get("", response_model=list[OrganizationResponse])
async def list_organizations(
    user: CurrentUserDep, service: OrganizationServiceDep
) -> list[OrganizationResponse]:
    organizations = await service.list_organizations(ListUserOrganizationsQuery(user.id))
    return [OrganizationResponse.model_validate(item) for item in organizations]


@router.get("/context", response_model=TenantContextResponse)
async def tenant_context(
    context: TenantContextDep, service: OrganizationServiceDep
) -> TenantContextResponse:
    locations = await service.list_locations(
        ListLocationsQuery(context.user_id, context.organization_id)
    )
    return TenantContextResponse(
        organization_id=context.organization_id,
        user_id=context.user_id,
        membership_id=context.membership_id,
        role=context.role,
        permissions=sorted(permission.value for permission in context.permissions),
        location_access=context.location_access,
        location_ids=[location.id for location in locations if location.is_active],
    )


@router.get("/{organization_id}", response_model=OrganizationResponse)
async def get_organization(
    organization_id: UUID,
    user: CurrentUserDep,
    service: OrganizationServiceDep,
) -> OrganizationResponse:
    try:
        organization = await service.get_organization(
            GetOrganizationQuery(user.id, organization_id)
        )
    except OrganizationNotFound as exc:
        raise _organization_not_found() from exc
    return OrganizationResponse.model_validate(organization)


@router.patch("/{organization_id}", response_model=OrganizationResponse)
async def update_organization(
    organization_id: UUID,
    payload: UpdateOrganizationRequest,
    user: CurrentUserDep,
    service: OrganizationServiceDep,
) -> OrganizationResponse:
    try:
        organization = await service.update_organization(
            UpdateOrganizationCommand(
                user_id=user.id,
                organization_id=organization_id,
                name=payload.name,
                country_code=payload.country_code,
                currency_code=payload.currency_code,
            )
        )
    except OrganizationNotFound as exc:
        raise _organization_not_found() from exc
    except PermissionDenied as exc:
        raise _forbidden() from exc
    except CurrencyLocked as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return OrganizationResponse.model_validate(organization)


@router.post(
    "/{organization_id}/locations",
    response_model=LocationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_location(
    organization_id: UUID,
    payload: CreateLocationRequest,
    user: CurrentUserDep,
    service: OrganizationServiceDep,
) -> LocationResponse:
    try:
        location = await service.create_location(
            CreateLocationCommand(
                user.id,
                organization_id,
                payload.name,
                payload.timezone,
                payload.address,
            )
        )
    except OrganizationNotFound as exc:
        raise _organization_not_found() from exc
    except PermissionDenied as exc:
        raise _forbidden() from exc
    return LocationResponse.model_validate(location)


@router.get("/{organization_id}/locations", response_model=list[LocationResponse])
async def list_locations(
    organization_id: UUID,
    user: CurrentUserDep,
    service: OrganizationServiceDep,
) -> list[LocationResponse]:
    try:
        locations = await service.list_locations(ListLocationsQuery(user.id, organization_id))
    except OrganizationNotFound as exc:
        raise _organization_not_found() from exc
    return [LocationResponse.model_validate(item) for item in locations]


@router.get("/{organization_id}/locations/{location_id}", response_model=LocationResponse)
async def get_location(
    organization_id: UUID,
    location_id: UUID,
    user: CurrentUserDep,
    service: OrganizationServiceDep,
) -> LocationResponse:
    try:
        location = await service.get_location(user.id, organization_id, location_id)
    except OrganizationNotFound as exc:
        raise _organization_not_found() from exc
    except LocationNotFound as exc:
        raise _location_not_found() from exc
    except PermissionDenied as exc:
        raise _forbidden() from exc
    return LocationResponse.model_validate(location)


@router.patch("/{organization_id}/locations/{location_id}", response_model=LocationResponse)
async def update_location(
    organization_id: UUID,
    location_id: UUID,
    payload: UpdateLocationRequest,
    user: CurrentUserDep,
    service: OrganizationServiceDep,
) -> LocationResponse:
    try:
        location = await service.update_location(
            UpdateLocationCommand(
                user_id=user.id,
                organization_id=organization_id,
                location_id=location_id,
                name=payload.name,
                timezone=payload.timezone,
                address=payload.address,
                address_set="address" in payload.model_fields_set,
                is_active=payload.is_active,
            )
        )
    except OrganizationNotFound as exc:
        raise _organization_not_found() from exc
    except LocationNotFound as exc:
        raise _location_not_found() from exc
    except PermissionDenied as exc:
        raise _forbidden() from exc
    return LocationResponse.model_validate(location)


def _organization_not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "Organization not found")


def _location_not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "Location not found")


def _forbidden() -> HTTPException:
    return HTTPException(status.HTTP_403_FORBIDDEN, "Permission denied")
