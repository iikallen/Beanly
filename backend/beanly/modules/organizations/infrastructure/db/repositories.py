from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from beanly.modules.organizations.domain.entities import (
    Location,
    MembershipLocation,
    Organization,
    OrganizationMembership,
)
from beanly.modules.organizations.domain.enums import LocationAccess, MembershipStatus
from beanly.modules.organizations.domain.exceptions import DuplicateMembership
from beanly.modules.organizations.infrastructure.db.mappers import (
    to_location,
    to_membership,
    to_organization,
)
from beanly.modules.organizations.infrastructure.db.models import (
    LocationModel,
    MembershipLocationModel,
    OrganizationMembershipModel,
    OrganizationModel,
)


class SqlAlchemyOrganizationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add_organization(self, organization: Organization) -> Organization:
        model = OrganizationModel(
            id=organization.id,
            name=organization.name,
            country_code=organization.country_code,
            currency_code=organization.currency_code,
            status=organization.status.value,
            created_by=organization.created_by,
            created_at=organization.created_at,
            updated_at=organization.updated_at,
        )
        self.session.add(model)
        await self.session.flush()
        return to_organization(model)

    async def add_location(self, location: Location) -> Location:
        model = LocationModel(
            id=location.id,
            organization_id=location.organization_id,
            name=location.name,
            timezone=location.timezone,
            address=location.address,
            is_active=location.is_active,
            is_primary=location.is_primary,
            created_at=location.created_at,
            updated_at=location.updated_at,
        )
        self.session.add(model)
        await self.session.flush()
        return to_location(model)

    async def add_membership(self, membership: OrganizationMembership) -> OrganizationMembership:
        model = OrganizationMembershipModel(
            id=membership.id,
            organization_id=membership.organization_id,
            user_id=membership.user_id,
            role=membership.role.value,
            status=membership.status.value,
            location_access=membership.location_access.value,
            created_at=membership.created_at,
            updated_at=membership.updated_at,
        )
        self.session.add(model)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            raise DuplicateMembership from exc
        return to_membership(model)

    async def list_for_user(self, user_id: UUID) -> list[Organization]:
        models = await self.session.scalars(
            select(OrganizationModel)
            .join(
                OrganizationMembershipModel,
                OrganizationMembershipModel.organization_id == OrganizationModel.id,
            )
            .where(
                OrganizationMembershipModel.user_id == user_id,
                OrganizationMembershipModel.status == MembershipStatus.ACTIVE.value,
            )
            .order_by(OrganizationModel.created_at)
        )
        return [to_organization(model) for model in models]

    async def get_for_user(self, organization_id: UUID, user_id: UUID) -> Organization | None:
        model = await self.session.scalar(
            select(OrganizationModel)
            .join(
                OrganizationMembershipModel,
                OrganizationMembershipModel.organization_id == OrganizationModel.id,
            )
            .where(
                OrganizationModel.id == organization_id,
                OrganizationMembershipModel.user_id == user_id,
                OrganizationMembershipModel.status == MembershipStatus.ACTIVE.value,
            )
        )
        return to_organization(model) if model else None

    async def get_membership(
        self, organization_id: UUID, user_id: UUID
    ) -> OrganizationMembership | None:
        model = await self.session.scalar(
            select(OrganizationMembershipModel).where(
                OrganizationMembershipModel.organization_id == organization_id,
                OrganizationMembershipModel.user_id == user_id,
                OrganizationMembershipModel.status == MembershipStatus.ACTIVE.value,
            )
        )
        return to_membership(model) if model else None

    async def get_membership_any_status(
        self, organization_id: UUID, user_id: UUID
    ) -> OrganizationMembership | None:
        model = await self.session.scalar(
            select(OrganizationMembershipModel).where(
                OrganizationMembershipModel.organization_id == organization_id,
                OrganizationMembershipModel.user_id == user_id,
            )
        )
        return to_membership(model) if model else None

    async def add_membership_locations(self, locations: tuple[MembershipLocation, ...]) -> None:
        self.session.add_all(
            MembershipLocationModel(
                membership_id=location.membership_id,
                location_id=location.location_id,
                created_at=location.created_at,
            )
            for location in locations
        )
        await self.session.flush()

    async def locations_belong_to_organization(
        self, organization_id: UUID, location_ids: tuple[UUID, ...]
    ) -> bool:
        if not location_ids:
            return False
        count = await self.session.scalar(
            select(func.count())
            .select_from(LocationModel)
            .where(
                LocationModel.organization_id == organization_id,
                LocationModel.id.in_(location_ids),
                LocationModel.is_active.is_(True),
            )
        )
        return count == len(location_ids)

    async def membership_can_access_location(
        self, membership: OrganizationMembership, location_id: UUID
    ) -> bool:
        location_exists = await self.session.scalar(
            select(LocationModel.id).where(
                LocationModel.id == location_id,
                LocationModel.organization_id == membership.organization_id,
                LocationModel.is_active.is_(True),
            )
        )
        if location_exists is None:
            return False
        if membership.location_access is LocationAccess.ALL:
            return True
        assigned = await self.session.scalar(
            select(MembershipLocationModel.membership_id).where(
                MembershipLocationModel.membership_id == membership.id,
                MembershipLocationModel.location_id == location_id,
            )
        )
        return assigned is not None

    async def update_organization(self, organization: Organization) -> Organization:
        model = await self.session.get(OrganizationModel, organization.id)
        if model is None:
            return organization
        model.name = organization.name
        model.country_code = organization.country_code
        model.currency_code = organization.currency_code
        model.updated_at = organization.updated_at
        await self.session.flush()
        return to_organization(model)

    async def list_locations(self, organization_id: UUID) -> list[Location]:
        models = await self.session.scalars(
            select(LocationModel)
            .where(LocationModel.organization_id == organization_id)
            .order_by(LocationModel.is_primary.desc(), LocationModel.created_at)
        )
        return [to_location(model) for model in models]

    async def list_accessible_locations(self, membership: OrganizationMembership) -> list[Location]:
        statement = select(LocationModel).where(
            LocationModel.organization_id == membership.organization_id
        )
        if membership.location_access is LocationAccess.SELECTED:
            statement = statement.join(
                MembershipLocationModel,
                MembershipLocationModel.location_id == LocationModel.id,
            ).where(MembershipLocationModel.membership_id == membership.id)
        models = await self.session.scalars(
            statement.order_by(LocationModel.is_primary.desc(), LocationModel.created_at)
        )
        return [to_location(model) for model in models]

    async def get_location(self, organization_id: UUID, location_id: UUID) -> Location | None:
        model = await self.session.scalar(
            select(LocationModel).where(
                LocationModel.id == location_id,
                LocationModel.organization_id == organization_id,
            )
        )
        return to_location(model) if model else None

    async def update_location(self, location: Location) -> Location:
        model = await self.session.get(LocationModel, location.id)
        if model is None:
            return location
        model.name = location.name
        model.timezone = location.timezone
        model.address = location.address
        model.is_active = location.is_active
        model.updated_at = location.updated_at
        await self.session.flush()
        return to_location(model)

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()
