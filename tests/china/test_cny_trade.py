import json
import tempfile
import unittest
from pathlib import Path

from china_macro.audit import audit_cny_snapshots
from china_macro.cny_trade import PAGE_URL, parse_cny_payload, save_snapshot


def table():
    return {"code": 0, "data": {"id": 123, "name": "2026年3月全国进出口总值表（人民币值）",
        "issueDate": "2026-04-28", "source": "海关总署", "content": """单位：亿元人民币
        <table><tr><td>项目</td><td>3月</td><td>1至3月累计</td><td>3月与上月环比增减±%</td><td>3月与去年同期同比增减±%</td><td>1至3月累计与去年同期同比增减±%</td></tr>
        <tr><td>进出口总值</td><td>41,046.4</td><td>118380</td><td>15.2</td><td>9.2</td><td>15</td></tr>
        <tr><td>出口总值</td><td>22,297.0</td><td>68466.7</td><td>6.2</td><td>-0.7</td><td>11.9</td></tr>
        <tr><td>进口总值</td><td>18,749.4</td><td>49913.3</td><td>28.2</td><td>23.8</td><td>19.6</td></tr>
        <tr><td>进出口差额</td><td>3,547.5</td><td>18553.4</td><td>-</td><td>-</td><td>-</td></tr></table>"""}}


class CNYTradeTests(unittest.TestCase):
    def test_only_explicit_monthly_rate_and_repost_date(self):
        rows = parse_cny_payload(table(), PAGE_URL + "123")
        self.assertEqual({r["key"]: r["value"] for r in rows}, {"export_yoy": -0.7, "import_yoy": 23.8})
        self.assertTrue(all(r["period"] == "2026-03" and "转载日期" in r["source_title"] for r in rows))

    def test_rejects_combined_period_usd_wrong_source_identity_and_bad_sum(self):
        for payload in ([], {"code": 0, "data": None}, {"code": 0, "data": []}):
            with self.assertRaises(ValueError):
                parse_cny_payload(payload, PAGE_URL + "123")
        for change in (lambda p: p["data"].update(name="2026年1至2月全国进出口总值表（人民币值）"),
                       lambda p: p["data"].update(content=p["data"]["content"].replace("亿元人民币", "亿美元")),
                       lambda p: p["data"].update(id=124),
                       lambda p: p["data"].update(source="some site"),
                       lambda p: p["data"].update(content=p["data"]["content"].replace("41,046.4", "42,046.4"))):
            payload = table()
            change(payload)
            with self.assertRaises(ValueError):
                parse_cny_payload(payload, PAGE_URL + "123")

    def test_snapshot_replay_and_missing_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = json.dumps(table()).encode("utf-8")
            rows = parse_cny_payload(table(), PAGE_URL + "123")
            save_snapshot(raw, PAGE_URL + "123", rows, root)
            result = audit_cny_snapshots(root, rows)
            self.assertEqual(result["cny_snapshot_checked_observations"], 2)
            self.assertEqual(result["cny_snapshot_errors"], [])
            rows[0]["value"] = 100
            self.assertTrue(audit_cny_snapshots(root, rows)["cny_snapshot_errors"])

    def test_recent_local_revision_wins_over_older_bundled_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root, bundled = Path(directory) / "local", Path(directory) / "bundled"
            original, revised = table(), table()
            revised["data"]["content"] = revised["data"]["content"].replace("<td>-0.7</td>", "<td>-0.8</td>")
            for payload, folder, fetched in ((original, bundled, "2026-05-01T00:00:00+00:00"),
                                              (revised, root, "2026-05-02T00:00:00+00:00")):
                rows = parse_cny_payload(payload, PAGE_URL + "123")
                save_snapshot(json.dumps(payload).encode(), PAGE_URL + "123", rows, folder)
                meta_path = next(folder.glob("*.meta.json"))
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                meta["fetched_at"] = fetched
                meta_path.write_text(json.dumps(meta), encoding="utf-8")
            latest = parse_cny_payload(revised, PAGE_URL + "123")
            self.assertEqual(audit_cny_snapshots(root, latest, bundled)["cny_snapshot_errors"], [])
            self.assertTrue(audit_cny_snapshots(root, parse_cny_payload(original, PAGE_URL + "123"), bundled)["cny_snapshot_errors"])


if __name__ == "__main__":
    unittest.main()
