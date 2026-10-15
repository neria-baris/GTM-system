"""Validate persisted Stage C state and refuse stale upstream inputs."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.models.canonical_store import validate_canonical
from scripts.repair_support import backup


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("database", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = validate_canonical(args.database)
    for name, expected in report["input_hashes"].items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != expected:
            raise ValueError("Canonical state is stale: " + name)
    if args.report:
        backup(ROOT, [args.report])
        args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in {"canonical_opportunity_ids", "input_hashes"}}, sort_keys=True))


if __name__ == "__main__":
    main()
