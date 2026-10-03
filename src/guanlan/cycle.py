"""美国月度工业产出收缩风险研究：时序回测与三状态混合模型。"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.mixture import GaussianMixture
from sklearn.preprocessing import StandardScaler

FEATURES = ["ip_yoy", "cpi_yoy", "unemployment_change_12m", "policy_rate"]
STATE_NAMES = ("较低历史收缩关联", "中等历史收缩关联", "较高历史收缩关联")


@dataclass(frozen=True)
class CycleSignal:
    as_of: str
    risk: float
    baseline: float
    state: str
    state_probability: float
    training_count: int
    training_last_month: str


def build_cycle_features(monthly: pd.DataFrame, horizon: int = 6) -> pd.DataFrame:
    """以月度原值构造同比特征；未来标签仅用于训练与事后评估。"""
    if horizon < 1:
        raise ValueError("预测窗口至少为一个月")
    wide = monthly.pivot(index="date", columns="series_code", values="value").sort_index()
    missing = {"UNEMP_SA", "CPI_SA", "IP_SA", "EFFR"} - set(wide.columns)
    if missing:
        raise ValueError(f"缺少美国官方序列：{sorted(missing)}")
    wide = wide.asfreq("MS")
    features = pd.DataFrame(index=wide.index)
    features["ip_yoy"] = 100 * (wide.IP_SA / wide.IP_SA.shift(12) - 1)
    features["cpi_yoy"] = 100 * (wide.CPI_SA / wide.CPI_SA.shift(12) - 1)
    features["unemployment_change_12m"] = wide.UNEMP_SA - wide.UNEMP_SA.shift(12)
    features["policy_rate"] = wide.EFFR
    future_ip = wide.IP_SA.shift(-horizon)
    features["contraction_at_horizon"] = np.where(
        wide.IP_SA.notna() & future_ip.notna(),
        (future_ip < wide.IP_SA).astype(float),
        np.nan,
    )
    features.index.name = "date"
    return features


def training_window(
    features: pd.DataFrame, prediction_position: int, horizon: int, lookback: int, min_train: int
) -> pd.DataFrame:
    """严格剔除当时尚不能知道未来标签的训练月份。"""
    if prediction_position >= len(features) or prediction_position < 0:
        return features.iloc[0:0]
    prediction_month = features.index[prediction_position]
    cutoff = prediction_month - pd.DateOffset(months=horizon)
    earliest = cutoff - pd.DateOffset(months=lookback)
    result = features.loc[(features.index >= earliest) & (features.index < cutoff)].dropna(
        subset=FEATURES + ["contraction_at_horizon"]
    )
    return result if len(result) >= min_train else features.iloc[0:0]


def _fit_and_predict(train: pd.DataFrame, current: pd.Series) -> tuple[float, float, str, float]:
    scaler = StandardScaler()
    x_train = scaler.fit_transform(train[FEATURES].to_numpy(dtype=float))
    x_current = scaler.transform(current[FEATURES].to_numpy(dtype=float).reshape(1, -1))
    model = GaussianMixture(
        n_components=3, covariance_type="diag", reg_covar=1e-4,
        init_params="random_from_data", n_init=3, random_state=42
    )
    model.fit(x_train)
    clusters = model.predict(x_train)
    posterior = model.predict_proba(x_current)[0]
    outcomes = train.contraction_at_horizon.to_numpy(dtype=float)
    # Beta(1,1) 平滑避免小样本簇给出虚假的 0% 或 100%。
    rates = np.array(
        [(outcomes[clusters == cluster].sum() + 1) / ((clusters == cluster).sum() + 2) for cluster in range(3)]
    )
    risk = float(np.dot(posterior, rates))
    baseline = float((outcomes.sum() + 1) / (len(outcomes) + 2))
    main_cluster = int(posterior.argmax())
    rank = int(np.argsort(rates).tolist().index(main_cluster))
    return risk, baseline, STATE_NAMES[rank], float(posterior[main_cluster])


def evaluate_cycle(
    features: pd.DataFrame, horizon: int = 6, lookback: int = 180, min_train: int = 120
) -> tuple[pd.DataFrame, CycleSignal, dict]:
    """逐月滚动回测，并用最近可用月份给出一个未验证的当前信号。"""
    if lookback < min_train or min_train < 60:
        raise ValueError("训练窗口设置无效")
    valid = features.dropna(subset=FEATURES).sort_index()
    if len(valid) < min_train + horizon + 1:
        raise ValueError("月度数据不足以训练并回测")
    rows = []
    for position in range(min_train + horizon, len(valid)):
        current = valid.iloc[position]
        if pd.isna(current.contraction_at_horizon):
            continue
        train = training_window(valid, position, horizon, lookback, min_train)
        if train.empty:
            continue
        risk, baseline, state, state_probability = _fit_and_predict(train, current)
        rows.append(
            {
                "date": valid.index[position],
                "risk": risk,
                "baseline": baseline,
                "outcome": int(current.contraction_at_horizon),
                "state": state,
                "state_probability": state_probability,
                "training_count": len(train),
                "training_last_month": train.index.max(),
            }
        )
    backtest = pd.DataFrame(rows)
    if backtest.empty:
        raise ValueError("没有可评估的历史月份")
    latest_position = len(valid) - 1
    latest_train = training_window(valid, latest_position, horizon, lookback, min_train)
    if latest_train.empty:
        raise ValueError("当前信号的历史训练样本不足")
    risk, baseline, state, state_probability = _fit_and_predict(latest_train, valid.iloc[latest_position])
    signal = CycleSignal(
        as_of=valid.index.max().date().isoformat(),
        risk=risk,
        baseline=baseline,
        state=state,
        state_probability=state_probability,
        training_count=len(latest_train),
        training_last_month=latest_train.index.max().date().isoformat(),
    )
    outcomes = backtest.outcome.to_numpy(dtype=int)
    metrics = {
        "months": len(backtest),
        "events": int(outcomes.sum()),
        "first_month": backtest.date.min().date().isoformat(),
        "last_month": backtest.date.max().date().isoformat(),
        "model_brier": float(brier_score_loss(outcomes, backtest.risk)),
        "baseline_brier": float(brier_score_loss(outcomes, backtest.baseline)),
        "roc_auc": float(roc_auc_score(outcomes, backtest.risk)) if len(set(outcomes)) == 2 else None,
        "horizon_months": horizon,
        "lookback_months": lookback,
    }
    return backtest, signal, metrics
