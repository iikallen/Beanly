#!/usr/bin/env python3
"""Read-only post-deployment smoke test for a dedicated synthetic organization."""

from __future__ import annotations

import json
import os
import ssl
import sys
from datetime import date, timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import uuid4


BASE_URL = os.environ.get("SMOKE_BASE_URL", "").rstrip("/")
TIMEOUT = float(os.environ.get("SMOKE_TIMEOUT_SECONDS", "10"))


def request(path: str, *, token: str | None = None, organization_id: str | None = None,
            payload: dict[str, str] | None = None) -> object:
    headers = {"Accept": "application/json", "X-Request-ID": str(uuid4())}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if organization_id:
        headers["X-Organization-ID"] = organization_id
    body = None
    method = "GET"
    if payload is not None:
        method = "POST"
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload).encode()
    req = Request(f"{BASE_URL}{path}", data=body, headers=headers, method=method)
    with urlopen(req, timeout=TIMEOUT, context=ssl.create_default_context()) as response:
        if not response.headers.get("X-Request-ID"):
            raise RuntimeError(f"{path}: response has no X-Request-ID")
        raw = response.read()
        return json.loads(raw) if raw else None


def main() -> int:
    if not BASE_URL.startswith("https://"):
        raise SystemExit("SMOKE_BASE_URL must be an https:// URL")
    email = os.environ.get("SMOKE_EMAIL")
    password = os.environ.get("SMOKE_PASSWORD")
    if not email or not password:
        raise SystemExit("SMOKE_EMAIL and SMOKE_PASSWORD for the synthetic tenant are required")

    try:
        request("/health/live")
        request("/health/ready")
        request("/health/version")
        login = request("/api/v1/auth/login", payload={"email": email, "password": password})
        token = login["access_token"]
        request("/api/v1/auth/me", token=token)
        organizations = request("/api/v1/organizations", token=token)
        if not organizations:
            raise RuntimeError("synthetic user has no organization")
        organization_id = organizations[0]["id"]
        locations = request(
            f"/api/v1/organizations/{organization_id}/locations",
            token=token,
            organization_id=organization_id,
        )
        if not locations:
            raise RuntimeError("synthetic organization has no location")
        location_id = locations[0]["id"]
        common = {"token": token, "organization_id": organization_id}
        request(f"/api/v1/menu?{urlencode({'location_id': location_id})}", **common)
        request("/api/v1/dashboard/overview?period=today", **common)
        today = date.today()
        query = urlencode({"date_from": today - timedelta(days=1), "date_to": today})
        request(f"/api/v1/analytics/overview?{query}", **common)
    except (HTTPError, URLError, RuntimeError, KeyError, ValueError) as exc:
        print(f"smoke failed: {exc}", file=sys.stderr)
        return 1

    print("smoke passed: health, identity, organization, menu, dashboard and analytics")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
