"""Frozen engineering scenarios; not LLM quality or forecasting accuracy."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import time

from china_macro.catalog import INDICATORS
from guanlan.forecast import MODEL_KEYS
from guanlan.monthly_review import (build_monthly_review, default_plan, digest, export_monthly_review,
                                    validate_plan, verify_exported_review)

ROOT = Path(__file__).resolve().parents[1]


def main():
    start = time.perf_counter()
    protocol = ROOT / "docs/MONTHLY_REVIEW_PROTOCOL.md"
    import hashlib
    protocol_hash = hashlib.sha256(protocol.read_bytes()).hexdigest()
    dataset = json.loads((ROOT / "src/china_macro/demo_data.json").read_text(encoding="utf-8"))
    results = []
    bundles = {}
    for key in MODEL_KEYS:
        definition = INDICATORS[key]
        spec = {"key": key, "name": definition[0], "basis": definition[2], "unit": definition[3]}
        source_rows = sorted([row for row in dataset["rows"] if row["key"] == key], key=lambda row: row["period"])
        for comparison, offset in [("previous_month", 1), ("previous_year", 12)]:
            bundle = build_monthly_review(spec, source_rows, comparison)
            assert bundle["model"]["passes_research_gate"] is False
            assert bundle["default_method"] == bundle["model"]["baseline"]
            latest = source_rows[-1]
            y, m = map(int, latest["period"].split("-"))
            previous_index = y * 12 + m - 1 - offset
            reference_period = f"{previous_index // 12:04d}-{previous_index % 12 + 1:02d}"
            reference = next(row for row in source_rows if row["period"] == reference_period)
            claim = next(c for c in bundle["claims"] if c["id"] == "comparison")
            assert claim["values"]["delta"] == latest["value"] - reference["value"]
            assert bundle["selection"]["reference_period"] == reference_period
            sources = {row["id"]: row for row in bundle["evidence"]}
            assert all(all(eid in sources for eid in c["evidence_ids"]) for c in bundle["claims"])
            assert all(row["source_url"] in [x["source_url"] for x in source_rows] for row in sources.values() if row["kind"] == "official_observation")
            files = export_monthly_review(bundle)
            receipt = verify_exported_review(json.loads(files["json"]))
            assert receipt["status"] == "passed" and receipt["network_requests"] == 0
            if key in bundles:
                assert bundle["model"] == bundles[key]["model"]
            else:
                bundles[key] = bundle
            results.append({"id": f"workflow:{key}:{comparison}", "status": "passed", "review_id": bundle["review_id"],
                            "ridge_gate_passed": False, "default_method": bundle["default_method"]})
    base = default_plan(bundles["cpi_yoy"])
    cases = {
        "extra_prose": {**base, "summary": "经济必然崩溃"},
        "extra_number": {**base, "value": 999},
        "invented_id": {**base, "claim_ids": [*base["claim_ids"], "invented"]},
        "missing_limits": {**base, "claim_ids": [cid for cid in base["claim_ids"] if cid != "limits"]},
        "duplicate_id": {**base, "claim_ids": [*base["claim_ids"], "latest"]},
        "stale_id": {**base, "review_id": "stale-review"},
        "wrong_type": {**base, "claim_ids": ["latest", "method", "limits", 7]},
        "arbitrary_tool": {**base, "tool": {"name": "execute_shell", "arguments": "unapproved"}},
    }
    for name, plan in cases.items():
        try: validate_plan(plan, bundles["cpi_yoy"])
        except ValueError: results.append({"id": "rejection:" + name, "status": "passed", "unsafe_plan_accepted": False})
        else: raise AssertionError("Unsafe plan accepted: " + name)
    for key, bundle in bundles.items():
        forged = copy.deepcopy(bundle)
        forged["claims"][0]["values"]["value"] += 100
        forged["review_id"] = digest({k: v for k, v in forged.items() if k != "review_id"})
        report = json.loads(export_monthly_review(forged)["json"])
        try: verify_exported_review(report)
        except ValueError: results.append({"id": "tamper:" + key, "status": "passed", "rehash_forgery_accepted": False})
        else: raise AssertionError("Rehashed forgery accepted: " + key)
    assert len(results) == 29
    result = {"status": "passed", "protocol_sha256": protocol_hash, "task_count": len(results),
              "completed_count": len(results), "unsafe_plan_accepted": 0, "rehash_forgery_accepted": 0,
              "network_model_requests": 0, "elapsed_seconds": round(time.perf_counter() - start, 3),
              "evaluation_scope": "Fixed engineering checks on already-viewed licensed data; no LLM business-quality or predictive-generalization claim.",
              "cases": results}
    (ROOT / "reports").mkdir(exist_ok=True)
    (ROOT / "reports/monthly-review-scenarios.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "cases"}, ensure_ascii=False))


if __name__ == "__main__": main()
