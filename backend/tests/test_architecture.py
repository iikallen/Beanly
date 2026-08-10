from pathlib import Path

from beanly.main import app


def test_openapi_contains_current_contract() -> None:
    paths = app.openapi()["paths"]
    assert {
        "/api/v1/auth/register",
        "/api/v1/auth/login",
        "/api/v1/auth/refresh",
        "/api/v1/auth/logout",
        "/api/v1/auth/me",
        "/api/v1/organizations",
        "/api/v1/organizations/{organization_id}",
        "/api/v1/organizations/context",
        "/api/v1/organizations/{organization_id}/locations",
        "/api/v1/organizations/{organization_id}/locations/{location_id}",
        "/api/v1/employees",
        "/api/v1/employees/{employee_id}",
        "/api/v1/employees/{employee_id}/deactivate",
        "/api/v1/team",
        "/api/v1/team/invitations",
        "/api/v1/team/invitations/{invitation_id}/revoke",
        "/api/v1/invitations/{token}",
        "/api/v1/invitations/{token}/accept",
        "/api/v1/inventory/warehouses",
        "/api/v1/inventory/items",
        "/api/v1/inventory/stock",
        "/api/v1/inventory/items/{item_id}/stock",
        "/api/v1/inventory/items/{item_id}/movements",
        "/api/v1/inventory/transactions",
        "/api/v1/inventory/transactions/{transaction_id}",
        "/api/v1/inventory/transactions/{transaction_id}/reverse",
        "/api/v1/inventory/adjustments",
        "/api/v1/inventory/opening-balances",
        "/api/v1/inventory/movements",
        "/api/v1/inventory/write-off-reasons",
        "/api/v1/inventory/write-off-reasons/{reason_id}",
        "/api/v1/inventory/write-off-reasons/{reason_id}/deactivate",
        "/api/v1/inventory/write-offs",
        "/api/v1/inventory/write-offs/{writeoff_id}",
        "/api/v1/inventory/write-offs/{writeoff_id}/post",
        "/api/v1/inventory/write-offs/{writeoff_id}/reverse",
        "/api/v1/inventory/counts",
        "/api/v1/inventory/counts/{count_id}",
        "/api/v1/inventory/counts/{count_id}/lines",
        "/api/v1/inventory/counts/{count_id}/lines/{line_id}",
        "/api/v1/inventory/counts/{count_id}/post",
        "/api/v1/inventory/counts/{count_id}/cancel",
        "/api/v1/inventory/transfers",
        "/api/v1/inventory/transfers/{transfer_id}",
        "/api/v1/inventory/transfers/{transfer_id}/post",
        "/api/v1/inventory/transfers/{transfer_id}/reverse",
        "/api/v1/suppliers",
        "/api/v1/suppliers/{supplier_id}",
        "/api/v1/suppliers/{supplier_id}/deactivate",
        "/api/v1/purchasing/orders",
        "/api/v1/purchasing/orders/{order_id}",
        "/api/v1/purchasing/orders/{order_id}/submit",
        "/api/v1/purchasing/orders/{order_id}/cancel",
        "/api/v1/purchasing/orders/{order_id}/receipts",
        "/api/v1/purchasing/receipts",
        "/api/v1/purchasing/receipts/{receipt_id}",
        "/api/v1/purchasing/receipts/{receipt_id}/post",
        "/api/v1/purchasing/receipts/{receipt_id}/reverse",
        "/api/v1/menu",
        "/api/v1/menu/categories",
        "/api/v1/menu/categories/{category_id}",
        "/api/v1/menu/categories/{category_id}/archive",
        "/api/v1/menu/products",
        "/api/v1/menu/products/{product_id}",
        "/api/v1/menu/products/{product_id}/archive",
        "/api/v1/menu/products/{product_id}/variants",
        "/api/v1/menu/products/{product_id}/locations/{location_id}",
        "/api/v1/menu/variants/{variant_id}",
        "/api/v1/menu/variants/{variant_id}/archive",
        "/api/v1/menu/variants/{variant_id}/recipe",
        "/api/v1/menu/variants/{variant_id}/cost",
        "/api/v1/menu/variants/{variant_id}/prices/{location_id}",
        "/api/v1/menu/costs",
    } <= paths.keys()
    assert "delete" not in paths["/api/v1/organizations/{organization_id}"]
    assert "delete" not in paths["/api/v1/suppliers/{supplier_id}"]


def test_domain_has_no_framework_or_infrastructure_imports() -> None:
    forbidden = ("fastapi", "sqlalchemy", "redis", "celery", "infrastructure")
    for domain in (
        Path("beanly/modules/identity/domain"),
        Path("beanly/modules/organizations/domain"),
        Path("beanly/modules/employees/domain"),
        Path("beanly/modules/inventory/domain"),
        Path("beanly/modules/purchasing/domain"),
        Path("beanly/modules/menu/domain"),
    ):
        for path in domain.glob("*.py"):
            source = path.read_text(encoding="utf-8").casefold()
            assert not any(name in source for name in forbidden), path


def test_purchasing_uses_inventory_application_boundary() -> None:
    for path in Path("beanly/modules/purchasing").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "StockBalance" not in source, path
        if path != Path("beanly/modules/purchasing/api/dependencies.py"):
            assert "inventory.infrastructure" not in source, path


def test_menu_uses_inventory_application_boundary() -> None:
    for path in Path("beanly/modules/menu").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "StockBalance" not in source, path
        if path != Path("beanly/modules/menu/api/dependencies.py"):
            assert "inventory.infrastructure" not in source, path


def test_sales_uses_application_ports_and_has_no_stage_eleven_side_effects() -> None:
    sales = Path("beanly/modules/sales")
    for layer in (sales / "domain", sales / "application"):
        for path in layer.rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            assert "fastapi" not in source.casefold(), path
            assert "sqlalchemy" not in source.casefold(), path
            assert "menu.infrastructure" not in source, path
            assert "inventory.infrastructure" not in source, path

    forbidden_side_effects = (
        "InventoryTransactionType.SALE",
        "SaleCompleted",
        "PaymentModel",
        "FinanceModel",
        "RevenueModel",
        "COGS",
    )
    for path in sales.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert not any(name in source for name in forbidden_side_effects), path
        assert "menu.infrastructure.db.models" not in source, path
        assert "ProductModel" not in source, path
        assert "ProductVariantModel" not in source, path
        assert "ModifierOptionModel" not in source, path
        assert "RecipeModel" not in source, path


def test_payments_settlement_uses_ports_and_never_reads_menu_or_finance() -> None:
    payments = Path("beanly/modules/payments")
    for layer in (payments / "domain", payments / "application"):
        for path in layer.rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            assert "fastapi" not in source.casefold(), path
            assert "sqlalchemy" not in source.casefold(), path
            assert "sales.infrastructure" not in source, path
            assert "inventory.infrastructure" not in source, path

    for path in payments.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "SalesOrderModel" not in source, path
        assert "OrderService" not in source, path
        assert "modules.menu" not in source, path
        assert "modules.finance" not in source, path
        assert "MenuService" not in source, path
        assert "RecipeModel" not in source, path
        assert "FinanceModel" not in source, path
        assert "RevenueModel" not in source, path


def test_transactional_outbox_replaces_post_commit_domain_publication() -> None:
    service_paths = (
        Path("beanly/modules/inventory/application/services.py"),
        Path("beanly/modules/payments/application/payment_service.py"),
        Path("beanly/modules/purchasing/application/services.py"),
    )
    for path in service_paths:
        source = path.read_text(encoding="utf-8")
        assert ".publish(" not in source, path
        assert "publish_events" not in source, path
        assert "stage_many" in source or ".stage(" in source, path

    writer = Path("beanly/core/events/outbox/writer.py").read_text(
        encoding="utf-8"
    )
    assert ".commit(" not in writer
    for path in (
        Path("beanly/modules/inventory/api/dependencies.py"),
        Path("beanly/modules/payments/api/dependencies.py"),
        Path("beanly/modules/purchasing/api/dependencies.py"),
    ):
        source = path.read_text(encoding="utf-8")
        assert "OutboxEventSink(OutboxRepository(session))" in source, path


def test_inventory_operations_use_ledger_application_boundary() -> None:
    source = Path("beanly/modules/inventory/application/operations.py").read_text(
        encoding="utf-8"
    )
    assert "infrastructure" not in source
    assert "StockBalanceModel" not in source
    assert "InventoryTransactionModel" not in source
    assert "self.inventory.repository" not in source
    assert "create_and_post_staged" in source
    assert "reverse_staged" in source
