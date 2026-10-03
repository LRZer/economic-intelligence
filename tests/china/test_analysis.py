import unittest

from china_macro.analysis import computed_analysis, empirical_percentile
from china_macro.catalog import INDICATORS
from china_macro.quality import coverage, month_number, period_from_number


class ReproducibleAnalysisTests(unittest.TestCase):
    def test_tied_values_use_midrank(self):
        self.assertEqual(empirical_percentile([1, 2, 2, 3], 2), 50.0)

    def test_year_ago_difference_and_sixty_month_rank(self):
        end = month_number("2026-08")
        observations = [
            {"period": period_from_number(end - 59 + i), "value": float(i),
             "source_url": f"https://www.stats.gov.cn/test/{i}"}
            for i in range(60)
        ]
        series = {"cpi_yoy": observations}
        catalog = [{"key": key, "name": spec[0], "basis": spec[2], "unit": spec[3]}
                   for key, spec in INDICATORS.items()]
        result = computed_analysis(series, catalog, coverage(series, window=60), "2026-08")
        item = next(row for row in result["findings"] if row["key"] == "cpi_yoy")
        self.assertEqual(item["year_ago_delta_pp"], 12.0)
        self.assertEqual(item["percentile_60m"], 99.2)
        self.assertEqual(item["sample_size"], 60)
        self.assertEqual(item["year_ago"]["source_url"], observations[47]["source_url"])

    def test_pmi_breadth_uses_same_period_and_strictly_above_fifty(self):
        series = {key: [{"period": "2026-08", "value": value, "source_url": "https://www.stats.gov.cn/a"}]
                  for key, value in zip(("manufacturing_pmi", "manufacturing_new_orders_pmi", "nonmanufacturing_pmi"),
                                        (49.8, 50.6, 50.0))}
        result = computed_analysis(series, [], coverage(series, window=60), "2026-08")
        self.assertEqual(result["pmi_breadth"]["above_50"], 1)
        self.assertEqual(result["pmi_breadth"]["equal_50"], 1)


if __name__ == "__main__":
    unittest.main()
