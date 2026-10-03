"""以固定特征和固定时间分割比较月度模型；不自动发布概率信号。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from guanlan.cycle import build_cycle_features, training_window
from guanlan.data import load_snapshot

LOGISTIC_FEATURES = ["ip_change_3m", "cpi_yoy", "unemployment_change_3m", "term_spread_10y_2y", "policy_rate"]
HORIZON = 6
LOOKBACK = 180
MIN_TRAIN = 120


def build_candidate_features(monthly: pd.DataFrame) -> pd.DataFrame:
    features = build_cycle_features(monthly, HORIZON)
    wide = monthly.pivot(index="date", columns="series_code", values="value").sort_index().asfreq("MS")
    features["ip_change_3m"] = 100 * (wide.IP_SA / wide.IP_SA.shift(3) - 1)
    features["unemployment_change_3m"] = wide.UNEMP_SA - wide.UNEMP_SA.shift(3)
    features["term_spread_10y_2y"] = wide.UST10Y - wide.UST2Y
    return features


def evaluate_candidate(features: pd.DataFrame) -> pd.DataFrame:
    valid = features.dropna(subset=LOGISTIC_FEATURES).sort_index()
    rows = []
    for position in range(MIN_TRAIN + HORIZON, len(valid)):
        current = valid.iloc[position]
        if pd.isna(current.contraction_at_horizon):
            continue
        train = training_window(valid, position, HORIZON, LOOKBACK, MIN_TRAIN)
        train = train.dropna(subset=LOGISTIC_FEATURES)
        if len(train) < MIN_TRAIN:
            continue
        y = train.contraction_at_horizon.astype(int)
        if y.nunique() < 2:
            continue
        model = make_pipeline(StandardScaler(), LogisticRegression(C=0.5, max_iter=1000))
        model.fit(train[LOGISTIC_FEATURES], y)
        risk = float(model.predict_proba(current[LOGISTIC_FEATURES].to_frame().T)[0, 1])
        baseline = float((y.sum() + 1) / (len(y) + 2))
        rows.append({"date": valid.index[position], "outcome": int(current.contraction_at_horizon),
                     "logistic": risk, "baseline": baseline, "training_last_month": train.index.max()})
    return pd.DataFrame(rows)


def report(frame: pd.DataFrame, label: str) -> None:
    y = frame.outcome
    auc = roc_auc_score(y, frame.logistic) if y.nunique() == 2 else float("nan")
    print(
        f"{label}: months={len(frame)}, events={int(y.sum())}, "
        f"logistic_brier={brier_score_loss(y, frame.logistic):.4f}, "
        f"baseline_brier={brier_score_loss(y, frame.baseline):.4f}, auc={auc:.3f}"
    )


def main() -> None:
    monthly, _ = load_snapshot("us_monthly")
    result = evaluate_candidate(build_candidate_features(monthly))
    split = pd.Timestamp("2019-01-01")
    report(result.loc[result.date < split], "Development pre-2019")
    report(result.loc[result.date >= split], "Holdout 2019+")
    print("latest evaluated month:", result.date.max().date())


if __name__ == "__main__":
    main()
