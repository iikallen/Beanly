from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

from beanly.core.money import MAX_BIGINT, MAX_NUMERIC_20_6_MINOR
from beanly.core.observability import metrics
from beanly.modules.onboarding.application.dto import CanonicalImportDraft
from beanly.modules.onboarding.application.ports import ImportApplyPort, OnboardingRepository
from beanly.modules.onboarding.domain.entities import ImportEntity, ImportRun
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
    ImportNotFound,
    ImportStateConflict,
    ImportValidationFailed,
)
from beanly.modules.organizations.domain.entities import TenantContext

_EDITABLE = frozenset({ImportStatus.NEEDS_REVIEW, ImportStatus.READY, ImportStatus.FAILED})


class ImportService:
    def __init__(self, repository: OnboardingRepository, apply_port: ImportApplyPort) -> None:
        self.repository = repository
        self.apply_port = apply_port

    async def ensure_location_access(
        self, context: TenantContext, location_id: UUID
    ) -> None:
        await self.apply_port.ensure_location_access(context, location_id)

    async def replay_source(
        self,
        context: TenantContext,
        *,
        client_import_id: UUID,
        location_id: UUID,
        source_type: ImportSourceType,
        file_hash: str,
    ) -> ImportRun | None:
        await self.ensure_location_access(context, location_id)
        existing = await self.repository.get_by_client_import_id(
            context.organization_id, client_import_id
        )
        if existing is None:
            return None
        if (
            existing.location_id != location_id
            or existing.source_type is not source_type
            or existing.file_hash != file_hash
        ):
            raise ImportIdempotencyConflict(
                "client_import_id was already used for a different source"
            )
        return existing

    async def create_from_draft(
        self,
        context: TenantContext,
        *,
        client_import_id: UUID,
        location_id: UUID,
        source_type: ImportSourceType,
        draft: CanonicalImportDraft,
        file_name: str | None = None,
        file_hash: str | None = None,
        mapping: dict[str, str] | None = None,
    ) -> ImportRun:
        await self.ensure_location_access(context, location_id)
        canonical = _canonical_bytes(
            draft,
            location_id=location_id,
            source_type=source_type,
            mapping=mapping or {},
        )
        payload_hash = hashlib.sha256(canonical).hexdigest()
        existing = await self.repository.get_by_client_import_id(
            context.organization_id, client_import_id
        )
        if existing is not None:
            if existing.payload_hash != payload_hash:
                raise ImportIdempotencyConflict(
                    "client_import_id was already used for different content"
                )
            return existing
        if len(draft.entities) > 10_000:
            raise ImportValidationFailed("Import exceeds the 10000 entity limit")
        now = datetime.now(UTC)
        run_id = uuid4()
        entities = [
            ImportEntity(
                id=uuid4(),
                import_run_id=run_id,
                entity_type=value.entity_type,
                source_key=value.source_key,
                payload=dict(value.payload),
                resolution=value.resolution,
                target_id=value.target_id,
                error_codes=list(value.error_codes),
                warning_codes=list(value.warning_codes),
                sort_order=value.sort_order,
            )
            for value in draft.entities
        ]
        error_count, warning_count = _validate_entities(entities, source_type)
        # AI always enters human review once; other warnings stay visible without blocking.
        # Review-sensitive starter recipes are still guarded explicitly at activation.
        status = (
            ImportStatus.NEEDS_REVIEW
            if error_count or source_type is ImportSourceType.AI_EXTRACTION
            else ImportStatus.READY
        )
        run = ImportRun(
            id=run_id,
            organization_id=context.organization_id,
            location_id=location_id,
            client_import_id=client_import_id,
            source_type=source_type,
            source_name=draft.source_name,
            source_version=draft.source_version,
            file_name=file_name,
            file_hash=file_hash,
            status=status,
            entity_count=len(entities),
            error_count=error_count,
            warning_count=warning_count,
            payload_hash=payload_hash,
            mapping=dict(mapping or {}),
            created_by=context.user_id,
            created_at=now,
            applied_at=None,
            failed_at=None,
            entities=entities,
        )
        try:
            await self.repository.add_run(run, entities)
            await self.repository.commit()
        except Exception:
            await self.repository.rollback()
            replay = await self.repository.get_by_client_import_id(
                context.organization_id, client_import_id
            )
            if replay is not None:
                if replay.payload_hash == payload_hash:
                    return replay
                raise ImportIdempotencyConflict(
                    "client_import_id was concurrently used for different content"
                ) from None
            raise
        metrics.menu_import_started.add(1, {"source_type": source_type.value})
        metrics.menu_import_entities.add(len(entities), {"source_type": source_type.value})
        if error_count:
            metrics.menu_import_errors.add(error_count, {"source_type": source_type.value})
        return run

    async def get(self, context: TenantContext, run_id: UUID) -> ImportRun:
        value = await self.repository.get_run(context.organization_id, run_id)
        if value is None:
            raise ImportNotFound("Import run not found")
        await self.apply_port.ensure_location_access(context, value.location_id)
        return value

    async def list_runs(
        self,
        context: TenantContext,
        *,
        status: ImportStatus | None,
        source_type: ImportSourceType | None,
        limit: int,
        offset: int,
    ) -> tuple[list[ImportRun], int]:
        location_ids = await self.apply_port.accessible_location_ids(context)
        return await self.repository.list_runs(
            context.organization_id,
            location_ids=location_ids,
            status=status,
            source_type=source_type,
            limit=limit,
            offset=offset,
        )

    async def patch_entity(
        self,
        context: TenantContext,
        run_id: UUID,
        entity_id: UUID,
        *,
        resolution: ImportResolution,
        target_id: UUID | None,
        payload: dict[str, object] | None,
    ) -> ImportEntity:
        try:
            run = await self._editable(context, run_id)
            entity = next((value for value in run.entities if value.id == entity_id), None)
            if entity is None:
                raise ImportEntityNotFound("Import entity not found")
            entity.resolution = resolution
            entity.target_id = target_id
            if payload is not None:
                _validate_payload_shape(payload)
                entity.payload = payload
            _validate_entities(run.entities, run.source_type)
            await self.repository.save_entity(entity)
            run.error_count = sum(len(value.error_codes) for value in run.entities)
            run.warning_count = sum(len(value.warning_codes) for value in run.entities)
            run.status = ImportStatus.NEEDS_REVIEW
            await self.repository.save_run(run)
            await self.repository.commit()
            return entity
        except Exception:
            await self.repository.rollback()
            raise

    async def validate(self, context: TenantContext, run_id: UUID) -> ImportRun:
        try:
            run = await self._editable(context, run_id)
            errors, warnings = _validate_entities(run.entities, run.source_type)
            for entity in run.entities:
                await self.repository.save_entity(entity)
            run.error_count = errors
            run.warning_count = warnings
            run.status = ImportStatus.READY if errors == 0 else ImportStatus.NEEDS_REVIEW
            await self.repository.save_run(run)
            await self.repository.commit()
            return run
        except Exception:
            await self.repository.rollback()
            raise

    async def bulk_prices(
        self, context: TenantContext, run_id: UUID, rows: dict[UUID, str]
    ) -> ImportRun:
        try:
            run = await self._editable(context, run_id)
            found: set[UUID] = set()
            for entity in run.entities:
                if entity.id not in rows:
                    continue
                if entity.entity_type not in {
                    ImportEntityType.VARIANT,
                    ImportEntityType.LOCATION_PRICE,
                }:
                    raise ImportValidationFailed(
                        "Price rows must target variant or location price"
                    )
                entity.payload["price_minor"] = rows[entity.id]
                found.add(entity.id)
                await self.repository.save_entity(entity)
            if found != set(rows):
                raise ImportEntityNotFound("One or more price entities were not found")
            return await self.validate(context, run_id)
        except Exception:
            await self.repository.rollback()
            raise

    async def apply(self, context: TenantContext, run_id: UUID) -> ImportRun:
        run = await self.repository.get_run(context.organization_id, run_id, lock=True)
        if run is None:
            raise ImportNotFound("Import run not found")
        if run.status is ImportStatus.APPLIED:
            return run
        if run.status is not ImportStatus.READY:
            raise ImportStateConflict("Only a READY import can be applied")
        run.status = ImportStatus.APPLYING
        await self.repository.save_run(run)
        try:
            await self.apply_port.apply(context, run)
            for entity in run.entities:
                await self.repository.save_entity(entity)
            run.status = ImportStatus.APPLIED
            run.applied_at = datetime.now(UTC)
            await self.repository.save_run(run)
            await self.repository.commit()
        except Exception:
            await self.repository.rollback()
            failed = await self.repository.get_run(context.organization_id, run_id, lock=True)
            if failed is not None and failed.status is not ImportStatus.APPLIED:
                failed.status = ImportStatus.FAILED
                failed.failed_at = datetime.now(UTC)
                await self.repository.save_run(failed)
                await self.repository.commit()
            metrics.menu_import_failed.add(1, {"source_type": run.source_type.value})
            raise
        metrics.menu_import_applied.add(1, {"source_type": run.source_type.value})
        return run

    async def cancel(self, context: TenantContext, run_id: UUID) -> ImportRun:
        try:
            run = await self._editable(context, run_id)
            run.status = ImportStatus.CANCELLED
            await self.repository.save_run(run)
            await self.repository.commit()
            return run
        except Exception:
            await self.repository.rollback()
            raise

    async def resume(self, context: TenantContext, run_id: UUID) -> ImportRun:
        try:
            run = await self.get(context, run_id)
            if run.status is not ImportStatus.FAILED:
                raise ImportStateConflict("Only a FAILED import can be resumed")
            run.status = ImportStatus.NEEDS_REVIEW
            run.failed_at = None
            await self.repository.save_run(run)
            await self.repository.commit()
            return run
        except Exception:
            await self.repository.rollback()
            raise

    async def activate_ready(
        self,
        context: TenantContext,
        run_id: UUID,
        product_ids: tuple[UUID, ...],
        *,
        confirm_starter_recipes_reviewed: bool,
    ) -> tuple[list[dict[str, object]], int]:
        try:
            run = await self.get(context, run_id)
            if run.status is not ImportStatus.APPLIED:
                raise ImportStateConflict("Products can be activated only after APPLIED")
            items, count = await self.apply_port.activate_ready(
                context,
                run,
                product_ids,
                confirm_starter_recipes_reviewed=confirm_starter_recipes_reviewed,
            )
            if any(not item["ready"] for item in items) or count != len(items):
                raise ActivationNotReady("No requested product is ready for activation")
            await self.repository.commit()
            return items, count
        except Exception:
            await self.repository.rollback()
            raise

    async def _editable(self, context: TenantContext, run_id: UUID) -> ImportRun:
        run = await self.repository.get_run(context.organization_id, run_id, lock=True)
        if run is None:
            raise ImportNotFound("Import run not found")
        if run.status not in _EDITABLE:
            raise ImportStateConflict("Import run is immutable in its current status")
        return run


def _canonical_bytes(
    draft: CanonicalImportDraft,
    *,
    location_id: UUID,
    source_type: ImportSourceType,
    mapping: dict[str, str],
) -> bytes:
    value = {
        "location_id": str(location_id),
        "source_type": source_type.value,
        "mapping": mapping,
        "source_name": draft.source_name,
        "source_version": draft.source_version,
        "entities": [
            {
                "entity_type": entity.entity_type.value,
                "source_key": entity.source_key,
                "payload": entity.payload,
                "resolution": entity.resolution.value,
                "target_id": str(entity.target_id) if entity.target_id else None,
                "errors": list(entity.error_codes),
                "warnings": list(entity.warning_codes),
                "sort_order": entity.sort_order,
            }
            for entity in draft.entities
        ],
    }
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _validate_entities(
    entities: list[ImportEntity], source_type: ImportSourceType | None = None
) -> tuple[int, int]:
    keys = {value.source_key for value in entities}
    duplicate_keys = len(keys) != len(entities)
    default_variants: dict[str, list[ImportEntity]] = {}
    variant_skus: dict[str, list[ImportEntity]] = {}
    for entity in entities:
        entity.error_codes = []
        _validate_payload_shape(entity.payload)
        if duplicate_keys:
            entity.error_codes.append("DUPLICATE_SOURCE_KEY")
        if not entity.source_key or len(entity.source_key) > 255:
            entity.error_codes.append("INVALID_SOURCE_KEY")
        if entity.resolution is ImportResolution.MATCH_EXISTING and entity.target_id is None:
            entity.error_codes.append("MATCH_TARGET_REQUIRED")
        for reference in _references(entity):
            if reference not in keys:
                entity.error_codes.append("REFERENCE_NOT_FOUND")
        if entity.entity_type in {ImportEntityType.VARIANT, ImportEntityType.LOCATION_PRICE}:
            _validate_minor(entity, "price_minor")
        if entity.entity_type is ImportEntityType.MODIFIER_OPTION:
            _validate_minor(entity, "price_delta_minor")
        if entity.entity_type is ImportEntityType.MODIFIER_GROUP:
            try:
                minimum = int(str(entity.payload.get("min_selections")))
                maximum = int(str(entity.payload.get("max_selections")))
            except (TypeError, ValueError):
                entity.error_codes.append("INVALID_MODIFIER_CONSTRAINTS")
            else:
                if (
                    minimum < 0
                    or maximum < 1
                    or minimum > maximum
                    or (
                        entity.payload.get("selection_type") == "SINGLE"
                        and maximum != 1
                    )
                ):
                    entity.error_codes.append("INVALID_MODIFIER_CONSTRAINTS")
        if entity.entity_type is ImportEntityType.INVENTORY_ITEM:
            if entity.payload.get("base_unit") not in {"g", "ml", "pcs"}:
                entity.error_codes.append("INVALID_UNIT")
        if entity.entity_type is ImportEntityType.PRODUCT:
            entity.payload["status"] = "DRAFT"
        if entity.entity_type is ImportEntityType.VARIANT and bool(
            entity.payload.get("is_default")
        ):
            product_key = str(entity.payload.get("product_key", ""))
            default_variants.setdefault(product_key, []).append(entity)
        if entity.entity_type is ImportEntityType.VARIANT and entity.payload.get("sku"):
            sku = str(entity.payload["sku"]).strip().casefold()
            variant_skus.setdefault(sku, []).append(entity)
        if entity.entity_type is ImportEntityType.RECIPE:
            components = entity.payload.get("components")
            if not isinstance(components, list) or not components:
                entity.error_codes.append("RECIPE_COMPONENTS_REQUIRED")
            else:
                component_keys: list[str] = []
                for component in components:
                    if not isinstance(component, dict):
                        entity.error_codes.append("INVALID_RECIPE_COMPONENT")
                        continue
                    key = str(component.get("inventory_item_key", ""))
                    component_keys.append(key)
                    if key not in keys:
                        entity.error_codes.append("REFERENCE_NOT_FOUND")
                if len(component_keys) != len(set(component_keys)):
                    entity.error_codes.append("DUPLICATE_RECIPE_COMPONENT")
        if entity.entity_type is ImportEntityType.MODIFIER_OPTION:
            deltas = entity.payload.get("inventory_deltas", [])
            if not isinstance(deltas, list):
                entity.error_codes.append("INVALID_MODIFIER_DELTAS")
            else:
                for delta in deltas:
                    if (
                        not isinstance(delta, dict)
                        or str(delta.get("inventory_item_key", "")) not in keys
                    ):
                        entity.error_codes.append("REFERENCE_NOT_FOUND")
        if source_type is ImportSourceType.AI_EXTRACTION:
            if entity.entity_type in {
                ImportEntityType.INVENTORY_ITEM,
                ImportEntityType.RECIPE,
                ImportEntityType.OPENING_BALANCE,
            }:
                entity.error_codes.append("AI_RESTRICTED_BUSINESS_FACT")
            if {"nkt_code", "vat_rate", "fiscal_unit_code"}.intersection(entity.payload):
                entity.error_codes.append("AI_RESTRICTED_BUSINESS_FACT")
    for variants in default_variants.values():
        if len(variants) > 1:
            for entity in variants:
                entity.error_codes.append("MULTIPLE_DEFAULT_VARIANTS")
    for variants in variant_skus.values():
        if len(variants) > 1:
            for entity in variants:
                entity.error_codes.append("DUPLICATE_VARIANT_SKU")
    return (
        sum(len(value.error_codes) for value in entities),
        sum(len(value.warning_codes) for value in entities),
    )


def _references(entity: ImportEntity) -> list[str]:
    fields = {
        ImportEntityType.PRODUCT: ("category_key",),
        ImportEntityType.VARIANT: ("product_key",),
        ImportEntityType.RECIPE: ("variant_key",),
        ImportEntityType.MODIFIER_GROUP: ("variant_key",),
        ImportEntityType.MODIFIER_OPTION: ("group_key",),
        ImportEntityType.LOCATION_PRICE: ("variant_key",),
        ImportEntityType.OPENING_BALANCE: ("inventory_item_key",),
    }.get(entity.entity_type, ())
    return [str(entity.payload[field]) for field in fields if field in entity.payload]


def _validate_minor(entity: ImportEntity, field: str) -> None:
    raw = entity.payload.get(field)
    try:
        value = int(str(raw))
    except (TypeError, ValueError):
        entity.error_codes.append("INVALID_MINOR_AMOUNT")
        return
    if str(value) != str(raw) or value < 0 or value > min(MAX_BIGINT, MAX_NUMERIC_20_6_MINOR):
        entity.error_codes.append("INVALID_MINOR_AMOUNT")


def _validate_payload_shape(payload: dict[str, object]) -> None:
    encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
    if len(encoded) > 65_536 or _depth(payload) > 10:
        raise ImportValidationFailed("Entity payload exceeds size or nesting limits")


def _depth(value: object) -> int:
    if isinstance(value, dict):
        return 1 + max((_depth(child) for child in value.values()), default=0)
    if isinstance(value, list):
        return 1 + max((_depth(child) for child in value), default=0)
    return 0
