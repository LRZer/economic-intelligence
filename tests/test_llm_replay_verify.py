"""Synthetic negative examples test engineering guards, not actual LLM performance."""
from copy import deepcopy
import json
import math
from pathlib import Path

import pytest

from guanlan.llm_replay_verify import (ABS_TOL, FIRST_MANIFEST_SHA, FIRST_REPLAY_SHA, POLICY,
                                     check_case, check_envelope, check_numbers, read_bounded_json, semantic_digest)
from guanlan.monthly_review import digest


def fixture_case():
    target = {"key": "fixture", "tool": "evaluation", "periods": [], "numbers": {"ridge_mae": 0.3, "test_n": 12},
              "evidence_ids": ["model:fixture:fixed_input"]}
    plan = {"snapshot_hash": "fixture", "key": "fixture", "tool": "evaluation", "periods": [], "direction": "max"}
    body = {"status": "answered", "scope": {k: target[k] for k in ("key", "tool", "periods")}, "tool_plan": plan,
            "numbers": target["numbers"].copy(), "evidence": [{"id": target["evidence_ids"][0], "model": {
                "baseline": "persistence", "passes_research_gate": False, "test_n": 12, "test_start": "2025-09",
                "backtest": [{"actual": 2.0, "ridge": 2.000123456123, "train_end": "2025-08"}],
                "forecast": {"period": "2026-09", "ridge": 1.0, "baseline": 2.0, "contributions": {"feature": 0.3}}}}],
            "retrieval": {"ranking": [{"score": 0.3}]}, "trace": {"numbers": target["numbers"].copy()}}
    answer = {**body, "answer_id": digest(body)}
    score = {"status": "passed", "scope_matches": True, "numbers_match": True, "evidence_ids_match": True,
             "numbers": target["numbers"].copy(), "evidence_ids": target["evidence_ids"].copy(), "answer_id": answer["answer_id"]}
    row = {"id": "synthetic_fixture_not_API", "status": "passed", "validated_plan": plan, "score": score}
    contract = {"id": row["id"], "original_answer_id": score["answer_id"], "canonical_semantic_sha256": semantic_digest(answer)}
    return row, target, contract, answer


def rehash(answer):
    answer["answer_id"] = digest({k: v for k, v in answer.items() if k != "answer_id"})
    return answer


def test_model_float_neighbor_preserves_semantics_and_reports_original_identity_false():
    row, target, contract, original = fixture_case()
    other = deepcopy(original)
    other["evidence"][0]["model"]["forecast"]["contributions"]["feature"] = math.nextafter(0.3, math.inf)
    rehash(other)
    result = check_case(row, target, contract, other)
    assert result["full_tool_semantics_passed"] and result["exact_reported_numbers_equal"]
    assert not result["exact_output_fingerprint_equal"] and not result["exact_score_dict_equal"]
    assert original["answer_id"] == row["score"]["answer_id"]


@pytest.mark.parametrize("tamper", ["derived_beyond_grid", "official_value", "baseline", "gate", "cutoff", "evidence", "scope", "count_type", "retrieval", "extra_field", "invalid_hash"])
def test_full_semantics_rejects_actual_errors_even_if_new_hash_is_recomputed(tamper):
    row, target, contract, answer = fixture_case()
    if tamper == "derived_beyond_grid": answer["evidence"][0]["model"]["forecast"]["contributions"]["feature"] += 1e-8
    elif tamper == "official_value": answer["evidence"][0]["model"]["backtest"][0]["actual"] += 1e-12
    elif tamper == "baseline": answer["evidence"][0]["model"]["baseline"] = "seasonal"
    elif tamper == "gate": answer["evidence"][0]["model"]["passes_research_gate"] = True
    elif tamper == "cutoff": answer["evidence"][0]["model"]["backtest"][0]["train_end"] = "2025-09"
    elif tamper == "evidence": answer["evidence"][0]["id"] = "unapproved"
    elif tamper == "scope": answer["scope"]["key"] = "other_indicator"
    elif tamper == "count_type": answer["numbers"]["test_n"] = 12.0
    elif tamper == "retrieval": answer["retrieval"]["ranking"][0]["score"] = math.nextafter(0.3, math.inf)
    elif tamper == "extra_field": answer["unverified"] = "extra"
    rehash(answer)
    if tamper == "invalid_hash": answer["answer_id"] = "0" * 64
    with pytest.raises(ValueError): check_case(row, target, contract, answer)


@pytest.mark.parametrize("tamper", ["numeric_error", "unsupported_evidence", "false_flag", "integer_flag", "new_answer_id", "extra_score_field"])
def test_original_score_or_evidence_tampering_is_not_treated_as_platform_variance(tamper):
    row, target, contract, answer = fixture_case()
    if tamper == "numeric_error": row["score"]["numbers"]["ridge_mae"] += 1e-5
    elif tamper == "unsupported_evidence": row["score"]["evidence_ids"] = ["unsupported"]
    elif tamper == "false_flag": row["score"]["numbers_match"] = False
    elif tamper == "integer_flag": row["score"]["scope_matches"] = 1
    elif tamper == "new_answer_id": row["score"]["answer_id"] = "0" * 64
    elif tamper == "extra_score_field": row["score"]["hidden"] = True
    with pytest.raises(ValueError): check_case(row, target, contract, answer)


@pytest.mark.parametrize("invalid", [True, "0.3", float("nan"), float("inf"), 0.30000001])
def test_unchanged_frozen_number_rule_rejects_types_nonfinite_and_out_of_tolerance(invalid):
    with pytest.raises(ValueError): check_numbers({"x": 0.3}, {"x": invalid}, {"x": 0.3})
    assert ABS_TOL == 1e-9


def test_exact_integer_count_and_quantization_boundary_are_not_relaxed():
    with pytest.raises(ValueError): check_numbers({"n": 12}, {"n": 12.0}, {"n": 12})
    first = {"evidence": [{"model": {"forecast": {"ridge": 0.300000000499}}}]}
    other = {"evidence": [{"model": {"forecast": {"ridge": 0.300000000501}}}]}
    assert abs(other["evidence"][0]["model"]["forecast"]["ridge"] - first["evidence"][0]["model"]["forecast"]["ridge"]) < 1e-9
    assert semantic_digest(first) != semantic_digest(other)


def envelope_fixture():
    ids = [f"synthetic{i}" for i in range(12)]
    run = {"mode": "live_user_triggered", "status": "complete", "protocol_manifest_sha256": FIRST_MANIFEST_SHA,
           "planned_requests": 12, "records": [{"id": case} for case in ids], "automatic_retry": False,
           "input_usd_per_million": "0.30", "output_usd_per_million": "1.20", "local_cap_usd": "0.03"}
    contract = {"kind": "compact_semantic_fingerprints_anchored_to_first_tool_outputs", "original_replay_sha256": FIRST_REPLAY_SHA,
                "original_manifest_sha256": FIRST_MANIFEST_SHA, "records": [{"id": case} for case in ids], "policy": deepcopy(POLICY)}
    return run, [{"id": case} for case in ids], contract


@pytest.mark.parametrize("tamper", ["incomplete", "order", "retry", "cap", "model_manifest", "policy"])
def test_first_run_completeness_order_budget_and_policy_cannot_be_relaxed(tamper):
    run, cases, contract = envelope_fixture()
    if tamper == "incomplete": run["records"].pop()
    elif tamper == "order": run["records"].reverse()
    elif tamper == "retry": run["automatic_retry"] = True
    elif tamper == "cap": run["local_cap_usd"] = "0.04"
    elif tamper == "model_manifest": run["protocol_manifest_sha256"] = "0" * 64
    elif tamper == "policy": contract["policy"]["business_numeric_abs_tol"] = 1.0
    with pytest.raises(ValueError): check_envelope(run, cases, contract)


@pytest.mark.parametrize("content", ['{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}', '[]'])
def test_replay_json_duplicate_fields_and_nonfinite_are_rejected(tmp_path, content):
    path = tmp_path / "synthetic.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError): read_bounded_json(path)


def test_published_first_replay_and_semantic_contract_verify_without_network(monkeypatch):
    from unittest.mock import patch
    from guanlan.llm_replay_verify import verify_first_replay
    root = Path(__file__).resolve().parents[1]
    replay = root / "docs/validation/llm-business-first-run-replay.json"
    contract = root / "docs/validation/llm-business-portable-semantics.json"
    before = replay.read_bytes()
    with patch("socket.socket.connect", side_effect=AssertionError("No network")), patch("requests.Session.request", side_effect=AssertionError("No HTTP")), patch("getpass.getpass", side_effect=AssertionError("No credential")):
        result = verify_first_replay(root, replay, contract)
    assert result["correct_business_cases"] == 12 and result["full_tool_semantics_gate_passed"]
    assert result["new_live_calls"] == result["credential_reads"] == 0 and replay.read_bytes() == before
