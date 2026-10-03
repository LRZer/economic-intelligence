"""查看本地快照批次，并回退当前完整生效的刷新批次。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from guanlan.data import DEFAULT_DATA_DIR, refresh_audit, restore_batch, snapshot_catalog


def main() -> None:
    parser = argparse.ArgumentParser(description="观澜快照批次审计与回退")
    parser.add_argument("--directory", type=Path, default=DEFAULT_DATA_DIR, help="快照目录")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="查看当前活动快照及最近 20 条刷新事件")
    rollback = commands.add_parser("rollback", help="回退仍完整生效的目标批次")
    rollback.add_argument("batch_id", help="要回退的已发布批次 ID")
    args = parser.parse_args()

    if args.command == "list":
        active = snapshot_catalog(args.directory)
        print("活动快照：")
        for stem, reference in sorted(active.items()):
            print(f"  {stem}: {reference}")
        if not active:
            print("  仓库随附的基础快照")
        events = refresh_audit(args.directory)
        print("最近刷新事件：")
        for row in events.itertuples():
            print(f"  {row.at_utc}  {row.status:9}  {row.batch_id}  "
                  f"{row.operation}  {','.join(row.stems)}")
        if events.empty:
            print("  暂无")
    else:
        restore_id = restore_batch(args.batch_id, args.directory)
        print(f"已回退批次 {args.batch_id}；审计事件 ID：{restore_id}")


if __name__ == "__main__":
    main()
