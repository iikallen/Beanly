import json
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Form, HTTPException, Query, Response, UploadFile, status

from beanly.modules.onboarding.api.dependencies import (
    ImportApplyDep,
    ImportServiceDep,
    MenuImportDep,
    OnboardingReadDep,
    OnboardingServiceDep,
    OnboardingWriteDep,
    TemplateServiceDep,
)
from beanly.modules.onboarding.api.schemas import (
    ActivateReadyRequest,
    ActivateReadyResponse,
    BootstrapRequest,
    BootstrapResponse,
    BulkPriceRequest,
    CapabilityResponse,
    ImportEntityPatchRequest,
    ImportEntityResponse,
    ImportInspectResponse,
    ImportRunListResponse,
    ImportRunResponse,
    ImportRunSummaryResponse,
    ImportValidationResponse,
    OnboardingCapabilitiesResponse,
    OnboardingStatusResponse,
    PosterCapabilityResponse,
    PublicMenuUrlRequest,
    SpreadsheetCapabilityResponse,
    TemplateListResponse,
    TemplatePreviewRequest,
    TemplateSummaryResponse,
)
from beanly.modules.onboarding.domain.enums import (
    ImportSourceType,
    ImportStatus,
    UploadSourceType,
)
from beanly.modules.onboarding.domain.exceptions import (
    AiExtractionUnavailable,
    ImportEntityNotFound,
    ImportFileTooLarge,
    ImportFileTypeInvalid,
    ImportIdempotencyConflict,
    ImportLocationNotFound,
    ImportNotFound,
    ImportParseFailed,
    ImportStateConflict,
    ImportValidationFailed,
    OnboardingError,
    TemplateNotFound,
)
from beanly.modules.onboarding.infrastructure.spreadsheets import (
    MAX_UPLOAD_BYTES,
    inspect_spreadsheet,
    parse_spreadsheet,
)

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


@router.get("/status", response_model=OnboardingStatusResponse)
async def onboarding_status(
    context: OnboardingReadDep, service: OnboardingServiceDep
) -> OnboardingStatusResponse:
    return OnboardingStatusResponse.model_validate(await service.status(context))


@router.post("/bootstrap", response_model=BootstrapResponse)
async def bootstrap(
    payload: BootstrapRequest,
    context: OnboardingWriteDep,
    service: OnboardingServiceDep,
) -> BootstrapResponse:
    try:
        return BootstrapResponse.model_validate(
            await service.bootstrap(context, payload.warehouse_name, payload.register_name)
        )
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"code": "ONBOARDING_BOOTSTRAP_CONFLICT", "message": str(exc)},
        ) from exc


@router.post("/dismiss", response_model=OnboardingStatusResponse)
async def dismiss(
    context: OnboardingWriteDep, service: OnboardingServiceDep
) -> OnboardingStatusResponse:
    return OnboardingStatusResponse.model_validate(await service.dismiss(context))


@router.get("/capabilities", response_model=OnboardingCapabilitiesResponse)
async def capabilities(_: OnboardingReadDep) -> OnboardingCapabilitiesResponse:
    return OnboardingCapabilitiesResponse(
        ai=CapabilityResponse(available=False, reason="AI_EXTRACTION_UNAVAILABLE"),
        poster=PosterCapabilityResponse(
            available=True,
            reason="Real anonymized Poster fixture has not been verified",
            real_fixture_verified=False,
            extensions=[".xls", ".xlsx"],
        ),
        spreadsheet=SpreadsheetCapabilityResponse(csv=True, xlsx=True, max_bytes=MAX_UPLOAD_BYTES),
    )


@router.get("/templates", response_model=TemplateListResponse)
async def templates(_: OnboardingReadDep, service: TemplateServiceDep) -> TemplateListResponse:
    return TemplateListResponse(
        items=[TemplateSummaryResponse.model_validate(value) for value in service.list()],
        spreadsheet_download_url="/api/v1/onboarding/templates/spreadsheet",
    )


@router.get("/templates/spreadsheet")
async def spreadsheet_template(_: OnboardingReadDep, service: TemplateServiceDep) -> Response:
    return Response(
        service.workbook(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="beanly-import-template.xlsx"'},
    )


@router.post("/templates/{code}/preview", response_model=ImportRunResponse)
async def preview_template(
    code: str,
    payload: TemplatePreviewRequest,
    context: MenuImportDep,
    templates: TemplateServiceDep,
    imports: ImportServiceDep,
) -> ImportRunResponse:
    try:
        draft = templates.draft(code, payload.version, payload.options.model_dump())
        return await _run_response(
            await imports.create_from_draft(
                context,
                client_import_id=payload.client_import_id,
                location_id=payload.location_id,
                source_type=ImportSourceType.BEANLY_TEMPLATE,
                draft=draft,
            ),
            imports,
        )
    except OnboardingError as exc:
        raise _http_error(exc) from exc


@router.post("/imports", response_model=ImportRunResponse)
async def upload_import(
    context: MenuImportDep,
    imports: ImportServiceDep,
    client_import_id: Annotated[UUID, Form()],
    location_id: Annotated[UUID, Form()],
    file: Annotated[UploadFile, File()],
    source_type: Annotated[UploadSourceType, Form()] = UploadSourceType.AUTO,
    mapping_json: Annotated[str | None, Form()] = None,
) -> ImportRunResponse:
    try:
        content = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(content) > MAX_UPLOAD_BYTES:
            raise ImportFileTooLarge("Import file exceeds 10 MB")
        mapping = _mapping(mapping_json)
        draft, detected, file_hash = parse_spreadsheet(
            content,
            file.filename or "upload",
            file.content_type,
            source_type,
            mapping,
        )
        run = await imports.create_from_draft(
            context,
            client_import_id=client_import_id,
            location_id=location_id,
            source_type=detected,
            draft=draft,
            file_name=(file.filename or "upload")[:255],
            file_hash=file_hash,
            mapping=mapping,
        )
        return await _run_response(run, imports)
    except OnboardingError as exc:
        raise _http_error(exc) from exc
    finally:
        await file.close()


@router.post("/imports/inspect", response_model=ImportInspectResponse)
async def inspect_import(
    _: MenuImportDep,
    file: Annotated[UploadFile, File()],
    source_type: Annotated[UploadSourceType, Form()] = UploadSourceType.AUTO,
) -> ImportInspectResponse:
    try:
        content = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(content) > MAX_UPLOAD_BYTES:
            raise ImportFileTooLarge("Import file exceeds 10 MB")
        return ImportInspectResponse.model_validate(
            inspect_spreadsheet(
                content,
                file.filename or "upload",
                file.content_type,
                source_type,
            )
        )
    except OnboardingError as exc:
        raise _http_error(exc) from exc
    finally:
        await file.close()


@router.post("/imports/ai", response_model=ImportRunResponse)
async def ai_file_unavailable(
    _: MenuImportDep, file: Annotated[UploadFile, File()]
) -> ImportRunResponse:
    await file.close()
    raise _http_error(AiExtractionUnavailable("AI extraction adapter is not configured"))


@router.post("/imports/ai/url", response_model=ImportRunResponse)
async def ai_url_unavailable(_: MenuImportDep, payload: PublicMenuUrlRequest) -> ImportRunResponse:
    del payload
    raise _http_error(AiExtractionUnavailable("AI extraction adapter is not configured"))


@router.get("/imports", response_model=ImportRunListResponse)
async def list_imports(
    context: OnboardingReadDep,
    imports: ImportServiceDep,
    import_status: Annotated[ImportStatus | None, Query(alias="status")] = None,
    source_type: ImportSourceType | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> ImportRunListResponse:
    values, total = await imports.list_runs(
        context,
        status=import_status,
        source_type=source_type,
        limit=limit,
        offset=offset,
    )
    return ImportRunListResponse(
        items=[ImportRunSummaryResponse.model_validate(value) for value in values],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/imports/{run_id}", response_model=ImportRunResponse)
async def get_import(
    run_id: UUID, context: OnboardingReadDep, imports: ImportServiceDep
) -> ImportRunResponse:
    try:
        return await _run_response(await imports.get(context, run_id), imports)
    except OnboardingError as exc:
        raise _http_error(exc) from exc


@router.patch("/imports/{run_id}/entities/{entity_id}", response_model=ImportEntityResponse)
async def patch_import_entity(
    run_id: UUID,
    entity_id: UUID,
    payload: ImportEntityPatchRequest,
    context: MenuImportDep,
    imports: ImportServiceDep,
) -> ImportEntityResponse:
    try:
        return ImportEntityResponse.model_validate(
            await imports.patch_entity(context, run_id, entity_id, **payload.model_dump())
        )
    except OnboardingError as exc:
        raise _http_error(exc) from exc


@router.post("/imports/{run_id}/validate", response_model=ImportValidationResponse)
async def validate_import(
    run_id: UUID, context: MenuImportDep, imports: ImportServiceDep
) -> ImportValidationResponse:
    try:
        run = await imports.validate(context, run_id)
        return ImportValidationResponse(
            run=await _run_response(run, imports),
            valid=run.error_count == 0,
            error_count=run.error_count,
            warning_count=run.warning_count,
        )
    except OnboardingError as exc:
        raise _http_error(exc) from exc


@router.put("/imports/{run_id}/prices", response_model=ImportValidationResponse)
async def bulk_prices(
    run_id: UUID,
    payload: BulkPriceRequest,
    context: MenuImportDep,
    imports: ImportServiceDep,
) -> ImportValidationResponse:
    try:
        run = await imports.bulk_prices(
            context, run_id, {value.entity_id: value.price_minor for value in payload.rows}
        )
        return ImportValidationResponse(
            run=await _run_response(run, imports),
            valid=run.error_count == 0,
            error_count=run.error_count,
            warning_count=run.warning_count,
        )
    except OnboardingError as exc:
        raise _http_error(exc) from exc


@router.post("/imports/{run_id}/apply", response_model=ImportRunResponse)
async def apply_import(
    run_id: UUID, context: ImportApplyDep, imports: ImportServiceDep
) -> ImportRunResponse:
    try:
        return await _run_response(await imports.apply(context, run_id), imports)
    except OnboardingError as exc:
        raise _http_error(exc) from exc


@router.post("/imports/{run_id}/cancel", response_model=ImportRunResponse)
async def cancel_import(
    run_id: UUID, context: MenuImportDep, imports: ImportServiceDep
) -> ImportRunResponse:
    try:
        return await _run_response(await imports.cancel(context, run_id), imports)
    except OnboardingError as exc:
        raise _http_error(exc) from exc


@router.post("/imports/{run_id}/resume", response_model=ImportRunResponse)
async def resume_import(
    run_id: UUID, context: MenuImportDep, imports: ImportServiceDep
) -> ImportRunResponse:
    try:
        return await _run_response(await imports.resume(context, run_id), imports)
    except OnboardingError as exc:
        raise _http_error(exc) from exc


@router.post("/imports/{run_id}/activate-ready", response_model=ActivateReadyResponse)
async def activate_ready(
    run_id: UUID,
    payload: ActivateReadyRequest,
    context: ImportApplyDep,
    imports: ImportServiceDep,
) -> ActivateReadyResponse:
    try:
        items, count = await imports.activate_ready(
            context,
            run_id,
            tuple(payload.product_ids),
            confirm_starter_recipes_reviewed=payload.confirm_starter_recipes_reviewed,
        )
        return ActivateReadyResponse(items=items, activated_count=count)
    except OnboardingError as exc:
        raise _http_error(exc) from exc


async def _run_response(run, imports: ImportServiceDep) -> ImportRunResponse:
    duplicate_id = (
        await imports.repository.find_duplicate_file(
            run.organization_id, run.file_hash, exclude_id=run.id
        )
        if run.file_hash
        else None
    )
    return ImportRunResponse.model_validate(run).model_copy(
        update={
            "duplicate_file_run_id": duplicate_id,
            "duplicate_warning": "DUPLICATE_FILE" if duplicate_id else None,
        }
    )


def _http_error(exc: OnboardingError) -> HTTPException:
    detail = {"code": exc.code, "message": str(exc)}
    if isinstance(
        exc, (ImportNotFound, ImportEntityNotFound, ImportLocationNotFound, TemplateNotFound)
    ):
        return HTTPException(status.HTTP_404_NOT_FOUND, detail)
    if isinstance(exc, AiExtractionUnavailable):
        return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail)
    if isinstance(exc, (ImportIdempotencyConflict, ImportStateConflict)):
        return HTTPException(status.HTTP_409_CONFLICT, detail)
    if isinstance(exc, ImportFileTooLarge):
        return HTTPException(413, detail)
    if isinstance(exc, (ImportFileTypeInvalid, ImportParseFailed, ImportValidationFailed)):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail)
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail)


def _mapping(raw: str | None) -> dict[str, str]:
    if raw is None:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ImportParseFailed("mapping_json must be valid JSON") from exc
    if not isinstance(value, dict) or not all(
        isinstance(key, str) and isinstance(mapped, str) for key, mapped in value.items()
    ):
        raise ImportParseFailed("mapping_json must be a source-column to field object")
    return value
