"""CLI: database backups (pg_dump), for cron/off-host scheduling or manual runs.

  python -m app.tools.backup create   # create a new backup
  python -m app.tools.backup list     # list existing backups

Restore is documented in docs/deployment.md (pg_restore) — deliberately not a CLI
action to avoid an accidental destructive overwrite.
"""
from __future__ import annotations

import asyncio
import sys

from app.services import backup


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    cmd = argv[0] if argv else "create"

    if cmd == "list":
        rows = backup.list_backups()
        if not rows:
            print("No backups found.")
        for b in rows:
            print(f"{b['created_at']}  {b['size_bytes']:>12} bytes  {b['filename']}")
        return 0

    if cmd == "create":
        try:
            result = asyncio.run(backup.create_backup())
        except RuntimeError as exc:
            print(f"Backup failed: {exc}", file=sys.stderr)
            return 1
        print(f"Backup created: {result['path']} ({result['size_bytes']} bytes)")
        return 0

    print(f"Unknown command '{cmd}' (use: create | list)", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
