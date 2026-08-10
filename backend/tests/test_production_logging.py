import json
import logging
from uuid import uuid4

from beanly.core.logging.config import JsonFormatter
from beanly.core.logging.context import reset_request_context, set_request_context, set_user_id


def test_json_logs_carry_service_and_request_context_without_secrets() -> None:
    request_id = uuid4()
    organization_id = uuid4()
    user_id = uuid4()
    tokens = set_request_context(str(request_id), organization_id)
    try:
        set_user_id(user_id)
        record = logging.LogRecord(
            "beanly.test",
            logging.INFO,
            __file__,
            1,
            'Authorization: Bearer jwt.payload.signature password="coffee" '
            'refresh_token="refresh-value" webhook_signature="signed-value"',
            (),
            None,
        )
        record.order_id = uuid4()
        record.password = "must-never-be-serialized"

        payload = json.loads(JsonFormatter("beanly-api").format(record))
    finally:
        reset_request_context(tokens)

    assert payload["service"] == "beanly-api"
    assert payload["request_id"] == str(request_id)
    assert payload["organization_id"] == str(organization_id)
    assert payload["user_id"] == str(user_id)
    assert payload["order_id"] == str(record.order_id)
    assert "password" not in payload
    serialized = json.dumps(payload)
    for secret in (
        "jwt.payload.signature",
        "coffee",
        "refresh-value",
        "signed-value",
        "must-never-be-serialized",
    ):
        assert secret not in serialized
    assert "[REDACTED]" in payload["message"]


def test_json_log_context_is_reset_after_request() -> None:
    tokens = set_request_context(str(uuid4()), uuid4())
    reset_request_context(tokens)

    record = logging.LogRecord("beanly.test", logging.INFO, __file__, 1, "ok", (), None)
    payload = json.loads(JsonFormatter("beanly-worker").format(record))

    assert payload["service"] == "beanly-worker"
    assert payload["request_id"] is None
    assert payload["organization_id"] is None
    assert payload["user_id"] is None
