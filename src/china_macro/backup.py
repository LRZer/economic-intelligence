"""Create and validate an online SQLite backup without stopping the server."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from .app import DB_PATH, connect


def verify_connection(db: sqlite3.Connection) -> int:
    integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity != "ok":
        raise ValueError(f"SQLite integrity check failed: {integrity}")
    return db.execute("SELECT COUNT(*) FROM observations").fetchone()[0]


def create_backup(destination: Path) -> dict:
    destination = destination.resolve()
    if destination.exists():
        raise FileExistsError(f"Backup already exists: {destination}")
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database does not exist: {DB_PATH}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with connect() as source, closing(sqlite3.connect(destination)) as target:
        source.backup(target)
        backed_up_count = verify_connection(target)
        with closing(sqlite3.connect(":memory:")) as restored:
            target.backup(restored)
            restored_count = verify_connection(restored)
    if restored_count != backed_up_count:
        raise ValueError("Restored observation count differs from backup")
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "backup_path": str(destination), "sha256": digest,
        "observation_count": backed_up_count,
        "restore_check": "ok", "restored_observation_count": restored_count,
    }
    destination.with_suffix(destination.suffix + ".json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Back up and restore-check the local SQLite database")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    name = datetime.now(timezone.utc).strftime("macro-%Y%m%dT%H%M%SZ.sqlite3")
    destination = args.output or DB_PATH.parent / "backups" / name
    report = create_backup(destination)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
