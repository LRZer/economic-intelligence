"""Reader observations compare exact, compatible periods without causal claims."""
import unittest

from china_macro.analysis import reader_summary


def row(period, value):
    return {"period": period, "value": value, "source_url": "https://www.stats.gov.cn/a", "source_title": "official"}


class ReaderSummaryTests(unittest.TestCase):
    def test_sparse_history_does_not_become_previous_month(self):
        result = reader_summary({"industrial_yoy": [row("2026-06", 3), row("2026-08", 5)]},
                                [{"key": "industrial_yoy", "name": "工业", "basis": "单月同比", "unit": "%"}], "2026-08")
        self.assertIsNone(result["changes"]["industrial_yoy"]["delta"])
        self.assertEqual(result["observations"], [])

    def test_cumulative_amounts_and_year_boundaries_are_not_compared(self):
        catalog = [{"key": "fai_ytd_yoy", "name": "投资", "basis": "年内累计同比", "unit": "%"},
                   {"key": "loans_ytd", "name": "贷款", "basis": "年内累计", "unit": "万亿元"}]
        result = reader_summary({"fai_ytd_yoy": [row("2025-12", 2), row("2026-01", 3)],
                                 "loans_ytd": [row("2026-07", 12), row("2026-08", 13)]}, catalog, "2026-08")
        self.assertIsNone(result["changes"]["fai_ytd_yoy"]["delta"])
        self.assertIsNone(result["changes"]["loans_ytd"]["delta"])

    def test_unemployment_direction_does_not_claim_improvement(self):
        result = reader_summary({"unemployment": [row("2026-07", 5.2), row("2026-08", 5.3)]},
                                [{"key": "unemployment", "name": "失业率", "basis": "当月水平", "unit": "%"}], "2026-08")
        item = result["changes"]["unemployment"]
        self.assertEqual((item["comparison_period"], item["delta"], item["direction"]), ("2026-07", .1, "上升"))
        self.assertIn("读数上升", result["observations"][0]["title"])
        self.assertNotIn("改善", result["observations"][0]["title"])

    def test_different_data_months_are_not_combined(self):
        catalog = [{"key": key, "name": key, "basis": "单月同比", "unit": "%"} for key in ("industrial_yoy", "retail_yoy")]
        result = reader_summary({"industrial_yoy": [row("2026-07", 4), row("2026-08", 5)],
                                 "retail_yoy": [row("2026-06", 3), row("2026-07", 2)]}, catalog, "2026-08")
        self.assertEqual(result["observations"][0]["keys"], ["industrial_yoy"])


if __name__ == "__main__":
    unittest.main()
