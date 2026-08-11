from contextvars import ContextVar, Token
from uuid import UUID

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
organization_id_var: ContextVar[str | None] = ContextVar("organization_id", default=None)
user_id_var: ContextVar[str | None] = ContextVar("user_id", default=None)
ip_hash_var: ContextVar[str | None] = ContextVar("ip_hash", default=None)


def set_request_context(
    request_id: str,
    organization_id: UUID | str | None = None,
    ip_hash: str | None = None,
) -> tuple[Token[str | None], Token[str | None], Token[str | None], Token[str | None]]:
    return (
        request_id_var.set(request_id),
        organization_id_var.set(str(organization_id) if organization_id else None),
        user_id_var.set(None),
        ip_hash_var.set(ip_hash),
    )


def set_user_id(user_id: UUID | str) -> None:
    user_id_var.set(str(user_id))


def reset_request_context(
    tokens: tuple[
        Token[str | None], Token[str | None], Token[str | None], Token[str | None]
    ],
) -> None:
    request_id_var.reset(tokens[0])
    organization_id_var.reset(tokens[1])
    user_id_var.reset(tokens[2])
    ip_hash_var.reset(tokens[3])
