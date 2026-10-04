"""Recompute the whole published graph report locally, without network or keys."""
from pathlib import Path
import argparse,json
from guanlan.trade_graph import verify_graph_report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report',type=Path)
    args=parser.parse_args()
    try:
        if args.report.stat().st_size>32*1024**2:raise ValueError('报告超过32MiB')
        result=verify_graph_report(json.loads(args.report.read_text(encoding='utf-8')))
    except (OSError,ValueError,TypeError):raise SystemExit('图报告未通过离线核验，请检查结构、源边、假设与文件大小。') from None
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
