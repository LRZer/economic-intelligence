"""Print exact cross-platform first-pilot score differences without accepting them."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from unittest.mock import patch

from guanlan.llm_replay import diagnose

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--tool-fingerprints", action="store_true", help="Print field paths/types/SHA only; never full results or numeric tool values")
    args = parser.parse_args()
    if args.run.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("Run file exceeds bound")
    recorded = json.loads(args.run.read_text(encoding="utf-8"))
    with patch("socket.socket.connect", side_effect=AssertionError("Diagnostic network forbidden")), \
         patch("socket.socket.connect_ex", side_effect=AssertionError("Diagnostic network forbidden")), \
         patch("socket.create_connection", side_effect=AssertionError("Diagnostic network forbidden")), \
         patch("requests.Session.request", side_effect=AssertionError("Diagnostic HTTP forbidden")), \
         patch("getpass.getpass", side_effect=AssertionError("Diagnostic credential input forbidden")):
        result = diagnose(ROOT, recorded, include_tool_fingerprints=args.tool_fingerprints)
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
