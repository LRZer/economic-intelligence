"""Independent first-run portability checks; frozen scoring and records stay intact."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_EVEN, localcontext
import hashlib
import json
import math
from pathlib import Path
import re

from guanlan.assistant_plans import execute_tool_plan
from guanlan.llm_business import COUNT, cost_bound, load_pilot, sha, usage_cost
from guanlan.llm_replay import environment
from guanlan.monthly_review import canonical, digest

FIRST_MANIFEST_SHA = "687dea3224e0f002485093afa36948fa783578344d7b85e094c66f4a54390a1f"
FIRST_REPLAY_SHA = "471adcb9402d3ee4c1fa5c6bc61b8e8ef6c83954c70c1ea21d8971facd7aa8bf"
REL_TOL = ABS_TOL = 1e-9  # The unchanged frozen score_plan rule, not fitted to Linux differences.
GRID = Decimal("0.000000001")
_DERIVED = re.compile(
    r"answer\.evidence\[\d+\]\.model\.(?:"
    r"backtest\[\d+\]\.ridge|metrics\.(?:validation|test)\.(?:ridge|persistence|seasonal)\.[^.]+|"
    r"paired_mae_difference_95\[\d+\]|interval_radius|test_interval_coverage|"
    r"forecast\.(?:ridge|lower|upper|intercept|contributions\.[^.]+))$"
)
_ANSWER_NUMBERS = re.compile(r"answer\.(?:numbers|trace\.numbers)\.(?:ridge_mae|persistence_mae|seasonal_mae|experimental)$")
POLICY = {
    "version": "first-run-full-tool-semantics-v1",
    "business_numeric_rel_tol": REL_TOL,
    "business_numeric_abs_tol": ABS_TOL,
    "derived_model_float_grid": str(GRID),
    "rounding": "Decimal.from_float / ROUND_HALF_EVEN",
    "allowed_derived_paths_regex": [_DERIVED.pattern, _ANSWER_NUMBERS.pattern],
    "all_other_floats": "exact IEEE-754 hexadecimal representation",
    "all_types_structure_sources_scope_counts_decisions_and_text": "exact",
    "original_top_answer_id": "retained and reported separately; anchored by fixed original replay SHA",
    "maximum_equal_grid_bucket_span": "strictly less than 1e-9; boundary crossings can reject close values",
}
SCORE_FIELDS = {"status", "scope_matches", "numbers_match", "evidence_ids_match", "numbers", "evidence_ids", "answer_id"}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def semantic_tree(value: object, path: str = "answer") -> object:
    """Canonicalize only predeclared derived model floats; retain all other semantics."""
    if isinstance(value, dict):
        return {key: semantic_tree(item, f"{path}.{key}") for key, item in value.items()
                if not (path == "answer" and key == "answer_id")}
    if isinstance(value, list):
        return [semantic_tree(item, f"{path}[{i}]") for i, item in enumerate(value)]
    if type(value) is float:
        require(math.isfinite(value), f"Non-finite tool field: {path}")
        if _DERIVED.fullmatch(path) or _ANSWER_NUMBERS.fullmatch(path):
            with localcontext() as context:
                context.prec = 400
                rounded = Decimal.from_float(value).quantize(GRID, rounding=ROUND_HALF_EVEN)
            if rounded == 0:
                rounded = abs(rounded)
            return {"derived_float_9dp": format(rounded, "f")}
        return {"exact_float_hex": value.hex()}
    require(value is None or type(value) in (str, int, bool), f"Non-JSON tool field: {path}")
    return value


def semantic_digest(answer: dict) -> str:
    return digest(semantic_tree(answer))


def check_numbers(saved: dict, recomputed: dict, gold: dict) -> None:
    require(saved.keys() == recomputed.keys() == gold.keys(), "Numeric fields differ")
    for key, target in gold.items():
        left, right = saved[key], recomputed[key]
        if type(target) is int:
            require(type(left) is int and type(right) is int and left == right == target, f"Count or integer differs: {key}")
        else:
            require(type(target) is float and type(left) is float and type(right) is float, f"Numeric type differs: {key}")
            require(all(math.isfinite(v) for v in (left, right, target)), f"Non-finite numeric field: {key}")
            require(math.isclose(left, target, rel_tol=REL_TOL, abs_tol=ABS_TOL)
                    and math.isclose(right, target, rel_tol=REL_TOL, abs_tol=ABS_TOL)
                    and math.isclose(left, right, rel_tol=REL_TOL, abs_tol=ABS_TOL), f"Frozen numeric tolerance exceeded: {key}")


def check_case(row: dict, target: dict, contract_case: dict, answer: dict) -> dict:
    saved = row["score"]
    require(set(saved) == SCORE_FIELDS, "Saved score schema differs")
    require(saved["status"] == "passed" and row["status"] == "passed", "Original business score is not passed")
    for field in ("scope_matches", "numbers_match", "evidence_ids_match"):
        require(type(saved[field]) is bool and saved[field] is True, f"Saved flag is not true boolean: {field}")
    require(contract_case["id"] == row["id"] and contract_case["original_answer_id"] == saved["answer_id"], "First output fingerprint changed")
    require(bool(re.fullmatch(r"[0-9a-f]{64}", saved["answer_id"])), "Invalid saved output fingerprint")
    require(answer["answer_id"] == digest({k: v for k, v in answer.items() if k != "answer_id"}), "Recomputed output fingerprint invalid")
    require(answer["status"] == "answered", "Tool did not answer")
    scope = answer["scope"]
    require(all(scope[key] == target[key] for key in ("key", "tool", "periods")), "Business scope differs")
    require(answer["tool_plan"] == row["validated_plan"], "Validated plan differs from executed plan")
    actual_ids = [entry["id"] for entry in answer["evidence"]]
    expected_ids = sorted(target["evidence_ids"])
    require(len(actual_ids) == len(set(actual_ids)) and sorted(actual_ids) == saved["evidence_ids"] == expected_ids,
            "Source or evidence IDs differ")
    check_numbers(saved["numbers"], answer["numbers"], target["numbers"])
    require(semantic_digest(answer) == contract_case["canonical_semantic_sha256"],
            "Full tool semantics differ: source/type/scope/decision/metadata or derived float bucket")
    fresh_score = {"status": "passed", "scope_matches": True, "numbers_match": True,
                   "evidence_ids_match": True, "numbers": answer["numbers"], "evidence_ids": expected_ids,
                   "answer_id": answer["answer_id"]}
    return {"id": row["id"], "business_scope_numbers_evidence_passed": True, "full_tool_semantics_passed": True,
            "original_output_fingerprint_preserved": True, "exact_score_dict_equal": fresh_score == saved,
            "exact_reported_numbers_equal": answer["numbers"] == saved["numbers"],
            "exact_output_fingerprint_equal": answer["answer_id"] == saved["answer_id"]}


def check_envelope(run: dict, requests: list[dict], contract: dict) -> tuple[Decimal, Decimal, Decimal]:
    require(run["mode"] == "live_user_triggered" and run["status"] == "complete", "Not a completed first recorded run")
    require(run["protocol_manifest_sha256"] == FIRST_MANIFEST_SHA, "First source/input manifest differs")
    require(type(run["planned_requests"]) is int and run["planned_requests"] == COUNT and len(run["records"]) == COUNT,
            "First-run denominator is not exactly 12")
    require(run["automatic_retry"] is False, "Original automatic retry field differs")
    require([row["id"] for row in run["records"]] == [case["id"] for case in requests]
            == [row["id"] for row in contract["records"]], "First ordered cases differ")
    require(contract["kind"] == "compact_semantic_fingerprints_anchored_to_first_tool_outputs"
            and contract["original_replay_sha256"] == FIRST_REPLAY_SHA
            and contract["original_manifest_sha256"] == FIRST_MANIFEST_SHA, "Semantic contract provenance differs")
    require(canonical(contract["policy"]) == canonical(POLICY), "Semantic policy changed")
    input_rate, output_rate, cap = (Decimal(run[key]) for key in ("input_usd_per_million", "output_usd_per_million", "local_cap_usd"))
    require(input_rate == Decimal("0.30") and output_rate == Decimal("1.20") and cap == Decimal("0.03"), "Original reviewed rates or cap differ")
    require(COUNT * cost_bound(input_rate, output_rate) <= cap, "Frozen complete-request budget exceeds cap")
    return input_rate, output_rate, cap


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    obj = {}
    for key, value in pairs:
        require(key not in obj, "Duplicate JSON field")
        obj[key] = value
    return obj


def _reject_nonfinite(value: str) -> object:
    raise ValueError(f"Non-finite JSON token: {value}")


def read_bounded_json(path: Path) -> dict:
    require(path.stat().st_size <= 2 * 1024 * 1024, "Evidence file exceeds bound")
    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object, parse_constant=_reject_nonfinite)
    require(type(value) is dict, "Evidence root must be an object")
    return value


def verify_first_replay(root: Path, run_path: Path, contract_path: Path) -> dict:
    require(sha(run_path) == FIRST_REPLAY_SHA, "Published original replay bytes changed")
    require(sha(root / "evaluation/llm-business-pilot-v1/manifest.json") == FIRST_MANIFEST_SHA, "Frozen original manifest changed")
    run, contract = read_bounded_json(run_path), read_bounded_json(contract_path)
    manifest, _, requests, gold, store = load_pilot(root)
    input_rate, output_rate, cap = check_envelope(run, requests, contract)
    targets = {row["id"]: row["expected"] for row in gold["business"]}
    checks = []
    total = Decimal(0)
    for request, row, expected_contract in zip(requests, run["records"], contract["records"]):
        payload_hash = hashlib.sha256(json.dumps(request["request"], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        require(row["request_payload_sha256"] == payload_hash, "Original request payload differs")
        require(type(row["http_status"]) is int and row["http_status"] == 200, "Original HTTP status differs")
        require(row["served_model"] == "deepseek-flash", "Original served-model alias differs")
        _, cost = usage_cost(row["usage"], input_rate, output_rate)
        require(Decimal(row["conservative_usage_usd"]) == cost, "Original per-case usage cost differs")
        total += cost
        answer = json.loads(canonical(execute_tool_plan(request["question"], row["validated_plan"], store)))
        checks.append(check_case(row, targets[row["id"]], expected_contract, answer))
    require(total == Decimal(run["cost_upper_estimate_usd"]) and total <= cap, "Original total usage cost differs")
    return {"mode": "portable_semantic_verification_of_saved_first_run_not_new_execution", "status": "passed",
            "pipeline_business_gate_passed": True, "full_tool_semantics_gate_passed": True,
            "planned_requests": COUNT, "verified_cases": len(checks), "correct_business_cases": len(checks),
            "exact_score_dict_matches": sum(row["exact_score_dict_equal"] for row in checks),
            "exact_reported_numeric_case_matches": sum(row["exact_reported_numbers_equal"] for row in checks),
            "original_frozen_exact_identity_gate_passed_on_this_platform": all(row["exact_score_dict_equal"] for row in checks),
            "original_replay_sha256": FIRST_REPLAY_SHA, "original_manifest_sha256": FIRST_MANIFEST_SHA,
            "source_and_input_frozen_files_verified": len(manifest["files"]), "semantic_contract_sha256": sha(contract_path),
            "semantic_policy": POLICY, "cases": checks, "environment": environment(),
            "conservative_usage_cost_usd_not_invoice": str(total), "new_live_calls": 0, "credential_reads": 0,
            "original_or_source_files_rewritten": False,
            "limit": "This separately reports original bit identity and full tool semantics. Small seen pilot, alias-only model, no provider attestation, no new AI quality evaluation."}
