"""Read-only diagnostics outside the frozen first-pilot implementation."""
from __future__ import annotations

from importlib.metadata import version
import math
from pathlib import Path
import platform
import sys

from guanlan.llm_business import load_pilot, score_plan


def type_name(value: object) -> str:
    cls = type(value)
    return f"{cls.__module__}.{cls.__qualname__}"


def typed_differences(saved: object, recomputed: object, path: str = "score") -> list[dict]:
    """Expose exact values and types; this function does not define acceptance."""
    if isinstance(saved, dict) and isinstance(recomputed, dict):
        result: list[dict] = []
        for key in sorted(saved.keys() | recomputed.keys()):
            where = f"{path}.{key}"
            if key not in saved or key not in recomputed:
                result.append({"field": where, "kind": "missing_field", "saved_present": key in saved,
                               "recomputed_present": key in recomputed})
            else:
                result.extend(typed_differences(saved[key], recomputed[key], where))
        return result
    if isinstance(saved, list) and isinstance(recomputed, list):
        result = []
        if len(saved) != len(recomputed):
            result.append({"field": path, "kind": "list_length", "saved": len(saved), "recomputed": len(recomputed)})
        for index, (left, right) in enumerate(zip(saved, recomputed)):
            result.extend(typed_differences(left, right, f"{path}[{index}]"))
        return result
    if saved == recomputed and type(saved) is type(recomputed):
        return []
    delta: int | float | None = None
    if isinstance(saved, (int, float)) and isinstance(recomputed, (int, float)) and not isinstance(saved, bool) and not isinstance(recomputed, bool):
        if math.isfinite(saved) and math.isfinite(recomputed):
            delta = recomputed - saved
    return [{"field": path, "kind": "value_or_type", "saved": saved, "recomputed": recomputed,
             "saved_type": type_name(saved), "recomputed_type": type_name(recomputed), "numeric_delta": delta}]


def environment() -> dict:
    return {"platform": platform.platform(), "machine": platform.machine(), "python": platform.python_version(),
            "implementation": platform.python_implementation(), "byteorder": sys.byteorder,
            "dependencies": {name: version(name) for name in ("numpy", "scipy", "scikit-learn", "pandas", "requests")}}


def diagnose(root: Path, run: dict) -> dict:
    manifest, _, requests, gold, store = load_pilot(root)
    if [row["id"] for row in run["records"]] != [case["id"] for case in requests]:
        raise ValueError("Diagnostic requires the complete frozen ordered run")
    targets = {row["id"]: row["expected"] for row in gold["business"]}
    cases = []
    for case, row in zip(requests, run["records"]):
        rescored = score_plan(case["question"], row["validated_plan"], targets[case["id"]], store)
        cases.append({"id": case["id"], "tool": row["validated_plan"]["tool"],
                      "exact_score_dict_equal": rescored == row["score"],
                      "differences": typed_differences(row["score"], rescored),
                      "saved_gold_status": row["score"]["status"], "recomputed_gold_status": rescored["status"],
                      "scope_matches": rescored["scope_matches"], "numbers_match": rescored["numbers_match"],
                      "evidence_ids_match": rescored["evidence_ids_match"]})
    return {"mode": "diagnostic_only_not_acceptance_or_new_execution", "environment": environment(),
            "frozen_source_input_files_verified": len(manifest["files"]), "cases": cases,
            "exact_equal_cases": sum(case["exact_score_dict_equal"] for case in cases),
            "recomputed_gold_correct_cases": sum(case["recomputed_gold_status"] == "passed" for case in cases),
            "new_live_calls": 0, "credential_reads": 0, "source_original_or_replay_writes": 0,
            "limit": "Printed diagnostics do not replace or relax the frozen score gate; original scores are never rewritten."}
