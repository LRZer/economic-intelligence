"""Recompute a downloaded restricted-assistant JSON without network or key lookup."""
import argparse
import json
from pathlib import Path
from guanlan.evidence_assistant import verify_answer_report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report',type=Path)
    args=parser.parse_args()
    try:
        if not args.report.is_file() or args.report.stat().st_size>8*1024*1024:raise ValueError
        result=verify_answer_report(json.loads(args.report.read_text(encoding='utf-8')))
    except (OSError,UnicodeError,ValueError,TypeError,RecursionError):
        print(json.dumps({'status':'failed','reason':'问答文件结构、来源、计算或指纹与本地复算不一致。'},ensure_ascii=False))
        return 1
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0


if __name__=='__main__':raise SystemExit(main())
