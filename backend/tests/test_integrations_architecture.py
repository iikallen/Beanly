import tomllib
from pathlib import Path

INTEGRATIONS = Path("beanly/modules/integrations")


def test_stage18_runtime_dependencies_are_production_dependencies() -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"]
    dependencies = tuple(value.casefold() for value in project["dependencies"])
    assert any(value.startswith("cryptography") for value in dependencies)
    assert any(value.startswith("httpx") for value in dependencies)


def test_core_bounded_contexts_do_not_import_concrete_integration_providers() -> None:
    forbidden = "integrations.infrastructure.providers"
    for module in ("sales", "payments", "inventory", "finance", "analytics"):
        for path in Path(f"beanly/modules/{module}").rglob("*.py"):
            assert forbidden not in path.read_text(encoding="utf-8"), path


def test_integrations_layers_and_provider_adapters_keep_boundaries() -> None:
    assert INTEGRATIONS.is_dir()
    for layer in (INTEGRATIONS / "domain", INTEGRATIONS / "application"):
        for path in layer.rglob("*.py"):
            source = path.read_text(encoding="utf-8").casefold()
            assert "fastapi" not in source, path
            assert "sqlalchemy" not in source, path
            assert "infrastructure" not in source, path

    forbidden_models = (
        "SalesOrderModel",
        "StockBalanceModel",
        "FinanceEntryModel",
    )
    providers = INTEGRATIONS / "infrastructure" / "providers"
    assert providers.is_dir()
    for path in providers.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert not any(value in source for value in forbidden_models), path


def test_connection_api_does_not_accept_arbitrary_provider_urls() -> None:
    schemas = (INTEGRATIONS / "api" / "schemas.py").read_text(encoding="utf-8")
    forbidden_fields = ("provider_url:", "base_url:", "endpoint_url:")
    assert not any(value in schemas for value in forbidden_fields)
