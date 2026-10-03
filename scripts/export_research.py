"""从活动快照导出一份可离线核验的研究包。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from guanlan.analytics import GROWTH
from guanlan.data import DEFAULT_DATA_DIR, load_snapshot, snapshot_catalog
from guanlan.research import COHORTS
from guanlan.research_bundle import build_research_bundle


def main() -> None:
    parser = argparse.ArgumentParser(description="导出观澜宏观研究包 ZIP")
    parser.add_argument("--country", required=True, help="经济体 ISO3 代码，例如 CHN")
    parser.add_argument("--year", required=True, type=int, help="WDI 观察年份")
    parser.add_argument("--indicator", default=GROWTH, help="同组参照的 WDI 指标代码")
    parser.add_argument("--cohort", choices=list(COHORTS), default="同收入组", help="同组范围")
    parser.add_argument("--directory", type=Path, default=DEFAULT_DATA_DIR, help="快照目录")
    parser.add_argument("--output", type=Path, help="输出 ZIP 路径；默认写入 reports/ 并带报告编号")
    parser.add_argument("--force", action="store_true", help="覆盖已有但内容不同的输出文件")
    args = parser.parse_args()

    active = snapshot_catalog(args.directory)

    def read(stem: str):
        return load_snapshot(stem, args.directory, active)

    macro, macro_meta = read("macro")
    try:
        trade, trade_meta = read("baci_partner")
        _, chapter_meta = read("baci_chapter")
        if trade_meta.get("build_id") != chapter_meta.get("build_id"):
            raise ValueError("BACI 伙伴与商品章快照版本不一致")
    except FileNotFoundError:
        if "baci_partner" in active or "baci_chapter" in active:
            raise
        try:
            trade, trade_meta = read("trade")
        except FileNotFoundError:
            if "trade" in active:
                raise
            trade, trade_meta = pd.DataFrame(), {}
    try:
        weo, weo_meta = read("weo")
    except FileNotFoundError:
        if "weo" in active:
            raise
        weo, weo_meta = pd.DataFrame(), {}

    def optional_read(stem: str):
        try:
            return read(stem)
        except FileNotFoundError:
            if stem in active:
                raise
            return pd.DataFrame(), {}

    bis_policy, bis_policy_meta = optional_read("bis_policy")
    bis_credit, bis_credit_meta = optional_read("bis_credit")

    bundle = build_research_bundle(
        macro, trade, macro_meta, trade_meta, args.country.upper(), args.year,
        args.indicator, args.cohort, weo=weo, weo_meta=weo_meta,
        bis_policy=bis_policy, bis_credit=bis_credit,
        bis_policy_meta=bis_policy_meta, bis_credit_meta=bis_credit_meta,
    )
    target = args.output or Path("reports") / f"guanlan_{args.country.upper()}_{args.year}_{bundle.report_id}.zip"
    if target.exists() and target.read_bytes() != bundle.archive and not args.force:
        parser.error(f"输出文件已存在且内容不同：{target}；使用 --force 覆盖")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(bundle.archive)
    print(f"研究包：{target.resolve()}\n报告编号：{bundle.report_id}", flush=True)


if __name__ == "__main__":
    main()
