from guanlan.llm_replay import typed_differences
from guanlan.llm_replay import validate_tool_reference
from guanlan.llm_replay import tool_field_fingerprints
from guanlan.monthly_review import digest
from copy import deepcopy
import pytest


def test_diagnostic_prints_float_delta_and_types_without_rounding_away_failure():
    original = {"numbers": {"ridge_mae": 0.3}, "answer_id": "first_hash"}
    other_platform = {"numbers": {"ridge_mae": 0.30000000000000004}, "answer_id": "different_hash"}
    diffs = typed_differences(original, other_platform)
    assert {d["field"] for d in diffs} == {"score.numbers.ridge_mae", "score.answer_id"}
    numeric = next(d for d in diffs if d["field"] == "score.numbers.ridge_mae")
    assert numeric["numeric_delta"] > 0 and numeric["saved_type"] == numeric["recomputed_type"] == "builtins.float"
    assert original["numbers"]["ridge_mae"] == 0.3


def test_diagnostic_exposes_bool_numeric_type_confusion_and_missing_evidence():
    assert typed_differences(True, 1)[0]["saved_type"] == "builtins.bool"
    assert typed_differences({"evidence_ids": ["obs:a"]}, {"evidence_ids": []})[0]["kind"] == "list_length"
    assert typed_differences({"numbers": {"value": 1}}, {"numbers": {}})[0]["kind"] == "missing_field"


def test_reconstructed_tool_payload_is_anchored_to_first_recorded_fingerprint():
    body = {"numbers": {"value": 12.0}}
    answer = {**body, "answer_id": digest(body)}
    original = {"records": [{"id": "fixture_not_API", "score": {"answer_id": answer["answer_id"]}}]}
    reference = {"kind": "offline_reconstruction_of_first_local_tool_outputs_not_provider_response",
                 "records": [{"id": "fixture_not_API", "answer": answer}]}
    assert validate_tool_reference(original, reference)["fixture_not_API"] == answer
    for recompute_hash in (False, True):
        altered = deepcopy(reference)
        altered["records"][0]["answer"]["numbers"]["value"] = 13.0
        if recompute_hash:
            altered["records"][0]["answer"]["answer_id"] = digest({"numbers": {"value": 13.0}})
        with pytest.raises(ValueError):
            validate_tool_reference(original, altered)


def test_fingerprint_diagnostic_exposes_no_full_or_scalar_tool_values():
    payload = {"internal_field": {"numeric_value": 12345.678901234, "text_value": "unique_internal_text"}}
    nodes = tool_field_fingerprints(payload)
    assert all(set(node) == {"field", "type", "sha256"} for node in nodes)
    assert all(len(node["sha256"]) == 64 for node in nodes)
    assert all("unique_internal_text" not in str(node) and "12345.678901234" not in str(node) for node in nodes)
