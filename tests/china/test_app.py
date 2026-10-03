"""Persistence checks for data refresh audit state."""

import tempfile
import sqlite3
import unittest
from pathlib import Path
from contextlib import closing
from unittest.mock import patch

from china_macro import app


class RefreshAuditTests(unittest.TestCase):
    def test_legacy_analysis_migration_preserves_content(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'macro.sqlite3'
            with closing(sqlite3.connect(path)) as db:
                with db:
                    db.execute('CREATE TABLE analyses (id INTEGER PRIMARY KEY, created_at TEXT, snapshot_hash TEXT, content TEXT, model TEXT)')
                    db.execute("INSERT INTO analyses VALUES (1,'2026-09-01','old','saved content','model')")
            with patch.object(app, 'DB_PATH', path), patch.object(app, 'ROOT', Path(directory)):
                app.initialize()
                app.initialize()
                saved = app.dashboard()['analysis']
                self.assertEqual(saved['content'], 'saved content')
                self.assertEqual(saved['recipe_version'], '1')

    def test_snapshot_survives_resync_but_invalidates_on_evidence_revision(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(app, 'DB_PATH', Path(directory) / 'macro.sqlite3'), patch.object(app, 'ROOT', Path(directory)):
                app.initialize()
                with app.connect() as db:
                    db.execute("INSERT INTO observations VALUES ('cpi_yoy','2026-08',0.8,'https://www.stats.gov.cn/a','report','2026-09-09','2026-09-10')")
                signature = app.dashboard()['snapshot_hash']
                with app.connect() as db:
                    db.execute("UPDATE observations SET fetched_at='2026-10-04'")
                self.assertEqual(app.dashboard()['snapshot_hash'], signature)
                with app.connect() as db:
                    db.execute("UPDATE observations SET source_title='revised title'")
                self.assertNotEqual(app.dashboard()['snapshot_hash'], signature)

    def test_duplicate_generation_and_failure_release_lock(self):
        with patch.dict(app.STATE, refreshing=False, analyzing=False):
            app.ANALYZE_LOCK.acquire()
            try:
                self.assertFalse(app.analyze()['ok'])
            finally:
                app.ANALYZE_LOCK.release()
            with patch.object(app, '_analyze', side_effect=ValueError('test failure')):
                with self.assertRaises(ValueError):
                    app.analyze()
            self.assertFalse(app.STATE['analyzing'])
            self.assertFalse(app.ANALYZE_LOCK.locked())

    def test_infrastructure_migration_moves_old_observations_and_revisions(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(app, "DB_PATH", Path(directory) / "macro.sqlite3"), patch.object(app, "ROOT", Path(directory)):
                app.initialize()
                with app.connect() as db:
                    db.execute("""INSERT INTO observations
                        (key,period,value,source_url,source_title,published,fetched_at)
                        VALUES ('infrastructure_fai_ytd_yoy','2025-09',1.1,'https://www.stats.gov.cn/a','report','','2025-10-20')""")
                    db.execute("""INSERT INTO observation_changes
                        (key,period,old_value,new_value,old_source_url,new_source_url,detected_at,change_type)
                        VALUES ('infrastructure_fai_ytd_yoy','2025-09',1.0,1.1,'a','b','2025-10-20','value_revision')""")
                app.initialize()
                with app.connect() as db:
                    key = db.execute("SELECT key FROM observations").fetchone()[0]
                    revision_key = db.execute("SELECT key FROM observation_changes").fetchone()[0]
                self.assertEqual(key, "infrastructure_ex_utilities_ytd_yoy")
                self.assertEqual(revision_key, key)

    def test_partial_refresh_is_visible_in_dashboard(self):
        with tempfile.TemporaryDirectory() as directory:
            row = {
                "key": "cpi_yoy", "period": "2026-08", "value": 0.8,
                "source_url": "https://www.stats.gov.cn/xxgk/sjfb/zxfb2020/202609/t20260909_1965000.html",
                "source_title": "2026年8月份居民消费价格", "published": "2026-09-09",
            }
            with patch.object(app, "DB_PATH", Path(directory) / "macro.sqlite3"), patch.object(app, "ROOT", Path(directory)):
                app.initialize()
                with patch.object(app, "collect", return_value=([row], ["目录后续页不可访问"])):
                    result = app.refresh()
                self.assertTrue(result["ok"])
                dashboard = app.dashboard()
                run = dashboard["ingestion_runs"][0]
                self.assertEqual(run["status"], "partial")
                self.assertEqual(run["added_count"], 1)
                self.assertEqual(run["warnings"], ["目录后续页不可访问"])

    def test_refresh_preserves_tsf_table_revision_when_table_fetch_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            table = {"key": "tsf_stock_yoy", "period": "2025-11", "value": 7.8,
                     "source_url": "https://www.pbc.gov.cn/diaochatongjisi/attachDir/2026/table.htm",
                     "source_title": "2025年社会融资规模存量统计表", "published": ""}
            report = {**table, "value": 8.1,
                      "source_url": "https://www.pbc.gov.cn/diaochatongjisi/116219/116225/report/index.html"}
            cpi = {**table, "key": "cpi_yoy", "value": .8, "source_url": "https://www.stats.gov.cn/report.html"}
            with patch.object(app, "DB_PATH", root / "db.sqlite3"), patch.object(app, "ROOT", root):
                app.initialize()
                with app.connect() as db:
                    app.save_rows(db, [table], "2026-01-01")
                with patch.object(app, "collect", return_value=([report, cpi], ["年度表读取失败"])):
                    app.refresh()
                with app.connect() as db:
                    saved = dict(db.execute("SELECT * FROM observations WHERE key='tsf_stock_yoy'").fetchone())
                self.assertEqual((saved["value"], saved["source_url"]), (7.8, table["source_url"]))
                with patch.object(app, "collect", return_value=([{**table, "value": 7.9}], [])):
                    app.refresh()
                with app.connect() as db:
                    self.assertEqual(db.execute("SELECT value FROM observations WHERE key='tsf_stock_yoy'").fetchone()[0], 7.9)


if __name__ == "__main__":
    unittest.main()
