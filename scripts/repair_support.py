"""Timestamped pre-write backups for repair build commands; never copies secrets."""
from datetime import datetime
from pathlib import Path
import shutil


def backup(root, paths):
    root = Path(root).resolve()
    destination = root / (".repair-backup-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
    for path in paths:
        path = Path(path).resolve()
        if path.exists():
            target = destination / path.relative_to(root)
            target.parent.mkdir(parents=True, exist_ok=True)
            if path.is_dir():
                shutil.copytree(path, target)
            else:
                shutil.copy2(path, target)
    return destination
