"""导入 CEPII BACI HS17 官方数据包，构建全球贸易研究快照。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from guanlan.baci import BACI_RELEASE, BACI_URL, YEARS, build_baci_snapshots, download_baci_zip
from guanlan.data import DEFAULT_DATA_DIR, record_refresh_failure


def main() -> None:
    parser = argparse.ArgumentParser(description="从 BACI 官方压缩包构建可审计的伙伴与商品章快照")
    parser.add_argument("--zip", type=Path,
                        default=Path("data/raw") / f"BACI_HS17_V{BACI_RELEASE}.zip",
                        help="官方 BACI HS17 压缩包路径")
    parser.add_argument("--years", nargs="+", type=int, default=list(YEARS), help="导入年份，默认 2017—2024")
    parser.add_argument("--download", action="store_true", help="若压缩包不存在，直接从 CEPII 官方地址下载")
    parser.add_argument("--directory", type=Path, default=DEFAULT_DATA_DIR, help="快照目录")
    args = parser.parse_args()
    try:
        if args.download and not args.zip.exists():
            download_baci_zip(args.zip)
        if not args.zip.exists():
            parser.error(f"缺少数据包：{args.zip}。官方下载：{BACI_URL}")
        meta = build_baci_snapshots(args.zip, tuple(args.years), args.directory)
    except Exception as exc:
        if not getattr(exc, "_guanlan_refresh_logged", False):
            record_refresh_failure("import_baci:source_or_build", ["baci_partner", "baci_chapter"], exc, args.directory)
        raise
    print(f"完成：{meta['raw_rows']:,} 条原始商品流；{meta['partner_rows']:,} 条伙伴聚合；"
          f"{meta['chapter_rows']:,} 条商品章聚合", flush=True)


if __name__ == "__main__":
    main()
