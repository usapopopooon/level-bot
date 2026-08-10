"""Verify that the marimo integration token reaches only the API service."""

import json
import os
import subprocess
from pathlib import Path

project_directory = Path(__file__).resolve().parents[1]
environment = os.environ | {
    "ADMIN_PASSWORD": "scope-admin-password",
    "SESSION_SECRET_KEY": "scope-session-secret",
    "MARIMO_BOT_API_TOKEN": "scope-marimo-token",
}
result = subprocess.run(
    [
        "docker",
        "compose",
        "-f",
        "docker-compose.coolify.yml",
        "config",
        "--format",
        "json",
    ],
    cwd=project_directory,
    env=environment,
    check=True,
    capture_output=True,
    text=True,
)
services = json.loads(result.stdout)["services"]
assert services["api"]["environment"]["MARIMO_BOT_API_TOKEN"] == ("scope-marimo-token")
for service_name in ("bot", "frontend", "postgres"):
    assert services[service_name]["environment"]["MARIMO_BOT_API_TOKEN"] == "", (
        f"MARIMO_BOT_API_TOKEN leaked into {service_name}"
    )
