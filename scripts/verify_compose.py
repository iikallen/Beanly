#!/usr/bin/env python3
"""Fail when a production-like Compose file violates Beanly's ingress contract."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("compose_file", type=Path, nargs="?", default=Path("compose.production.yaml"))
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--allow-placeholder-digests", action="store_true")
    args = parser.parse_args()
    compose_file = args.compose_file
    command = ["docker", "compose"]
    if args.env_file:
        command.extend(["--env-file", str(args.env_file)])
    command.extend(["-f", str(compose_file), "config", "--format", "json"])
    result = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
    )
    config = json.loads(result.stdout)
    services = config["services"]

    published: list[tuple[str, int]] = []
    for name, service in services.items():
        for port in service.get("ports", []):
            published.append((name, int(port["published"])))
    assert sorted(published) == [("reverse-proxy", 80), ("reverse-proxy", 443)], published

    assert config["networks"]["data"]["internal"] is True
    api_command = " ".join(services["api"]["command"])
    assert "--forwarded-allow-ips" in api_command and "--no-server-header" in api_command
    assert services["api"]["environment"]["FORWARDED_ALLOW_IPS"] != "*"

    hardened = {
        "api",
        "frontend",
        "integration-worker",
        "otel-collector",
        "outbox-worker",
        "redis",
        "reverse-proxy",
        "worker",
    }
    for name in hardened:
        service = services[name]
        assert service.get("read_only") is True, f"{name}: root filesystem must be read-only"
        assert "ALL" in service.get("cap_drop", []), f"{name}: capabilities not dropped"
        assert service.get("restart") == "unless-stopped", f"{name}: restart policy missing"
        assert service.get("mem_limit") not in {None, 0, "0"}, (
            f"{name}: memory budget missing"
        )

    git_sha = services["api"]["environment"]["GIT_SHA"]
    assert re.fullmatch(r"[0-9a-f]{40}", git_sha), "GIT_SHA is not an exact commit identity"
    assert services["api"]["image"].endswith(f":{git_sha}")
    assert services["frontend"]["image"].endswith(f":{git_sha}")
    for name in ("postgres", "redis", "reverse-proxy", "otel-collector"):
        image = services[name]["image"]
        match = re.search(r"@sha256:([0-9a-f]{64})$", image)
        assert match, f"{name}: image is not digest-pinned"
        if not args.allow_placeholder_digests:
            assert set(match.group(1)) != {"0"}, f"{name}: placeholder digest is forbidden"

    print(f"{compose_file}: ingress, isolation, hardening and image identity verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
