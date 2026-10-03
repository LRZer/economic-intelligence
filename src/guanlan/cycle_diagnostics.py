"""对时间相关的逐月回测误差做成组抽样与分段诊断。"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd


def _validated(backtest: pd.DataFrame) -> pd.DataFrame:
    required = ["date", "risk", "baseline", "outcome"]
    missing = set(required) - set(backtest)
    if missing:
        raise ValueError(f"回测缺少必要字段：{sorted(missing)}")
    frame = backtest[required].copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    if frame.date.isna().any() or frame.date.duplicated().any():
        raise ValueError("回测日期无效或重复")
    if not frame.date.is_monotonic_increasing:
        raise ValueError("回测日期必须按时间升序")
    if not frame.outcome.isin([0, 1]).all():
        raise ValueError("回测事件必须为 0 或 1")
    for column in ("risk", "baseline"):
        values = frame[column].to_numpy(dtype=float)
        if not np.isfinite(values).all() or ((values < 0) | (values > 1)).any():
            raise ValueError(f"回测 {column} 不是有效概率")
    return frame


def paired_block_brier_interval(backtest: pd.DataFrame, block_observations: int = 12,
                                replications: int = 4000, seed: int = 20260927) -> dict:
    """成对循环移动块自助法；正差值表示模型的 Brier 误差较高。"""
    frame = _validated(backtest)
    if block_observations < 6 or replications < 1000 or len(frame) < 2 * block_observations:
        raise ValueError("回测样本或成组抽样参数不足")
    event = frame.outcome.to_numpy(dtype=float)
    difference = ((frame.risk.to_numpy(dtype=float) - event) ** 2
                  - (frame.baseline.to_numpy(dtype=float) - event) ** 2)
    count = len(difference)
    random = np.random.default_rng(seed)
    starts = random.integers(0, count, size=(replications, math.ceil(count / block_observations)))
    offsets = np.arange(block_observations)
    indices = ((starts[:, :, None] + offsets) % count).reshape(replications, -1)[:, :count]
    means = difference[indices].mean(axis=1)
    low, high = np.quantile(means, [0.025, 0.975])
    calendar_span = len(pd.period_range(frame.date.min(), frame.date.max(), freq="M"))
    return {
        "method": "paired circular moving-block bootstrap",
        "brier_difference_model_minus_baseline": float(difference.mean()),
        "ci_95_lower": float(low), "ci_95_upper": float(high),
        "block_observations": block_observations, "replications": replications,
        "seed": seed, "evaluated_months": count,
        "missing_calendar_months": calendar_span - count,
    }


def cycle_period_breakdown(backtest: pd.DataFrame) -> pd.DataFrame:
    """固定日历阶段的描述性误差；不把阶段当作额外独立留出集。"""
    frame = _validated(backtest)
    periods = [(None, 2009), (2010, 2018), (2019, None)]
    rows = []
    for start, end in periods:
        selected = frame if start is None else frame.loc[frame.date.dt.year.ge(start)]
        if end is not None:
            selected = selected.loc[selected.date.dt.year.le(end)]
        if selected.empty:
            continue
        event = selected.outcome.to_numpy(dtype=float)
        model = float(np.mean((selected.risk.to_numpy(dtype=float) - event) ** 2))
        baseline = float(np.mean((selected.baseline.to_numpy(dtype=float) - event) ** 2))
        rows.append({"period": f"{selected.date.min().year}—{selected.date.max().year}",
                     "months": len(selected), "events": int(event.sum()),
                     "model_brier": model, "baseline_brier": baseline,
                     "difference": model - baseline})
    return pd.DataFrame(rows)
