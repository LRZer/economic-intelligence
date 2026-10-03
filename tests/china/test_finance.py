import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bs4 import BeautifulSoup

from china_macro import app
from china_macro.audit import audit_finance_snapshots
from china_macro.collector import parse_pbc
from china_macro.finance import (parse_m1_backcast, parse_tsf_table, replay_snapshot,
                     save_snapshot, collect_finance)

URL = "https://www.pbc.gov.cn/diaochatongjisi/116219/116225/report/index.html"


class FinanceTests(unittest.TestCase):
    def report(self, text, title):
        return parse_pbc(BeautifulSoup("<div class='content'>" + text + "</div>", "html.parser"),
                         URL, title, "2025-01-14")

    def test_annual_january_and_written_ytd_periods(self):
        cases = [("2024年金融统计数据报告", "全年人民币贷款增加18.09万亿元", "2024-12", 18.09),
                 ("2024年1月金融统计数据报告", "1月份人民币贷款增加4.92万亿元", "2024-01", 4.92),
                 ("2022年11月金融统计数据报告", "1-11月，人民币贷款累计增加19.91万亿元", "2022-11", 19.91),
                 ("2022年5月金融统计数据报告", "今年前5个月，人民币贷款累计增加10.87万亿元", "2022-05", 10.87),
                 ("2024年2月金融统计数据报告", "前两个月人民币贷款增加6.37万亿元", "2024-02", 6.37)]
        for title, text, period, value in cases:
            with self.subTest(title=title):
                row = self.report(text, title)[0]
                self.assertEqual((row["key"], row["period"], row["value"]), ("loans_ytd", period, value))
                self.assertEqual(row["published"], "2025-01-14")

    def test_monthly_and_tsf_loan_component_are_not_ytd_loans(self):
        self.assertEqual(self.report("4月份人民币贷款增加7188亿元。对实体经济发放的人民币贷款增加4.9万亿元。", "2023年4月金融统计数据报告"), [])
        self.assertEqual(self.report("上半年人民币贷款增加13.27万亿元", "2024年5月金融统计数据报告"), [])

    def test_m1_scope_split_and_punctuation(self):
        text = "狭义货币(M1)余额100万亿元。同比下降2%。广义货币（M2）余额300万亿元，同比增长8%。"
        old = {row["key"]: row["value"] for row in self.report(text, "2024年金融统计数据报告")}
        new = {row["key"]: row["value"] for row in self.report(text, "2025年1月金融统计数据报告")}
        self.assertEqual(old, {"m1_legacy_yoy": -2, "m2_yoy": 8})
        self.assertEqual(new, {"m1_yoy": -2, "m2_yoy": 8})

    def test_tsf_table_uses_growth_header_and_total_not_component(self):
        html = """<table><tr><td>社会融资规模存量统计表</td><td>单位：万亿元人民币</td></tr>
        <tr><td></td><td colspan='2'>2021.1</td><td colspan='2'>2021.2</td></tr>
        <tr><td>项目</td><td>存量</td><td>增速（%）</td><td>存量</td><td>增速（%）</td></tr>
        <tr><td>社会融资规模存量 AFRE(stock)</td><td>289.74</td><td>13.0</td><td>291.36</td><td>13.3</td></tr>
        <tr><td>人民币贷款</td><td>175.41</td><td>99</td><td>176.76</td><td>98</td></tr></table>"""
        source = {"year": 2021, "source_url": "https://www.pbc.gov.cn/diaochatongjisi/attachDir/test.htm",
                  "source_title": "2021年社会融资规模存量统计表", "kind": "tsf_table", "published": ""}
        raw = ('<meta charset="gb2312">' + html).encode("gb2312")
        rows = replay_snapshot(raw, source)
        self.assertEqual([(r["period"], r["value"]) for r in rows], [("2021-01", 13), ("2021-02", 13.3)])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = save_snapshot(raw, source, rows, root)
            self.assertFalse(audit_finance_snapshots(root, rows)["finance_snapshot_errors"])
            (root / manifest["file"]).write_bytes(raw + b"tampered")
            self.assertTrue(audit_finance_snapshots(root, rows)["finance_snapshot_errors"])

    def test_backcast_requires_all_twelve_explicit_official_rates(self):
        headers = "".join(f"<td>2024.{m:02d}</td>" for m in range(1, 13))
        rates = "".join(f"<td>{m/10}%</td>" for m in range(1, 13))
        html = "2025年1月份启用修订口径，按可比口径回溯2024年。<table><tr><td></td>" + headers + "</tr><tr><td>同比增速</td>" + rates + "</tr></table>"
        source = {"source_url": "https://www.pbc.gov.cn/diaochatongjisi/attachDir/test.htm", "source_title": "官方回溯", "published": ""}
        rows = parse_m1_backcast(BeautifulSoup(html, "html.parser"), source)
        self.assertEqual(len(rows), 12)
        self.assertTrue(all(r["key"] == "m1_yoy" for r in rows))
        with self.assertRaises(ValueError):
            parse_m1_backcast(BeautifulSoup(html.replace("<td>1.2%</td>", "<td>—</td>"), "html.parser"), source)

    def test_migration_preserves_backcast_and_separates_old_m1_idempotently(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(app, "DB_PATH", root / "db.sqlite3"), patch.object(app, "ROOT", root):
                app.initialize()
                with app.connect() as db:
                    db.execute("INSERT INTO observations VALUES ('m1_yoy','2024-03',-1.7,?,'report','','now')", (URL,))
                    db.execute("INSERT INTO observations VALUES ('m1_yoy','2024-04',0.6,'https://www.pbc.gov.cn/diaochatongjisi/attachDir/table.htm','official backcast','','now')")
                app.initialize()
                app.initialize()
                with app.connect() as db:
                    rows = {(r[0], r[1]) for r in db.execute("SELECT key,period FROM observations")}
                self.assertEqual(rows, {("m1_legacy_yoy", "2024-03"), ("m1_yoy", "2024-04")})

    def test_daily_refresh_keeps_annual_tsf_revision_after_report(self):
        report = {"source_url": URL, "source_title": "2026年8月金融统计数据报告", "published": "2026-09-14"}
        table = {"source_url": "https://www.pbc.gov.cn/diaochatongjisi/attachDir/table.htm",
                 "source_title": "2026年社会融资规模存量统计表", "year": 2026, "kind": "tsf_table", "published": ""}
        original = {"key": "tsf_stock_yoy", "period": "2026-08", "value": 7.2}
        revised = {**original, "value": 7.3}
        with patch("china_macro.finance.discover_reports", return_value=[report]), \
             patch("china_macro.finance.discover_tables", return_value=[table]), \
             patch("china_macro.finance.fetch", return_value=(None, b"report")), \
             patch("china_macro.finance.fetch_table", return_value=(None, b"table")), \
             patch("china_macro.finance.replay_snapshot", side_effect=[[original], [revised]]), \
             patch("china_macro.finance.save_snapshot"), patch("china_macro.finance.time.sleep"):
            rows, errors = collect_finance()
        self.assertEqual(errors, [])
        final = {(r["key"], r["period"]): r for r in rows}
        self.assertEqual(final["tsf_stock_yoy", "2026-08"]["value"], 7.3)


if __name__ == "__main__":
    unittest.main()
