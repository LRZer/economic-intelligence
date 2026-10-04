"""Verify a downloaded review JSON by refitting local models, without network."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from guanlan.monthly_review import verify_exported_review


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    try:
        if not args.report.is_file() or args.report.stat().st_size > 8 * 1024 * 1024:
            raise ValueError
        report = json.loads(args.report.read_text(encoding="utf-8"))
        result = verify_exported_review(report)
    except (OSError, UnicodeError, ValueError, TypeError, RecursionError):
        print(json.dumps({"status": "failed", "reason": "核验文件无法读取，或指纹、结构、来源与本地模型重算不一致。"}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
