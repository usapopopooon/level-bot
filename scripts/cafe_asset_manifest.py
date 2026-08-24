#!/usr/bin/env python3
"""Create or verify the immutable Cafe Collection image manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import TypedDict

EXPECTED_IMAGE_COUNT = 363


class AssetEntry(TypedDict):
    sha256: str
    size: int


class AssetManifest(TypedDict):
    version: int
    files: dict[str, AssetEntry]


def build_manifest(asset_dir: Path) -> AssetManifest:
    files: dict[str, AssetEntry] = {}
    for path in sorted(asset_dir.glob("*.jpg")):
        files[path.name] = {
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "size": path.stat().st_size,
        }
    if len(files) != EXPECTED_IMAGE_COUNT:
        raise ValueError(
            f"expected {EXPECTED_IMAGE_COUNT} Cafe images, found {len(files)}"
        )
    return {"version": 1, "files": files}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("asset_dir", type=Path)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    manifest_path = args.asset_dir / "manifest.json"
    actual = build_manifest(args.asset_dir)
    if args.write:
        manifest_path.write_text(
            json.dumps(actual, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return 0
    if not manifest_path.is_file():
        raise FileNotFoundError(f"missing Cafe asset manifest: {manifest_path}")
    expected = json.loads(manifest_path.read_text(encoding="utf-8"))
    if actual != expected:
        raise ValueError("Cafe image files do not match manifest.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
