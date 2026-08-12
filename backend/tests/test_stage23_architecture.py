from pathlib import Path

ONBOARDING = Path("beanly/modules/onboarding")


def test_onboarding_domain_and_application_depend_only_on_ports() -> None:
    forbidden = (
        "fastapi",
        "sqlalchemy",
        "modules.onboarding.infrastructure",
        "modules.inventory.infrastructure",
        "modules.menu.infrastructure",
        "modules.organizations.infrastructure",
        "modules.sales.infrastructure",
    )
    for layer in (ONBOARDING / "domain", ONBOARDING / "application"):
        for path in layer.rglob("*.py"):
            source = path.read_text(encoding="utf-8").casefold()
            assert not any(value in source for value in forbidden), path


def test_onboarding_never_owns_business_facts_or_raw_upload_bytes() -> None:
    forbidden = (
        "stockbalancemodel",
        "productmodel(",
        "productvariantmodel(",
        "inventoryitemmodel(",
        "warehousestockmodel",
        "largebinary",
        "file_bytes",
        "raw_file",
    )
    for path in ONBOARDING.rglob("*.py"):
        source = path.read_text(encoding="utf-8").casefold()
        assert not any(value in source for value in forbidden), path


def test_templates_are_code_versioned_and_database_surface_stays_bounded() -> None:
    templates = ONBOARDING / "templates"
    assert {path.name for path in templates.glob("*.json")} == {
        "classic_coffee_shop.v1.json",
        "specialty_coffee.v1.json",
        "coffee_bakery.v1.json",
        "takeaway_coffee.v1.json",
    }
    model_source = (ONBOARDING / "infrastructure/db/models.py").read_text(
        encoding="utf-8"
    )
    assert "starter_products" not in model_source
    assert "starter_categories" not in model_source
    assert "starter_recipes" not in model_source
