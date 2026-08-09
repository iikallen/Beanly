from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from beanly.modules.employees.infrastructure.db.models import EmployeeModel
from beanly.modules.organizations.infrastructure.db.invitation_repository import (
    SqlAlchemyInvitationRepository,
)
from beanly.modules.organizations.infrastructure.db.models import (
    InvitationLocationModel,
    MembershipLocationModel,
    OrganizationInvitationModel,
    OrganizationMembershipModel,
)


async def _register_and_login(
    client: AsyncClient, email: str, first_name: str = "Invitee"
) -> tuple[dict[str, str], dict]:
    password = "correct-horse-battery-staple"
    registered = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": password,
            "first_name": first_name,
            "last_name": "Beanly",
        },
    )
    assert registered.status_code == 201
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200
    headers = {"authorization": f"Bearer {login.json()['access_token']}"}
    me = await client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200
    return headers, me.json()


async def _workspace(
    client: AsyncClient, owner: dict[str, str], name: str
) -> tuple[dict[str, str], str, str]:
    response = await client.post(
        "/api/v1/organizations",
        headers=owner,
        json={
            "name": name,
            "country_code": "KZ",
            "currency_code": "KZT",
            "first_location": {
                "name": "Dostyk",
                "timezone": "Asia/Almaty",
            },
        },
    )
    assert response.status_code == 201
    body = response.json()
    organization_id = body["organization"]["id"]
    return (
        {**owner, "X-Organization-ID": organization_id},
        organization_id,
        body["location"]["id"],
    )


def _token_pair(token: str) -> tuple[str, str]:
    return token, sha256(token.encode()).hexdigest()


@pytest.mark.anyio
async def test_invitation_survives_registration_and_links_employee(app_client, monkeypatch) -> None:
    client, sessions = app_client
    token = "new-user-invitation-token-with-more-than-thirty-two-characters"
    monkeypatch.setattr(
        "beanly.modules.organizations.application.services.invitation_service."
        "create_invitation_token",
        lambda: _token_pair(token),
    )
    owner, _ = await _register_and_login(client, "new-flow-owner@example.com", "Owner")
    owner_headers, organization_id, location_id = await _workspace(client, owner, "New User Coffee")

    invited = await client.post(
        "/api/v1/team/invitations",
        headers=owner_headers,
        json={
            "email": "brand-new-user@example.com",
            "role": "BARISTA",
            "location_ids": [location_id],
        },
    )
    assert invited.status_code == 201

    public = await client.get(f"/api/v1/invitations/{token}")
    assert public.status_code == 200
    assert set(public.json()) == {"organization_name", "role", "email", "expires_at"}
    assert public.json()["email"] == "brand-new-user@example.com"

    invitee, user = await _register_and_login(client, "brand-new-user@example.com", "Brand")
    accepted = await client.post(f"/api/v1/invitations/{token}/accept", headers=invitee)
    assert accepted.status_code == 204

    async with sessions() as session:
        membership = await session.scalar(
            select(OrganizationMembershipModel).where(
                OrganizationMembershipModel.organization_id == UUID(organization_id),
                OrganizationMembershipModel.user_id == UUID(user["id"]),
            )
        )
        employee = await session.scalar(
            select(EmployeeModel).where(
                EmployeeModel.organization_id == UUID(organization_id),
                EmployeeModel.user_id == UUID(user["id"]),
            )
        )
        assert membership is not None
        assert membership.status == "ACTIVE"
        assert membership.location_access == "SELECTED"
        assert employee is not None
        assert employee.first_name == "Brand"
        assert employee.position == "Barista"
        assert (
            await session.scalar(
                select(func.count())
                .select_from(MembershipLocationModel)
                .where(
                    MembershipLocationModel.membership_id == membership.id,
                    MembershipLocationModel.location_id == UUID(location_id),
                )
            )
            == 1
        )

    member_headers = {**invitee, "X-Organization-ID": organization_id}
    team = await client.get("/api/v1/team", headers=member_headers)
    assert team.status_code == 403
    organizations = await client.get("/api/v1/organizations", headers=invitee)
    assert [item["id"] for item in organizations.json()] == [organization_id]


@pytest.mark.anyio
async def test_expired_invitation_is_rejected_and_reported_effectively(
    app_client, monkeypatch
) -> None:
    client, sessions = app_client
    token = "expired-invitation-token-with-more-than-thirty-two-characters"
    monkeypatch.setattr(
        "beanly.modules.organizations.application.services.invitation_service."
        "create_invitation_token",
        lambda: _token_pair(token),
    )
    owner, _ = await _register_and_login(client, "expiry-owner@example.com", "Owner")
    headers, _, location_id = await _workspace(client, owner, "Expiry Coffee")
    invited = await client.post(
        "/api/v1/team/invitations",
        headers=headers,
        json={
            "email": "expired-user@example.com",
            "role": "CASHIER",
            "location_ids": [location_id],
        },
    )
    assert invited.status_code == 201

    async with sessions() as session:
        invitation = await session.get(OrganizationInvitationModel, UUID(invited.json()["id"]))
        assert invitation is not None
        invitation.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()

    assert (await client.get(f"/api/v1/invitations/{token}")).status_code == 410
    assert (
        await client.post(f"/api/v1/invitations/{token}/accept", headers=owner)
    ).status_code == 410
    listed = await client.get("/api/v1/team/invitations", headers=headers)
    assert listed.status_code == 200
    assert listed.json()[0]["status"] == "EXPIRED"


@pytest.mark.anyio
async def test_acceptance_failure_rolls_back_every_write(app_client, monkeypatch) -> None:
    client, sessions = app_client
    token = "rollback-invitation-token-with-more-than-thirty-two-characters"
    monkeypatch.setattr(
        "beanly.modules.organizations.application.services.invitation_service."
        "create_invitation_token",
        lambda: _token_pair(token),
    )
    owner, _ = await _register_and_login(client, "rollback-owner@example.com", "Owner")
    headers, organization_id, location_id = await _workspace(client, owner, "Rollback Coffee")
    invited = await client.post(
        "/api/v1/team/invitations",
        headers=headers,
        json={
            "email": "rollback-user@example.com",
            "role": "MANAGER",
            "location_ids": [location_id],
        },
    )
    assert invited.status_code == 201
    invitee, user = await _register_and_login(client, "rollback-user@example.com")

    async def fail_after_membership_and_employee_write(self, invitation):
        raise RuntimeError("forced acceptance failure")

    monkeypatch.setattr(
        SqlAlchemyInvitationRepository,
        "update",
        fail_after_membership_and_employee_write,
    )
    with pytest.raises(RuntimeError, match="forced acceptance failure"):
        await client.post(f"/api/v1/invitations/{token}/accept", headers=invitee)

    async with sessions() as session:
        invitation = await session.get(OrganizationInvitationModel, UUID(invited.json()["id"]))
        assert invitation is not None
        assert invitation.status == "PENDING"
        assert invitation.accepted_by is None
        assert (
            await session.scalar(
                select(func.count())
                .select_from(OrganizationMembershipModel)
                .where(
                    OrganizationMembershipModel.organization_id == UUID(organization_id),
                    OrganizationMembershipModel.user_id == UUID(user["id"]),
                )
            )
            == 0
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(EmployeeModel)
                .where(EmployeeModel.user_id == UUID(user["id"]))
            )
            == 0
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(MembershipLocationModel)
                .join(
                    OrganizationMembershipModel,
                    OrganizationMembershipModel.id == MembershipLocationModel.membership_id,
                )
                .where(OrganizationMembershipModel.organization_id == UUID(organization_id))
            )
            == 0
        )


@pytest.mark.anyio
async def test_foreign_employee_cannot_be_attached_to_invitation(app_client, monkeypatch) -> None:
    client, sessions = app_client
    token = "foreign-employee-token-with-more-than-thirty-two-characters"
    monkeypatch.setattr(
        "beanly.modules.organizations.application.services.invitation_service."
        "create_invitation_token",
        lambda: _token_pair(token),
    )
    owner, _ = await _register_and_login(client, "foreign-employee-owner@example.com")
    first_headers, first_organization_id, first_location_id = await _workspace(
        client, owner, "First Coffee"
    )
    second_headers, _, second_location_id = await _workspace(client, owner, "Second Coffee")
    employee = await client.post(
        "/api/v1/employees",
        headers=second_headers,
        json={
            "first_name": "Foreign",
            "last_name": "Employee",
            "location_ids": [second_location_id],
        },
    )
    assert employee.status_code == 201

    rejected = await client.post(
        "/api/v1/team/invitations",
        headers=first_headers,
        json={
            "email": "foreign-employee@example.com",
            "role": "BARISTA",
            "location_ids": [first_location_id],
            "employee_id": employee.json()["id"],
        },
    )
    assert rejected.status_code == 404

    async with sessions() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(OrganizationInvitationModel)
                .where(OrganizationInvitationModel.organization_id == UUID(first_organization_id))
            )
            == 0
        )
        assert await session.scalar(select(func.count()).select_from(InvitationLocationModel)) == 0
