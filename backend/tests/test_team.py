from hashlib import sha256
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from beanly.modules.employees.infrastructure.db.models import EmployeeModel
from beanly.modules.organizations.domain.enums import MembershipRole
from beanly.modules.organizations.domain.permissions import Permission, permissions_for
from beanly.modules.organizations.infrastructure.db.models import (
    OrganizationInvitationModel,
    OrganizationMembershipModel,
)


def workspace_payload(name: str) -> dict:
    return {
        "name": name,
        "country_code": "KZ",
        "currency_code": "KZT",
        "first_location": {
            "name": "Dostyk",
            "timezone": "Asia/Almaty",
            "address": "Dostyk 123",
        },
    }


async def authenticated_user(
    client: AsyncClient, email: str, first_name: str = "Team"
) -> dict[str, str]:
    payload = {
        "email": email,
        "password": "correct-horse-battery-staple",
        "first_name": first_name,
        "last_name": "Beanly",
    }
    assert (await client.post("/api/v1/auth/register", json=payload)).status_code == 201
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": payload["password"]},
    )
    assert response.status_code == 200
    return {"authorization": f"Bearer {response.json()['access_token']}"}


async def workspace(
    client: AsyncClient, headers: dict[str, str], name: str
) -> tuple[dict[str, str], str, str]:
    response = await client.post(
        "/api/v1/organizations", json=workspace_payload(name), headers=headers
    )
    assert response.status_code == 201
    body = response.json()
    organization_id = body["organization"]["id"]
    location_id = body["location"]["id"]
    return {**headers, "X-Organization-ID": organization_id}, organization_id, location_id


def test_permission_matrix_is_fixed_and_owner_has_every_permission() -> None:
    assert permissions_for(MembershipRole.OWNER) == frozenset(Permission)
    assert Permission.ORGANIZATION_UPDATE not in permissions_for(MembershipRole.ADMIN)
    assert Permission.TEAM_INVITE in permissions_for(MembershipRole.ADMIN)
    assert permissions_for(MembershipRole.MANAGER) & {
        Permission.TEAM_READ,
        Permission.INVENTORY_WRITE,
        Permission.MENU_WRITE,
    } == {
        Permission.TEAM_READ,
        Permission.INVENTORY_WRITE,
        Permission.MENU_WRITE,
    }
    assert Permission.FINANCE_WRITE in permissions_for(MembershipRole.ACCOUNTANT)
    assert Permission.INVENTORY_ADJUST in permissions_for(MembershipRole.ADMIN)
    assert Permission.INVENTORY_ADJUST in permissions_for(MembershipRole.MANAGER)
    assert Permission.INVENTORY_READ in permissions_for(MembershipRole.ACCOUNTANT)
    assert Permission.PAYMENTS_CREATE in permissions_for(MembershipRole.CASHIER)
    assert Permission.INVENTORY_READ_LIMITED in permissions_for(MembershipRole.BARISTA)


@pytest.mark.anyio
async def test_employee_crud_is_tenant_scoped_and_owner_is_immutable(app_client) -> None:
    client, _ = app_client
    owner = await authenticated_user(client, "employees-owner@example.com", "Owner")
    headers, _, location_id = await workspace(client, owner, "Employees Coffee")

    missing_header = await client.get("/api/v1/employees", headers=owner)
    assert missing_header.status_code == 422

    created = await client.post(
        "/api/v1/employees",
        headers=headers,
        json={
            "first_name": "Dana",
            "last_name": "Barista",
            "phone": "+77010000000",
            "position": "Barista",
            "location_ids": [location_id],
        },
    )
    assert created.status_code == 201
    employee_id = created.json()["id"]
    assert created.json()["location_ids"] == [location_id]

    listed = await client.get("/api/v1/employees", headers=headers)
    assert [employee["id"] for employee in listed.json()] == [employee_id]
    updated = await client.patch(
        f"/api/v1/employees/{employee_id}",
        headers=headers,
        json={"position": "Lead barista"},
    )
    assert updated.status_code == 200
    assert updated.json()["position"] == "Lead barista"

    foreign_owner = await authenticated_user(client, "foreign-owner@example.com", "Other")
    foreign_headers, _, _ = await workspace(client, foreign_owner, "Foreign Coffee")
    assert (
        await client.get(f"/api/v1/employees/{employee_id}", headers=foreign_headers)
    ).status_code == 404

    team = await client.get("/api/v1/team", headers=headers)
    owner_member = next(member for member in team.json()["members"] if member["role"] == "OWNER")
    assert owner_member["employee_id"] is None
    employee_member = next(
        member for member in team.json()["members"] if member["employee_id"] == employee_id
    )
    assert employee_member["phone"] == "+77010000000"
    assert employee_member["position"] == "Lead barista"
    assert employee_member["user_id"] is None

    assert (
        await client.post(f"/api/v1/employees/{employee_id}/deactivate", headers=headers)
    ).status_code == 204


@pytest.mark.anyio
async def test_invitation_token_is_hash_only_and_acceptance_is_single_use(
    app_client, monkeypatch
) -> None:
    client, sessions = app_client
    raw_token = "stage3-invitation-token-with-at-least-thirty-two-characters"
    token_hash = sha256(raw_token.encode()).hexdigest()
    monkeypatch.setattr(
        "beanly.modules.organizations.application.services.invitation_service."
        "create_invitation_token",
        lambda: (raw_token, token_hash),
    )
    owner = await authenticated_user(client, "invite-owner@example.com", "Owner")
    headers, organization_id, location_id = await workspace(client, owner, "Invite Coffee")
    member = await authenticated_user(client, "manager@example.com", "Mira")

    invited = await client.post(
        "/api/v1/team/invitations",
        headers=headers,
        json={
            "email": "manager@example.com",
            "role": "MANAGER",
            "location_ids": [location_id],
        },
    )
    assert invited.status_code == 201
    assert "token" not in invited.json()
    assert "token_hash" not in invited.json()

    async with sessions() as session:
        stored = await session.scalar(select(OrganizationInvitationModel))
        assert stored is not None
        assert stored.token_hash == token_hash
        assert raw_token not in stored.token_hash

    inspected = await client.get(f"/api/v1/invitations/{raw_token}")
    assert inspected.status_code == 200
    assert inspected.json()["organization_name"] == "Invite Coffee"

    accepted = await client.post(f"/api/v1/invitations/{raw_token}/accept", headers=member)
    assert accepted.status_code == 204
    assert (
        await client.post(f"/api/v1/invitations/{raw_token}/accept", headers=member)
    ).status_code == 409

    member_headers = {**member, "X-Organization-ID": organization_id}
    team = await client.get("/api/v1/team", headers=member_headers)
    assert team.status_code == 200
    manager = next(member for member in team.json()["members"] if member["role"] == "MANAGER")
    assert manager["email"] == "manager@example.com"
    assert manager["locations"] == ["Dostyk"]
    assert (
        await client.post(
            "/api/v1/employees",
            headers=member_headers,
            json={
                "first_name": "No",
                "last_name": "Access",
                "location_ids": [location_id],
            },
        )
    ).status_code == 403

    async with sessions() as session:
        membership = await session.scalar(
            select(OrganizationMembershipModel).where(
                OrganizationMembershipModel.organization_id == UUID(organization_id),
                OrganizationMembershipModel.role == "MANAGER",
            )
        )
        assert membership is not None
        assert membership.location_access == "SELECTED"

    owner_team = await client.get("/api/v1/team", headers=headers)
    manager_employee = next(
        item for item in owner_team.json()["members"] if item["role"] == "MANAGER"
    )
    assert (
        await client.post(
            f"/api/v1/employees/{manager_employee['employee_id']}/deactivate",
            headers=headers,
        )
    ).status_code == 204
    assert (await client.get("/api/v1/team", headers=member_headers)).status_code == 403

    async with sessions() as session:
        suspended = await session.scalar(
            select(OrganizationMembershipModel).where(
                OrganizationMembershipModel.organization_id == UUID(organization_id),
                OrganizationMembershipModel.role == "MANAGER",
            )
        )
        assert suspended is not None and suspended.status == "SUSPENDED"
        deactivated = await session.get(EmployeeModel, UUID(manager_employee["employee_id"]))
        assert deactivated is not None and deactivated.status == "INACTIVE"


@pytest.mark.anyio
async def test_invitation_validation_revoke_and_foreign_employee(app_client, monkeypatch) -> None:
    client, sessions = app_client
    tokens = iter(
        [
            "stage3-revoke-token-with-at-least-thirty-two-characters",
            "stage3-second-token-with-at-least-thirty-two-characters",
        ]
    )

    def token_pair() -> tuple[str, str]:
        token = next(tokens)
        return token, sha256(token.encode()).hexdigest()

    monkeypatch.setattr(
        "beanly.modules.organizations.application.services.invitation_service."
        "create_invitation_token",
        token_pair,
    )
    owner = await authenticated_user(client, "validation-owner@example.com", "Owner")
    headers, _, location_id = await workspace(client, owner, "Validation Coffee")
    _, _, foreign_location_id = await workspace(client, owner, "Second Coffee")
    other = await authenticated_user(client, "wrong-person@example.com", "Wrong")

    assert (
        await client.post(
            "/api/v1/team/invitations",
            headers=headers,
            json={
                "email": "foreign-location@example.com",
                "role": "BARISTA",
                "location_ids": [foreign_location_id],
            },
        )
    ).status_code == 422
    async with sessions() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(OrganizationInvitationModel)
                .where(OrganizationInvitationModel.email == "foreign-location@example.com")
            )
            == 0
        )

    assert (
        await client.post(
            "/api/v1/team/invitations",
            headers=headers,
            json={
                "email": "validation-owner@example.com",
                "role": "MANAGER",
                "location_ids": [location_id],
            },
        )
    ).status_code == 409
    assert (
        await client.post(
            "/api/v1/team/invitations",
            headers=headers,
            json={
                "email": "new-owner@example.com",
                "role": "OWNER",
                "location_ids": [location_id],
            },
        )
    ).status_code == 422

    invited = await client.post(
        "/api/v1/team/invitations",
        headers=headers,
        json={
            "email": "cashier@example.com",
            "role": "CASHIER",
            "location_ids": [location_id],
        },
    )
    assert invited.status_code == 201
    raw_token = "stage3-revoke-token-with-at-least-thirty-two-characters"
    assert (
        await client.post(f"/api/v1/invitations/{raw_token}/accept", headers=other)
    ).status_code == 403
    assert (
        await client.post(
            f"/api/v1/team/invitations/{invited.json()['id']}/revoke",
            headers=headers,
        )
    ).status_code == 204
    assert (await client.get(f"/api/v1/invitations/{raw_token}")).status_code == 410
    assert (await client.get("/api/v1/invitations/unknown-token")).status_code == 404
