import copy
import csv
import io
import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from china_macro.catalog import INDICATORS
from guanlan.forecast import MODEL_KEYS, month_id, period_label
from guanlan.monthly_review import (build_monthly_review, build_review_payload, canonical, default_plan,
                                    digest, export_monthly_review, selected_claims, validate_plan,
                                    verify_exported_review, verify_monthly_review)

ROOT = Path(__file__).resolve().parents[1]


def spec(key="cpi_yoy"):
    definition = INDICATORS[key]
    return {"key": key, "name": definition[0], "basis": definition[2], "unit": definition[3]}


def synthetic_rows(values):
    start = month_id("2020-01")
    return [{"period": period_label(start + i), "value": value,
             "source_url": "https://www.stats.gov.cn/synthetic-fixture-not-an-observation"} for i, value in enumerate(values)]


@pytest.fixture(scope="module")
def bundles():
    rows = json.loads((ROOT / "src/china_macro/demo_data.json").read_text(encoding="utf-8"))["rows"]
    return {key: build_monthly_review(spec(key), [row for row in rows if row["key"] == key]) for key in MODEL_KEYS}


@pytest.mark.parametrize("values,expected,direction", [([1., 2.], 1., "上升"), ([2., 1.], -1., "下降"), ([1., 1.], 0., "持平")])
def test_reading_delta_is_arithmetic_not_growth_rate(values, expected, direction):
    bundle = build_monthly_review(spec(), synthetic_rows(values))
    claim = next(c for c in bundle["claims"] if c["id"] == "comparison")
    assert claim["values"]["delta"] == expected
    assert claim["values"]["direction"] == direction
    assert claim["values"]["unit"] == "百分点"
    assert len(claim["evidence_ids"]) == 2
    assert "重新计算增长率" in claim["text"]


def test_missing_natural_month_does_not_substitute_last_observation():
    rows = synthetic_rows([1., 2., 3.])
    bundle = build_monthly_review(spec(), [rows[0], rows[2]])
    claim = next(c for c in bundle["claims"] if c["id"] == "comparison")
    assert claim["kind"] == "unavailable" and claim["values"]["delta"] is None
    assert bundle["default_method"] == "unavailable"
    assert not any(c["kind"] == "model_forecast" for c in bundle["claims"])


@pytest.mark.parametrize("bad", ["empty", "duplicate", "nan", "inf", "boolean", "wrong_key", "wrong_basis", "wrong_name", "spoof_host", "http", "user_info"])
def test_invalid_inputs_stop_before_any_model_fit(bad):
    rows, definition = synthetic_rows([1., 2.]), spec()
    if bad == "empty": rows = []
    if bad == "duplicate": rows.append(rows[0])
    if bad == "nan": rows[0]["value"] = float("nan")
    if bad == "inf": rows[0]["value"] = float("inf")
    if bad == "boolean": rows[0]["value"] = True
    if bad == "wrong_key": rows[0]["key"] = "ppi_yoy"
    if bad == "wrong_basis": definition["basis"] = "累计金额"
    if bad == "wrong_name": definition["name"] = "模型证明经济危机"
    if bad == "spoof_host": rows[0]["source_url"] = "https://www.stats.gov.cn.evil.invalid/"
    if bad == "http": rows[0]["source_url"] = "http://www.stats.gov.cn/"
    if bad == "user_info": rows[0]["source_url"] = "https://secret@www.stats.gov.cn/"
    with patch("guanlan.monthly_review.analyze_series") as fit, pytest.raises(ValueError):
        build_monthly_review(definition, rows)
    fit.assert_not_called()


def test_real_snapshot_all_models_keep_original_failed_gates_and_default_references(bundles):
    for key, bundle in bundles.items():
        model = bundle["model"]
        assert model["status"] == "evaluated" and model["passes_research_gate"] is False
        assert bundle["default_method"] == model["baseline"]
        claims = {c["id"]: c for c in bundle["claims"]}
        assert claims["method"]["values"]["baseline_selection_split"] == "validation"
        assert "未通过" in claims["method"]["text"]
        assert claims["interval"]["values"]["applies_to"] == "ridge"
        assert claims["forecast"]["values"]["period"] > claims["forecast"]["values"]["train_end"]
        assert bundle["anomaly"]["train_end"] < bundle["anomaly"]["period"]
        assert bundle["network_requests"] == 0


def bad_plans(bundle):
    base = default_plan(bundle)
    return [
        {**base, "summary": "经济必然崩溃"},
        {**base, "value": 999},
        {**base, "claim_ids": [*base["claim_ids"], "invented"]},
        {**base, "claim_ids": [cid for cid in base["claim_ids"] if cid != "limits"]},
        {**base, "claim_ids": [*base["claim_ids"], "latest"]},
        {**base, "review_id": "stale-review"},
        {**base, "claim_ids": ["latest", "method", "limits", 7]},
        {**base, "tool": {"name": "execute_shell", "arguments": "unapproved"}},
    ]


@pytest.mark.parametrize("index", range(8))
def test_untrusted_or_contradictory_plans_rejected_without_displayed_prose(bundles, index):
    bundle = bundles["cpi_yoy"]
    with pytest.raises(ValueError): validate_plan(bad_plans(bundle)[index], bundle)


def test_plan_can_select_and_order_but_cannot_hide_method_or_limits(bundles):
    bundle = bundles["cpi_yoy"]
    plan = {"review_id": bundle["review_id"], "claim_ids": ["limits", "latest", "method"]}
    claims = selected_claims(bundle, plan)
    assert [c["id"] for c in claims] == plan["claim_ids"]
    assert claims[-1] == next(c for c in bundle["claims"] if c["id"] == "method")
    other = build_monthly_review(spec(), bundle["source_rows"], "previous_year")
    assert bundle["model"] == other["model"]
    with pytest.raises(ValueError): validate_plan(plan, other)


def test_input_fingerprint_includes_sources_and_indicator_and_ignores_private_fields(bundles):
    bundle = bundles["cpi_yoy"]
    rows = [{**r, "private_note": "must-not-appear"} for r in reversed(bundle["source_rows"])]
    same = build_monthly_review({**spec(), "private_field": "hidden"}, rows)
    assert same == bundle and "must-not-appear" not in canonical(same).decode()
    rows[0]["source_url"] = "https://www.stats.gov.cn/changed-source"
    changed = build_monthly_review(spec(), rows)
    assert changed["model_snapshot_hash"] == bundle["model_snapshot_hash"]
    assert changed["input_sha256"] != bundle["input_sha256"]
    assert changed["review_id"] != bundle["review_id"]


def test_export_round_trip_csv_dependencies_and_offline_html(bundles):
    bundle = bundles["cpi_yoy"]
    files = export_monthly_review(bundle)
    report = json.loads(files["json"])
    receipt = verify_exported_review(report)
    assert receipt["models_recomputed"] and receipt["status"] == "passed"
    document = files["html"].decode()
    assert "<script" not in document.lower()
    assert bundle["review_id"] in document and report["report_id"] in document
    csv_rows = list(csv.DictReader(io.StringIO(files["csv"].decode("utf-8-sig"))))
    assert len(csv_rows) == len(bundle["claims"])
    evidence = {row["id"] for row in bundle["evidence"]}
    assert all(set(json.loads(row["evidence_ids_json"])) <= evidence for row in csv_rows)


def test_rehashed_forgery_still_rejected_by_model_and_claim_recomputation(bundles):
    forged = copy.deepcopy(bundles["cpi_yoy"])
    forged["claims"][0]["values"]["value"] += 100
    forged["review_id"] = digest({k: v for k, v in forged.items() if k != "review_id"})
    with pytest.raises(ValueError, match="重算"):
        verify_monthly_review(forged)
    forged = copy.deepcopy(bundles["cpi_yoy"])
    forged["model"]["metrics"]["test"]["ridge"]["mae"] = 0
    forged["review_id"] = digest({k: v for k, v in forged.items() if k != "review_id"})
    with pytest.raises(ValueError): verify_monthly_review(forged)


@pytest.mark.parametrize("malformed", [None, [], {}, {"bundle": []}, {"schema_version": "wrong"}])
def test_malformed_reports_fail_cleanly(malformed):
    with pytest.raises((ValueError, TypeError)):
        verify_exported_review(malformed)


def test_prepare_payload_is_offline_and_sends_only_approved_claim_catalog(bundles):
    with patch("requests.post") as post:
        payload = build_review_payload(bundles["cpi_yoy"])
    post.assert_not_called()
    assert payload["max_tokens"] == 400 and payload["thinking"] == {"type": "disabled"}
    material = json.loads(payload["messages"][1]["content"])
    assert set(material) == {"review_id", "required_claim_ids", "claims"}
    assert "source_rows" not in material


def test_optional_api_requires_separate_opt_in_and_explicit_key_and_one_mock_request(monkeypatch, bundles):
    from guanlan.ai import generate_review_plan
    bundle = bundles["cpi_yoy"]
    monkeypatch.delenv("ENABLE_PAID_AI", raising=False)
    with patch("guanlan.ai.requests.post") as post, pytest.raises(ValueError, match="默认关闭"):
        generate_review_plan(bundle, api_key="unit-test-placeholder")
    post.assert_not_called()
    monkeypatch.setenv("ENABLE_PAID_AI", "1")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "must-not-be-looked-up")
    with patch("guanlan.ai.requests.post") as post, pytest.raises(ValueError, match="显式"):
        generate_review_plan(bundle)
    post.assert_not_called()
    response = Mock(status_code=200)
    response.json.return_value = {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(default_plan(bundle))}}]}
    with patch("guanlan.ai.requests.post", return_value=response) as post:
        assert generate_review_plan(bundle, api_key="unit-test-placeholder") == default_plan(bundle)
    assert post.call_count == 1 and post.call_args.kwargs["allow_redirects"] is False
    assert "unit-test-placeholder" not in json.dumps(post.call_args.kwargs["json"])
    response.json.return_value["choices"][0]["message"]["content"] = json.dumps(bad_plans(bundle)[0])
    with patch("guanlan.ai.requests.post", return_value=response), pytest.raises(ValueError, match="未通过"):
        generate_review_plan(bundle, api_key="unit-test-placeholder")
