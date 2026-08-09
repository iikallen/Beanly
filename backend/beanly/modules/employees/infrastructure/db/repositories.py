from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from beanly.modules.employees.domain.entities import Employee
from beanly.modules.employees.infrastructure.db.mappers import to_employee
from beanly.modules.employees.infrastructure.db.models import (
    EmployeeLocationModel,
    EmployeeModel,
)
from beanly.modules.identity.infrastructure.db.models import UserModel
from beanly.modules.organizations.domain.entities import TeamMember
from beanly.modules.organizations.domain.enums import (
    LocationAccess,
    MembershipRole,
    MembershipStatus,
)
from beanly.modules.organizations.infrastructure.db.models import (
    LocationModel,
    MembershipLocationModel,
    OrganizationMembershipModel,
)


class SqlAlchemyEmployeeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, employee: Employee) -> Employee:
        model = EmployeeModel(
            id=employee.id,
            organization_id=employee.organization_id,
            user_id=employee.user_id,
            first_name=employee.first_name,
            last_name=employee.last_name,
            phone=employee.phone,
            position=employee.position,
            status=employee.status.value,
            created_at=employee.created_at,
            updated_at=employee.updated_at,
        )
        self.session.add(model)
        await self.session.flush()
        return to_employee(model, employee.location_ids)

    async def replace_locations(self, employee_id: UUID, location_ids: tuple[UUID, ...]) -> None:
        await self.session.execute(
            delete(EmployeeLocationModel).where(EmployeeLocationModel.employee_id == employee_id)
        )
        now = datetime.now(UTC)
        self.session.add_all(
            EmployeeLocationModel(
                employee_id=employee_id,
                location_id=location_id,
                created_at=now,
            )
            for location_id in location_ids
        )
        await self.session.flush()

    async def list_for_organization(self, organization_id: UUID) -> list[Employee]:
        models = list(
            await self.session.scalars(
                select(EmployeeModel)
                .where(EmployeeModel.organization_id == organization_id)
                .order_by(EmployeeModel.created_at)
            )
        )
        locations = await self._location_map([model.id for model in models])
        return [to_employee(model, locations.get(model.id, ())) for model in models]

    async def get(self, organization_id: UUID, employee_id: UUID) -> Employee | None:
        model = await self.session.scalar(
            select(EmployeeModel).where(
                EmployeeModel.id == employee_id,
                EmployeeModel.organization_id == organization_id,
            )
        )
        if model is None:
            return None
        locations = await self._location_map([model.id])
        return to_employee(model, locations.get(model.id, ()))

    async def update(self, employee: Employee) -> Employee:
        model = await self.session.scalar(
            select(EmployeeModel).where(
                EmployeeModel.id == employee.id,
                EmployeeModel.organization_id == employee.organization_id,
            )
        )
        if model is None:
            return employee
        model.first_name = employee.first_name
        model.last_name = employee.last_name
        model.phone = employee.phone
        model.position = employee.position
        model.user_id = employee.user_id
        model.status = employee.status.value
        model.updated_at = employee.updated_at
        await self.session.flush()
        return to_employee(model, employee.location_ids)

    async def get_by_user(self, organization_id: UUID, user_id: UUID) -> Employee | None:
        model = await self.session.scalar(
            select(EmployeeModel).where(
                EmployeeModel.organization_id == organization_id,
                EmployeeModel.user_id == user_id,
            )
        )
        if model is None:
            return None
        locations = await self._location_map([model.id])
        return to_employee(model, locations.get(model.id, ()))

    async def list_team_members(self, organization_id: UUID) -> list[TeamMember]:
        employees = await self.list_for_organization(organization_id)
        by_user = {employee.user_id: employee for employee in employees if employee.user_id}
        membership_rows = list(
            (
                await self.session.execute(
                    select(OrganizationMembershipModel, UserModel)
                    .join(UserModel, UserModel.id == OrganizationMembershipModel.user_id)
                    .where(
                        OrganizationMembershipModel.organization_id == organization_id,
                        OrganizationMembershipModel.status == MembershipStatus.ACTIVE.value,
                    )
                    .order_by(OrganizationMembershipModel.created_at)
                )
            ).all()
        )
        membership_ids = [membership.id for membership, _ in membership_rows]
        member_locations: dict[UUID, list[str]] = {}
        if membership_ids:
            rows = await self.session.execute(
                select(MembershipLocationModel.membership_id, LocationModel.name)
                .join(LocationModel, LocationModel.id == MembershipLocationModel.location_id)
                .where(MembershipLocationModel.membership_id.in_(membership_ids))
                .order_by(LocationModel.created_at)
            )
            for membership_id, name in rows:
                member_locations.setdefault(membership_id, []).append(name)

        result = [
            TeamMember(
                employee_id=(employee.id if (employee := by_user.get(user.id)) else None),
                user_id=user.id,
                first_name=employee.first_name if employee else user.first_name,
                last_name=employee.last_name if employee else user.last_name,
                phone=employee.phone if employee else None,
                position=employee.position if employee else None,
                email=user.email,
                role=MembershipRole(membership.role),
                status=membership.status,
                location_access=LocationAccess(membership.location_access),
                locations=tuple(member_locations.get(membership.id, ())),
            )
            for membership, user in membership_rows
        ]
        linked_ids = {member.employee_id for member in result if member.employee_id}
        employee_location_names = await self._employee_location_name_map(
            [employee.id for employee in employees if employee.id not in linked_ids]
        )
        result.extend(
            TeamMember(
                employee_id=employee.id,
                user_id=None,
                first_name=employee.first_name,
                last_name=employee.last_name,
                phone=employee.phone,
                position=employee.position,
                email=None,
                role=None,
                status=employee.status.value,
                location_access=None,
                locations=tuple(employee_location_names.get(employee.id, ())),
            )
            for employee in employees
            if employee.id not in linked_ids
        )
        return result

    async def locations_belong_to_organization(
        self, organization_id: UUID, location_ids: tuple[UUID, ...]
    ) -> bool:
        if not location_ids:
            return True
        count = await self.session.scalar(
            select(func.count())
            .select_from(LocationModel)
            .where(
                LocationModel.organization_id == organization_id,
                LocationModel.id.in_(location_ids),
            )
        )
        return count == len(location_ids)

    async def membership_role(self, organization_id: UUID, user_id: UUID) -> MembershipRole | None:
        value = await self.session.scalar(
            select(OrganizationMembershipModel.role).where(
                OrganizationMembershipModel.organization_id == organization_id,
                OrganizationMembershipModel.user_id == user_id,
            )
        )
        return MembershipRole(value) if value else None

    async def suspend_membership(self, organization_id: UUID, user_id: UUID) -> None:
        await self.session.execute(
            update(OrganizationMembershipModel)
            .where(
                OrganizationMembershipModel.organization_id == organization_id,
                OrganizationMembershipModel.user_id == user_id,
                OrganizationMembershipModel.role != MembershipRole.OWNER.value,
            )
            .values(status=MembershipStatus.SUSPENDED.value, updated_at=datetime.now(UTC))
        )

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()

    async def _location_map(self, employee_ids: list[UUID]) -> dict[UUID, tuple[UUID, ...]]:
        if not employee_ids:
            return {}
        rows = await self.session.execute(
            select(
                EmployeeLocationModel.employee_id,
                EmployeeLocationModel.location_id,
            )
            .where(EmployeeLocationModel.employee_id.in_(employee_ids))
            .order_by(EmployeeLocationModel.created_at)
        )
        result: dict[UUID, list[UUID]] = {}
        for employee_id, location_id in rows:
            result.setdefault(employee_id, []).append(location_id)
        return {employee_id: tuple(values) for employee_id, values in result.items()}

    async def _employee_location_name_map(self, employee_ids: list[UUID]) -> dict[UUID, list[str]]:
        if not employee_ids:
            return {}
        rows = await self.session.execute(
            select(EmployeeLocationModel.employee_id, LocationModel.name)
            .join(LocationModel, LocationModel.id == EmployeeLocationModel.location_id)
            .where(EmployeeLocationModel.employee_id.in_(employee_ids))
            .order_by(LocationModel.created_at)
        )
        result: dict[UUID, list[str]] = {}
        for employee_id, name in rows:
            result.setdefault(employee_id, []).append(name)
        return result
