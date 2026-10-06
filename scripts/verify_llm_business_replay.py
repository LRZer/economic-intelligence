"""Verify preserved first-run tool semantics without network, keys or record writes."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import json
from pathlib import Path
from unittest.mock import patch

from guanlan.llm_replay_verify import verify_first_replay

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", nargs="?", type=Path, default=ROOT / "docs/validation/llm-business-first-run-replay.json")
    parser.add_argument("--contract", type=Path, default=ROOT / "docs/validation/llm-business-portable-semantics.json")
    args = parser.parse_args()
    with ExitStack() as stack:
        for operation in ("socket.socket.connect", "socket.socket.connect_ex", "socket.create_connection",
                          "requests.Session.request", "getpass.getpass"):
            stack.enter_context(patch(operation, side_effect=AssertionError("Offline verifier network/credentials forbidden")))
        result = verify_first_replay(ROOT, args.run, args.contract)
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
