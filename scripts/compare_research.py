"""核验并比较两份研究包，导出版次差异及逐项 CSV。"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from guanlan.research_compare import compare_research_packages, comparison_csv_bytes, verify_research_package


def main() -> None:
    parser = argparse.ArgumentParser(description="比较两份观澜宏观研究包")
    parser.add_argument("earlier", type=Path, help="旧研究包 ZIP")
    parser.add_argument("current", type=Path, help="新研究包 ZIP")
    parser.add_argument("--output-dir", type=Path, help="差异输出目录；默认写入 reports/")
    parser.add_argument("--force", action="store_true", help="覆盖已有但内容不同的输出文件")
    args = parser.parse_args()
    old_bytes, new_bytes = args.earlier.read_bytes(), args.current.read_bytes()
    earlier, current = (verify_research_package(old_bytes), verify_research_package(new_bytes))
    result = compare_research_packages(earlier, current)
    directory = args.output_dir or Path("reports") / f"comparison_{result.earlier_id}_{result.current_id}"
    files = {
        "summary.md": result.markdown.encode("utf-8"),
        "report_text.diff": result.report_diff.encode("utf-8"),
        "source_changes.csv": comparison_csv_bytes(result.source_changes),
        "peer_summary.csv": comparison_csv_bytes(result.peer_summary),
    }
    output_tables = {
        "年度 WDI 指标": "annual", "同组样本": "peer", "增长通胀历史": "history",
        "出口伙伴": "partners", "IMF 预测": "forecast", "BIS 金融条件": "bis_financial",
    }
    for label, stem in output_tables.items():
        files[f"{stem}_changes.csv"] = comparison_csv_bytes(result.tables[label])
    manifest = {
        "earlier_report_id": result.earlier_id,
        "current_report_id": result.current_id,
        "earlier_archive_sha256": hashlib.sha256(old_bytes).hexdigest(),
        "current_archive_sha256": hashlib.sha256(new_bytes).hexdigest(),
        "selection": current.manifest["selection"],
        "files_sha256": {name: hashlib.sha256(content).hexdigest() for name, content in sorted(files.items())},
    }
    files["comparison.json"] = (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if not args.force:
        conflicts = [name for name, content in files.items()
                     if (directory / name).exists() and (directory / name).read_bytes() != content]
        if conflicts:
            parser.error(f"已有内容不同的差异文件：{', '.join(conflicts)}；使用 --force 覆盖")
    directory.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (directory / name).write_bytes(content)
    print(f"比较结果：{directory.resolve()}")


if __name__ == "__main__":
    main()
