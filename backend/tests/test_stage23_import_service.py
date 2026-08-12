from dataclasses import replace
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from beanly.modules.onboarding.application.dto import (
    CanonicalImportDraft,
    CanonicalImportEntity,
)
from beanly.modules.onboarding.application.import_service import ImportService
from beanly.modules.onboarding.domain.entities import ImportRun
from beanly.modules.onboarding.domain.enums import (
    ImportEntityType,
    ImportResolution,
    ImportSourceType,
    ImportStatus,
)
from beanly.modules.onboarding.domain.exceptions import (
    ActivationNotReady,
    ImportEntityNotFound,
    ImportIdempotencyConflict,
)


class MemoryRepository:
    def __init__(self) -> None:
        self.runs: dict[tuple[UUID, UUID], ImportRun] = {}
        self.commits = 0
        self.rollbacks = 0

    async def get_by_client_import_id(
        self, organization_id: UUID, client_import_id: UUID
    ) -> ImportRun | None:
        return self.runs.get((organization_id, client_import_id))

    async def add_run(self, run: ImportRun, _entities) -> None:
        self.runs[(run.organization_id, run.client_import_id)] = run

    async def get_run(
        self, organization_id: UUID, run_id: UUID, *, lock: bool = False
    ) -> ImportRun | None:
        del lock
        return next(
            (
                run
                for (tenant_id, _), run in self.runs.items()
                if tenant_id == organization_id and run.id == run_id
            ),
            None,
        )

    async def save_run(self, _run: ImportRun) -> None:
        return None

    async def save_entity(self, _entity) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


class ApplySpy:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls = 0
        self.error = error

    async def apply(self, _context, _run) -> None:
        self.calls += 1
        if self.error:
            raise self.error

    async def ensure_location_access(self, _context, _location_id) -> None:
        return None

    async def resolve_preview(self, _context, _entities) -> None:
        return None


class PartialActivation(ApplySpy):
    async def activate_ready(self, _context, _run, product_ids, **_kwargs):
        return (
            [
                {"product_id": product_ids[0], "ready": True, "reasons": []},
                {
                    "product_id": product_ids[1],
                    "ready": False,
                    "reasons": ["NEEDS_RECIPE"],
                },
            ],
            1,
        )


class FailingRepository(MemoryRepository):
    def __init__(self, failing_method: str) -> None:
        super().__init__()
        self.failing_method = failing_method

    async def save_run(self, _run: ImportRun) -> None:
        if self.failing_method == "save_run":
            raise RuntimeError("injected save_run failure")

    async def save_entity(self, _entity) -> None:
        if self.failing_method == "save_entity":
            raise RuntimeError("injected save_entity failure")

    async def commit(self) -> None:
        if self.failing_method == "commit":
            raise RuntimeError("injected commit failure")
        await super().commit()


class FailingActivation(ApplySpy):
    async def activate_ready(self, *_args, **_kwargs):
        raise RuntimeError("injected activation failure")


def _context():
    return SimpleNamespace(organization_id=uuid4(), user_id=uuid4())


def _base_entities() -> list[CanonicalImportEntity]:
    return [
        CanonicalImportEntity(
            ImportEntityType.CATEGORY,
            "category:coffee",
            {"name": "Coffee"},
            sort_order=0,
        ),
        CanonicalImportEntity(
            ImportEntityType.PRODUCT,
            "product:latte",
            {"category_key": "category:coffee", "name": "Latte"},
            sort_order=1,
        ),
        CanonicalImportEntity(
            ImportEntityType.VARIANT,
            "variant:latte:350",
            {
                "product_key": "product:latte",
                "name": "350",
                "price_minor": "170000",
                "is_default": True,
            },
            sort_order=2,
        ),
        CanonicalImportEntity(
            ImportEntityType.INVENTORY_ITEM,
            "inventory:milk",
            {"name": "Milk", "sku": "MILK", "base_unit": "ml"},
            sort_order=3,
        ),
    ]


async def _create(
    service: ImportService,
    context,
    entities: list[CanonicalImportEntity],
    *,
    source_type: ImportSourceType = ImportSourceType.BEANLY_TEMPLATE,
    client_import_id: UUID | None = None,
    file_hash: str | None = None,
    location_id: UUID | None = None,
    mapping: dict[str, str] | None = None,
) -> ImportRun:
    return await service.create_from_draft(
        context,
        client_import_id=client_import_id or uuid4(),
        location_id=location_id or uuid4(),
        source_type=source_type,
        draft=CanonicalImportDraft("test", 1, tuple(entities)),
        file_name="menu.xlsx" if file_hash else None,
        file_hash=file_hash,
        mapping=mapping,
    )


@pytest.mark.anyio
async def test_file_replay_hash_includes_canonical_mapping() -> None:
    repository = MemoryRepository()
    service = ImportService(repository, ApplySpy())
    context = _context()
    client_import_id = uuid4()
    first = _base_entities()
    await _create(
        service,
        context,
        first,
        client_import_id=client_import_id,
        file_hash="a" * 64,
    )
    changed = _base_entities()
    changed[2].payload["price_minor"] = "180000"
    with pytest.raises(ImportIdempotencyConflict):
        await _create(
            service,
            context,
            changed,
            client_import_id=client_import_id,
            file_hash="a" * 64,
        )


@pytest.mark.anyio
async def test_idempotency_hash_includes_location_source_and_column_mapping() -> None:
    repository = MemoryRepository()
    service = ImportService(repository, ApplySpy())
    context = _context()
    client_import_id = uuid4()
    location_id = uuid4()
    await _create(
        service,
        context,
        _base_entities(),
        client_import_id=client_import_id,
        file_hash="b" * 64,
        location_id=location_id,
        mapping={"Наименование": "product"},
    )
    with pytest.raises(ImportIdempotencyConflict):
        await _create(
            service,
            context,
            _base_entities(),
            source_type=ImportSourceType.POSTER_EXPORT,
            client_import_id=client_import_id,
            file_hash="b" * 64,
            location_id=uuid4(),
            mapping={"Наименование": "inventory_item"},
        )


@pytest.mark.anyio
async def test_recipe_components_require_existing_unique_inventory_references() -> None:
    repository = MemoryRepository()
    service = ImportService(repository, ApplySpy())
    entities = _base_entities()
    entities.append(
        CanonicalImportEntity(
            ImportEntityType.RECIPE,
            "recipe:latte:350",
            {
                "variant_key": "variant:latte:350",
                "review_required": True,
                "components": [
                    {"inventory_item_key": "inventory:missing", "quantity": "1", "unit": "ml"},
                    {"inventory_item_key": "inventory:missing", "quantity": "1", "unit": "ml"},
                ],
            },
            sort_order=4,
        )
    )
    run = await _create(service, _context(), entities)
    assert run.status is ImportStatus.NEEDS_REVIEW
    assert run.entities[-1].error_codes


@pytest.mark.anyio
async def test_only_one_default_variant_is_allowed_per_product() -> None:
    repository = MemoryRepository()
    service = ImportService(repository, ApplySpy())
    entities = _base_entities()
    entities.append(
        CanonicalImportEntity(
            ImportEntityType.VARIANT,
            "variant:latte:450",
            {
                "product_key": "product:latte",
                "name": "450",
                "price_minor": "190000",
                "is_default": True,
            },
            sort_order=4,
        )
    )
    run = await _create(service, _context(), entities)
    assert run.status is ImportStatus.NEEDS_REVIEW
    variants = [
        entity for entity in run.entities if entity.entity_type is ImportEntityType.VARIANT
    ]
    assert any(entity.error_codes for entity in variants)


@pytest.mark.anyio
async def test_modifier_inventory_deltas_are_canonical_references() -> None:
    repository = MemoryRepository()
    service = ImportService(repository, ApplySpy())
    entities = _base_entities()
    entities.extend(
        (
            CanonicalImportEntity(
                ImportEntityType.MODIFIER_GROUP,
                "modifier-group:milk",
                {"variant_key": "variant:latte:350", "name": "Milk"},
                sort_order=4,
            ),
            CanonicalImportEntity(
                ImportEntityType.MODIFIER_OPTION,
                "modifier:oat",
                {
                    "group_key": "modifier-group:milk",
                    "name": "Oat",
                    "price_delta_minor": "30000",
                    "inventory_deltas": [
                        {"inventory_item_key": "inventory:missing", "quantity": "220", "unit": "ml"}
                    ],
                },
                sort_order=5,
            ),
        )
    )
    run = await _create(service, _context(), entities)
    assert run.status is ImportStatus.NEEDS_REVIEW
    assert run.entities[-1].error_codes


@pytest.mark.anyio
async def test_single_modifier_group_with_one_max_selection_is_valid() -> None:
    repository = MemoryRepository()
    service = ImportService(repository, ApplySpy())
    entities = _base_entities()
    entities.extend(
        (
            CanonicalImportEntity(
                ImportEntityType.MODIFIER_GROUP,
                "modifier-group:milk",
                {
                    "variant_key": "variant:latte:350",
                    "name": "Milk",
                    "selection_type": "SINGLE",
                    "min_selections": 0,
                    "max_selections": 1,
                },
                sort_order=4,
            ),
            CanonicalImportEntity(
                ImportEntityType.MODIFIER_OPTION,
                "modifier:regular",
                {
                    "group_key": "modifier-group:milk",
                    "name": "Regular",
                    "price_delta_minor": "0",
                    "inventory_deltas": [],
                },
                sort_order=5,
            ),
        )
    )

    run = await _create(service, _context(), entities)

    assert run.status is ImportStatus.READY
    assert not run.entities[-2].error_codes


@pytest.mark.anyio
async def test_patched_entity_missing_required_reference_cannot_become_ready() -> None:
    repository = MemoryRepository()
    service = ImportService(repository, ApplySpy())
    context = _context()
    run = await _create(service, context, _base_entities())
    product = next(
        entity for entity in run.entities if entity.entity_type is ImportEntityType.PRODUCT
    )

    patched = await service.patch_entity(
        context,
        run.id,
        product.id,
        resolution=ImportResolution.CREATE,
        target_id=None,
        payload={"name": "Latte"},
    )
    assert "CATEGORY_KEY_REQUIRED" in patched.error_codes
    validated = await service.validate(context, run.id)

    assert validated.status is ImportStatus.NEEDS_REVIEW
    assert product.error_codes


@pytest.mark.anyio
async def test_ai_draft_cannot_introduce_restricted_business_facts() -> None:
    repository = MemoryRepository()
    service = ImportService(repository, ApplySpy())
    entities = _base_entities()
    entities.append(
        CanonicalImportEntity(
            ImportEntityType.RECIPE,
            "recipe:invented",
            {
                "variant_key": "variant:latte:350",
                "review_required": True,
                "components": [],
                "nkt_code": "invented",
                "vat_rate": "12",
            },
            sort_order=4,
        )
    )
    run = await _create(
        service,
        _context(),
        entities,
        source_type=ImportSourceType.AI_EXTRACTION,
    )
    assert run.status is ImportStatus.NEEDS_REVIEW
    assert run.entities[-1].error_codes


@pytest.mark.anyio
async def test_low_confidence_ai_entity_requires_explicit_review() -> None:
    repository = MemoryRepository()
    service = ImportService(repository, ApplySpy())
    context = _context()
    entities = _base_entities()[:3]
    entities[1] = replace(entities[1], warning_codes=("AI_LOW_CONFIDENCE",))
    run = await _create(
        service,
        context,
        entities,
        source_type=ImportSourceType.AI_EXTRACTION,
    )

    assert (await service.validate(context, run.id)).status is ImportStatus.NEEDS_REVIEW
    product = run.entities[1]
    await service.patch_entity(
        context,
        run.id,
        product.id,
        resolution=ImportResolution.CREATE,
        target_id=None,
        payload=product.payload,
    )

    assert "AI_LOW_CONFIDENCE" not in product.warning_codes
    assert (await service.validate(context, run.id)).status is ImportStatus.READY


@pytest.mark.anyio
async def test_applied_import_replay_has_no_second_side_effect() -> None:
    repository = MemoryRepository()
    apply = ApplySpy()
    service = ImportService(repository, apply)
    context = _context()
    run = await _create(service, context, _base_entities())
    assert run.status is ImportStatus.READY
    first = await service.apply(context, run.id)
    second = await service.apply(context, run.id)
    assert first is second
    assert second.status is ImportStatus.APPLIED
    assert apply.calls == 1


@pytest.mark.anyio
async def test_duplicate_variant_sku_blocks_apply_readiness() -> None:
    repository = MemoryRepository()
    service = ImportService(repository, ApplySpy())
    entities = _base_entities()
    entities.append(
        CanonicalImportEntity(
            ImportEntityType.VARIANT,
            "variant:latte:450",
            {
                "product_key": "product:latte",
                "name": "450",
                "sku": "LATTE-350",
                "price_minor": "190000",
                "is_default": False,
            },
            sort_order=4,
        )
    )
    entities[2].payload["sku"] = "LATTE-350"
    run = await _create(service, _context(), entities)
    assert run.status is ImportStatus.NEEDS_REVIEW
    assert any(entity.error_codes for entity in run.entities[2:])


@pytest.mark.anyio
async def test_batch_activation_is_all_or_none_for_requested_products() -> None:
    repository = MemoryRepository()
    service = ImportService(repository, PartialActivation())
    context = _context()
    run = await _create(service, context, _base_entities())
    run.status = ImportStatus.APPLIED
    before_commits = repository.commits
    with pytest.raises(ActivationNotReady):
        await service.activate_ready(
            context,
            run.id,
            (uuid4(), uuid4()),
            confirm_starter_recipes_reviewed=True,
        )
    assert repository.commits == before_commits


@pytest.mark.anyio
@pytest.mark.parametrize("operation", ("patch", "validate", "cancel", "resume"))
async def test_mutating_import_operations_rollback_on_repository_failure(operation: str) -> None:
    repository = FailingRepository(
        "save_entity" if operation in {"patch", "validate"} else "save_run"
    )
    service = ImportService(repository, ApplySpy())
    context = _context()
    run = await _create(service, context, _base_entities())
    if operation == "resume":
        run.status = ImportStatus.FAILED
    with pytest.raises(RuntimeError, match="injected"):
        if operation == "patch":
            await service.patch_entity(
                context,
                run.id,
                run.entities[0].id,
                resolution=ImportResolution.CREATE,
                target_id=None,
                payload={"name": "Coffee updated"},
            )
        elif operation == "validate":
            await service.validate(context, run.id)
        elif operation == "cancel":
            await service.cancel(context, run.id)
        else:
            await service.resume(context, run.id)
    assert repository.rollbacks == 1


@pytest.mark.anyio
async def test_bulk_price_validation_failure_rolls_back_staged_entity_changes() -> None:
    repository = MemoryRepository()
    service = ImportService(repository, ApplySpy())
    context = _context()
    run = await _create(service, context, _base_entities())
    with pytest.raises(ImportEntityNotFound):
        await service.bulk_prices(context, run.id, {uuid4(): "180000"})
    assert repository.rollbacks == 1


@pytest.mark.anyio
async def test_activation_gateway_failure_rolls_back_session() -> None:
    repository = MemoryRepository()
    service = ImportService(repository, FailingActivation())
    context = _context()
    run = await _create(service, context, _base_entities())
    run.status = ImportStatus.APPLIED
    with pytest.raises(RuntimeError, match="activation"):
        await service.activate_ready(
            context,
            run.id,
            (uuid4(),),
            confirm_starter_recipes_reviewed=True,
        )
    assert repository.rollbacks == 1
