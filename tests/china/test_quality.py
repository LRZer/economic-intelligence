"""Release timing must not turn unpublished data into collection failures."""
import unittest
from datetime import datetime

from china_macro.quality import CHINA_TIME, coverage, planned_release


class ReleaseStateTests(unittest.TestCase):
    def test_september_pmi_does_not_make_other_september_data_missing(self):
        result = coverage({"manufacturing_pmi": [{"period": "2026-09", "value": 49.5}]},
                          window=1, as_of=datetime(2026, 10, 4, 12, tzinfo=CHINA_TIME))
        items = {item["key"]: item for item in result["metrics"]}
        for key in ("industrial_yoy", "retail_yoy", "fai_ytd_yoy", "unemployment", "cpi_yoy", "ppi_mom", "industrial_profit_ytd_yoy"):
            self.assertEqual(items[key]["pending"], ["2026-09"])
            self.assertEqual(items[key]["missing"], [])
            self.assertEqual(items[key]["expected"], 0)
        for key in ("m2_yoy", "fiscal_revenue_ytd_yoy", "export_usd_yoy"):
            self.assertEqual(items[key]["unconfirmed"], ["2026-09"])
            self.assertEqual(items[key]["expected"], 0)

    def test_price_release_boundary_and_plan_is_not_proof_of_publication(self):
        series = {"manufacturing_pmi": [{"period": "2026-09", "value": 50}]}
        before = coverage(series, window=1, as_of=datetime(2026, 10, 14, 9, 29, tzinfo=CHINA_TIME))
        after = coverage(series, window=1, as_of=datetime(2026, 10, 14, 9, 30, tzinfo=CHINA_TIME))
        prior = next(item for item in before["metrics"] if item["key"] == "cpi_yoy")
        current = next(item for item in after["metrics"] if item["key"] == "cpi_yoy")
        self.assertEqual(prior["pending"], ["2026-09"])
        self.assertEqual(current["missing"], ["2026-09"])
        self.assertIn("实际发布仍需核查", current["period_states"][0]["reason"])

    def test_pmi_february_delay_and_overview_previous_month(self):
        self.assertEqual(planned_release("manufacturing_pmi", "2026-02"), datetime(2026, 3, 4, 9, 30, tzinfo=CHINA_TIME))
        self.assertEqual(planned_release("industrial_yoy", "2026-09"), datetime(2026, 10, 19, 10, tzinfo=CHINA_TIME))
        self.assertEqual(planned_release("industrial_yoy", "2025-12"), datetime(2026, 1, 19, 10, tzinfo=CHINA_TIME))

    def test_recorded_value_precedes_plan_and_old_scope_is_inactive(self):
        result = coverage({"cpi_yoy": [{"period": "2026-09", "value": .8}]}, window=1,
                          as_of=datetime(2026, 10, 4, tzinfo=CHINA_TIME))
        items = {item["key"]: item for item in result["metrics"]}
        self.assertEqual(items["cpi_yoy"]["period_states"][0]["code"], "recorded")
        old = items["infrastructure_ex_utilities_ytd_yoy"]
        self.assertTrue(old["inactive"])
        self.assertEqual(old["expected"], 0)
        self.assertEqual(old["period_states"][0]["code"], "inactive")


if __name__ == "__main__":
    unittest.main()
