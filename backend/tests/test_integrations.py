import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
from cryptography.fernet import Fernet
from httpx import AsyncClient
from sqlalchemy import func, select

from beanly.core.config.settings import Settings, get_settings
from beanly.core.events.handlers.registry import EventHandlerRegistry
from beanly.core.events.outbox.dispatcher import OutboxDispatcher
from beanly.core.events.outbox.models import OutboxEventModel
from beanly.core.events.outbox.repositories import OutboxRepository
from beanly.core.events.outbox.writer import OutboxEventSink
from beanly.core.events.registry import to_envelope
from beanly.core.security.audit import SecurityAuditEventModel
from beanly.modules.integrations.application.connection_service import (
    IntegrationConnectionService,
)
from beanly.modules.integrations.application.dto import (
    NormalizedWebhookEvent,
    ProviderDescriptor,
)
from beanly.modules.integrations.application.job_service import IntegrationJobService
from beanly.modules.integrations.application.oauth_service import (
    IntegrationOAuthService,
)
from beanly.modules.integrations.application.webhook_service import (
    IntegrationWebhookService,
)
from beanly.modules.integrations.domain.entities import IntegrationConnection
from beanly.modules.integrations.domain.enums import (
    IntegrationAuthType,
    IntegrationCapability,
    IntegrationConnectionStatus,
)
from beanly.modules.integrations.domain.events import (
    IntegrationConnectionActivated,
    IntegrationConnectionCreated,
)
from beanly.modules.integrations.domain.exceptions import (
    InvalidWebhookSignature,
    OAuthSessionInvalid,
)
from beanly.modules.integrations.infrastructure.crypto.fernet_cipher import (
    FernetSecretCipher,
)
from beanly.modules.integrations.infrastructure.db.models import (
    IntegrationConnectionModel,
    IntegrationInboxEventModel,
    IntegrationOAuthSessionModel,
)
from beanly.modules.integrations.infrastructure.db.repositories import (
    SqlAlchemyIntegrationRepository,
)
from beanly.modules.integrations.infrastructure.handlers import (
    register_integration_handlers,
)
from beanly.modules.integrations.infrastructure.providers.registry import (
    ProviderRegistry,
    build_provider_registry,
)
from beanly.modules.integrations.infrastructure.source_reader import (
    SqlAlchemyIntegrationSourceReader,
)
from beanly.modules.organizations.domain.entities import TenantContext
from beanly.modules.organizations.domain.enums import LocationAccess, MembershipRole
from beanly.modules.organizations.domain.permissions import permissions_for
from beanly.modules.payments.domain.events import PaymentCompleted


async def _api_user(client: AsyncClient, email: str) -> dict[str, str]:
    password = "correct-horse-battery-staple"
    created = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": password,
            "first_name": "Integration",
            "last_name": "User",
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    assert login.status_code == 200, login.text
    return {"authorization": f"Bearer {login.json()['access_token']}"}


async def _api_workspace(
    client: AsyncClient, auth: dict[str, str], name: str
) -> tuple[dict[str, str], str, str]:
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
    organization_id = created.json()["organization"]["id"]
    location_id = created.json()["location"]["id"]
    return (
        {**auth, "X-Organization-ID": organization_id},
        organization_id,
        location_id,
    )


async def _api_member(
    client: AsyncClient,
    owner: dict[str, str],
    auth: dict[str, str],
    *,
    email: str,
    role: str,
    location_id: str,
    token: str,
) -> dict[str, str]:
    invited = await client.post(
        "/api/v1/team/invitations",
        headers=owner,
        json={"email": email, "role": role, "location_ids": [location_id]},
    )
    assert invited.status_code == 201, invited.text
    accepted = await client.post(
        f"/api/v1/invitations/{token}/accept", headers=auth
    )
    assert accepted.status_code == 204, accepted.text
    return {**auth, "X-Organization-ID": owner["X-Organization-ID"]}


def _context(organization_id: UUID | None = None) -> TenantContext:
    return TenantContext(
        user_id=uuid4(),
        organization_id=organization_id or uuid4(),
        membership_id=uuid4(),
        role=MembershipRole.OWNER,
        permissions=permissions_for(MembershipRole.OWNER),
        location_access=LocationAccess.ALL,
    )


def _connection(
    organization_id: UUID,
    *,
    provider_code: str = "mock_fiscal",
    ciphertext: str | None = None,
) -> IntegrationConnection:
    now = datetime.now(UTC)
    return IntegrationConnection(
        id=uuid4(),
        organization_id=organization_id,
        provider_code=provider_code,
        display_name="Mock Fiscal",
        status=IntegrationConnectionStatus.ACTIVE,
        auth_type=IntegrationAuthType.API_KEY,
        config={},
        credentials_ciphertext=ciphertext,
        credentials_key_version=1 if ciphertext else None,
        external_account_id=None,
        connected_at=now,
        last_health_check_at=now,
        last_success_at=now,
        last_error_code=None,
        last_error_message=None,
        created_by=uuid4(),
        created_at=now,
        updated_at=now,
    )


class _PlannerRepository:
    def __init__(self, connection: IntegrationConnection) -> None:
        self.connection = connection
        self.jobs = {}

    async def active_connections(self, organization_id, capability, location_id):
        assert organization_id == self.connection.organization_id
        assert capability is IntegrationCapability.FISCAL
        return [(self.connection, location_id)]

    async def add_job(self, value):
        self.jobs.setdefault((value.connection_id, value.idempotency_key), value)
        return self.jobs[(value.connection_id, value.idempotency_key)]


@pytest.mark.anyio
async def test_payment_outbox_planner_is_reference_only_idempotent_and_offline(
    monkeypatch,
) -> None:
    organization_id = uuid4()
    location_id = uuid4()
    payment_id = uuid4()
    repository = _PlannerRepository(_connection(organization_id))
    registry = EventHandlerRegistry()
    register_integration_handlers(registry, repository)  # type: ignore[arg-type]

    async def forbidden_http(*args, **kwargs):
        raise AssertionError("Outbox planning must not perform external HTTP")

    monkeypatch.setattr(httpx.AsyncClient, "request", forbidden_http)
    envelope = to_envelope(
        PaymentCompleted(payment_id, uuid4(), organization_id, location_id, 170_000)
    )
    await registry.dispatch(envelope)
    await registry.dispatch(envelope)

    assert len(repository.jobs) == 1
    job = next(iter(repository.jobs.values()))
    assert job.source_event_id == envelope.id
    assert job.source_type == "PAYMENT"
    assert job.source_id == payment_id
    assert job.idempotency_key == f"fiscalize:payment:{payment_id}"
    assert not hasattr(job, "payload")
    assert "secret" not in repr(job).casefold()


class _WebhookAdapter:
    def __init__(self, *, reject: bool = False) -> None:
        self.reject = reject
        self.verified = False

    def verify_webhook(self, raw_body, headers, credentials):
        assert raw_body == b'{"id":"evt_18"}'
        assert headers["x-signature"] == "signed-raw-body"
        assert credentials == {"webhook_secret": "secret"}
        if self.reject:
            raise InvalidWebhookSignature("bad signature")
        self.verified = True
        return NormalizedWebhookEvent("evt_18", "receipt.ready", {"status": "ready"})


class _WebhookRepository:
    def __init__(self, connection, adapter) -> None:
        self.connection = connection
        self.adapter = adapter
        self.persisted = 0
        self.committed = 0

    async def get_connection_by_id(self, connection_id):
        return self.connection if connection_id == self.connection.id else None

    async def add_inbox_event(self, connection, event, payload_hash):
        assert self.adapter.verified
        assert event.payload == {"status": "ready"}
        assert payload_hash == hashlib.sha256(b'{"id":"evt_18"}').hexdigest()
        self.persisted += 1
        return uuid4()

    async def commit(self):
        self.committed += 1


@pytest.mark.anyio
async def test_webhook_verifies_raw_signature_before_durable_inbox_insert() -> None:
    cipher = FernetSecretCipher([Fernet.generate_key().decode()])
    ciphertext = cipher.encrypt(b'{"webhook_secret":"secret"}')
    connection = _connection(uuid4(), ciphertext=ciphertext)

    for reject in (False, True):
        adapter = _WebhookAdapter(reject=reject)
        repository = _WebhookRepository(connection, adapter)
        registry = ProviderRegistry()
        registry.register(
            ProviderDescriptor(
                code="mock_fiscal",
                name="Mock Fiscal",
                capabilities=frozenset({IntegrationCapability.FISCAL}),
                auth_type=IntegrationAuthType.API_KEY,
                supports_webhooks=True,
            ),
            adapter,  # type: ignore[arg-type]
        )
        service = IntegrationWebhookService(
            repository, registry, cipher  # type: ignore[arg-type]
        )
        if reject:
            with pytest.raises(InvalidWebhookSignature):
                await service.receive(
                    "mock_fiscal",
                    connection.id,
                    b'{"id":"evt_18"}',
                    {"x-signature": "signed-raw-body"},
                )
            assert repository.persisted == 0
            assert repository.committed == 0
        else:
            await service.receive(
                "mock_fiscal",
                connection.id,
                b'{"id":"evt_18"}',
                {"x-signature": "signed-raw-body"},
            )
            assert repository.persisted == 1
            assert repository.committed == 1


class _OAuthAdapter:
    def authorization_url(self, **values):
        self.authorization_values = values
        return "https://oauth.example/authorize"

    async def exchange_code(self, **values):
        self.exchange_values = values
        return {"access_token": "access", "refresh_token": "refresh"}

    async def refresh_credentials(self, values):
        assert values["refresh_token"] == "refresh"
        return {"access_token": "access-2", "refresh_token": "refresh-2"}


class _OAuthRepository:
    def __init__(self) -> None:
        self.session = None
        self.commits = 0

    async def add_oauth_session(self, *values):
        self.session = values
        return uuid4()

    async def consume_oauth_session(self, provider_code, state_hash):
        if self.session is None or state_hash != self.session[3]:
            return None
        if getattr(self, "used", False):
            return None
        self.used = True
        return SimpleNamespace(
            code_verifier_ciphertext=self.session[4],
            redirect_uri=self.session[5],
            organization_id=self.session[0],
            user_id=self.session[1],
        )

    async def add_connection(self, value):
        self.connection = value
        return value

    async def update_connection(self, value):
        self.connection = value
        return value

    async def commit(self):
        self.commits += 1


class _EventSink:
    def __init__(self) -> None:
        self.events = []

    async def stage(self, value):
        self.events.append(value)

    async def stage_many(self, values):
        self.events.extend(values)


@pytest.mark.anyio
async def test_oauth_uses_hashed_one_use_state_pkce_s256_and_encrypted_tokens() -> None:
    adapter = _OAuthAdapter()
    registry = ProviderRegistry()
    registry.register(
        ProviderDescriptor(
            code="mock_oauth",
            name="Mock OAuth",
            capabilities=frozenset({IntegrationCapability.PAYMENT}),
            auth_type=IntegrationAuthType.OAUTH2,
        ),
        adapter,  # type: ignore[arg-type]
    )
    repository = _OAuthRepository()
    cipher = FernetSecretCipher([Fernet.generate_key().decode()])
    sink = _EventSink()
    service = IntegrationOAuthService(
        repository,  # type: ignore[arg-type]
        registry,
        cipher,
        sink,  # type: ignore[arg-type]
        "https://beanly.example",
    )
    context = _context()
    started = await service.start(context, "mock_oauth")

    assert started.code_challenge_method == "S256"
    assert adapter.authorization_values["code_challenge_method"] == "S256"
    assert repository.session[3] == hashlib.sha256(started.state.encode()).hexdigest()
    assert started.state not in repository.session
    verifier = cipher.decrypt(repository.session[4]).decode()
    expected_challenge = hashlib.sha256(verifier.encode()).digest()
    assert started.code_challenge == base64.urlsafe_b64encode(expected_challenge).rstrip(
        b"="
    ).decode()

    connection_id, redirect_uri = await service.consume(
        "mock_oauth", started.state, "authorization-code"
    )
    assert connection_id == repository.connection.id
    assert redirect_uri == (
        "https://beanly.example/api/v1/integrations/oauth/mock_oauth/callback"
    )
    assert adapter.exchange_values["code_verifier"] == verifier
    encrypted = repository.connection.credentials_ciphertext
    assert encrypted is not None
    assert json.loads(cipher.decrypt(encrypted)) == {
        "access_token": "access",
        "refresh_token": "refresh",
    }
    assert "access" not in encrypted and "refresh" not in encrypted
    assert [type(value) for value in sink.events] == [
        IntegrationConnectionCreated,
        IntegrationConnectionActivated,
    ]
    refreshed = await service.refresh(repository.connection)
    assert refreshed.credentials_ciphertext != encrypted
    assert json.loads(cipher.decrypt(refreshed.credentials_ciphertext)) == {
        "access_token": "access-2",
        "refresh_token": "refresh-2",
    }
    with pytest.raises(OAuthSessionInvalid):
        await service.consume("mock_oauth", started.state, "replayed-code")


@pytest.mark.anyio
async def test_integrations_api_encrypts_secrets_and_enforces_rbac_tenant_location(
    app_client, monkeypatch
) -> None:
    monkeypatch.setattr(get_settings(), "audit_enabled", True)
    client, sessions = app_client
    tokens = {
        role: f"stage18-{role.casefold()}-invitation-token-more-than-thirty-two"
        for role in ("MANAGER", "ACCOUNTANT", "CASHIER", "BARISTA")
    }
    token_values = iter(tokens.values())

    def token_pair() -> tuple[str, str]:
        token = next(token_values)
        return token, hashlib.sha256(token.encode()).hexdigest()

    monkeypatch.setattr(
        "beanly.modules.organizations.application.services.invitation_service."
        "create_invitation_token",
        token_pair,
    )

    owner_auth = await _api_user(client, "integration-owner@example.com")
    owner, organization_id, location_id = await _api_workspace(
        client, owner_auth, "Integration Coffee"
    )
    members = {}
    for role in tokens:
        email = f"integration-{role.casefold()}@example.com"
        auth = await _api_user(client, email)
        members[role] = await _api_member(
            client,
            owner,
            auth,
            email=email,
            role=role,
            location_id=location_id,
            token=tokens[role],
        )

    secret = "stage18-api-secret-must-never-leak"
    created = await client.post(
        "/api/v1/integrations/connections",
        headers=owner,
        json={
            "provider_code": "mock_fiscal",
            "display_name": "Dostyk fiscal",
            "config": {"environment": "sandbox"},
            "credentials": {"api_key": secret, "webhook_secret": secret},
        },
    )
    assert created.status_code == 201, created.text
    connection_id = created.json()["id"]
    assert created.json()["has_credentials"] is True
    assert "credentials" not in created.json()
    assert "credentials_ciphertext" not in created.json()
    assert secret not in created.text

    async with sessions() as session:
        persisted = await session.get(
            IntegrationConnectionModel, UUID(connection_id)
        )
        assert persisted is not None
        assert persisted.credentials_ciphertext
        assert secret not in persisted.credentials_ciphertext
        assert persisted.config == {"environment": "sandbox"}

    tested = await client.post(
        f"/api/v1/integrations/connections/{connection_id}/test", headers=owner
    )
    assert tested.status_code == 200, tested.text
    assert tested.json()["status"] == "ACTIVE"
    bound = await client.put(
        f"/api/v1/integrations/connections/{connection_id}/locations/{location_id}",
        headers=owner,
        json={"capability": "FISCAL", "settings": {}},
    )
    assert bound.status_code == 200, bound.text

    warehouse = await client.post(
        "/api/v1/inventory/warehouses",
        headers=owner,
        json={"location_id": location_id, "name": "Integration warehouse"},
    )
    assert warehouse.status_code == 201, warehouse.text
    inventory_item = await client.post(
        "/api/v1/inventory/items",
        headers=owner,
        json={"name": "Integration beans", "base_unit": "g"},
    )
    assert inventory_item.status_code == 201, inventory_item.text
    category = await client.post(
        "/api/v1/menu/categories", headers=owner, json={"name": "Integration"}
    )
    assert category.status_code == 201, category.text
    product = await client.post(
        "/api/v1/menu/products",
        headers=owner,
        json={
            "category_id": category.json()["id"],
            "name": "Integration flat white",
            "default_variant": {
                "name": "Default",
                "base_price_minor": 170_000,
                "is_default": True,
            },
        },
    )
    assert product.status_code == 201, product.text
    variant_id = product.json()["variants"][0]["id"]
    recipe = await client.put(
        f"/api/v1/menu/variants/{variant_id}/recipe",
        headers=owner,
        json={
            "components": [
                {
                    "inventory_item_id": inventory_item.json()["id"],
                    "quantity": "18",
                    "unit": "g",
                }
            ]
        },
    )
    assert recipe.status_code == 200, recipe.text
    activated = await client.patch(
        f"/api/v1/menu/products/{product.json()['id']}",
        headers=owner,
        json={"status": "ACTIVE"},
    )
    assert activated.status_code == 200, activated.text
    register = await client.post(
        "/api/v1/sales/registers",
        headers=owner,
        json={"location_id": location_id, "name": "Integration register"},
    )
    assert register.status_code == 201, register.text
    shift = await client.post(
        "/api/v1/sales/shifts/open",
        headers=owner,
        json={
            "register_id": register.json()["id"],
            "warehouse_id": warehouse.json()["id"],
        },
    )
    assert shift.status_code == 201, shift.text
    order = await client.post(
        "/api/v1/sales/orders",
        headers=owner,
        json={
            "client_order_id": str(uuid4()),
            "shift_id": shift.json()["id"],
            "order_type": "TAKEAWAY",
        },
    )
    assert order.status_code == 201, order.text
    order_item = await client.post(
        f"/api/v1/sales/orders/{order.json()['id']}/items",
        headers=owner,
        json={
            "client_item_id": str(uuid4()),
            "variant_id": variant_id,
            "selected_option_ids": [],
            "quantity": 1,
        },
    )
    assert order_item.status_code == 201, order_item.text
    paid = await client.post(
        f"/api/v1/payments/orders/{order.json()['id']}/complete",
        headers=owner,
        json={
            "client_payment_id": str(uuid4()),
            "lines": [{"method": "CARD", "amount_minor": 170_000}],
        },
    )
    assert paid.status_code == 201, paid.text

    async with sessions() as session:
        handlers = EventHandlerRegistry()
        integration_repository = SqlAlchemyIntegrationRepository(session)
        register_integration_handlers(handlers, integration_repository)
        dispatched = await OutboxDispatcher(
            OutboxRepository(session), handlers, "stage18-outbox"
        ).run_once()
        assert dispatched >= 1
    async with sessions() as session:
        integration_repository = SqlAlchemyIntegrationRepository(session)
        claimed = await integration_repository.claim_jobs(
            "stage18-integration-worker", 10, 60
        )
        await integration_repository.commit()
        assert len(claimed) == 1
        settings = Settings(environment="test")
        await IntegrationJobService(
            integration_repository,
            SqlAlchemyIntegrationSourceReader(session),
            build_provider_registry(settings),
            FernetSecretCipher(settings.integration_encryption_key_list),
            OutboxEventSink(OutboxRepository(session)),
            max_attempts=2,
        ).execute(claimed[0], "stage18-integration-worker")
    activity = await client.get("/api/v1/integrations/jobs", headers=owner)
    assert activity.status_code == 200, activity.text
    assert activity.json()["total"] == 1
    assert activity.json()["items"][0]["status"] == "SUCCESS"
    assert activity.json()["items"][0]["external_id"].startswith("mock-receipt-")
    assert activity.json()["items"][0]["attempt_history"][0]["outcome"] == "SUCCESS"
    assert (
        await client.get("/api/v1/integrations/jobs", headers=members["MANAGER"])
    ).status_code == 403

    degraded = await client.post(
        "/api/v1/integrations/connections",
        headers=owner,
        json={
            "provider_code": "mock_fiscal",
            "display_name": "Broken fiscal",
            "credentials": {"api_key": ""},
        },
    )
    assert degraded.status_code == 201, degraded.text
    degraded_test = await client.post(
        f"/api/v1/integrations/connections/{degraded.json()['id']}/test",
        headers=owner,
    )
    assert degraded_test.status_code == 200, degraded_test.text
    assert degraded_test.json()["status"] == "DEGRADED"
    for role in ("MANAGER", "ACCOUNTANT"):
        listing = await client.get(
            "/api/v1/integrations/connections", headers=members[role]
        )
        assert listing.status_code == 200, listing.text
        assert listing.json()[0]["can_manage"] is False
        forbidden = await client.post(
            "/api/v1/integrations/connections",
            headers=members[role],
            json={
                "provider_code": "mock_fiscal",
                "display_name": "Forbidden",
                "credentials": {"api_key": "forbidden"},
            },
        )
        assert forbidden.status_code == 403, forbidden.text
    for role in ("CASHIER", "BARISTA"):
        assert (
            await client.get(
                "/api/v1/integrations/providers", headers=members[role]
            )
        ).status_code == 403

    foreign_auth = await _api_user(client, "integration-foreign@example.com")
    foreign, _, foreign_location_id = await _api_workspace(
        client, foreign_auth, "Foreign Coffee"
    )
    assert (
        await client.get(
            f"/api/v1/integrations/connections/{connection_id}", headers=foreign
        )
    ).status_code == 404
    assert (
        await client.put(
            f"/api/v1/integrations/connections/{connection_id}/locations/"
            f"{foreign_location_id}",
            headers=owner,
            json={"capability": "FISCAL", "settings": {}},
        )
    ).status_code in {404, 422}

    for config in (
        {"nested": {"api_key": "plaintext"}},
        {"nested": {"provider_url": "http://169.254.169.254"}},
    ):
        rejected = await client.patch(
            f"/api/v1/integrations/connections/{connection_id}",
            headers=owner,
            json={"config": config},
        )
        assert rejected.status_code == 422, rejected.text
    unknown = await client.post(
        "/api/v1/integrations/connections",
        headers=owner,
        json={
            "provider_code": "sql_inserted_provider",
            "display_name": "Unknown",
            "credentials": {"api_key": "secret"},
        },
    )
    assert unknown.status_code == 422, unknown.text

    raw = b'{"id":"evt_stage18","type":"receipt.ready","data":{"status":"ready"}}'
    signature = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    webhook_url = f"/api/v1/integrations/webhooks/mock_fiscal/{connection_id}"
    first = await client.post(
        webhook_url,
        content=raw,
        headers={"x-mock-signature": signature},
    )
    duplicate = await client.post(
        webhook_url,
        content=raw,
        headers={"x-mock-signature": signature},
    )
    assert first.status_code == duplicate.status_code == 202
    assert first.json()["inbox_event_id"] == duplicate.json()["inbox_event_id"]
    invalid = await client.post(
        webhook_url,
        content=b'{"id":"evt_invalid","type":"receipt.ready","data":{}}',
        headers={"x-mock-signature": "invalid"},
    )
    assert invalid.status_code == 401
    async with sessions() as session:
        assert await session.scalar(
            select(func.count(IntegrationInboxEventModel.id)).where(
                IntegrationInboxEventModel.connection_id == UUID(connection_id)
            )
        ) == 1

    disconnected = await client.post(
        f"/api/v1/integrations/connections/{connection_id}/disconnect",
        headers=owner,
    )
    assert disconnected.status_code == 200, disconnected.text
    assert disconnected.json()["status"] == "REVOKED"
    assert disconnected.json()["has_credentials"] is False
    async with sessions() as session:
        lifecycle_events = set(
            await session.scalars(
                select(OutboxEventModel.event_name).where(
                    OutboxEventModel.organization_id == UUID(organization_id)
                )
            )
        )
        audit_events = (
            await session.scalars(
                select(SecurityAuditEventModel).where(
                    SecurityAuditEventModel.organization_id == UUID(organization_id),
                    SecurityAuditEventModel.resource_id == UUID(connection_id),
                )
            )
        ).all()
    assert {
        "integration.connection_created",
        "integration.connection_activated",
        "integration.connection_degraded",
        "integration.connection_revoked",
        "integration.job_succeeded",
    } <= lifecycle_events
    assert [event.action for event in audit_events] == ["INTEGRATION_DISCONNECTED"]
    assert audit_events[0].event_metadata == {}


@pytest.mark.anyio
async def test_oauth_repository_rejects_expired_and_replayed_state(app_client) -> None:
    _, sessions = app_client
    now = datetime.now(UTC)
    async with sessions() as session:
        repository = SqlAlchemyIntegrationRepository(session)
        expired_hash = hashlib.sha256(b"expired-state").hexdigest()
        expired_id = await repository.add_oauth_session(
            uuid4(),
            uuid4(),
            "mock_oauth",
            expired_hash,
            "encrypted-verifier",
            "https://beanly.example/callback",
            now - timedelta(seconds=1),
        )
        valid_hash = hashlib.sha256(b"valid-state").hexdigest()
        valid_id = await repository.add_oauth_session(
            uuid4(),
            uuid4(),
            "mock_oauth",
            valid_hash,
            "encrypted-verifier",
            "https://beanly.example/callback",
            now + timedelta(minutes=10),
        )
        await repository.commit()

    async with sessions() as session:
        repository = SqlAlchemyIntegrationRepository(session)
        assert await repository.consume_oauth_session(
            "mock_oauth", expired_hash, now
        ) is None
        consumed = await repository.consume_oauth_session(
            "mock_oauth", valid_hash, now
        )
        assert consumed is not None
        assert consumed.redirect_uri == "https://beanly.example/callback"
        await repository.commit()

    async with sessions() as session:
        repository = SqlAlchemyIntegrationRepository(session)
        assert await repository.consume_oauth_session(
            "mock_oauth", valid_hash, now + timedelta(seconds=1)
        ) is None
        expired = await session.get(IntegrationOAuthSessionModel, expired_id)
        valid = await session.get(IntegrationOAuthSessionModel, valid_id)
        assert expired is not None and valid is not None
        assert expired.used_at is None
        assert valid.used_at is not None
        assert valid.state_hash == valid_hash
        assert not hasattr(valid, "state")


class _FailingSink:
    async def stage(self, value):
        raise RuntimeError("outbox unavailable")


@pytest.mark.anyio
async def test_connection_and_lifecycle_event_are_atomic_on_sink_failure(
    app_client,
) -> None:
    _, sessions = app_client
    settings = Settings(environment="test")
    context = _context()
    async with sessions() as session:
        repository = SqlAlchemyIntegrationRepository(session)
        service = IntegrationConnectionService(
            repository,
            SimpleNamespace(),  # type: ignore[arg-type]
            build_provider_registry(settings),
            FernetSecretCipher(settings.integration_encryption_key_list),
            _FailingSink(),  # type: ignore[arg-type]
        )
        with pytest.raises(RuntimeError, match="outbox unavailable"):
            await service.create(
                context,
                "mock_fiscal",
                "Atomic fiscal",
                {},
                {"api_key": "encrypted-before-rollback"},
            )
        await repository.rollback()

    async with sessions() as session:
        assert await session.scalar(
            select(func.count(IntegrationConnectionModel.id)).where(
                IntegrationConnectionModel.organization_id == context.organization_id
            )
        ) == 0
        assert await session.scalar(
            select(func.count(OutboxEventModel.id)).where(
                OutboxEventModel.organization_id == context.organization_id
            )
        ) == 0
