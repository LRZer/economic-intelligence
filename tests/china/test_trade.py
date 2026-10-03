"""Validate the MOFCOM table before any trade observations enter SQLite."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from china_macro.audit import audit_trade_snapshots
from china_macro.trade import parse_trade_payload, save_source_snapshot


def sample():
    return [[{"trade_date": "202608", "total_value": 6837.97,
              "export_value": 4014.41, "import_value": 2823.56,
              "imexgap_value": 1190.85, "export_per": 25.0, "import_per": 28.2}]]


class TradeSourceTests(unittest.TestCase):
    def test_parses_dollar_levels_and_reported_rates_as_distinct_series(self):
        rows = parse_trade_payload(sample(), "202101", "202608")
        self.assertEqual({row["key"]: row["value"] for row in rows}, {
            "export_usd": 4014.41, "import_usd": 2823.56,
            "export_usd_yoy": 25.0, "import_usd_yoy": 28.2,
        })
        self.assertTrue(all(row["period"] == "2026-08" and not row["published"] for row in rows))

    def test_rejects_inconsistent_totals_and_duplicate_months(self):
        payload = sample()
        payload[0][0]["total_value"] = 7000
        with self.assertRaisesRegex(ValueError, "sum does not reconcile"):
            parse_trade_payload(payload, "202101", "202608")
        payload = sample()
        payload[0].append(payload[0][0].copy())
        with self.assertRaisesRegex(ValueError, "duplicate"):
            parse_trade_payload(payload, "202101", "202608")

    def test_snapshot_keeps_exact_source_bytes_and_checksum(self):
        content = json.dumps(sample(), separators=(",", ":")).encode("utf-8")
        with tempfile.TemporaryDirectory() as directory:
            rows = parse_trade_payload(sample(), "202101", "202608")
            report = save_source_snapshot(content, rows,
                                          "202101", "202608", Path(directory))
            stored = Path(report["path"])
            self.assertEqual(stored.read_bytes(), content)
            self.assertEqual(report["sha256"], hashlib.sha256(content).hexdigest())
            self.assertEqual(json.loads(stored.with_suffix(".meta.json").read_text(encoding="utf-8")), report)
            self.assertEqual(audit_trade_snapshots(Path(directory), rows)["snapshot_errors"], [])
            stored.write_bytes(b"corrupt")
            self.assertEqual(len(audit_trade_snapshots(Path(directory), rows)["snapshot_errors"]), 1)


if __name__ == "__main__":
    unittest.main()
