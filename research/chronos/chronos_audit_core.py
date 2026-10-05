"""Existing-dependency scaffolding. No Chronos import, download or actual-model CLI."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
import json
import math
from typing import Callable, Protocol

import numpy as np

from guanlan.forecast import features, month_id, new_model, period_label

KEYS = ("cpi_yoy", "ppi_yoy", "cpi_mom", "ppi_mom", "manufacturing_pmi",
        "manufacturing_new_orders_pmi", "nonmanufacturing_pmi")
BASELINES = ("persistence", "seasonal", "drift", "ridge")
VERSION = "chronos-synth-retrospective-preparation-v1"


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                      separators=(",", ":")).encode("utf-8")


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


@dataclass(frozen=True)
class Context:
    indicator: str
    target_period: str
    issue_date: str
    periods: tuple[str, ...]
    values: tuple[float, ...]
    source_rows_hash: str


@dataclass(frozen=True)
class Quantiles:
    p10: float
    p50: float
    p90: float

    def validate(self) -> None:
        values = (self.p10, self.p50, self.p90)
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
            raise ValueError("Non-finite or invalid model quantile")
        if not self.p10 <= self.p50 <= self.p90:
            raise ValueError("Crossed quantiles; no sorting repair permitted")


class Predictor(Protocol):
    identity: str

    def predict(self, context: Context) -> Quantiles: ...


def validate_rows(rows: list[dict], *, fixture: bool = False) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {key: [] for key in KEYS}
    for row in rows:
        key = row.get("key")
        if key not in grouped:
            continue
        month_id(row["period"])
        value = row["value"]
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError("Invalid observed number")
        date.fromisoformat(row["published"])
        url = row["source_url"]
        if not isinstance(url, str) or not url.startswith("https://www.stats.gov.cn/"):
            if not fixture or not isinstance(url, str) or not url.startswith("fixture://"):
                raise ValueError("Source outside the approved snapshot")
        grouped[key].append({"key": key, "period": row["period"], "value": float(value),
                             "published": row["published"], "source_url": url})
    for key, series in grouped.items():
        series.sort(key=lambda r: r["period"])
        months = [month_id(r["period"]) for r in series]
        if not months or len(months) != len(set(months)):
            raise ValueError(f"Empty/duplicate source: {key}")
        if any(b != a + 1 for a, b in zip(months, months[1:])):
            raise ValueError(f"Calendar gap: {key}; no interpolation permitted")
    return grouped


def context_for(series: list[dict], indicator: str, target: str) -> Context:
    target_id = month_id(target)
    prefix = [r for r in series if month_id(r["period"]) < target_id]
    if not 36 <= len(prefix) <= 60 or not prefix or prefix[-1]["period"] != period_label(target_id - 1):
        raise ValueError("Missing/oversized historical context")
    issue_date = target + "-20"
    if any(r["published"] >= issue_date for r in prefix):
        raise ValueError("Context publication after the declared issue boundary")
    return Context(indicator, target, issue_date, tuple(r["period"] for r in prefix),
                   tuple(r["value"] for r in prefix), digest(prefix))


def baseline_predictions(context: Context) -> dict:
    # Only this immutable prefix reaches fitting and scaling, never target actuals.
    values = dict(zip((month_id(p) for p in context.periods), context.values))
    target = month_id(context.target_period)
    x = features(values, target)
    training = [(m, features(values, m), y) for m, y in values.items()]
    training = [(m, f, y) for m, f, y in training if f is not None][-120:]
    if x is None or len(training) < 24:
        raise ValueError("Ridge has fewer than 24 past complete lag samples")
    model = new_model().fit([t[1] for t in training], [t[2] for t in training])
    y = context.values
    return {"persistence": y[-1], "seasonal": values[target - 12],
            "drift": y[-1] + (y[-1] - y[0]) / (len(y) - 1),
            "ridge": float(model.predict([x])[0]), "ridge_train_n": len(training),
            "ridge_train_end": period_label(training[-1][0])}


def seasonal_scale(context: Context) -> float | None:
    values = context.values
    scale = math.fsum(abs(values[i] - values[i - 12]) for i in range(12, len(values))) / (len(values) - 12)
    return scale if scale > 1e-12 else None


def metric(records: list[dict], model: str) -> dict:
    if not records:
        raise ValueError("No complete paired records")
    errors = [r["predictions"][model] - r["actual"] for r in records]
    valid_scales = all(r["mase_scale"] is not None for r in records)
    return {"n": len(records), "mae": math.fsum(abs(e) for e in errors) / len(errors),
            "rmse": math.sqrt(math.fsum(e * e for e in errors) / len(errors)),
            "mase": math.fsum(abs(e) / r["mase_scale"] for e, r in zip(errors, records)) / len(errors) if valid_scales else None,
            "mase_undefined_n": sum(r["mase_scale"] is None for r in records)}


def paired_block_interval(deltas: list[float], *, repeats: int = 2000) -> list[float] | None:
    if len(deltas) < 12:
        return None
    rng = np.random.default_rng(42)
    start = rng.integers(0, len(deltas), size=(repeats, math.ceil(len(deltas) / 3)))
    index = ((start[:, :, None] + np.arange(3)) % len(deltas)).reshape(repeats, -1)[:, :len(deltas)]
    return np.quantile(np.asarray(deltas)[index].mean(axis=1), [.025, .975]).tolist()


def interval_diagnostics(records: list[dict]) -> dict:
    losses = {}
    for q, field in [(.1, "p10"), (.5, "p50"), (.9, "p90")]:
        errors = [r["actual"] - r["quantiles"][field] for r in records]
        losses[str(q)] = math.fsum(max(q * e, (q - 1) * e) for e in errors) / len(errors)
    covered = sum(r["quantiles"]["p10"] <= r["actual"] <= r["quantiles"]["p90"] for r in records)
    return {"n": len(records), "nominal_coverage": .8, "coverage": covered / len(records),
            "mean_width": math.fsum(r["quantiles"]["p90"] - r["quantiles"]["p10"] for r in records) / len(records),
            "pinball_loss": losses, "calibration_fitted": False,
            "limits": "Twelve revised-snapshot months; model quantiles are not guaranteed economic confidence bands."}


def build_plan(rows: list[dict], protocol: dict, *, fixture: bool = False) -> dict:
    grouped = validate_rows(rows, fixture=fixture)
    origins = []
    for key in KEYS:
        series = [r for r in grouped[key] if r["period"] <= protocol["common_end"]]
        if len(series) != 60 or series[0]["period"] != "2021-09" or series[-1]["period"] != "2026-08":
            raise ValueError("Snapshot differs from the fixed 60-month per-indicator contract")
        for split in ["development", "audit"]:
            start, end = protocol["splits"][split]
            for t in range(month_id(start), month_id(end) + 1):
                target = period_label(t)
                context = context_for(series, key, target)
                actual_row = next(r for r in series if r["period"] == target)
                if actual_row["published"] <= context.issue_date:
                    raise ValueError("Target already published at the declared issue boundary")
                origins.append({"key": key, "target": target, "split": split,
                                "issue_date": context.issue_date, "context_n": len(context.values),
                                "context_start": context.periods[0], "context_end": context.periods[-1],
                                "context_sha256": context.source_rows_hash,
                                "latest_context_publication": max(r["published"] for r in series if r["period"] < target),
                                "target_publication": actual_row["published"]})
    payload = {"protocol_id": digest(protocol), "origins": origins, "origin_count": len(origins),
               "chronos_predictions_planned": sum(o["split"] == "audit" for o in origins),
               "source_rows_sha256": digest([r for k in KEYS for r in grouped[k] if r["period"] <= protocol["common_end"]]),
               "fixture": fixture, "real_time_vintage_verified": False,
               "mode": "planning_only_no_fits_or_model_predictions"}
    return {**payload, "plan_id": digest(payload)}


def score_origin(series: list[dict], indicator: str, target: str, *, predictor: Predictor | None = None) -> dict:
    context = context_for(series, indicator, target)
    predictions = baseline_predictions(context)
    quantiles = None
    if predictor is not None:
        result = predictor.predict(context)
        if not isinstance(result, Quantiles):
            raise ValueError("Backend must return the fixed three-quantile contract")
        result.validate()
        quantiles = {"p10": result.p10, "p50": result.p50, "p90": result.p90}
        predictions["challenger"] = result.p50
    # Retrieve target only after constructing every forecast from the prefix.
    actual = next(r["value"] for r in series if r["period"] == target)
    return {"key": indicator, "target": target, "actual": actual,
            "predictions": {k: predictions[k] for k in BASELINES if k in predictions} | ({"challenger": predictions["challenger"]} if predictor else {}),
            "quantiles": quantiles, "mase_scale": seasonal_scale(context),
            "context_n": len(context.values), "context_end": context.periods[-1],
            "context_sha256": context.source_rows_hash,
            "ridge_train_n": predictions["ridge_train_n"], "ridge_train_end": predictions["ridge_train_end"]}


def evaluate(rows: list[dict], protocol: dict, predictor: Predictor, *, fixture: bool = False,
             progress: Callable[[dict], None] | None = None) -> dict:
    plan = build_plan(rows, protocol, fixture=fixture)
    grouped = validate_rows(rows, fixture=fixture)
    emit = progress or (lambda event: None)
    records: dict[str, list[dict]] = {"development": [], "audit": []}
    for origin in plan["origins"]:
        emit({"event": "origin_started", "key": origin["key"], "target": origin["target"], "split": origin["split"]})
        record = score_origin(grouped[origin["key"]], origin["key"], origin["target"],
                              predictor=predictor if origin["split"] == "audit" else None)
        records[origin["split"]].append(record)
        emit({"event": "origin_finished", "record": record, "split": origin["split"]})
    development_metrics = {key: {b: metric([r for r in records["development"] if r["key"] == key], b) for b in BASELINES} for key in KEYS}
    # Four-way reference selection is distinct from the unchanged production default.
    references = {key: min(BASELINES, key=lambda b: development_metrics[key][b]["mae"]) for key in KEYS}
    indicator_metrics = {key: {b: metric([r for r in records["audit"] if r["key"] == key], b) for b in (*BASELINES, "challenger")} for key in KEYS}
    intervals = {key: interval_diagnostics([r for r in records["audit"] if r["key"] == key]) for key in KEYS}
    defined = all(indicator_metrics[key][b]["mase"] is not None for key in KEYS for b in (*BASELINES, "challenger"))
    macro = {b: math.fsum(indicator_metrics[key][b]["mase"] for key in KEYS) / len(KEYS) for b in (*BASELINES, "challenger")} if defined else None
    paired: dict[str, dict[str, list[float] | None]] = {}
    macro_interval: list[float] | None = None
    if defined:
        for key in KEYS:
            part = [r for r in records["audit"] if r["key"] == key]
            paired[key] = {b: paired_block_interval([(abs(r["predictions"]["challenger"] - r["actual"]) - abs(r["predictions"][b] - r["actual"])) / r["mase_scale"] for r in part]) for b in BASELINES}
        month_deltas = []
        for target in sorted({r["target"] for r in records["audit"]}):
            part = [r for r in records["audit"] if r["target"] == target]
            month_deltas.append(math.fsum((abs(r["predictions"]["challenger"] - r["actual"]) - abs(r["predictions"][references[r["key"]]] - r["actual"])) / r["mase_scale"] for r in part) / len(KEYS))
        macro_interval = paired_block_interval(month_deltas)
    wins = sum(indicator_metrics[k]["challenger"]["mase"] < indicator_metrics[k][references[k]]["mase"] - 1e-8 for k in KEYS) if defined else 0
    descriptive_screen = bool(defined and macro and all(macro["challenger"] < macro[b] - 1e-8 for b in BASELINES)
                              and macro_interval is not None and macro_interval[1] < 0 and wins >= 5)
    slices = {key: {label: {b: metric([r for r in records["audit"] if r["key"] == key and start <= r["target"] <= end], b) for b in (*BASELINES, "challenger")}
                   for label, start, end in [("2025_sep_dec", "2025-09", "2025-12"), ("2026_jan_aug", "2026-01", "2026-08")]} for key in KEYS}
    output = {"version": VERSION, "status": "fixture_only_complete" if fixture else "retrospective_complete",
              "not_economic_evidence": fixture, "plan_id": plan["plan_id"], "protocol_id": plan["protocol_id"],
              "backend_identity": predictor.identity, "model_predictions": 84, "development_challenger_predictions": 0,
              "development_metrics": development_metrics, "audit_references": references,
              "audit_metrics": indicator_metrics, "macro_equal_indicator_mase": macro,
              "paired_block_descriptive_95": {"indicator_vs_baselines": paired, "macro_vs_development_reference": macro_interval},
              "interval_diagnostics": intervals, "time_slices": slices,
              "descriptive_retrospective_screen": descriptive_screen, "indicators_beating_development_reference": wins,
              "production_default_changed": False, "prospective_validation_required": True,
              "records": records, "failures_dropped": 0, "fine_tuning": False, "real_time_vintage_verified": False}
    return {**output, "report_id": digest(output)}


class PersistenceFixture:
    identity = "synthetic_fixture_persistence_only_not_chronos"

    def predict(self, context: Context) -> Quantiles:
        value = context.values[-1]
        return Quantiles(value - 1., value, value + 1.)


def fixture_rows(*, constant: bool = False) -> list[dict]:
    rows = []
    for k, key in enumerate(KEYS):
        for i in range(60):
            month = month_id("2021-09") + i
            rows.append({"key": key, "period": period_label(month), "value": float(k * 10 + (0 if constant else i)),
                         "published": period_label(month + 1) + "-10", "source_url": "fixture://linear-series"})
    return rows
