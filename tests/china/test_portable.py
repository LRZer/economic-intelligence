"""A fresh copy can boot from the bundled snapshot without prior local state."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2] / "src" / "china_macro"


class PortableSnapshotTests(unittest.TestCase):
    def test_fresh_checkout_loads_full_bundled_snapshot(self):
        snapshot = json.loads((ROOT / "demo_data.json").read_text(encoding="utf-8"))
        expected = len(snapshot["rows"])
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "china_macro"
            target.mkdir()
            for source in ROOT.glob("*.py"):
                shutil.copy2(source, target / source.name)
            shutil.copy2(ROOT / "demo_data.json", target / "demo_data.json")
            shutil.copytree(ROOT / "bundled_snapshots", target / "bundled_snapshots")
            environment = os.environ.copy()
            environment.pop("PYTHONPATH", None)
            environment["CHINA_DATA_DIR"] = str(target.parent / "data" / "china")
            environment["CHINA_DB_PATH"] = str(target.parent / "data" / "china" / "macro.sqlite3")
            result = subprocess.run(
                [sys.executable, "-c", "from china_macro import app;app.initialize();print(app.dashboard()['quality']['observation_count'])"],
                cwd=target.parent, env=environment, text=True, capture_output=True, timeout=20,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(int(result.stdout.strip()), expected)
            audited = subprocess.run(
                [sys.executable, "-m", "china_macro.audit", "--output", "data/portable_audit.json",
                 "--as-of", snapshot["captured_at"]],
                # Replaying over 60 MB of historical HTML can exceed a minute
                # on Windows. Keep all integrity assertions and bound the run.
                cwd=target.parent, env=environment, text=True, capture_output=True, timeout=180,
            )
            self.assertEqual(audited.returncode, 0, audited.stderr + audited.stdout)
            report = json.loads((target.parent / "data" / "portable_audit.json").read_text(encoding="utf-8"))
            self.assertEqual(report["fiscal_snapshot_checked_observations"], 620)
            self.assertEqual(report["nbs_gap_snapshot_checked_observations"], 246)
            self.assertEqual(report["finance_snapshot_count"], 75)
            self.assertEqual(report["finance_snapshot_checked_observations"], 272)
            self.assertEqual(report["cny_snapshot_checked_observations"], 4)
            price = {item["key"]: item for item in report["indicator_60m"]
                     if item["key"] in {"cpi_yoy", "cpi_mom", "ppi_yoy", "ppi_mom"}}
            self.assertEqual({key: (item["observed"], item["expected"])
                              for key, item in price.items()},
                             {key: (59, 59) for key in
                              ("cpi_yoy", "cpi_mom", "ppi_yoy", "ppi_mom")})
            metrics = {item["key"]: item for item in report["indicator_60m"]}
            for key, expected_periods in (("unemployment", 54), ("retail_yoy", 49),
                                          ("manufacturing_pmi", 60),
                                          ("manufacturing_new_orders_pmi", 60),
                                          ("nonmanufacturing_pmi", 60),
                                          ("m1_legacy_yoy", 39), ("m1_yoy", 32),
                                          ("m2_yoy", 59), ("tsf_stock_yoy", 59)):
                self.assertEqual((metrics[key]["observed"], metrics[key]["expected"]),
                                 (expected_periods, expected_periods))
            self.assertEqual((metrics["export_yoy"]["observed"],
                              metrics["import_yoy"]["observed"]), (48, 48))
            self.assertEqual((metrics["loans_ytd"]["observed"], metrics["loans_ytd"]["expected"]),
                             (52, 59))
            self.assertEqual(report["errors"], [])


if __name__ == "__main__":
    unittest.main()
