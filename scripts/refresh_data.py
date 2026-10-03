"""从官方接口更新本地研究快照。"""

from __future__ import annotations

import argparse
import sys
from dataclasses import asdict
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from guanlan.data import DEFAULT_DATA_DIR, fetch_wdi, publish_snapshots, record_refresh_failure
from guanlan.cycle import build_cycle_features, evaluate_cycle
from guanlan.cycle_diagnostics import paired_block_brier_interval
from guanlan.us_official import fetch_us_monthly


def acquire_snapshots(args: argparse.Namespace) -> dict[str, tuple[pd.DataFrame, dict]]:
    snapshots = {}

    if not args.trade_only and not args.us_only:
        print("正在获取世界银行 WDI 数据……", flush=True)
        frame, meta = fetch_wdi(args.start, args.end)
        snapshots["macro"] = (frame, meta)
        print(f"已取得宏观数据：{meta['countries']} 个经济体，{meta['indicators']} 项指标，{meta['rows']} 行", flush=True)
    if args.trade_only:
        raise ValueError("UN Comtrade 再分发授权未确认。请使用 scripts/import_baci.py 导入许可明确的完整贸易数据。")
    if not args.macro_only and not args.trade_only:
        print("正在获取 美国官方月度宏观序列……", flush=True)
        frame, meta = fetch_us_monthly(raw_directory=args.directory.parent / "raw" / "us_official")
        backtest, signal, metrics = evaluate_cycle(build_cycle_features(frame))
        uncertainty = paired_block_brier_interval(backtest)
        snapshots["us_monthly"] = (frame, meta)
        snapshots["us_cycle_backtest"] = (
            backtest, {
                "provider": "Guanlan / direct official US retrospective backtest",
                "source_snapshot_utc": meta["downloaded_at_utc"],
                "downloaded_at_utc": meta["downloaded_at_utc"],
                "signal": asdict(signal),
                "metrics": metrics,
                "uncertainty": uncertainty,
                "validated_for_decision": False,
                "method": "3-component Gaussian mixture; 180-month rolling window; six-month label purge",
                "model_limit": "当前版本的修订后历史数据；不是实时版本回测；不能推断资产回报",
            },
        )
        print(f"已取得美国官方数据：{len(meta['series'])} 项序列，{meta['rows']} 行", flush=True)
        print(
            f"周期回测：{metrics['months']} 个月，模型 Brier {metrics['model_brier']:.3f}，"
            f"基线 Brier {metrics['baseline_brier']:.3f}",
            flush=True,
        )
    return snapshots


def main() -> None:
    parser = argparse.ArgumentParser(description="刷新世界银行与美国官方数据；贸易使用独立 BACI 导入")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--macro-only", action="store_true", help="仅刷新宏观数据")
    group.add_argument("--trade-only", action="store_true", help="仅刷新贸易样本")
    group.add_argument("--us-only", action="store_true", help="仅刷新美国月度序列")
    parser.add_argument("--start", type=int, default=2000, help="宏观数据开始年份")
    parser.add_argument("--end", type=int, default=2025, help="宏观数据结束年份")
    parser.add_argument("--directory", type=Path, default=DEFAULT_DATA_DIR, help="快照目录")
    args = parser.parse_args()
    stems = (["macro"] if args.macro_only else ["trade"] if args.trade_only else
             ["us_monthly", "us_cycle_backtest"] if args.us_only else
             ["macro", "us_monthly", "us_cycle_backtest"])
    try:
        snapshots = acquire_snapshots(args)
    except Exception as exc:
        record_refresh_failure("refresh_data:source_or_model", stems, exc, args.directory)
        raise
    batch_id = publish_snapshots(snapshots, args.directory, operation="refresh_data")
    print(f"整批快照已发布；批次 ID：{batch_id}", flush=True)


if __name__ == "__main__":
    main()
