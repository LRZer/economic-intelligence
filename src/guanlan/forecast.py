"""Reproducible, strictly chronological monthly research models.

No network calls, no random split, no imputation, and no external model files.
Historical results use the current revised snapshot, not real-time vintages.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any

import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

VERSION = "china-monthly-v1"
FEATURES = ["上月读数", "前两月读数", "前三月读数", "去年同月读数", "月份正弦", "月份余弦"]
MODEL_KEYS = ("cpi_yoy", "ppi_yoy", "cpi_mom", "ppi_mom", "manufacturing_pmi",
              "manufacturing_new_orders_pmi", "nonmanufacturing_pmi")
MIN_TRAIN = 24
HOLDOUT_MONTHS = 12


def month_id(period: str) -> int:
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", period):
        raise ValueError("期别必须为有效的 YYYY-MM")
    return int(period[:4]) * 12 + int(period[5:]) - 1


def period_label(month: int) -> str:
    return f"{month // 12:04d}-{month % 12 + 1:02d}"


def observations(rows: list[dict]) -> dict[int, float]:
    result = {}
    for row in rows:
        month = month_id(row["period"])
        value = float(row["value"])
        if month in result:
            raise ValueError("同一指标存在重复期别，拒绝静默覆盖")
        if not math.isfinite(value):
            raise ValueError("观测包含非有限值")
        result[month] = value
    return dict(sorted(result.items()))


def features(values: dict[int, float], target: int) -> list[float] | None:
    lags = [values.get(target - n) for n in (1, 2, 3, 12)]
    if any(x is None for x in lags):
        return None
    angle = 2 * math.pi * (target % 12) / 12
    return [float(value) for value in lags if value is not None] + [math.sin(angle), math.cos(angle)]


def new_model():
    return make_pipeline(StandardScaler(), Ridge(alpha=10.0))


def metric(records: list[dict], field: str) -> dict:
    errors = np.array([r[field] - r["actual"] for r in records], dtype=float)
    return {"n": len(records), "mae": float(np.abs(errors).mean()),
            "rmse": float(np.sqrt(np.square(errors).mean()))}


def paired_interval(records: list[dict], baseline: str) -> list[float]:
    """Descriptive paired circular block bootstrap, not a significance test."""
    deltas = np.array([abs(r["ridge"]-r["actual"])-abs(r[baseline]-r["actual"]) for r in records])
    rng = np.random.default_rng(42)
    starts = rng.integers(0, len(deltas), size=(2000, math.ceil(len(deltas) / 3)))
    indices = ((starts[:, :, None] + np.arange(3)) % len(deltas)).reshape(2000, -1)[:, :len(deltas)]
    return np.quantile(deltas[indices].mean(axis=1), [.025, .975]).tolist()


def analyze_series(rows: list[dict], *, min_train: int = MIN_TRAIN) -> dict:
    values = observations(rows)
    signature = hashlib.sha256(json.dumps({"version": VERSION, "values": list(values.items()),
                                          "min_train": min_train}, separators=(",", ":")).encode()).hexdigest()
    result = {"version": VERSION, "snapshot_hash": signature, "status": "insufficient",
              "observation_count": len(values), "feature_names": FEATURES,
              "limits": "当前修订版历史快照；没有逐期实时版本。区间不保证未来覆盖率。"}
    if not values:
        return {**result, "reason": "没有观测数据"}
    samples: list[tuple[int, list[float], float]] = []
    for month, value in values.items():
        x = features(values, month)
        if x is not None:
            samples.append((month, x, value))
    cutoff = max(values) - HOLDOUT_MONTHS + 1
    records: list[dict[str, Any]] = []
    for i, (month, x, actual) in enumerate(samples):
        if i < min_train:
            continue
        train = samples[max(0, i - 120):i]
        model = new_model().fit([t[1] for t in train], [t[2] for t in train])
        records.append({"period": period_label(month), "actual": actual,
                        "ridge": float(model.predict([x])[0]),
                        "persistence": values[month-1], "seasonal": values[month-12],
                        "train_start": period_label(train[0][0]), "train_end": period_label(train[-1][0]),
                        "latest_feature_period": period_label(month-1), "train_n": len(train),
                        "split": "test" if month >= cutoff else "validation"})
    validation = [r for r in records if r["split"] == "validation"]
    test = [r for r in records if r["split"] == "test"]
    result.update(backtest=records, test_start=period_label(cutoff), validation_n=len(validation), test_n=len(test))
    if len(validation) < 6 or len(test) < 8:
        return {**result, "reason": "至少需要6个开发验证月、8个留出评估月；缺口不插值"}
    # Baseline selection uses development validation only, never the test set.
    baseline = min(("persistence", "seasonal"), key=lambda k: metric(validation, k)["mae"])
    metrics = {stage: {k: metric(part, k) for k in ("ridge", "persistence", "seasonal")}
               for stage, part in (("validation", validation), ("test", test))}
    delta_interval = paired_interval(test, baseline)
    passed = (metrics["test"]["ridge"]["mae"] < min(metrics["test"][k]["mae"] for k in ("persistence", "seasonal"))
              and delta_interval[1] < 0)
    calibration_errors = np.abs([r["ridge"] - r["actual"] for r in validation])
    radius = float(np.quantile(calibration_errors, min(1.0, math.ceil((len(validation)+1)*.9)/len(validation)), method="higher"))
    coverage = float(np.mean([abs(r["ridge"]-r["actual"]) <= radius for r in test]))
    result.update(status="evaluated", baseline=baseline, metrics=metrics,
                  passes_research_gate=passed, paired_mae_difference_95=delta_interval,
                  interval_radius=radius, test_interval_coverage=coverage,
                  interval_calibration_n=len(validation))
    target = max(values) + 1
    x = features(values, target)
    if x is None:
        result["forecast_unavailable"] = "下一期需要的自然月滞后值缺失"
        return result
    train = samples[-120:]
    model = new_model().fit([t[1] for t in train], [t[2] for t in train])
    prediction = float(model.predict([x])[0])
    z = model[0].transform([x])[0]
    contributions = model[1].coef_ * z
    result["forecast"] = {"period": period_label(target), "ridge": prediction,
                          "baseline": values[target-1] if baseline == "persistence" else values[target-12],
                          "lower": prediction-radius, "upper": prediction+radius,
                          "train_end": period_label(train[-1][0]), "train_n": len(train),
                          "intercept": float(model[1].intercept_),
                          "contributions": dict(zip(FEATURES, contributions.tolist()))}
    return result


def anomaly(rows: list[dict]) -> dict:
    """Fit historical observations before the latest reading, then score it."""
    values = observations(rows)
    if not values:
        return {"status": "insufficient", "reason": "没有观测数据"}
    latest = max(values)
    samples = [(m, [y, y-values[m-1], y-values[m-12]]) for m, y in values.items()
               if m-1 in values and m-12 in values]
    train = [s for s in samples if s[0] < latest][-60:]
    current = next((s for s in samples if s[0] == latest), None)
    if len(train) < MIN_TRAIN or current is None:
        return {"status": "insufficient", "reason": "历史同口径样本不足，或自然月滞后缺失"}
    model = IsolationForest(n_estimators=200, contamination=.1, random_state=42, n_jobs=1)
    model.fit([s[1] for s in train])
    score = float(model.decision_function([current[1]])[0])
    return {"status": "scored", "period": period_label(latest), "flag": score < 0,
            "score": score, "train_n": len(train), "train_end": period_label(train[-1][0]),
            "inputs": dict(zip(["本期读数", "较上月差", "较去年同月差"], current[1])),
            "limits": "无监督异常提示；没有异常真值标签，不报告准确率。异常可能是经济冲击、修订或解析问题。"}
