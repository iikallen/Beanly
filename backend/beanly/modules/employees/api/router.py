from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status

from beanly.modules.employees.api.schemas import (
    CreateEmployeeRequest,
    EmployeeResponse,
    UpdateEmployeeRequest,
)
from beanly.modules.employees.application.commands.create_employee import (
    CreateEmployeeCommand,
)
from beanly.modules.employees.application.commands.deactivate_employee import (
    DeactivateEmployeeCommand,
)
from beanly.modules.employees.application.commands.update_employee import (
    UpdateEmployeeCommand,
)
from beanly.modules.employees.application.queries.get_employee import GetEmployeeQuery
from beanly.modules.employees.application.queries.list_employees import ListEmployeesQuery
from beanly.modules.employees.domain.exceptions import (
    EmployeeNotFound,
    InvalidEmployeeLocations,
    OwnerEmployeeImmutable,
)
from beanly.modules.organizations.api.dependencies import (
    EmployeeServiceDep,
    OrganizationServiceDep,
    ensure_location_scope,
    require_permission,
)
from beanly.modules.organizations.domain.entities import TenantContext
from beanly.modules.organizations.domain.permissions import Permission

router = APIRouter(prefix="/employees", tags=["employees"])

TeamReadDep = Annotated[TenantContext, Depends(require_permission(Permission.TEAM_READ))]
TeamUpdateDep = Annotated[TenantContext, Depends(require_permission(Permission.TEAM_UPDATE))]
TeamRemoveDep = Annotated[TenantContext, Depends(require_permission(Permission.TEAM_REMOVE))]


@router.post("", response_model=EmployeeResponse, status_code=status.HTTP_201_CREATED)
async def create_employee(
    payload: CreateEmployeeRequest,
    context: TeamUpdateDep,
    service: EmployeeServiceDep,
    organizations: OrganizationServiceDep,
) -> EmployeeResponse:
    await ensure_location_scope(context, tuple(payload.location_ids), organizations)
    try:
        employee = await service.create(
            CreateEmployeeCommand(
                organization_id=context.organization_id,
                first_name=payload.first_name,
                last_name=payload.last_name,
                phone=payload.phone,
                position=payload.position,
                location_ids=tuple(payload.location_ids),
            )
        )
    except InvalidEmployeeLocations as exc:
        raise _invalid_locations() from exc
    return EmployeeResponse.model_validate(employee)


@router.get("", response_model=list[EmployeeResponse])
async def list_employees(
    context: TeamReadDep, service: EmployeeServiceDep
) -> list[EmployeeResponse]:
    employees = await service.list(ListEmployeesQuery(context.organization_id))
    return [EmployeeResponse.model_validate(employee) for employee in employees]


@router.get("/{employee_id}", response_model=EmployeeResponse)
async def get_employee(
    employee_id: UUID,
    context: TeamReadDep,
    service: EmployeeServiceDep,
) -> EmployeeResponse:
    try:
        employee = await service.get(GetEmployeeQuery(context.organization_id, employee_id))
    except EmployeeNotFound as exc:
        raise _not_found() from exc
    return EmployeeResponse.model_validate(employee)


@router.patch("/{employee_id}", response_model=EmployeeResponse)
async def update_employee(
    employee_id: UUID,
    payload: UpdateEmployeeRequest,
    context: TeamUpdateDep,
    service: EmployeeServiceDep,
    organizations: OrganizationServiceDep,
) -> EmployeeResponse:
    if payload.location_ids is not None:
        await ensure_location_scope(context, tuple(payload.location_ids), organizations)
    try:
        employee = await service.update(
            UpdateEmployeeCommand(
                organization_id=context.organization_id,
                employee_id=employee_id,
                first_name=payload.first_name,
                last_name=payload.last_name,
                phone=payload.phone,
                phone_set="phone" in payload.model_fields_set,
                position=payload.position,
                position_set="position" in payload.model_fields_set,
                location_ids=(
                    tuple(payload.location_ids) if payload.location_ids is not None else None
                ),
            )
        )
    except EmployeeNotFound as exc:
        raise _not_found() from exc
    except InvalidEmployeeLocations as exc:
        raise _invalid_locations() from exc
    return EmployeeResponse.model_validate(employee)


@router.post("/{employee_id}/deactivate", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_employee(
    employee_id: UUID,
    context: TeamRemoveDep,
    service: EmployeeServiceDep,
) -> Response:
    try:
        await service.deactivate(DeactivateEmployeeCommand(context.organization_id, employee_id))
    except EmployeeNotFound as exc:
        raise _not_found() from exc
    except OwnerEmployeeImmutable as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "Owner cannot be deactivated") from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "Employee not found")


def _invalid_locations() -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Invalid locations")
