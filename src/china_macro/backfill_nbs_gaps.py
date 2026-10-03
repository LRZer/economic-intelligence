"""Fill selected NBS series from already identified official specialist reports."""

from __future__ import annotations

import argparse
import re
import time

import requests

from .app import connect, dashboard, initialize, now, record_run, save_rows
from .collector import SourceAccessBlocked, fetch
from .nbs_gap import (PRICE_MISSING_REPORTS, PRICE_SOURCE_OVERRIDES,
                     SELECTED_NBS_REPORTS, TARGETS, parse_target, save_snapshot)


def article_title(soup) -> str:
    meta = soup.find("meta", attrs={"name": re.compile(r"^ArticleTitle$", re.I)})
    if meta and meta.get("content", "").strip():
        return meta["content"].strip()
    for heading in soup.select("h1, h2"):
        title = heading.get_text(" ", strip=True)
        if title and len(title) > 8 and not re.match(r"^20\d{2}[/.-]\d{1,2}[/.-]\d{1,2}", title) and "字体" not in title:
            return title
    title = soup.title.get_text(" ", strip=True).removesuffix(" - 国家统计局") if soup.title else ""
    if not title or title == "国家统计局信息公开":
        raise ValueError("NBS article title unavailable")
    return title


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay selected NBS specialist articles for missing series")
    parser.add_argument("--reparse", action="store_true", help="Recheck all source periods for the targeted indicators")
    parser.add_argument("--allow-partial", action="store_true", help="Commit valid rows if an article is unavailable")
    args = parser.parse_args()
    initialize()
    started = now()
    data = dashboard()
    rows: list[dict] = []
    snapshots: list[tuple[bytes, dict, dict]] = []
    errors: list[str] = []
    session = requests.Session()
    for target, (reference_key, _) in TARGETS.items():
        if target == reference_key:
            continue  # These series are replayed only from PRICE_MISSING_REPORTS below.
        existing = {row["period"] for row in data["series"].get(target, [])}
        for source in data["series"].get(reference_key, []):
            period = source["period"]
            if int(period[:4]) < 2021 or (period in existing and not args.reparse):
                continue
            replacement = PRICE_SOURCE_OVERRIDES.get((target, period))
            if replacement:
                source = {**source, "source_url": replacement[0],
                          "source_title": replacement[1], "published": replacement[2]}
            try:
                soup, raw = fetch(session, source["source_url"], include_raw=True)
                parsed = parse_target(soup, source, target)
                if parsed is None:
                    errors.append(f"国家统计局：{target} {period} 已收录报告中没有可确认数值")
                else:
                    snapshots.append((raw, source, parsed))
                    rows.append(parsed)
            except SourceAccessBlocked:
                errors.append(f"国家统计局：{target} {period} 遇到访问验证；暂停本次回填")
                break
            except (requests.RequestException, UnicodeError, ValueError, TypeError) as exc:
                errors.append(f"国家统计局：{target} {period} 获取或解析失败（{type(exc).__name__}）")
            time.sleep(0.4)
    for kind, period, url, title, published in PRICE_MISSING_REPORTS:
        keys = (f"{kind}_yoy", f"{kind}_mom")
        missing = [key for key in keys if args.reparse or not any(
            row["period"] == period for row in data["series"].get(key, []))]
        if not missing:
            continue
        source = {"period": period, "source_url": url,
                  "source_title": title, "published": published}
        try:
            soup, raw = fetch(session, url, include_raw=True)
            for key in missing:
                parsed = parse_target(soup, source, key)
                if parsed is None:
                    errors.append(f"国家统计局：{key} {period} 专题报告中没有可确认数值")
                else:
                    snapshots.append((raw, source, parsed))
                    rows.append(parsed)
        except SourceAccessBlocked:
            errors.append(f"国家统计局：{kind} {period} 遇到访问验证；暂停本次回填")
            break
        except (requests.RequestException, UnicodeError, ValueError, TypeError) as exc:
            errors.append(f"国家统计局：{kind} {period} 获取或解析失败（{type(exc).__name__}）")
        time.sleep(0.4)
    for period, url, published, kind, keys in SELECTED_NBS_REPORTS:
        missing = [key for key in keys if args.reparse or not any(
            row["period"] == period for row in data["series"].get(key, []))]
        if not missing:
            continue
        try:
            soup, raw = fetch(session, url, include_raw=True)
            source = {"period": period, "source_url": url,
                      "source_title": article_title(soup), "published": published}
            for key in missing:
                parsed = parse_target(soup, source, key)
                if parsed is None:
                    errors.append(f"国家统计局：{key} {period} 精选报告中没有可确认数值")
                else:
                    snapshots.append((raw, source, parsed))
                    rows.append(parsed)
        except SourceAccessBlocked:
            errors.append(f"国家统计局：{kind} {period} 遇到访问验证；暂停本次回填")
            break
        except (requests.RequestException, UnicodeError, ValueError, TypeError) as exc:
            errors.append(f"国家统计局：{kind} {period} 获取或解析失败（{type(exc).__name__}）")
        time.sleep(0.4)
    if errors and not args.allow_partial:
        with connect() as db:
            record_run(db, started, "nbs_gap_backfill", "rejected", len(rows), 0, errors)
        raise SystemExit(f"NBS gap backfill had {len(errors)} errors; database unchanged. "
                         + "; ".join(errors[:3]))
    if not rows:
        print("No new targeted NBS observations")
        return
    for raw, source, parsed in snapshots:
        save_snapshot(raw, source, parsed)
    with connect() as db:
        before = db.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
        save_rows(db, rows, now())
        after = db.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
        record_run(db, started, "nbs_gap_backfill", "partial" if errors else "complete",
                   len(rows), after-before, errors)
    print(f"Parsed {len(rows)} targeted NBS observations; added {after-before}; warnings {len(errors)}")
    for error in errors[:10]:
        print(" -", error)


if __name__ == "__main__":
    main()
