"""Local, portable HTTP application for curated Chinese macroeconomic data."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterator
from urllib.parse import urlparse

import requests

from .analysis import computed_analysis, reader_summary
from .catalog import GROUPS, INDICATORS
from .collector import collect
from .quality import coverage
from .paths import DATA_ROOT

ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("CHINA_DB_PATH", str(DATA_ROOT / "macro.sqlite3")))
WEB_ROOT = ROOT / "web"
REFRESH_LOCK = threading.Lock()
ANALYZE_LOCK = threading.Lock()
AI_RECIPE_VERSION = "3"
STATE = {"refreshing": False, "analyzing": False, "last_error": "", "last_result": ""}


def load_env() -> None:
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=15)
    db.row_factory = sqlite3.Row
    try:
        with db:
            yield db
    finally:
        db.close()


def initialize() -> None:
    with connect() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS observations (
              key TEXT NOT NULL, period TEXT NOT NULL, value REAL NOT NULL,
              source_url TEXT NOT NULL, source_title TEXT NOT NULL,
              published TEXT NOT NULL DEFAULT '', fetched_at TEXT NOT NULL,
              PRIMARY KEY (key, period)
            );
            CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS analyses (
              id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
              snapshot_hash TEXT NOT NULL, content TEXT NOT NULL, model TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS observation_changes (
              id INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT NOT NULL, period TEXT NOT NULL,
              old_value REAL NOT NULL, new_value REAL NOT NULL,
              old_source_url TEXT NOT NULL, new_source_url TEXT NOT NULL,
              detected_at TEXT NOT NULL, change_type TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS ingestion_runs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              started_at TEXT NOT NULL, finished_at TEXT NOT NULL,
              kind TEXT NOT NULL, status TEXT NOT NULL,
              parsed_count INTEGER NOT NULL, added_count INTEGER NOT NULL,
              warnings_json TEXT NOT NULL
            );
        """)
        if "recipe_version" not in {row[1] for row in db.execute("PRAGMA table_info(analyses)")}:
            db.execute("ALTER TABLE analyses ADD COLUMN recipe_version TEXT NOT NULL DEFAULT '1'")
        # 2026 changed the published scope of infrastructure investment.
        # Older observations must not appear on the new-scope series.
        db.execute("""
            UPDATE observations SET key='infrastructure_ex_utilities_ytd_yoy'
            WHERE key='infrastructure_fai_ytd_yoy' AND period<'2026-01'
              AND NOT EXISTS (
                SELECT 1 FROM observations AS existing
                WHERE existing.key='infrastructure_ex_utilities_ytd_yoy'
                  AND existing.period=observations.period
              )
        """)
        db.execute("""
            DELETE FROM observations
            WHERE key='infrastructure_fai_ytd_yoy' AND period<'2026-01'
              AND EXISTS (
                SELECT 1 FROM observations AS existing
                WHERE existing.key='infrastructure_ex_utilities_ytd_yoy'
                  AND existing.period=observations.period
              )
        """)
        db.execute("""
            UPDATE observation_changes SET key='infrastructure_ex_utilities_ytd_yoy'
            WHERE key='infrastructure_fai_ytd_yoy' AND period<'2026-01'
        """)
        # Only original pre-2025 monthly reports are old M1. The 2024 new-scope
        # backcast has an annual statistical-table source and must stay separate.
        db.execute("""
            INSERT OR IGNORE INTO observations
            SELECT 'm1_legacy_yoy', period, value, source_url, source_title, published, fetched_at
            FROM observations WHERE key='m1_yoy' AND period<'2025-01'
              AND source_url NOT LIKE '%/attachDir/%'
              AND source_url NOT LIKE '%/fileDir/%'
        """)
        db.execute("""
            DELETE FROM observations WHERE key='m1_yoy' AND period<'2025-01'
              AND source_url NOT LIKE '%/attachDir/%'
              AND source_url NOT LIKE '%/fileDir/%'
        """)
        db.execute("""
            UPDATE observation_changes SET key='m1_legacy_yoy'
            WHERE key='m1_yoy' AND period<'2025-01'
              AND old_source_url NOT LIKE '%/attachDir/%'
              AND old_source_url NOT LIKE '%/fileDir/%'
              AND new_source_url NOT LIKE '%/attachDir/%'
              AND new_source_url NOT LIKE '%/fileDir/%'
        """)
        count = db.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
        demo = ROOT / "demo_data.json"
        if not count and demo.exists():
            payload = json.loads(demo.read_text(encoding="utf-8"))
            save_rows(db, payload["rows"], payload["captured_at"])
            db.execute("INSERT OR REPLACE INTO metadata VALUES ('demo_captured_at', ?)", (payload["captured_at"],))


def save_rows(db: sqlite3.Connection, rows: list[dict], fetched: str) -> None:
    # Keep one final, deterministic candidate per indicator and period.
    unique = {(row["key"], row["period"]): row for row in rows}
    for row in unique.values():
        previous = db.execute(
            "SELECT value, source_url FROM observations WHERE key=? AND period=?",
            (row["key"], row["period"]),
        ).fetchone()
        if previous and (previous["value"] != row["value"] or previous["source_url"] != row["source_url"]):
            change_type = "value_revision" if previous["value"] != row["value"] else "source_update"
            db.execute("""
                INSERT INTO observation_changes
                  (key, period, old_value, new_value, old_source_url, new_source_url, detected_at, change_type)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (row["key"], row["period"], previous["value"], row["value"],
                  previous["source_url"], row["source_url"], fetched, change_type))
    db.executemany("""
        INSERT INTO observations (key, period, value, source_url, source_title, published, fetched_at)
        VALUES (:key, :period, :value, :source_url, :source_title, :published, :fetched_at)
        ON CONFLICT(key, period) DO UPDATE SET
          value=excluded.value, source_url=excluded.source_url,
          source_title=excluded.source_title, published=excluded.published,
          fetched_at=excluded.fetched_at
    """, [{**row, "fetched_at": fetched} for row in unique.values()])


def record_run(db: sqlite3.Connection, started: str, kind: str, status: str,
               parsed_count: int, added_count: int, warnings: list[str]) -> None:
    db.execute("""
        INSERT INTO ingestion_runs
          (started_at, finished_at, kind, status, parsed_count, added_count, warnings_json)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (started, now(), kind, status, parsed_count, added_count,
          json.dumps(warnings, ensure_ascii=False)))


def refresh() -> dict:
    if not REFRESH_LOCK.acquire(blocking=False):
        return {"ok": False, "message": "数据更新正在进行中"}
    STATE["refreshing"] = True
    started = now()
    try:
        with connect() as db:
            known_cny = {(r[0], r[1]) for r in db.execute(
                "SELECT key,period FROM observations WHERE key IN ('export_yoy','import_yoy')")}
            table_periods = {r[0] for r in db.execute("""
                SELECT period FROM observations WHERE key='tsf_stock_yoy'
                  AND (source_url LIKE 'https://www.pbc.gov.cn/diaochatongjisi/attachDir/%'
                       OR source_url LIKE 'https://www.pbc.gov.cn/diaochatongjisi/fileDir/%')
            """)}
        rows, errors = collect(known_cny_periods=known_cny)
        # A failed annual-table fetch must not let an older monthly report
        # replace a previously verified table revision.
        rows = [r for r in rows if not (
            r["key"] == "tsf_stock_yoy" and r["period"] in table_periods
            and "/attachDir/" not in r["source_url"] and "/fileDir/" not in r["source_url"])]
        if not rows:
            STATE["last_error"] = "；".join(errors) or "官方页面未返回可识别的指标"
            with connect() as db:
                record_run(db, started, "refresh", "failed", 0, 0, errors or [STATE["last_error"]])
            return {"ok": False, "message": STATE["last_error"]}
        fetched = now()
        with connect() as db:
            before = db.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
            save_rows(db, rows, fetched)
            added = db.execute("SELECT COUNT(*) FROM observations").fetchone()[0] - before
            db.execute("INSERT OR REPLACE INTO metadata VALUES ('last_refresh', ?)", (fetched,))
            record_run(db, started, "refresh", "partial" if errors else "complete",
                       len(rows), added, errors)
        STATE["last_error"] = "；".join(errors)
        count = len({(row["key"], row["period"]) for row in rows})
        STATE["last_result"] = f"核验 {count} 条指标记录"
        return {"ok": True, "count": count, "warnings": errors}
    except Exception as exc:
        STATE["last_error"] = f"更新失败：{type(exc).__name__}: {exc}"
        try:
            with connect() as db:
                record_run(db, started, "refresh", "failed", 0, 0, [STATE["last_error"]])
        except sqlite3.Error:
            pass
        return {"ok": False, "message": STATE["last_error"]}
    finally:
        STATE["refreshing"] = False
        REFRESH_LOCK.release()


def dashboard() -> dict:
    with connect() as db:
        rows = [dict(row) for row in db.execute("SELECT * FROM observations ORDER BY period DESC")]
        meta = {r["key"]: r["value"] for r in db.execute("SELECT * FROM metadata")}
        analysis = db.execute("SELECT created_at, snapshot_hash, content, model, recipe_version FROM analyses ORDER BY id DESC LIMIT 1").fetchone()
        changes = [dict(row) for row in db.execute(
            "SELECT key, period, old_value, new_value, detected_at, change_type FROM observation_changes ORDER BY id DESC LIMIT 20"
        )]
        runs = [dict(row) for row in db.execute(
            "SELECT started_at, finished_at, kind, status, parsed_count, added_count, warnings_json "
            "FROM ingestion_runs ORDER BY id DESC LIMIT 10"
        )]
    for run in runs:
        run["warnings"] = json.loads(run.pop("warnings_json"))
    series = {}
    for row in rows:
        series.setdefault(row["key"], []).append(row)
    for values in series.values():
        values.sort(key=lambda item: item["period"])
    latest = {key: values[-1] for key, values in series.items() if values}
    catalog = [{"key": key, "name": spec[0], "group": spec[1], "basis": spec[2],
                "unit": spec[3], "source": spec[4], "description": spec[5]}
               for key, spec in INDICATORS.items()]
    signature = hashlib.sha256(json.dumps(
        [(r["key"], r["period"], r["value"], r["source_url"], r["source_title"], r["published"])
         for r in sorted(rows, key=lambda item: (item["key"], item["period"]))], ensure_ascii=False
    ).encode("utf-8")).hexdigest()[:16]
    recent_quality = coverage(series)
    long_quality = coverage(series, window=60)
    return {
        "catalog": catalog, "groups": GROUPS, "series": series, "latest": latest,
        "snapshot_hash": signature, "last_refresh": meta.get("last_refresh"),
        "demo_captured_at": meta.get("demo_captured_at"),
        "refreshing": STATE["refreshing"], "last_error": STATE["last_error"],
        "last_result": STATE["last_result"], "ai_ready": bool(os.getenv("DEEPSEEK_API_KEY", "").strip()),
        "ai_analyzing": STATE["analyzing"], "ai_recipe_version": AI_RECIPE_VERSION,
        "analysis": dict(analysis) if analysis else None,
        "quality": recent_quality, "quality_60m": long_quality,
        "computed_analysis": computed_analysis(series, catalog, long_quality,
                                                 recent_quality["latest_period"]),
        "reader_summary": reader_summary(series, catalog, recent_quality["latest_period"]),
        "recent_changes": changes, "ingestion_runs": runs,
    }


def analyze() -> dict:
    if STATE["refreshing"]:
        return {"ok": False, "message": "数据正在同步，请在完成后生成观察摘要。"}
    if not ANALYZE_LOCK.acquire(blocking=False):
        return {"ok": False, "message": "已有摘要正在生成，请稍候。"}
    STATE["analyzing"] = True
    try:
        return _analyze()
    finally:
        STATE["analyzing"] = False
        ANALYZE_LOCK.release()


def _analyze() -> dict:
    key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not key:
        return {"ok": False, "message": "请在 .env 中配置 DEEPSEEK_API_KEY 后重启服务。"}
    data = dashboard()
    if not data["latest"]:
        return {"ok": False, "message": "尚无可分析的数据。"}
    selected = []
    quality_by_key = {item["key"]: item for item in data["quality"]["metrics"]}
    for metric in data["catalog"]:
        values = data["series"].get(metric["key"], [])[-4:]
        if values:
            selected.append({"name": metric["name"], "basis": metric["basis"],
                             "unit": metric["unit"],
                             "coverage_24m_pct": quality_by_key[metric["key"]]["coverage_pct"],
                             "missing_24m": quality_by_key[metric["key"]]["missing"],
                             "previous_calendar_month_comparison": data["reader_summary"]["changes"].get(metric["key"]),
                             "points": [{"period": v["period"], "value": v["value"],
                                         "source": v["source_url"]} for v in values]})
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-flash")
    prompt = (
        "基于以下中国官方宏观指标，写一份约800至1500字的中文本期观察摘要。\n"
        "先给不超过80字的本期变化，再挑选4至6个有连续月份依据的具体观察。"
        "每条采用‘变化、依据、解释边界’结构，先指出读数之间的变化关系，再给两期数字和统计口径。"
        "每条只需展示本期和比较期，不再复述全部四个月；优先组合同一期、同主题的变化关系。"
        "上月比较只允许使用previous_calendar_month_comparison中delta非空的记录，"
        "不得把上一条记录冒充上个自然月；不同期别不得合并为同一期判断。"
        "准确标出指标期别和口径，覆盖率低于70%的指标仅陈述观测事实，不概括长期趋势。"
        "只比较同名指标；累计值不可直接与单月同比比较，缺失的期别不能推断。"
        "每个判断后用两个独立的[指标名·YYYY-MM]标明本期和比较期证据，指标名必须与name字段完全一致。"
        "方向只写上升、下降或持平，不机械评价好坏；增速差不等于环比增长。"
        "给定数据不包含原因证据，不生成原因猜测；解释边界指出需要哪些额外材料。"
        "正文面向经济数据读者，不提字段名、程序变量、delta、JSON、内部校验规则等实现细节；将其改写为自然语言。"
        "最后用短段说明关键缺口。不要预测、编造政策结论或投资建议。\n数据："
        + json.dumps(selected, ensure_ascii=False, separators=(",", ":"))
    )
    try:
        response = requests.post(
            "https://api.deepseek.com/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"model": model, "messages": [
                {"role": "system", "content": "你是严谨的宏观数据分析员。只依据给定数据，不把推断写成事实。"},
                {"role": "user", "content": prompt}], "stream": False, "temperature": 0.2},
            timeout=70,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"].strip()
        if not content:
            raise ValueError("模型返回空内容")
        with connect() as db:
            db.execute("INSERT INTO analyses (created_at, snapshot_hash, content, model, recipe_version) VALUES (?, ?, ?, ?, ?)",
                       (now(), data["snapshot_hash"], content, model, AI_RECIPE_VERSION))
        return {"ok": True, "content": content}
    except (requests.RequestException, KeyError, IndexError, ValueError) as exc:
        return {"ok": False, "message": f"DeepSeek 请求失败：{type(exc).__name__}。请检查密钥、余额、网络与模型名称。"}


class Handler(BaseHTTPRequestHandler):
    def send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/dashboard":
            return self.send_json(dashboard())
        if path == "/api/export.csv":
            with connect() as db:
                rows = db.execute("SELECT key, period, value, source_url, source_title, published, fetched_at FROM observations ORDER BY key, period").fetchall()
            file = io.StringIO()
            writer = csv.writer(file)
            writer.writerow(["指标代码", "指标名称", "分类", "统计口径", "期别", "数值", "单位", "来源机构", "来源标题", "来源链接", "发布或转载日期", "日期类型", "抓取时间UTC"])
            for row in rows:
                spec = INDICATORS[row["key"]]
                repost = urlparse(row["source_url"]).hostname == "fdi.mofcom.gov.cn"
                date_kind = "网页转载日期" if repost else "官方发布日期"
                source = "商务部转载海关总署" if repost else spec[4]
                writer.writerow([row["key"], spec[0], spec[1], spec[2], row["period"], row["value"], spec[3], source, row["source_title"], row["source_url"], row["published"], date_kind if row["published"] else "未核实", row["fetched_at"]])
            body = ("\ufeff" + file.getvalue()).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition", 'attachment; filename="china-macro-data.csv"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return self.wfile.write(body)
        if path == "/" or path.rstrip("/") in {"/quality", "/trends", "/data", "/insights", "/sources"}:
            path = "/index.html"
        target = (WEB_ROOT / path.lstrip("/")).resolve()
        if not target.is_relative_to(WEB_ROOT) or not target.is_file():
            return self.send_error(404)
        media = {".html": "text/html", ".css": "text/css", ".js": "text/javascript", ".svg": "image/svg+xml"}.get(target.suffix, "application/octet-stream")
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", media + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        origin = self.headers.get("Origin")
        expected_origin = f"http://{self.headers.get('Host', '')}"
        if origin and origin != expected_origin:
            return self.send_json({"ok": False, "message": "不接受跨站请求"}, 403)
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip() != "application/json":
            return self.send_json({"ok": False, "message": "请使用 JSON 请求"}, 415)
        length = int(self.headers.get("Content-Length", "0"))
        if length > 1024:
            return self.send_json({"ok": False, "message": "请求过大"}, 413)
        self.rfile.read(length)
        path = urlparse(self.path).path
        if path == "/api/refresh":
            result = refresh()
            return self.send_json(result, 200 if result["ok"] else 503)
        if path == "/api/analyze":
            result = analyze()
            return self.send_json(result, 200 if result["ok"] else 503)
        return self.send_error(404)


def periodic_refresh() -> None:
    while True:
        time.sleep(24 * 60 * 60)
        refresh()


if __name__ == "__main__":
    load_env()
    initialize()
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    print(f"中国宏观经济观察台已启动：http://{host}:{port}", flush=True)
    if os.getenv("AUTO_REFRESH", "0") != "0":
        threading.Thread(target=refresh, daemon=True).start()
        threading.Thread(target=periodic_refresh, daemon=True).start()
    ThreadingHTTPServer((host, port), Handler).serve_forever()
