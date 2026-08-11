import hashlib
import hmac
import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import Request
from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from beanly.core.database.base import Base
from beanly.core.logging.context import ip_hash_var, request_id_var

logger = logging.getLogger(__name__)
_FORBIDDEN_METADATA_KEYS = frozenset(
    {"password", "token", "secret", "credentials", "authorization", "signature"}
)


class SecurityAuditEventModel(Base):
    __tablename__ = "security_audit_events"
    __table_args__ = (
        Index("ix_security_audit_org_created", "organization_id", "created_at"),
        Index("ix_security_audit_action_created", "action", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True,
    )
    actor_user_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    action: Mapped[str] = mapped_column(String(120))
    resource_type: Mapped[str] = mapped_column(String(80))
    resource_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    request_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    ip_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_metadata: Mapped[dict[str, object]] = mapped_column(
        "metadata",
        JSON().with_variant(JSONB, "postgresql"),
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SecurityAuditRecorder:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record(
        self,
        *,
        action: str,
        resource_type: str,
        organization_id: UUID | None = None,
        actor_user_id: UUID | None = None,
        resource_id: UUID | None = None,
        request_id: UUID | None = None,
        ip_hash: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> SecurityAuditEventModel:
        if not action or len(action) > 120:
            raise ValueError("Audit action must contain between 1 and 120 characters")
        if not resource_type or len(resource_type) > 80:
            raise ValueError("Audit resource type must contain between 1 and 80 characters")
        safe_metadata = dict(metadata or {})
        _validate_metadata(safe_metadata)
        event = SecurityAuditEventModel(
            id=uuid4(),
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            request_id=request_id or _uuid(request_id_var.get()),
            ip_hash=ip_hash or ip_hash_var.get(),
            event_metadata=safe_metadata,
            created_at=datetime.now(UTC),
        )
        self.session.add(event)
        await self.session.flush()
        return event


def mark_security_event(
    request: Request,
    *,
    action: str,
    resource_type: str,
    organization_id: UUID | None = None,
    actor_user_id: UUID | None = None,
    resource_id: UUID | None = None,
    metadata: Mapping[str, object] | None = None,
) -> None:
    request.state.security_audit_event = {
        "action": action,
        "resource_type": resource_type,
        "organization_id": organization_id,
        "actor_user_id": actor_user_id,
        "resource_id": resource_id,
        "metadata": dict(metadata or {}),
    }


class SecurityAuditMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        ip_hash_secret: str,
        enabled: bool = True,
    ) -> None:
        self.app = app
        self.session_factory = session_factory
        self.ip_hash_secret = ip_hash_secret.encode()
        self.enabled = enabled

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self.enabled:
            await self.app(scope, receive, send)
            return
        status_code = 500

        async def capture_status(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        await self.app(scope, receive, capture_status)
        event = scope.get("state", {}).get("security_audit_event")
        if event is None and scope["path"] == "/api/v1/auth/login" and status_code == 401:
            event = {"action": "USER_LOGIN_FAILED", "resource_type": "user"}
        if event is None or not (
            200 <= status_code < 400 or event["action"] == "USER_LOGIN_FAILED"
        ):
            return
        client = scope.get("client")
        ip_hash = (
            hmac.new(self.ip_hash_secret, str(client[0]).encode(), hashlib.sha256).hexdigest()
            if client
            else None
        )
        state = scope.get("state", {})
        try:
            async with self.session_factory() as session:
                await SecurityAuditRecorder(session).record(
                    action=event["action"],
                    resource_type=event["resource_type"],
                    actor_user_id=event.get("actor_user_id")
                    or _uuid(state.get("actor_user_id")),
                    organization_id=event.get("organization_id"),
                    resource_id=event.get("resource_id"),
                    request_id=_uuid(state.get("request_id")),
                    ip_hash=ip_hash,
                    metadata=event.get("metadata"),
                )
                await session.commit()
        except Exception:
            logger.exception("Could not persist security audit event")


def _uuid(value: object) -> UUID | None:
    try:
        return UUID(str(value)) if value else None
    except ValueError:
        return None


def _validate_metadata(value: object) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).casefold()
            if any(fragment in normalized for fragment in _FORBIDDEN_METADATA_KEYS):
                raise ValueError("Audit metadata cannot contain secrets")
            _validate_metadata(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _validate_metadata(child)
