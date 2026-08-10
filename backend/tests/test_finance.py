from hashlib import sha256
from uuid import UUID

import pytest
from httpx import AsyncClient


async def _workspace(
    client: AsyncClient, email: str, name: str
) -> tuple[dict[str, str], UUID, UUID]:
    password = "correct-horse-battery-staple"
    registered = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": password,
            "first_name": "Finance",
            "last_name": "Owner",
        },
    )
    assert registered.status_code == 201, registered.text
    login = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    assert login.status_code == 200, login.text
    auth = {"authorization": f"Bearer {login.json()['access_token']}"}
    created = await client.post(
        "/api/v1/organizations",
        headers=auth,
        json={
            "name": name,
            "country_code": "KZ",
            "currency_code": "KZT",
            "first_location": {"name": "Dostyk", "timezone": "Asia/Almaty"},
        },
    )
    assert created.status_code == 201, created.text
    organization_id = UUID(created.json()["organization"]["id"])
    location_id = UUID(created.json()["location"]["id"])
    return (
        {**auth, "X-Organization-ID": str(organization_id)},
        organization_id,
        location_id,
    )


async def _account(
    client: AsyncClient,
    headers: dict[str, str],
    name: str,
    *,
    location_id: UUID | None = None,
    opening: str = "0",
) -> dict:
    response = await client.post(
        "/api/v1/finance/accounts",
        headers=headers,
        json={
            "name": name,
            "type": "BANK",
            "location_id": str(location_id) if location_id else None,
            "opening_balance_minor": opening,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.anyio
async def test_expense_immutable_ledger_reports_bounds_filters_and_tenant_isolation(
    app_client,
) -> None:
    client, _ = app_client
    headers, organization_id, location_id = await _workspace(
        client, "finance-expense@example.com", "Finance Expense"
    )
    other_headers, _, other_location_id = await _workspace(
        client, "finance-other@example.com", "Other Finance"
    )
    account = await _account(
        client, headers, "Bank", location_id=location_id, opening="100000"
    )
    default_account = await _account(client, headers, "Default opening")
    assert default_account["opening_balance_minor"] == "0"
    assert default_account["balance_minor"] == "0"

    renamed = await client.patch(
        f"/api/v1/finance/accounts/{account['id']}",
        headers=headers,
        json={"name": "Main bank", "opening_balance_minor": "999999"},
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["opening_balance_minor"] == "100000"

    category = await client.post(
        "/api/v1/finance/expense-categories",
        headers=headers,
        json={"name": "Rent", "sort_order": 10},
    )
    assert category.status_code == 201, category.text
    category_id = category.json()["id"]
    base_expense = {
        "category_id": category_id,
        "occurred_at": "2026-08-10T10:00:00Z",
    }
    for invalid in ("0", "-1", "9223372036854775808", "9999999999999999999"):
        response = await client.post(
            "/api/v1/finance/expenses",
            headers=headers,
            json={**base_expense, "amount_minor": invalid},
        )
        assert response.status_code == 422, (invalid, response.text)

    created = await client.post(
        "/api/v1/finance/expenses",
        headers=headers,
        json={
            **base_expense,
            "amount_minor": "500000",
            "cash_account_id": account["id"],
            "vendor": "Landlord",
        },
    )
    assert created.status_code == 201, created.text
    expense_id = created.json()["id"]
    assert created.json()["location_id"] is None

    posted = await client.post(
        f"/api/v1/finance/expenses/{expense_id}/post", headers=headers
    )
    assert posted.status_code == 200, posted.text
    assert posted.json()["status"] == "POSTED"
    assert posted.json()["finance_entry_id"]
    assert posted.json()["cash_entry_id"]
    posted_again = await client.post(
        f"/api/v1/finance/expenses/{expense_id}/post", headers=headers
    )
    assert posted_again.status_code == 200, posted_again.text
    assert posted_again.json()["finance_entry_id"] == posted.json()["finance_entry_id"]
    assert (
        await client.patch(
            f"/api/v1/finance/expenses/{expense_id}",
            headers=headers,
            json={"amount_minor": "1"},
        )
    ).status_code == 422

    report_params = {
        "date_from": "2026-08-10T00:00:00Z",
        "date_to": "2026-08-11T00:00:00Z",
    }
    pnl = await client.get("/api/v1/finance/pnl", headers=headers, params=report_params)
    assert pnl.status_code == 200, pnl.text
    assert pnl.json()["operating_expenses"] == "5000.000000"
    assert pnl.json()["operating_profit"] == "-5000.000000"
    breakdown = await client.get(
        "/api/v1/finance/pnl/breakdown", headers=headers, params=report_params
    )
    assert breakdown.status_code == 200, breakdown.text
    assert breakdown.json()["operating_expenses"] == [
        {"category_id": category_id, "name": "Rent", "amount": "5000.000000"}
    ]
    locations = await client.get(
        "/api/v1/finance/pnl/locations", headers=headers, params=report_params
    )
    assert locations.status_code == 200, locations.text
    assert locations.json() == [
        {
            "location_id": None,
            "location_name": "Central / Unallocated",
            "revenue": "0",
            "cogs": "0",
            "gross_profit": "0",
            "operating_expenses": "5000.000000",
            "operating_profit": "-5000.000000",
        }
    ]

    included = await client.get(
        "/api/v1/finance/entries",
        headers=headers,
        params={**report_params, "source_type": "expense", "source_id": expense_id},
    )
    assert included.status_code == 200, included.text
    assert [entry["amount"] for entry in included.json()] == ["-5000.000000"]
    excluded = await client.get(
        "/api/v1/finance/entries",
        headers=headers,
        params={
            "date_from": "2026-08-09T00:00:00Z",
            "date_to": "2026-08-10T10:00:00Z",
        },
    )
    assert excluded.status_code == 200, excluded.text
    assert excluded.json() == []
    assert (
        await client.get(
            "/api/v1/finance/pnl",
            headers=headers,
            params={
                **report_params,
                "location_id": str(other_location_id),
            },
        )
    ).status_code == 404

    cash_flow = await client.get(
        "/api/v1/finance/cash-flow", headers=headers, params=report_params
    )
    assert cash_flow.status_code == 200, cash_flow.text
    assert cash_flow.json()["opening_cash_minor"] == "100000"
    assert cash_flow.json()["operating"] == {
        "inflows_minor": "0",
        "outflows_minor": "500000",
        "net_minor": "-500000",
    }
    assert cash_flow.json()["closing_cash_minor"] == "-400000"

    reversed_expense = await client.post(
        f"/api/v1/finance/expenses/{expense_id}/reverse", headers=headers
    )
    assert reversed_expense.status_code == 200, reversed_expense.text
    assert reversed_expense.json()["status"] == "REVERSED"
    entries = await client.get(
        "/api/v1/finance/entries",
        headers=headers,
        params={"source_id": expense_id},
    )
    assert entries.status_code == 200, entries.text
    assert {entry["amount"] for entry in entries.json()} == {
        "-5000.000000",
        "5000.000000",
    }
    reversal = next(entry for entry in entries.json() if entry["amount"] == "5000.000000")
    assert reversal["reversal_of_id"] == posted.json()["finance_entry_id"]
    accounts = await client.get("/api/v1/finance/accounts", headers=headers)
    assert accounts.status_code == 200, accounts.text
    assert next(value for value in accounts.json() if value["id"] == account["id"])[
        "balance_minor"
    ] == "100000"

    assert (
        await client.get(f"/api/v1/finance/expenses/{expense_id}", headers=other_headers)
    ).status_code == 404
    assert (await client.get("/api/v1/finance/expenses", headers=other_headers)).json() == []
    assert (await client.get("/api/v1/finance/accounts", headers=other_headers)).json() == []
    other_pnl = await client.get(
        "/api/v1/finance/pnl", headers=other_headers, params=report_params
    )
    assert other_pnl.status_code == 200, other_pnl.text
    assert other_pnl.json()["operating_profit"] == "0"


@pytest.mark.anyio
async def test_cash_movements_are_cash_only_shaped_and_derive_activity(app_client) -> None:
    client, _ = app_client
    headers, organization_id, location_id = await _workspace(
        client, "finance-cash@example.com", "Finance Cash"
    )
    second_location = await client.post(
        f"/api/v1/organizations/{organization_id}/locations",
        headers=headers,
        json={"name": "Airport", "timezone": "Asia/Almaty"},
    )
    assert second_location.status_code == 201, second_location.text
    cash = await _account(client, headers, "Cash", location_id=location_id)
    bank = await _account(client, headers, "Bank")
    occurred_at = "2026-08-10T12:00:00Z"

    invalid = (
        {"type": "TRANSFER", "from_account_id": cash["id"]},
        {"type": "OWNER_CONTRIBUTION", "from_account_id": cash["id"]},
        {"type": "SUPPLIER_PAYMENT", "to_account_id": bank["id"]},
        {
            "type": "TRANSFER",
            "from_account_id": cash["id"],
            "to_account_id": cash["id"],
        },
    )
    for value in invalid:
        response = await client.post(
            "/api/v1/finance/cash-movements",
            headers=headers,
            json={**value, "amount_minor": "100", "occurred_at": occurred_at},
        )
        assert response.status_code == 422, (value, response.text)
    for amount in ("0", "9223372036854775808", "9999999999999999999"):
        response = await client.post(
            "/api/v1/finance/cash-movements",
            headers=headers,
            json={
                "type": "SUPPLIER_PAYMENT",
                "amount_minor": amount,
                "from_account_id": cash["id"],
                "occurred_at": occurred_at,
            },
        )
        assert response.status_code == 422, (amount, response.text)

    mismatched_location = await client.post(
        "/api/v1/finance/cash-movements",
        headers=headers,
        json={
            "location_id": second_location.json()["id"],
            "type": "SUPPLIER_PAYMENT",
            "amount_minor": "100",
            "from_account_id": cash["id"],
            "occurred_at": occurred_at,
        },
    )
    assert mismatched_location.status_code == 422, mismatched_location.text

    supplier = await client.post(
        "/api/v1/finance/cash-movements",
        headers=headers,
        json={
            "type": "SUPPLIER_PAYMENT",
            "amount_minor": "80000",
            "from_account_id": cash["id"],
            "cash_flow_activity": "FINANCING",
            "occurred_at": occurred_at,
        },
    )
    assert supplier.status_code == 201, supplier.text
    assert supplier.json()["cash_flow_activity"] == "OPERATING"
    contribution = await client.post(
        "/api/v1/finance/cash-movements",
        headers=headers,
        json={
            "type": "OWNER_CONTRIBUTION",
            "amount_minor": "100000",
            "to_account_id": bank["id"],
            "cash_flow_activity": "OPERATING",
            "occurred_at": occurred_at,
        },
    )
    assert contribution.status_code == 201, contribution.text
    assert contribution.json()["cash_flow_activity"] == "FINANCING"
    transfer = await client.post(
        "/api/v1/finance/cash-movements",
        headers=headers,
        json={
            "type": "TRANSFER",
            "amount_minor": "20000",
            "from_account_id": bank["id"],
            "to_account_id": cash["id"],
            "occurred_at": occurred_at,
        },
    )
    assert transfer.status_code == 201, transfer.text

    report_params = {
        "date_from": "2026-08-10T00:00:00Z",
        "date_to": "2026-08-11T00:00:00Z",
    }
    pnl = await client.get("/api/v1/finance/pnl", headers=headers, params=report_params)
    assert pnl.status_code == 200, pnl.text
    assert pnl.json()["operating_profit"] == "0"
    flow = await client.get(
        "/api/v1/finance/cash-flow", headers=headers, params=report_params
    )
    assert flow.status_code == 200, flow.text
    assert flow.json()["operating"] == {
        "inflows_minor": "20000",
        "outflows_minor": "100000",
        "net_minor": "-80000",
    }
    assert flow.json()["financing"] == {
        "inflows_minor": "100000",
        "outflows_minor": "0",
        "net_minor": "100000",
    }
    assert flow.json()["net_cash_movement_minor"] == "20000"

    for movement_id in (supplier.json()["id"], contribution.json()["id"], transfer.json()["id"]):
        reversed_movement = await client.post(
            f"/api/v1/finance/cash-movements/{movement_id}/reverse", headers=headers
        )
        assert reversed_movement.status_code == 200, reversed_movement.text
        assert reversed_movement.json()["reversed_at"] is not None
    accounts = await client.get("/api/v1/finance/accounts", headers=headers)
    assert accounts.status_code == 200, accounts.text
    assert {value["balance_minor"] for value in accounts.json()} == {"0"}


@pytest.mark.anyio
async def test_selected_location_finance_member_cannot_cross_location_scope(
    app_client, monkeypatch
) -> None:
    client, _ = app_client
    owner_headers, organization_id, allowed_location_id = await _workspace(
        client, "finance-scope-owner@example.com", "Finance Scope"
    )
    forbidden_location = await client.post(
        f"/api/v1/organizations/{organization_id}/locations",
        headers=owner_headers,
        json={"name": "Forbidden", "timezone": "Asia/Almaty"},
    )
    assert forbidden_location.status_code == 201, forbidden_location.text
    forbidden_location_id = forbidden_location.json()["id"]

    password = "correct-horse-battery-staple"
    accountant_email = "finance-scope-accountant@example.com"
    assert (
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": accountant_email,
                "password": password,
                "first_name": "Selected",
                "last_name": "Accountant",
            },
        )
    ).status_code == 201
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": accountant_email, "password": password},
    )
    accountant_auth = {"authorization": f"Bearer {login.json()['access_token']}"}
    token = "finance-selected-location-token-with-thirty-two-characters"
    monkeypatch.setattr(
        "beanly.modules.organizations.application.services.invitation_service."
        "create_invitation_token",
        lambda: (token, sha256(token.encode()).hexdigest()),
    )
    invited = await client.post(
        "/api/v1/team/invitations",
        headers=owner_headers,
        json={
            "email": accountant_email,
            "role": "ACCOUNTANT",
            "location_ids": [str(allowed_location_id)],
        },
    )
    assert invited.status_code == 201, invited.text
    assert (
        await client.post(f"/api/v1/invitations/{token}/accept", headers=accountant_auth)
    ).status_code == 204
    accountant_headers = {
        **accountant_auth,
        "X-Organization-ID": str(organization_id),
    }

    allowed_account = await _account(
        client, owner_headers, "Allowed", location_id=allowed_location_id
    )
    forbidden_account = await _account(
        client,
        owner_headers,
        "Forbidden",
        location_id=UUID(forbidden_location_id),
    )
    category = await client.post(
        "/api/v1/finance/expense-categories",
        headers=owner_headers,
        json={"name": "Scoped rent"},
    )
    assert category.status_code == 201, category.text
    forbidden_expense = await client.post(
        "/api/v1/finance/expenses",
        headers=owner_headers,
        json={
            "location_id": forbidden_location_id,
            "category_id": category.json()["id"],
            "amount_minor": "10000",
            "occurred_at": "2026-08-10T10:00:00Z",
        },
    )
    assert forbidden_expense.status_code == 201, forbidden_expense.text
    assert (
        await client.post(
            f"/api/v1/finance/expenses/{forbidden_expense.json()['id']}/post",
            headers=owner_headers,
        )
    ).status_code == 200

    visible_accounts = await client.get(
        "/api/v1/finance/accounts", headers=accountant_headers
    )
    assert visible_accounts.status_code == 200, visible_accounts.text
    assert {value["id"] for value in visible_accounts.json()} == {allowed_account["id"]}
    assert (
        await client.get("/api/v1/finance/expenses", headers=accountant_headers)
    ).json() == []
    assert (
        await client.get(
            f"/api/v1/finance/expenses/{forbidden_expense.json()['id']}",
            headers=accountant_headers,
        )
    ).status_code == 404
    assert (
        await client.post(
            "/api/v1/finance/accounts",
            headers=accountant_headers,
            json={
                "name": "Escalated",
                "type": "BANK",
                "location_id": forbidden_location_id,
            },
        )
    ).status_code in {404, 422}
    assert (
        await client.post(
            "/api/v1/finance/expenses",
            headers=accountant_headers,
            json={
                "location_id": forbidden_location_id,
                "category_id": category.json()["id"],
                "amount_minor": "1",
                "occurred_at": "2026-08-10T10:00:00Z",
            },
        )
    ).status_code in {404, 422}
    assert (
        await client.post(
            "/api/v1/finance/cash-movements",
            headers=accountant_headers,
            json={
                "type": "SUPPLIER_PAYMENT",
                "amount_minor": "1",
                "from_account_id": forbidden_account["id"],
                "occurred_at": "2026-08-10T10:00:00Z",
            },
        )
    ).status_code in {404, 422}

    report_params = {
        "date_from": "2026-08-10T00:00:00Z",
        "date_to": "2026-08-11T00:00:00Z",
    }
    scoped_pnl = await client.get(
        "/api/v1/finance/pnl", headers=accountant_headers, params=report_params
    )
    assert scoped_pnl.status_code == 200, scoped_pnl.text
    assert scoped_pnl.json()["operating_expenses"] == "0"
    scoped_entries = await client.get(
        "/api/v1/finance/entries", headers=accountant_headers
    )
    assert scoped_entries.status_code == 200, scoped_entries.text
    assert scoped_entries.json() == []
    scoped_cash_flow = await client.get(
        "/api/v1/finance/cash-flow",
        headers=accountant_headers,
        params=report_params,
    )
    assert scoped_cash_flow.status_code == 200, scoped_cash_flow.text
    assert scoped_cash_flow.json()["opening_cash_minor"] == "0"
    assert scoped_cash_flow.json()["net_cash_movement_minor"] == "0"
    scoped_locations = await client.get(
        "/api/v1/finance/pnl/locations",
        headers=accountant_headers,
        params=report_params,
    )
    assert scoped_locations.status_code == 200, scoped_locations.text
    assert scoped_locations.json() == []
    assert (
        await client.get(
            "/api/v1/finance/pnl",
            headers=accountant_headers,
            params={**report_params, "location_id": forbidden_location_id},
        )
    ).status_code == 404
