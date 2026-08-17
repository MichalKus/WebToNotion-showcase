#!/usr/bin/env python3
"""Generate the deployment .env file from .env.example plus CI secrets.

Used by .github/workflows/deploy.yml. Every value is single-quoted so that a
secret containing shell metacharacters cannot be misparsed by Docker Compose
or, worse, executed by anything that reads the file.
"""

import os
import sys
from pathlib import Path
from typing import Mapping

# Keys that must be present in the environment. Missing any is a hard failure.
REQUIRED_SECRETS = [
    "NOTION_API_KEY",
    "LOGFIRE_TOKEN",
    "WHISPER_API_KEY",
    "OPENROUTER_API_KEY",
    "API_KEY",
    "HOST",
]

# Deployment-time values injected by the workflow. These override any default
# carried in .env.example, and are emitted exactly once (review R7).
DEPLOYMENT_VARS = [
    "WEBTONOTION_IMAGE",
    "PORT",
    "COMPOSE_PROJECT_NAME",
    "CACHE_VOLUME_NAME",
]

# The compose service name, always reachable from inside the Docker network.
INTERNAL_SERVICE_HOST = "webtonotion"


def quote_env_value(value: str) -> str:
    """Wrap a value in single quotes for a Docker Compose .env file.

    Compose treats single-quoted content literally and provides no escape
    sequence for an embedded single quote, so such values are rejected rather
    than mangled. No credential format in use here permits one.
    """
    if "'" in value:
        raise ValueError(
            "Value contains a single quote, which cannot be represented "
            "safely in a Docker Compose .env file."
        )
    return f"'{value}'"


def parse_env_example(text: str) -> list[tuple[str, str]]:
    """Parse .env.example content into ordered key/value pairs."""
    pairs: list[tuple[str, str]] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key:
            pairs.append((key, value.strip()))
    return pairs


def build_allowed_hosts(base_value: str, environ: Mapping[str, str]) -> str:
    """Merge template defaults, the HOST secret, and the compose service name."""
    hosts = [h.strip() for h in base_value.split(",") if h.strip()]
    host_secret = environ.get("HOST")
    if host_secret:
        hosts.append(host_secret)
    hosts.append(INTERNAL_SERVICE_HOST)

    deduped: list[str] = []
    seen: set[str] = set()
    for host in hosts:
        if host not in seen:
            deduped.append(host)
            seen.add(host)
    return ",".join(deduped)


def build_env_lines(template: str, environ: Mapping[str, str]) -> list[str]:
    """Build the full .env content as a list of `KEY='value'` lines."""
    missing = [key for key in REQUIRED_SECRETS if not environ.get(key)]
    if missing:
        raise ValueError(f"Missing required environment variables: {', '.join(missing)}")

    lines: list[str] = []
    emitted: set[str] = set()

    def emit(key: str, value: str) -> None:
        lines.append(f"{key}={quote_env_value(value)}")
        emitted.add(key)

    for key, default in parse_env_example(template):
        if key in emitted or key in DEPLOYMENT_VARS:
            # Deployment vars are emitted once, later, from the environment.
            continue
        if key == "ENVIRONMENT":
            emit(key, environ.get("ENVIRONMENT", "production"))
        elif key == "ALLOWED_HOSTS":
            emit(key, build_allowed_hosts(default, environ))
        elif key in REQUIRED_SECRETS:
            emit(key, environ[key])
        else:
            emit(key, default)

    for key in REQUIRED_SECRETS:
        if key not in emitted:
            emit(key, environ[key])

    for key in DEPLOYMENT_VARS:
        value = environ.get(key)
        if value:
            emit(key, value)

    return lines


def write_env_file(output_path: Path, lines: list[str]) -> None:
    """Write the .env file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    output_path.chmod(0o644)


def main() -> int:
    """Entry point. Returns a process exit code."""
    project_root = Path(__file__).resolve().parent.parent
    env_example_path = project_root / ".env.example"
    output_path = project_root / "docker" / ".env"

    if not env_example_path.exists():
        print(f"::error::{env_example_path} not found")
        return 1

    try:
        lines = build_env_lines(env_example_path.read_text(encoding="utf-8"), os.environ)
    except ValueError as exc:
        print(f"::error::{exc}")
        return 1

    write_env_file(output_path, lines)

    print(f"Generated {output_path} (mode 644)")
    print("Configured keys:")
    for line in lines:
        print(f"- {line.split('=', 1)[0]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
