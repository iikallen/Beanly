from uuid import uuid4

import pytest
from pydantic import ValidationError

from beanly.core.money import MAX_NUMERIC_20_6_MINOR
from beanly.modules.onboarding.api.schemas import (
    BulkPriceRowRequest,
    ImportRunListResponse,
    OnboardingStepResponse,
    TemplateOptionsRequest,
)


def test_onboarding_step_status_vocabulary_matches_public_contract() -> None:
    for value in ("COMPLETE", "NEEDS_ATTENTION", "OPTIONAL", "MISSING"):
        assert OnboardingStepResponse(status=value).status == value
    for value in ("READY", "BLOCKED"):
        with pytest.raises(ValidationError):
            OnboardingStepResponse(status=value)


def test_bulk_price_respects_finance_money_cap() -> None:
    entity_id = uuid4()
    assert BulkPriceRowRequest(
        entity_id=entity_id,
        price_minor=str(MAX_NUMERIC_20_6_MINOR),
    ).price_minor == str(MAX_NUMERIC_20_6_MINOR)
    with pytest.raises(ValidationError):
        BulkPriceRowRequest(
            entity_id=entity_id,
            price_minor=str(MAX_NUMERIC_20_6_MINOR + 1),
        )


def test_import_list_uses_summary_rows_without_entities() -> None:
    item_schema = ImportRunListResponse.model_json_schema()["$defs"][
        "ImportRunSummaryResponse"
    ]
    assert "entities" not in item_schema["properties"]


def test_template_options_are_normalized_and_casefold_deduplicated() -> None:
    options = TemplateOptionsRequest(
        sizes=[" 350 ", "350"],
        alternative_milks=["Oat", " oat "],
        extras=["Extra shot", "EXTRA SHOT"],
    )
    assert options.sizes == ["350"]
    assert options.alternative_milks == ["Oat"]
    assert options.extras == ["Extra shot"]
