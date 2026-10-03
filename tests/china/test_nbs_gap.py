import tempfile
import unittest
from pathlib import Path

from china_macro.audit import audit_nbs_gap_snapshots
from china_macro.nbs_gap import save_snapshot


class NbsGapSnapshotTests(unittest.TestCase):
    def test_snapshot_replay_detects_source_tampering_and_db_mismatch(self):
        content = ("<div class='TRS_Editor'>1—6月份，民间固定资产投资128570亿元，"
                   "下降0.2%。制造业投资增长6.0%。</div>").encode("utf-8")
        source = {
            "period": "2023-06", "published": "2023-07-17",
            "source_url": "https://www.stats.gov.cn/sj/zxfb/202307/t20230717_1941290.html",
            "source_title": "2023年1—6月份全国固定资产投资基本情况",
        }
        row = {"key": "private_fai_ytd_yoy", "period": source["period"], "value": -0.2,
               "source_url": source["source_url"]}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = save_snapshot(content, source, row, root)
            report = audit_nbs_gap_snapshots(root, [row])
            self.assertEqual(report["nbs_gap_snapshot_checked_observations"], 1)
            self.assertEqual(report["nbs_gap_snapshot_errors"], [])
            changed_row = {**row, "value": -0.3}
            self.assertTrue(audit_nbs_gap_snapshots(root, [changed_row])["nbs_gap_snapshot_errors"])
            (root / f"nbs-gap-{manifest['sha256']}.html").write_bytes(content + b"tampered")
            self.assertTrue(audit_nbs_gap_snapshots(root, [row])["nbs_gap_snapshot_errors"])


if __name__ == "__main__":
    unittest.main()
