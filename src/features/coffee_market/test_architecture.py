from __future__ import annotations

import ast
from pathlib import Path


def _imported_modules(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.append(node.module)
        elif isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
    return tuple(modules)


def test_coffee_market_core_reaches_xp_through_a_port() -> None:
    feature_root = Path(__file__).parent
    violations: list[str] = []
    for name in ("domain.py", "service.py", "ports.py"):
        path = feature_root / name
        for module in _imported_modules(path):
            if module.startswith(("src.features.leveling", "src.features.economy")):
                violations.append(f"{name} imports {module}")
    assert violations == []


def test_public_application_boundary_has_no_database_or_discord_dependency() -> None:
    feature_root = Path(__file__).parent
    violations: list[str] = []
    for name in ("application.py", "contracts.py", "domain.py", "presentation.py"):
        for module in _imported_modules(feature_root / name):
            if module.startswith(("sqlalchemy", "discord", "src.database")):
                violations.append(f"{name} imports {module}")
    assert violations == []


def test_discord_cog_uses_only_the_application_boundary() -> None:
    cog_path = Path(__file__).parents[2] / "cogs" / "coffee_market.py"
    forbidden = (
        "sqlalchemy",
        "src.database",
        "src.features.guilds",
        "src.features.leveling",
        "src.features.economy",
        "src.features.coffee_market.service",
        "src.features.coffee_market.ports",
    )
    violations = [
        module for module in _imported_modules(cog_path) if module.startswith(forbidden)
    ]
    assert violations == []
