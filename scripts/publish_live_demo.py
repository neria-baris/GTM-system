"""Publish a validated live presentation contract as the product demo.

The previous demo snapshot is archived (not deleted) under demo_archive/<business date>_<revision>/.
Only files listed in the live manifest are copied; the live contract is re-validated first.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.validate_presentation_contract import validate  # noqa: E402


def publish(runtime: Path, sqlite: Path, demo: Path, archive_root: Path) -> dict:
    result = validate(runtime, sqlite)
    live = json.loads((runtime / "manifest.json").read_text(encoding="utf-8"))
    old = json.loads((demo / "manifest.json").read_text(encoding="utf-8"))
    if old.get("revision_id") == live.get("revision_id"):
        return {"published": False, "reason": "demo already shows this revision", **result}
    target = archive_root / f"{old['business_as_of']}_{old['revision_id']}"
    if not target.exists():
        shutil.copytree(demo, target)
    for path in demo.glob("*.json"):
        path.unlink()
    for name in ["manifest.json", *live["files"]]:
        shutil.copy2(runtime / name, demo / name)
    return {"published": True, "archived_previous_demo": target.relative_to(ROOT).as_posix(),
            "revision_id": live["revision_id"], "source_run_ids": live.get("source_run_ids"), **result}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, default=ROOT / "outputs/D/runtime")
    parser.add_argument("--sqlite", type=Path, default=ROOT / "data/runtime/gtm_state.sqlite")
    args = parser.parse_args()
    print(json.dumps(publish(args.runtime, args.sqlite, ROOT / "demo", ROOT / "demo_archive"), indent=2))


if __name__ == "__main__":
    main()
