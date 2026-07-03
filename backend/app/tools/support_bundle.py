"""CLI: write a redacted support bundle to disk (for air-gapped/offline use).

  python -m app.tools.support_bundle [output_dir]

Produces the same zip as the in-app download, without needing the web UI — handy
when support access is restricted to a shell on the host.
"""
from __future__ import annotations

import sys
from pathlib import Path

from app.services import support_bundle


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    out_dir = Path(argv[0]) if argv else Path(".")
    out_dir.mkdir(parents=True, exist_ok=True)
    filename, data = support_bundle.build_bundle()
    path = out_dir / filename
    path.write_bytes(data)
    print(f"Wrote support bundle -> {path} ({len(data)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
