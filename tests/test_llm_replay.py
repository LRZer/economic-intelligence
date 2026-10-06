from guanlan.llm_replay import typed_differences


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
