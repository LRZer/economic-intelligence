"""下载或导入 BIS 利率、信贷与有效汇率数据并整批发布快照。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from guanlan.bis import (
    BIS_CREDIT_URL, BIS_EER_URL, BIS_POLICY_URL, download_bis_zip,
    normalize_bis_credit_zip, normalize_bis_eer_zip, normalize_bis_policy_zip,
)
from guanlan.data import DEFAULT_DATA_DIR, publish_snapshots, record_refresh_failure


def main() -> None:
    parser = argparse.ArgumentParser(description="刷新 BIS 政策利率、信贷/GDP 与有效汇率")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--policy-only", action="store_true", help="仅刷新政策利率")
    group.add_argument("--credit-only", action="store_true", help="仅刷新信贷/GDP 数据")
    group.add_argument("--eer-only", action="store_true", help="仅刷新有效汇率")
    parser.add_argument("--policy-zip", type=Path, help="已有 BIS WS_CBPOL_csv_flat.zip")
    parser.add_argument("--credit-zip", type=Path, help="已有 BIS WS_CREDIT_GAP_csv_flat.zip")
    parser.add_argument("--eer-zip", type=Path, help="已有 BIS WS_EER_csv_flat.zip")
    parser.add_argument("--directory", type=Path, default=DEFAULT_DATA_DIR, help="快照目录")
    args = parser.parse_args()
    if (args.policy_only and (args.credit_zip or args.eer_zip)
            or args.credit_only and (args.policy_zip or args.eer_zip)
            or args.eer_only and (args.policy_zip or args.credit_zip)):
        parser.error("单来源刷新参数不能同时指定另一个来源的 ZIP")
    stems = (["bis_policy"] if args.policy_only else ["bis_credit"] if args.credit_only
             else ["bis_eer"] if args.eer_only
             else ["bis_policy", "bis_credit", "bis_eer"])
    try:
        snapshots = {}
        if "bis_policy" in stems:
            content, modified = ((args.policy_zip.read_bytes(), None) if args.policy_zip else
                                 download_bis_zip(BIS_POLICY_URL))
            snapshots["bis_policy"] = normalize_bis_policy_zip(content, modified)
            print(f"BIS 月度政策利率：{len(snapshots['bis_policy'][0]):,} 行", flush=True)
        if "bis_credit" in stems:
            content, modified = ((args.credit_zip.read_bytes(), None) if args.credit_zip else
                                 download_bis_zip(BIS_CREDIT_URL))
            snapshots["bis_credit"] = normalize_bis_credit_zip(content, modified)
            print(f"BIS 季度信贷/GDP：{len(snapshots['bis_credit'][0]):,} 行", flush=True)
        if "bis_eer" in stems:
            content, modified = ((args.eer_zip.read_bytes(), None) if args.eer_zip else
                                 download_bis_zip(BIS_EER_URL))
            snapshots["bis_eer"] = normalize_bis_eer_zip(content, modified)
            print(f"BIS 月度有效汇率：{len(snapshots['bis_eer'][0]):,} 行", flush=True)
    except Exception as exc:
        record_refresh_failure("refresh_bis:source_or_validation", stems, exc, args.directory)
        raise
    batch_id = publish_snapshots(snapshots, args.directory, operation="refresh_bis")
    print(f"BIS 快照整批发布；批次 ID：{batch_id}", flush=True)


if __name__ == "__main__":
    main()
