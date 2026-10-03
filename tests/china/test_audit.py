import unittest

from china_macro.audit import audit_observations


class DataAuditTests(unittest.TestCase):
    def test_rejects_invalid_source_value_and_publication_date(self):
        row = {
            "key": "cpi_yoy", "period": "2026-08", "value": 99,
            "source_url": "https://example.com/data", "source_title": "",
            "published": "2026-13-01",
        }
        result = audit_observations([row])
        self.assertEqual(len(result["errors"]), 4)
        self.assertEqual(result["undated_count"], 1)

    def test_marks_unusual_publication_lag_without_rejecting_data(self):
        row = {
            "key": "cpi_yoy", "period": "2021-09", "value": 0.7,
            "source_url": "https://www.stats.gov.cn/sj/zxfb/report.html",
            "source_title": "Official report", "published": "2023-02-03",
        }
        result = audit_observations([row])
        self.assertFalse(result["errors"])
        self.assertEqual(len(result["warnings"]), 1)


if __name__ == "__main__":
    unittest.main()
