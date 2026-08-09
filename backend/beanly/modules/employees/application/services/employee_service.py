from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

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
from beanly.modules.employees.domain.entities import Employee
from beanly.modules.employees.domain.enums import EmployeeStatus
from beanly.modules.employees.domain.exceptions import (
    EmployeeNotFound,
    InvalidEmployeeLocations,
    OwnerEmployeeImmutable,
)
from beanly.modules.employees.domain.repositories import EmployeeRepository
from beanly.modules.organizations.domain.enums import MembershipRole


class EmployeeService:
    def __init__(self, repository: EmployeeRepository) -> None:
        self.repository = repository

    async def create(self, command: CreateEmployeeCommand) -> Employee:
        locations = _unique(command.location_ids)
        if not await self.repository.locations_belong_to_organization(
            command.organization_id, locations
        ):
            raise InvalidEmployeeLocations
        now = datetime.now(UTC)
        employee = Employee(
            id=uuid4(),
            organization_id=command.organization_id,
            user_id=None,
            first_name=_required(command.first_name, "First name", 100),
            last_name=_required(command.last_name, "Last name", 100),
            phone=_optional(command.phone, 40),
            position=_optional(command.position, 100),
            status=EmployeeStatus.ACTIVE,
            location_ids=locations,
            created_at=now,
            updated_at=now,
        )
        try:
            await self.repository.add(employee)
            await self.repository.replace_locations(employee.id, locations)
            await self.repository.commit()
        except Exception:
            await self.repository.rollback()
            raise
        return employee

    async def list(self, query: ListEmployeesQuery) -> list[Employee]:
        return await self.repository.list_for_organization(query.organization_id)

    async def get(self, query: GetEmployeeQuery) -> Employee:
        employee = await self.repository.get(query.organization_id, query.employee_id)
        if employee is None:
            raise EmployeeNotFound
        return employee

    async def update(self, command: UpdateEmployeeCommand) -> Employee:
        employee = await self.get(GetEmployeeQuery(command.organization_id, command.employee_id))
        locations = (
            _unique(command.location_ids)
            if command.location_ids is not None
            else employee.location_ids
        )
        if not await self.repository.locations_belong_to_organization(
            command.organization_id, locations
        ):
            raise InvalidEmployeeLocations
        updated = replace(
            employee,
            first_name=(
                _required(command.first_name, "First name", 100)
                if command.first_name is not None
                else employee.first_name
            ),
            last_name=(
                _required(command.last_name, "Last name", 100)
                if command.last_name is not None
                else employee.last_name
            ),
            phone=_optional(command.phone, 40) if command.phone_set else employee.phone,
            position=(
                _optional(command.position, 100) if command.position_set else employee.position
            ),
            location_ids=locations,
            updated_at=datetime.now(UTC),
        )
        try:
            await self.repository.update(updated)
            if command.location_ids is not None:
                await self.repository.replace_locations(updated.id, locations)
            await self.repository.commit()
        except Exception:
            await self.repository.rollback()
            raise
        return updated

    async def deactivate(self, command: DeactivateEmployeeCommand) -> None:
        employee = await self.get(GetEmployeeQuery(command.organization_id, command.employee_id))
        if employee.user_id is not None:
            role = await self.repository.membership_role(command.organization_id, employee.user_id)
            if role is MembershipRole.OWNER:
                raise OwnerEmployeeImmutable
        updated = replace(
            employee,
            status=EmployeeStatus.INACTIVE,
            updated_at=datetime.now(UTC),
        )
        try:
            await self.repository.update(updated)
            if employee.user_id is not None:
                await self.repository.suspend_membership(command.organization_id, employee.user_id)
            await self.repository.commit()
        except Exception:
            await self.repository.rollback()
            raise


def _required(value: str, label: str, maximum: int) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise ValueError(f"{label} must contain between 1 and {maximum} characters")
    return normalized


def _optional(value: str | None, maximum: int) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if len(normalized) > maximum:
        raise ValueError(f"Value must not exceed {maximum} characters")
    return normalized or None


def _unique(values: tuple) -> tuple:
    return tuple(dict.fromkeys(values))
