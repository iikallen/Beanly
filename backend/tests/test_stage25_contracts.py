import subprocess
import sys
from pathlib import Path

from beanly.core.events.handlers.registry import EventHandlerRegistry
from beanly.main import app
from beanly.modules.customers.infrastructure.handlers import register_customer_handlers
from beanly.modules.offline_pos.api.schemas import OfflineOrderRequest
from beanly.modules.organizations.domain.enums import MembershipRole
from beanly.modules.organizations.domain.permissions import Permission, permissions_for

STAGE25_TABLES = {
    "customers",
    "loyalty_programs",
    "loyalty_tiers",
    "loyalty_accounts",
    "loyalty_ledger_entries",
    "loyalty_redemptions",
    "promotion_audiences",
    "promotion_audience_customers",
}


def test_stage25_openapi_exposes_customer_and_loyalty_contracts() -> None:
    paths = app.openapi()["paths"]
    expected = {
        "/api/v1/customers": {"get", "post"},
        "/api/v1/customers/{customer_id}": {"get", "patch"},
        "/api/v1/customers/{customer_id}/orders": {"get"},
        "/api/v1/customers/{customer_id}/loyalty": {"get"},
        "/api/v1/customers/{customer_id}/loyalty/adjustments": {"post"},
        "/api/v1/loyalty/program": {"get", "patch"},
        "/api/v1/loyalty/tiers": {"get", "post"},
        "/api/v1/loyalty/tiers/{tier_id}": {"patch"},
        "/api/v1/promotions/{promotion_id}/audience": {"get", "put"},
        "/api/v1/sales/orders/{order_id}/customer": {"put"},
        "/api/v1/sales/orders/{order_id}/loyalty/quote": {"post"},
        "/api/v1/sales/orders/{order_id}/loyalty/redeem": {"post"},
        "/api/v1/sales/orders/{order_id}/loyalty/redemption": {"delete"},
    }
    for path, methods in expected.items():
        assert methods <= set(paths[path]), path

    schemas = app.openapi()["components"]["schemas"]
    for schema, fields in {
        "CustomerResponse": {"lifetime_value_minor", "loyalty_points_balance"},
        "LoyaltyResponse": {
            "points_balance",
            "available_points",
            "lifetime_earned_points",
            "point_value_minor",
        },
        "LoyaltyLedgerEntryResponse": {"points_delta"},
        "LoyaltyTierResponse": {"threshold_lifetime_points"},
        "LoyaltyQuoteResponse": {"points", "discount_minor", "balance_points"},
    }.items():
        assert {
            schemas[schema]["properties"][field]["type"] for field in fields
        } == {"string"}, schema


def test_stage25_permissions_are_explicit_and_not_sales_catchalls() -> None:
    customer_read = Permission.CUSTOMERS_READ
    customer_write = Permission.CUSTOMERS_WRITE
    loyalty_read = Permission.LOYALTY_READ
    loyalty_adjust = Permission.LOYALTY_ADJUST
    loyalty_configure = Permission.LOYALTY_CONFIGURE
    loyalty_redeem = Permission.LOYALTY_REDEEM
    all_stage25 = {
        customer_read,
        customer_write,
        loyalty_read,
        loyalty_adjust,
        loyalty_configure,
        loyalty_redeem,
    }

    assert all_stage25 <= permissions_for(MembershipRole.OWNER)
    assert all_stage25 <= permissions_for(MembershipRole.ADMIN)
    assert {customer_read, customer_write, loyalty_read, loyalty_adjust, loyalty_redeem} <= (
        permissions_for(MembershipRole.MANAGER)
    )
    assert loyalty_configure not in permissions_for(MembershipRole.MANAGER)
    assert permissions_for(MembershipRole.ACCOUNTANT) & all_stage25 == {
        customer_read,
        loyalty_read,
    }
    assert permissions_for(MembershipRole.CASHIER) & all_stage25 == {
        customer_read,
        customer_write,
        loyalty_read,
        loyalty_redeem,
    }
    assert permissions_for(MembershipRole.BARISTA) & all_stage25 == {
        customer_read,
        customer_write,
        loyalty_read,
    }


def test_stage25_domains_are_framework_free_and_do_not_cross_infrastructure() -> None:
    root = Path("beanly/modules/customers")
    domain = root / "domain"
    assert domain.is_dir()
    for path in domain.rglob("*.py"):
        source = path.read_text(encoding="utf-8").casefold()
        assert "fastapi" not in source, path
        assert "sqlalchemy" not in source, path
        assert "infrastructure" not in source, path

    for path in (*root.glob("domain/**/*.py"), *root.glob("application/**/*.py")):
        source = path.read_text(encoding="utf-8")
        assert "modules.sales.infrastructure" not in source, path
        assert "modules.payments.infrastructure" not in source, path
        assert "modules.refunds.infrastructure" not in source, path


def test_stage25_customer_and_loyalty_actions_are_not_available_offline() -> None:
    fields = set(OfflineOrderRequest.model_fields)
    assert not fields & {
        "customer_id",
        "customer_name",
        "customer_phone",
        "loyalty_points",
        "loyalty_redemption",
    }
    for path in Path("beanly/modules/offline_pos").rglob("*.py"):
        source = path.read_text(encoding="utf-8").casefold()
        assert "customer_phone" not in source, path
        assert "loyalty_redemption" not in source, path


def test_stage25_outbox_projects_refunds_but_not_same_transaction_payments() -> None:
    registry = EventHandlerRegistry()
    register_customer_handlers(registry, object())  # type: ignore[arg-type]
    assert ("refund.completed", 1) in registry._handlers
    assert ("payment.completed", 1) not in registry._handlers


def test_stage25_migration_is_stacked_and_owns_only_customer_loyalty_schema() -> None:
    source = Path("migrations/versions/0025_customers_crm_loyalty.py").read_text(
        encoding="utf-8"
    )
    assert 'revision = "0025_customers_crm_loyalty"' in source
    assert 'down_revision = "0024_promotions_pricing"' in source
    assert {name for name in STAGE25_TABLES if f'"{name}"' in source} == STAGE25_TABLES
    assert {
        "customer_id",
        "customer_name_snapshot",
        "customer_phone_snapshot",
        "audience_kind",
    } <= {name for name in source.split('"') if name}
    assert "gift_card" not in source.casefold()
    assert "wallet" not in source.casefold()


def test_stage25_worker_bootstraps_register_customer_metadata_in_isolation() -> None:
    code = (
        "from beanly.core.database.base import Base; "
        "from sqlalchemy.orm import configure_mappers; "
        "import {module}; configure_mappers(); "
        "assert 'customers' in Base.metadata.tables"
    )
    for module in ("beanly.core.events.worker", "beanly.modules.integrations.worker"):
        result = subprocess.run(
            [sys.executable, "-c", code.format(module=module)],
            cwd=Path(__file__).parents[1],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, f"{module}: {result.stderr}"
