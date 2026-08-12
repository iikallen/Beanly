import json as jsonlib
from hashlib import sha256
from io import BytesIO
from uuid import UUID, uuid4

import httpx
import pytest
from PIL import Image
from pydantic import ValidationError
from pypdf import PdfWriter
from sqlalchemy import func, select

from beanly.core.money import MAX_NUMERIC_20_6_MINOR
from beanly.main import app
from beanly.modules.inventory.infrastructure.db.models import InventoryItemModel
from beanly.modules.menu.infrastructure.db.models import MenuCategoryModel, ProductModel
from beanly.modules.onboarding.api.dependencies import ai_menu_extractor
from beanly.modules.onboarding.application.dto import (
    CanonicalImportDraft,
)
from beanly.modules.onboarding.domain.enums import ImportEntityType
from beanly.modules.onboarding.domain.exceptions import (
    AiExtractionFailed,
    ImportFileTypeInvalid,
)
from beanly.modules.onboarding.infrastructure.ai.media import (
    PublicMenuFetcher,
    prepare_file,
    prepare_file_isolated,
)
from beanly.modules.onboarding.infrastructure.ai.ollama_client import OllamaMenuClient
from beanly.modules.onboarding.infrastructure.ai.schemas import (
    MenuExtractionDocument,
    to_canonical_draft,
)
from beanly.modules.onboarding.infrastructure.db.models import (
    OnboardingImportEntityModel,
    OnboardingImportRunModel,
)


def _menu_document(*, confidence: float = 0.95) -> dict[str, object]:
    return {
        "currency_code": "KZT",
        "categories": [
            {
                "name": "Coffee",
                "confidence": confidence,
                "source_reference": "page 1",
                "products": [
                    {
                        "name": "Latte",
                        "description": None,
                        "confidence": confidence,
                        "source_reference": "page 1",
                        "variants": [
                            {
                                "name": "350 ml",
                                "price_minor": 170_000,
                                "confidence": confidence,
                                "source_reference": "page 1",
                                "modifiers": [],
                            }
                        ],
                    }
                ],
            }
        ],
    }


def _draft(*, confidence: float = 0.95) -> CanonicalImportDraft:
    return to_canonical_draft(
        MenuExtractionDocument.model_validate(_menu_document(confidence=confidence)),
        confidence_threshold=0.8,
    )


def _contains_key(value: object, keys: set[str]) -> bool:
    if isinstance(value, dict):
        return any(key in keys or _contains_key(item, keys) for key, item in value.items())
    if isinstance(value, list):
        return any(_contains_key(item, keys) for item in value)
    return False


def test_money_range_is_validated_without_ollama_grammar_maximum() -> None:
    payload = _menu_document()
    payload["categories"][0]["products"][0]["variants"][0]["price_minor"] = (
        MAX_NUMERIC_20_6_MINOR + 1
    )
    with pytest.raises(ValidationError, match="supported range"):
        MenuExtractionDocument.model_validate(payload)
    assert str(MAX_NUMERIC_20_6_MINOR) not in jsonlib.dumps(
        MenuExtractionDocument.model_json_schema()
    )


class FakeExtractor:
    available = True

    def __init__(self, draft: CanonicalImportDraft | None = None) -> None:
        self.draft = draft or _draft()

    async def extract_file(
        self, content: bytes, media_type: str, file_name: str
    ) -> CanonicalImportDraft:
        assert content
        assert media_type == "image/png"
        assert file_name == "menu.png"
        return self.draft

    async def extract_url(self, public_url: str) -> CanonicalImportDraft:
        assert public_url.startswith("https://")
        return self.draft


class CountingExtractor(FakeExtractor):
    calls = 0

    async def extract_file(
        self, content: bytes, media_type: str, file_name: str
    ) -> CanonicalImportDraft:
        type(self).calls += 1
        return await super().extract_file(content, media_type, file_name)


async def _workspace(client, email: str, name: str):
    password = "correct-horse-battery-staple"
    registered = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": password,
            "first_name": "AI",
            "last_name": "Importer",
        },
    )
    assert registered.status_code == 201, registered.text
    login = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
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
    body = created.json()
    organization_id = UUID(body["organization"]["id"])
    location_id = UUID(body["location"]["id"])
    return (
        {**auth, "X-Organization-ID": str(organization_id)},
        organization_id,
        location_id,
    )


def test_ai_schema_is_strict_and_canonical_draft_contains_only_menu_facts() -> None:
    malicious = _menu_document()
    malicious["categories"][0]["products"][0]["recipe"] = {"milk_ml": 200}  # type: ignore[index]
    with pytest.raises(ValidationError):
        MenuExtractionDocument.model_validate(malicious)

    draft = _draft(confidence=0.3)
    assert {entity.entity_type for entity in draft.entities} == {
        ImportEntityType.CATEGORY,
        ImportEntityType.PRODUCT,
        ImportEntityType.VARIANT,
    }
    assert all("AI_LOW_CONFIDENCE" in entity.warning_codes for entity in draft.entities)
    serialized = jsonlib.dumps(
        [entity.payload for entity in draft.entities], ensure_ascii=False
    ).casefold()
    assert all(
        word not in serialized
        for word in ("recipe", "inventory", "opening", "nkt", "vat", "fiscal")
    )


@pytest.mark.anyio
async def test_ollama_uses_structured_schema_and_rejects_extra_business_fields(
    monkeypatch,
) -> None:
    requests: list[dict[str, object]] = []

    class FakeClient:
        def __init__(self, **kwargs) -> None:
            assert kwargs["follow_redirects"] is False
            assert kwargs["trust_env"] is False

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args) -> None:
            return None

        async def post(self, url: str, *, json: dict[str, object]):
            requests.append(json)
            invalid = _menu_document()
            invalid["categories"][0]["products"][0]["vat_rate"] = 12  # type: ignore[index]
            return httpx.Response(
                200,
                json={
                    "message": {
                        "content": "",
                        "thinking": jsonlib.dumps(invalid),
                    }
                },
                request=httpx.Request("POST", url),
            )

    monkeypatch.setattr(
        "beanly.modules.onboarding.infrastructure.ai.ollama_client.httpx.AsyncClient",
        FakeClient,
    )
    client = OllamaMenuClient("http://ollama:11434", "qwen3-vl:4b", 10)
    with pytest.raises(AiExtractionFailed):
        await client.extract(text="Latte 1700 KZT", images=())

    body = requests[0]
    assert body["stream"] is False
    assert body["think"] is False
    assert body["options"] == {"temperature": 0, "num_predict": 8192}
    system_prompt = body["messages"][0]["content"]  # type: ignore[index]
    assert "1700 KZT" in system_prompt and "170000" in system_prompt
    schema = body["format"]
    assert isinstance(schema, dict)
    assert schema["additionalProperties"] is False
    assert not _contains_key(schema, {"maximum", "maxItems", "maxLength"})
    assert "recipes" not in jsonlib.dumps(schema).casefold()


def test_ai_media_validates_magic_extension_and_pdf_page_limit() -> None:
    image = Image.new("RGB", (2, 2), "white")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    image.close()
    prepared = prepare_file(buffer.getvalue(), "image/png", "menu.png")
    assert prepared.text == ""
    assert len(prepared.images) == 1
    with pytest.raises(ImportFileTypeInvalid):
        prepare_file(buffer.getvalue(), "image/png", "menu.jpg")

    pdf = PdfWriter()
    for _ in range(21):
        pdf.add_blank_page(width=72, height=72)
    pdf_bytes = BytesIO()
    pdf.write(pdf_bytes)
    with pytest.raises(ImportFileTypeInvalid, match="1-20 pages"):
        prepare_file(pdf_bytes.getvalue(), "application/pdf", "menu.pdf")


def test_ai_media_isolated_worker_returns_sanitized_image() -> None:
    buffer = BytesIO()
    Image.new("RGB", (32, 16), "white").save(buffer, format="PNG")

    prepared = prepare_file_isolated(buffer.getvalue(), "image/png", "menu.png")

    assert prepared.text == ""
    assert len(prepared.images) == 1


@pytest.mark.anyio
@pytest.mark.parametrize(
    "url",
    (
        "http://127.0.0.1/menu.pdf",
        "http://localhost/menu.pdf",
        "http://169.254.169.254/latest/meta-data",
    ),
)
async def test_public_menu_fetch_rejects_private_and_metadata_networks(url: str) -> None:
    with pytest.raises(ImportFileTypeInvalid, match="public addresses"):
        await PublicMenuFetcher().fetch(url)


@pytest.mark.anyio
async def test_ai_disabled_capability_and_upload_return_explicit_503(app_client) -> None:
    client, _ = app_client
    headers, _, location_id = await _workspace(
        client, "ai-disabled@example.com", "Disabled AI"
    )
    capabilities = await client.get("/api/v1/onboarding/capabilities", headers=headers)
    assert capabilities.status_code == 200, capabilities.text
    assert capabilities.json()["ai"]["available"] is False
    assert capabilities.json()["ai"]["reason"] == "AI_EXTRACTION_UNAVAILABLE"

    rejected = await client.post(
        "/api/v1/onboarding/imports/ai",
        headers=headers,
        data={"client_import_id": str(uuid4()), "location_id": str(location_id)},
        files={"file": ("menu.png", b"not persisted", "image/png")},
    )
    assert rejected.status_code == 503
    assert rejected.json()["detail"]["code"] == "AI_EXTRACTION_UNAVAILABLE"


@pytest.mark.anyio
async def test_ai_preview_persists_only_hash_and_draft_until_apply(app_client) -> None:
    client, sessions = app_client
    headers, organization_id, location_id = await _workspace(
        client, "ai-preview@example.com", "Preview AI"
    )
    app.dependency_overrides[ai_menu_extractor] = FakeExtractor
    raw = b"sensitive raw menu bytes"
    response = await client.post(
        "/api/v1/onboarding/imports/ai",
        headers=headers,
        data={"client_import_id": str(uuid4()), "location_id": str(location_id)},
        files={"file": ("menu.png", raw, "image/png")},
    )
    assert response.status_code == 200, response.text
    assert response.json()["source_type"] == "AI_EXTRACTION"

    async with sessions() as session:
        run = await session.scalar(
            select(OnboardingImportRunModel).where(
                OnboardingImportRunModel.organization_id == organization_id
            )
        )
        payloads = list(
            await session.scalars(
                select(OnboardingImportEntityModel.payload).where(
                    OnboardingImportEntityModel.import_run_id == run.id
                )
            )
        )
        assert run.file_hash == sha256(raw).hexdigest()
        assert raw.decode() not in jsonlib.dumps(payloads)
        assert await session.scalar(select(func.count()).select_from(MenuCategoryModel)) == 0
        assert await session.scalar(select(func.count()).select_from(ProductModel)) == 0
        assert await session.scalar(select(func.count()).select_from(InventoryItemModel)) == 0


@pytest.mark.anyio
async def test_ai_upload_replay_skips_model_and_changed_source_conflicts(app_client) -> None:
    client, _ = app_client
    headers, _, location_id = await _workspace(
        client, "ai-replay@example.com", "Replay AI"
    )
    CountingExtractor.calls = 0
    app.dependency_overrides[ai_menu_extractor] = CountingExtractor
    client_import_id = uuid4()

    async def upload(content: bytes):
        return await client.post(
            "/api/v1/onboarding/imports/ai",
            headers=headers,
            data={
                "client_import_id": str(client_import_id),
                "location_id": str(location_id),
            },
            files={"file": ("menu.png", content, "image/png")},
        )

    first = await upload(b"same menu")
    replay = await upload(b"same menu")
    conflict = await upload(b"changed menu")

    assert first.status_code == 200, first.text
    assert replay.status_code == 200, replay.text
    assert replay.json()["id"] == first.json()["id"]
    assert CountingExtractor.calls == 1
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "IMPORT_IDEMPOTENCY_CONFLICT"


@pytest.mark.anyio
async def test_ai_import_enforces_tenant_location_and_rbac(
    app_client, monkeypatch
) -> None:
    client, _ = app_client
    owner, organization_id, location_a = await _workspace(
        client, "ai-owner@example.com", "AI tenant A"
    )
    _, _, foreign_location = await _workspace(
        client, "ai-other-owner@example.com", "AI tenant B"
    )
    cashier_auth, _, _ = await _workspace(
        client, "ai-cashier@example.com", "Temporary cashier workspace"
    )
    app.dependency_overrides[ai_menu_extractor] = FakeExtractor

    foreign = await client.post(
        "/api/v1/onboarding/imports/ai",
        headers=owner,
        data={
            "client_import_id": str(uuid4()),
            "location_id": str(foreign_location),
        },
        files={"file": ("menu.png", b"menu", "image/png")},
    )
    assert foreign.status_code == 404

    raw_token = "stage23-ai-rbac-token-with-more-than-thirty-two-characters"
    monkeypatch.setattr(
        "beanly.modules.organizations.application.services.invitation_service."
        "create_invitation_token",
        lambda: (raw_token, sha256(raw_token.encode()).hexdigest()),
    )
    invited = await client.post(
        "/api/v1/team/invitations",
        headers=owner,
        json={
            "email": "ai-cashier@example.com",
            "role": "CASHIER",
            "location_ids": [str(location_a)],
        },
    )
    assert invited.status_code == 201, invited.text
    assert (
        await client.post(
            f"/api/v1/invitations/{raw_token}/accept", headers=cashier_auth
        )
    ).status_code == 204
    cashier = {
        "authorization": cashier_auth["authorization"],
        "X-Organization-ID": str(organization_id),
    }
    forbidden = await client.post(
        "/api/v1/onboarding/imports/ai",
        headers=cashier,
        data={"client_import_id": str(uuid4()), "location_id": str(location_a)},
        files={"file": ("menu.png", b"menu", "image/png")},
    )
    assert forbidden.status_code == 403
