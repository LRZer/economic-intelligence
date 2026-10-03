"""刷新 IMF WEO 固定版本的中期预测快照。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from guanlan.data import DEFAULT_DATA_DIR, publish_snapshots, record_refresh_failure
from guanlan.weo import fetch_weo_forecasts


def main() -> None:
    parser = argparse.ArgumentParser(description="刷新固定版次 IMF WEO 预测")
    parser.add_argument("--directory", type=Path, default=DEFAULT_DATA_DIR, help="快照目录")
    args = parser.parse_args()
    try:
        frame, metadata = fetch_weo_forecasts()
    except Exception as exc:
        record_refresh_failure("refresh_weo:source", ["weo"], exc, args.directory)
        raise
    batch_id = publish_snapshots({"weo": (frame, metadata)}, args.directory, operation="refresh_weo")
    print(f"WEO {metadata['vintage']}：{metadata['countries']} 个经济体，"
          f"{metadata['indicators']} 项指标，{metadata['available_values']:,} 个可用预测值；"
          f"批次 ID：{batch_id}", flush=True)


if __name__ == "__main__":
    main()
