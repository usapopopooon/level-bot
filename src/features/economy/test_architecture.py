"""Architecture checks for cross-feature dependency boundaries."""

from __future__ import annotations

import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
FEATURES_ROOT = PROJECT_ROOT / "src" / "features"
LEGACY_WALLET_NAMES = {"Wallet", "lock_wallet", "spent_xp_for_user", "wallet_for_user"}


def _production_python_files() -> tuple[Path, ...]:
    return tuple(
        path
        for path in FEATURES_ROOT.rglob("*.py")
        if not path.name.startswith("test_") and "__pycache__" not in path.parts
    )


def test_features_do_not_depend_on_color_role_shop_for_the_shared_wallet() -> None:
    violations: list[str] = []
    for path in _production_python_files():
        if path == FEATURES_ROOT / "color_role_shop" / "service.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            if node.module != "src.features.color_role_shop.service":
                continue
            imported = LEGACY_WALLET_NAMES & {alias.name for alias in node.names}
            if imported:
                violations.append(
                    f"{path.relative_to(PROJECT_ROOT)} imports {sorted(imported)}"
                )
    assert violations == []


def test_cafe_core_uses_ports_instead_of_sibling_feature_implementations() -> None:
    allowed_feature_prefixes = (
        "src.features.cafe_gacha",
        "src.features.economy",
    )
    violations: list[str] = []
    for name in ("service.py", "leaderboard.py", "economy.py", "public_routes.py"):
        path = FEATURES_ROOT / "cafe_gacha" / name
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or node.module is None:
                continue
            if node.module.startswith("src.features.") and not node.module.startswith(
                allowed_feature_prefixes
            ):
                violations.append(
                    f"{path.relative_to(PROJECT_ROOT)} imports {node.module}"
                )
    assert violations == []


def test_marimo_core_uses_a_port_for_cafe_inventory() -> None:
    path = FEATURES_ROOT / "marimo_xp" / "service.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    violations = [
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module is not None
        and node.module.startswith("src.features.cafe_gacha")
    ]
    assert violations == []
