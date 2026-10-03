"""An online backup must be readable after an actual restore."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from china_macro import app
from china_macro import backup


class BackupTests(unittest.TestCase):
    def test_backup_restores_observations_and_writes_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "data" / "macro.sqlite3"
            destination = root / "archive" / "copy.sqlite3"
            with patch.object(app, "ROOT", root), patch.object(app, "DB_PATH", database), patch.object(backup, "DB_PATH", database):
                app.initialize()
                with app.connect() as db:
                    db.execute("""INSERT INTO observations
                        (key,period,value,source_url,source_title,published,fetched_at)
                        VALUES ('cpi_yoy','2026-08',0.8,'https://www.stats.gov.cn/a',
                                'CPI report','2026-09-09','2026-09-10')""")
                report = backup.create_backup(destination)

            self.assertEqual(report["observation_count"], 1)
            self.assertEqual(report["restored_observation_count"], 1)
            self.assertEqual(report["restore_check"], "ok")
            self.assertEqual(report["sha256"], hashlib.sha256(destination.read_bytes()).hexdigest())
            self.assertEqual(json.loads(destination.with_suffix(".sqlite3.json").read_text(encoding="utf-8")), report)


if __name__ == "__main__":
    unittest.main()
