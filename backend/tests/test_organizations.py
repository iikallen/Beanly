from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from beanly.core.database.session import get_session
from beanly.modules.identity.infrastructure.db.models import UserModel
from beanly.modules.identity.infrastructure.db.repositories import to_user
from beanly.modules.organizations.api.dependencies import (
    TenantContextDep,
    get_tenant_context,
)
from beanly.modules.organizations.application.commands.create_organization import (
    CreateOrganizationCommand,
)
from beanly.modules.organizations.application.services.organization_service import (
    OrganizationService,
)
from beanly.modules.organizations.domain.entities import OrganizationMembership
from beanly.modules.organizations.domain.enums import (
    LocationAccess,
    MembershipRole,
    MembershipStatus,
)
from beanly.modules.organizations.domain.exceptions import DuplicateMembership
from beanly.modules.organizations.infrastructure.db.models import (
    LocationModel,
    OrganizationMembershipModel,
    OrganizationModel,
)
from beanly.modules.organizations.infrastructure.db.repositories import (
    SqlAlchemyOrganizationRepository,
)


def workspace_payload(name: str = "Bean Coffee") -> dict:
    return {
        "name": name,
        "country_code": "kz",
        "currency_code": "kzt",
        "first_location": {
            "name": "Dostyk",
            "timezone": "Asia/Almaty",
            "address": "Dostyk 123",
        },
    }


async def authenticated_user(
    client: AsyncClient, email: str, first_name: str = "Owner"
) -> dict[str, str]:
    payload = {
        "email": email,
        "password": "correct-horse-battery-staple",
        "first_name": first_name,
        "last_name": "Beanly",
    }
    assert (await client.post("/api/v1/auth/register", json=payload)).status_code == 201
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": payload["email"], "password": payload["password"]},
    )
    assert login.status_code == 200
    return {"authorization": f"Bearer {login.json()['access_token']}"}


@pytest.mark.anyio
async def test_onboarding_creates_organization_location_and_owner(app_client) -> None:
    client, sessions = app_client
    headers = await authenticated_user(client, "stage2-owner@example.com")

    response = await client.post("/api/v1/organizations", json=workspace_payload(), headers=headers)

    assert response.status_code == 201
    body = response.json()
    assert body["organization"]["country_code"] == "KZ"
    assert body["organization"]["currency_code"] == "KZT"
    assert body["location"]["name"] == "Dostyk"
    assert body["location"]["is_primary"] is True
    assert body["membership"]["role"] == "OWNER"

    async with sessions() as session:
        organization = await session.scalar(select(OrganizationModel))
        location = await session.scalar(select(LocationModel))
        membership = await session.scalar(select(OrganizationMembershipModel))
    assert organization is not None
    assert location is not None and location.organization_id == organization.id
    assert membership is not None and membership.organization_id == organization.id
    assert membership.role == MembershipRole.OWNER.value


@pytest.mark.anyio
async def test_organization_creation_requires_authentication(app_client) -> None:
    client, _ = app_client
    response = await client.post("/api/v1/organizations", json=workspace_payload())
    assert response.status_code == 401


@pytest.mark.anyio
async def test_users_only_see_and_change_their_organizations(app_client) -> None:
    client, _ = app_client
    user_a = await authenticated_user(client, "tenant-a@example.com", "A")
    organization_a = (
        await client.post(
            "/api/v1/organizations", json=workspace_payload("Coffee A"), headers=user_a
        )
    ).json()["organization"]
    user_b = await authenticated_user(client, "tenant-b@example.com", "B")
    organization_b = (
        await client.post(
            "/api/v1/organizations", json=workspace_payload("Coffee B"), headers=user_b
        )
    ).json()["organization"]

    listed = await client.get("/api/v1/organizations", headers=user_a)
    assert [item["id"] for item in listed.json()] == [organization_a["id"]]
    assert (
        await client.get(f"/api/v1/organizations/{organization_b['id']}", headers=user_a)
    ).status_code == 404
    assert (
        await client.patch(
            f"/api/v1/organizations/{organization_b['id']}",
            json={"name": "Stolen"},
            headers=user_a,
        )
    ).status_code == 404

    updated = await client.patch(
        f"/api/v1/organizations/{organization_a['id']}",
        json={"name": "Coffee A Updated"},
        headers=user_a,
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Coffee A Updated"
    immutable_currency = await client.patch(
        f"/api/v1/organizations/{organization_a['id']}",
        json={"currency_code": "USD"},
        headers=user_a,
    )
    assert immutable_currency.status_code == 409


@pytest.mark.anyio
async def test_locations_are_scoped_and_second_location_is_not_primary(app_client) -> None:
    client, _ = app_client
    user_a = await authenticated_user(client, "locations-a@example.com", "A")
    created_a = (
        await client.post(
            "/api/v1/organizations", json=workspace_payload("Locations A"), headers=user_a
        )
    ).json()
    user_b = await authenticated_user(client, "locations-b@example.com", "B")
    created_b = (
        await client.post(
            "/api/v1/organizations", json=workspace_payload("Locations B"), headers=user_b
        )
    ).json()
    organization_a = created_a["organization"]["id"]
    organization_b = created_b["organization"]["id"]
    location_b = created_b["location"]["id"]

    second = await client.post(
        f"/api/v1/organizations/{organization_a}/locations",
        json={"name": "Mega", "timezone": "Asia/Almaty"},
        headers=user_a,
    )
    assert second.status_code == 201
    assert second.json()["is_primary"] is False

    listed = await client.get(f"/api/v1/organizations/{organization_a}/locations", headers=user_a)
    assert [item["name"] for item in listed.json()] == ["Dostyk", "Mega"]
    assert (
        await client.get(
            f"/api/v1/organizations/{organization_a}/locations/{location_b}",
            headers=user_a,
        )
    ).status_code == 404
    assert (
        await client.get(f"/api/v1/organizations/{organization_b}/locations", headers=user_a)
    ).status_code == 404

    updated = await client.patch(
        f"/api/v1/organizations/{organization_a}/locations/{second.json()['id']}",
        json={
            "name": "Mega Center",
            "timezone": "Europe/Warsaw",
            "address": None,
            "is_active": False,
        },
        headers=user_a,
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Mega Center"
    assert updated.json()["timezone"] == "Europe/Warsaw"
    assert updated.json()["address"] is None
    assert updated.json()["is_active"] is False


@pytest.mark.anyio
async def test_invalid_timezone_and_empty_patches_are_rejected(app_client) -> None:
    client, _ = app_client
    headers = await authenticated_user(client, "validation@example.com")
    invalid = workspace_payload()
    invalid["first_location"]["timezone"] = "UTC+5"
    assert (
        await client.post("/api/v1/organizations", json=invalid, headers=headers)
    ).status_code == 422

    created = await client.post("/api/v1/organizations", json=workspace_payload(), headers=headers)
    organization_id = created.json()["organization"]["id"]
    location_id = created.json()["location"]["id"]
    assert (
        await client.patch(f"/api/v1/organizations/{organization_id}", json={}, headers=headers)
    ).status_code == 422
    assert (
        await client.patch(
            f"/api/v1/organizations/{organization_id}/locations/{location_id}",
            json={"timezone": "UTC+5"},
            headers=headers,
        )
    ).status_code == 422


@pytest.mark.anyio
async def test_tenant_context_accepts_member_and_rejects_foreign_header(app_client) -> None:
    client, sessions = app_client
    user_a_headers = await authenticated_user(client, "context-a@example.com", "A")
    organization_a = (
        await client.post(
            "/api/v1/organizations", json=workspace_payload("Context A"), headers=user_a_headers
        )
    ).json()["organization"]["id"]
    user_b_headers = await authenticated_user(client, "context-b@example.com", "B")
    organization_b = (
        await client.post(
            "/api/v1/organizations", json=workspace_payload("Context B"), headers=user_b_headers
        )
    ).json()["organization"]["id"]

    async with sessions() as session:
        user_a_model = await session.scalar(
            select(UserModel).where(UserModel.email == "context-a@example.com")
        )
        assert user_a_model is not None
        user_a = to_user(user_a_model)
        service = OrganizationService(SqlAlchemyOrganizationRepository(session))
        tenant = await get_tenant_context(user_a, service, UUID(organization_a))
        assert tenant.organization_id.hex == organization_a.replace("-", "")
        assert tenant.role is MembershipRole.OWNER
        with pytest.raises(HTTPException) as denied:
            await get_tenant_context(user_a, service, UUID(organization_b))
        assert denied.value.status_code == 403


@pytest.mark.anyio
async def test_tenant_context_dependency_validates_header_and_membership(app_client) -> None:
    client, sessions = app_client
    user_a = await authenticated_user(client, "tenant-header-a@example.com", "A")
    organization_a = (
        await client.post(
            "/api/v1/organizations",
            json=workspace_payload("Tenant Header A"),
            headers=user_a,
        )
    ).json()["organization"]["id"]
    user_b = await authenticated_user(client, "tenant-header-b@example.com", "B")
    organization_b = (
        await client.post(
            "/api/v1/organizations",
            json=workspace_payload("Tenant Header B"),
            headers=user_b,
        )
    ).json()["organization"]["id"]

    tenant_app = FastAPI()

    async def override_session():
        async with sessions() as session:
            yield session

    @tenant_app.get("/tenant")
    async def tenant_probe(tenant: TenantContextDep) -> dict[str, str]:
        return {
            "user_id": str(tenant.user_id),
            "organization_id": str(tenant.organization_id),
            "role": tenant.role.value,
        }

    tenant_app.dependency_overrides[get_session] = override_session
    async with AsyncClient(
        transport=ASGITransport(app=tenant_app), base_url="http://tenant-test"
    ) as tenant_client:
        assert (await tenant_client.get("/tenant", headers=user_a)).status_code == 422
        malformed = {**user_a, "X-Organization-ID": "not-a-uuid"}
        assert (await tenant_client.get("/tenant", headers=malformed)).status_code == 422
        own = {**user_a, "X-Organization-ID": organization_a}
        own_response = await tenant_client.get("/tenant", headers=own)
        assert own_response.status_code == 200
        assert own_response.json()["organization_id"] == organization_a
        assert own_response.json()["role"] == MembershipRole.OWNER.value
        foreign = {**user_a, "X-Organization-ID": organization_b}
        assert (await tenant_client.get("/tenant", headers=foreign)).status_code == 403


@pytest.mark.anyio
async def test_duplicate_membership_is_rejected_by_repository(app_client) -> None:
    client, sessions = app_client
    headers = await authenticated_user(client, "duplicate-membership@example.com")
    created = await client.post("/api/v1/organizations", json=workspace_payload(), headers=headers)
    organization_id = created.json()["organization"]["id"]

    async with sessions() as session:
        existing = await session.scalar(select(OrganizationMembershipModel))
        assert existing is not None
        repository = SqlAlchemyOrganizationRepository(session)
        now = datetime.now(UTC)
        duplicate = OrganizationMembership(
            id=uuid4(),
            organization_id=existing.organization_id,
            user_id=existing.user_id,
            role=MembershipRole.OWNER,
            status=MembershipStatus.ACTIVE,
            location_access=LocationAccess.ALL,
            created_at=now,
            updated_at=now,
        )
        with pytest.raises(DuplicateMembership):
            await repository.add_membership(duplicate)
        await repository.rollback()

        count = await session.scalar(
            select(func.count())
            .select_from(OrganizationMembershipModel)
            .where(OrganizationMembershipModel.organization_id == UUID(organization_id))
        )
    assert count == 1


@pytest.mark.anyio
async def test_workspace_service_rolls_back_when_location_creation_fails() -> None:
    class FailingRepository:
        def __init__(self) -> None:
            self.organizations = []
            self.committed = False
            self.rolled_back = False

        async def add_organization(self, organization):
            self.organizations.append(organization)

        async def add_location(self, location):
            raise RuntimeError("location insert failed")

        async def rollback(self):
            self.organizations.clear()
            self.rolled_back = True

        async def commit(self):
            self.committed = True

    repository = FailingRepository()
    service = OrganizationService(repository)  # type: ignore[arg-type]
    command = CreateOrganizationCommand(
        user_id=uuid4(),
        name="Atomic Coffee",
        country_code="KZ",
        currency_code="KZT",
        location_name="Dostyk",
        timezone="Asia/Almaty",
    )
    with pytest.raises(RuntimeError, match="location insert failed"):
        await service.create_workspace(command)
    assert repository.organizations == []
    assert repository.rolled_back is True
    assert repository.committed is False
