"""Verify that the marimo integration token reaches only the API service."""

import json
import subprocess
from pathlib import Path

project_directory = Path(__file__).resolve().parents[1]
result = subprocess.run(
    [
        "docker",
        "compose",
        "-f",
        "docker-compose.coolify.yml",
        "config",
        "--no-interpolate",
        "--format",
        "json",
    ],
    cwd=project_directory,
    check=True,
    capture_output=True,
    text=True,
)
services = json.loads(result.stdout)["services"]
assert services["api"]["environment"]["MARIMO_BOT_API_TOKEN"] == (
    "${MARIMO_BOT_API_TOKEN:-}"
)
for service_name in ("bot", "frontend", "postgres"):
    assert services[service_name]["environment"]["MARIMO_BOT_API_TOKEN"] is None, (
        f"MARIMO_BOT_API_TOKEN leaked into {service_name}"
    )
