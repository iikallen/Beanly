from pathlib import Path

from beanly.main import app
from beanly.modules.organizations.domain.enums import MembershipRole
from beanly.modules.organizations.domain.permissions import Permission, permissions_for

STAGE26_PERMISSIONS = {
    Permission.CASH_DRAWER_USE,
    Permission.CASH_DRAWER_ADJUST,
    Permission.CASH_DRAWER_CLOSE,
    Permission.CASH_DRAWER_VIEW_EXPECTED,
    Permission.CASH_DRAWER_APPROVE_VARIANCE,
    Permission.CASH_DRAWER_REPORT,
}


def test_stage26_openapi_exposes_cash_and_fiscal_contracts() -> None:
    paths = app.openapi()["paths"]
    expected = {
        "/api/v1/cash/drawers/current": {"get"},
        "/api/v1/cash/drawers/{drawer_id}": {"get"},
        "/api/v1/cash/drawers/{drawer_id}/pay-in": {"post"},
        "/api/v1/cash/drawers/{drawer_id}/pay-out": {"post"},
        "/api/v1/cash/drawers/{drawer_id}/summary": {"get"},
        "/api/v1/cash/drawers/{drawer_id}/close": {"post"},
        "/api/v1/cash/drawers/{drawer_id}/approve-variance": {"post"},
        "/api/v1/cash/reports/drawers": {"get"},
        "/api/v1/cash/reports/drawers/{drawer_id}": {"get"},
        "/api/v1/fiscal/shifts/{shift_id}/x-report": {"post"},
        "/api/v1/fiscal/shifts/{shift_id}/status": {"get"},
        "/api/v1/fiscal/shifts/{shift_id}/reconcile": {"post"},
    }
    for path, methods in expected.items():
        assert methods <= set(paths[path]), path
    legacy = paths.get("/api/v1/sales/shifts/{shift_id}/close", {})
    if "post" in legacy:
        shift_service = Path("beanly/modules/sales/application/shift_service.py").read_text(
            encoding="utf-8"
        )
        assert "Use the cash drawer close workflow" in shift_service

    schemas = app.openapi()["components"]["schemas"]
    money = {
        "ShiftOpenRequest": {"starting_cash_minor"},
        "CashMovementRequest": {"amount_minor"},
        "CashCloseRequest": {"actual_cash_minor"},
        "CashDrawerResponse": {
            "starting_cash_minor",
            "expected_cash_minor_snapshot",
            "actual_cash_minor",
            "variance_minor",
        },
        "CashMovementResponse": {"amount_minor"},
        "CashDrawerSummaryResponse": {
            "starting_cash_minor",
            "cash_payments_minor",
            "cash_refunds_minor",
            "pay_in_minor",
            "pay_out_minor",
            "expected_cash_minor",
            "actual_cash_minor",
            "variance_minor",
        },
    }
    for schema, fields in money.items():
        key = next(
            (
                name
                for name in schemas
                if name == schema or name.endswith(f"cash_management__api__schemas__{schema}")
            ),
            None,
        )
        assert key is not None, schema
        for field in fields:
            value = schemas[key]["properties"][field]
            types = {value.get("type")} | {item.get("type") for item in value.get("anyOf", [])}
            assert "string" in types, (schema, field)


def test_stage26_role_permissions_preserve_blind_close() -> None:
    assert STAGE26_PERMISSIONS <= permissions_for(MembershipRole.OWNER)
    assert STAGE26_PERMISSIONS <= permissions_for(MembershipRole.ADMIN)
    assert STAGE26_PERMISSIONS <= permissions_for(MembershipRole.MANAGER)
    assert permissions_for(MembershipRole.ACCOUNTANT) & STAGE26_PERMISSIONS == {
        Permission.CASH_DRAWER_VIEW_EXPECTED,
        Permission.CASH_DRAWER_REPORT,
    }
    for role in (MembershipRole.CASHIER, MembershipRole.BARISTA):
        granted = permissions_for(role) & STAGE26_PERMISSIONS
        assert granted == {
            Permission.CASH_DRAWER_USE,
            Permission.CASH_DRAWER_CLOSE,
        }
        assert Permission.CASH_DRAWER_VIEW_EXPECTED not in granted


def test_cash_management_is_bounded_and_uses_existing_event_boundaries() -> None:
    root = Path("beanly/modules/cash_management")
    assert {path.name for path in root.iterdir() if path.is_dir()} >= {
        "api",
        "application",
        "domain",
        "infrastructure",
    }
    for path in (root / "domain").rglob("*.py"):
        source = path.read_text(encoding="utf-8").casefold()
        assert "fastapi" not in source, path
        assert "sqlalchemy" not in source, path
        assert "infrastructure" not in source, path

    sources = "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*.py"))
    assert "payment.completed" in sources
    assert "refund.completed" in sources
    assert "modules.finance" not in sources
    assert "gift_card" not in sources.casefold()
    assert "loyalty" not in sources.casefold()


def test_stage26_declares_only_public_cash_errors() -> None:
    sources = "\n".join(
        path.read_text(encoding="utf-8")
        for root in (
            Path("beanly/modules/cash_management"),
            Path("beanly/modules/fiscal"),
        )
        for path in root.rglob("*.py")
    )
    expected = {
        "CASH_DRAWER_NOT_FOUND",
        "CASH_DRAWER_NOT_OPEN",
        "CASH_DRAWER_ALREADY_CLOSED",
        "CASH_MOVEMENT_INVALID",
        "CASH_MOVEMENT_IDEMPOTENCY_CONFLICT",
        "CASH_CLOSE_IDEMPOTENCY_CONFLICT",
        "CASH_VARIANCE_APPROVAL_REQUIRED",
        "SHIFT_CLOSE_SYNC_PENDING",
        "FISCAL_SHIFT_CLOSE_FAILED",
        "FISCAL_SHIFT_CLOSE_UNKNOWN",
        "FISCAL_SHIFT_RECONCILIATION_REQUIRED",
    }
    assert all(code in sources for code in expected)
