"""Recompute RELEASE_MANIFEST.json hashes for the shipped release files.

Run after any intended change to a release file. It never includes secrets,
local environments, generated live outputs or build artefacts.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INCLUDE_DIRS = ("app", "assets", "config", "context", "demo", "demo_archive", "docs", "experiments", "packaging", "runtime",
                "schemas", "scripts", "src", "tests")
TOP_LEVEL = (".env.example", "INSTALL.md", "INSTALL.ps1", "README.md", "RUN_DEMO.ps1", "RUN_LIVE.ps1",
             "VALIDATION_REPORT.md", "pytest.ini", "requirements.txt")
EXCLUDED_PARTS = {"__pycache__", ".venv", "outputs", "data", ".local", "build", "dist", "node_modules"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".bak", ".exe", ".spec"}


def release_files(root: Path = ROOT) -> list[str]:
    files = [name for name in TOP_LEVEL if (root / name).is_file()]
    for folder in INCLUDE_DIRS:
        for path in sorted((root / folder).rglob("*")):
            rel = path.relative_to(root)
            if (path.is_file() and not EXCLUDED_PARTS.intersection(rel.parts) and path.suffix not in EXCLUDED_SUFFIXES
                    and path.name != ".env"):
                files.append(rel.as_posix())
    return sorted(set(files))


def update(root: Path = ROOT, *, version: str | None = None, extra: dict | None = None) -> dict:
    path = root / "RELEASE_MANIFEST.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["sha256"] = {rel: hashlib.sha256((root / rel).read_bytes()).hexdigest() for rel in release_files(root)}
    manifest["primary_frozen_data_files"] = sorted(rel for rel in manifest["sha256"] if rel.startswith("demo/"))
    if version:
        manifest["release_version"] = version
    manifest["release_timestamp"] = datetime.now(timezone.utc).isoformat()
    manifest.update(extra or {})
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version")
    args = parser.parse_args()
    manifest = update(version=args.version)
    print(json.dumps({"files": len(manifest["sha256"]), "release_version": manifest["release_version"]}))


if __name__ == "__main__":
    main()
