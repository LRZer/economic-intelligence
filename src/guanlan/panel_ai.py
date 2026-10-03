"""Global WDI panel forecasts with annual time boundaries and cohort diagnostics."""
from __future__ import annotations

import hashlib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.inspection import permutation_importance

TARGET = "NY.GDP.MKTP.KD.ZG"
INPUTS = (TARGET, "FP.CPI.TOTL.ZG", "SL.UEM.TOTL.ZS", "NE.GDI.TOTL.ZS", "BN.CAB.XOKA.GD.ZS")
FEATURE_NAMES = ["上年GDP增速", "上年通胀", "上年失业率", "上年资本形成占GDP", "上年经常账户占GDP", "前两年GDP增速"]
PARAMS = dict(max_iter=100, max_leaf_nodes=7, learning_rate=.05, l2_regularization=10., random_state=42)


def records(frame: pd.DataFrame) -> list[dict]:
    return frame.astype(object).where(pd.notna(frame), None).to_dict("records")


def prepare(frame: pd.DataFrame) -> pd.DataFrame:
    selected = frame.loc[frame.indicator_code.isin(INPUTS)]
    if selected.duplicated(["country_code", "year", "indicator_code"]).any():
        raise ValueError("WDI存在重复国家、年度与指标")
    wide = selected.pivot(index=["country_code", "year"], columns="indicator_code", values="value").reset_index()
    for code in INPUTS:
        if code not in wide:
            wide[code] = np.nan
    targets = wide[["country_code", "year", TARGET]].rename(columns={TARGET:"actual"})
    lag1 = wide[["country_code", "year", *INPUTS]].copy()
    lag1["year"] += 1
    lag1 = lag1.rename(columns=dict(zip(INPUTS, FEATURE_NAMES[:5])))
    lag2 = wide[["country_code", "year", TARGET]].copy()
    lag2["year"] += 2
    lag2 = lag2.rename(columns={TARGET:FEATURE_NAMES[5]})
    data = targets.merge(lag1, on=["country_code", "year"], how="outer").merge(lag2, on=["country_code", "year"], how="left")
    data = data.loc[data[FEATURE_NAMES[0]].notna()].sort_values(["year", "country_code"]).reset_index(drop=True)
    data["missing_features"] = data[FEATURE_NAMES].isna().sum(axis=1)
    return data


def metrics(rows: pd.DataFrame, field: str) -> dict:
    errors = rows[field]-rows.actual
    return {"n":len(rows), "mae":float(errors.abs().mean()), "rmse":float(np.sqrt((errors**2).mean()))}


def evaluate(frame: pd.DataFrame) -> dict:
    data = prepare(frame)
    digest = hashlib.sha256(pd.util.hash_pandas_object(data, index=True).values.tobytes()).hexdigest()
    result = {"version":"wdi-panel-v1", "snapshot_hash":digest, "status":"insufficient",
              "params":PARAMS, "features":FEATURE_NAMES,
              "limits":"当前修订版WDI；非实时版本。国家样本相关，缺失与发布滞后影响估计；GDP预测不等于资产回报。"}
    # Fixed calendar boundaries; no tuning on or after 2020.
    known = data.loc[data.actual.notna()]
    if len(known.loc[known.year<2015]) < 500:
        return {**result, "reason":"2015年前同口径训练样本不足500条"}
    predictions=[]
    for year in range(2015, 2025):
        train = known.loc[known.year<year]
        current = known.loc[known.year==year].copy()
        if current.empty:
            continue
        model = HistGradientBoostingRegressor(**PARAMS).fit(train[FEATURE_NAMES], train.actual)
        current["prediction"] = model.predict(current[FEATURE_NAMES])
        current["baseline"] = current[FEATURE_NAMES[0]]
        current["train_end"] = int(train.year.max())
        current["feature_year"] = year-1
        current["train_n"] = len(train)
        current["split"] = "validation" if year<2020 else "test"
        predictions.append(current)
    if not predictions:
        return result
    backtest = pd.concat(predictions, ignore_index=True)
    validation = backtest.loc[backtest.split=="validation"]
    test = backtest.loc[backtest.split=="test"]
    if validation.empty or test.empty:
        return {**result, "reason":"固定开发期或留出期没有标签"}
    radius = float(np.quantile((validation.prediction-validation.actual).abs(), .9, method="higher"))
    year_metrics = [{"year":int(y), "prediction":metrics(part,"prediction"), "baseline":metrics(part,"baseline")}
                    for y,part in test.groupby("year")]
    result.update(status="evaluated", validation={k:metrics(validation,k) for k in ("prediction","baseline")},
                  test={k:metrics(test,k) for k in ("prediction","baseline")}, yearly_metrics=year_metrics,
                  interval_radius=radius, test_interval_coverage=float(((test.prediction-test.actual).abs()<=radius).mean()),
                  backtest=records(backtest), test_countries=int(test.country_code.nunique()),
                  passes_research_gate=all(r["prediction"]["mae"]<r["baseline"]["mae"] for r in year_metrics))
    # Interpretation measured only on a fixed development year, not final test labels.
    train = known.loc[known.year<2019];development = known.loc[known.year==2019]
    model = HistGradientBoostingRegressor(**PARAMS).fit(train[FEATURE_NAMES], train.actual)
    if not development.empty:
        importance = permutation_importance(model, development[FEATURE_NAMES], development.actual,
                                            scoring="neg_mean_absolute_error", n_repeats=3, random_state=42, n_jobs=1)
        result["development_feature_importance"] = dict(zip(FEATURE_NAMES, importance.importances_mean.tolist()))
    # For each country only the next year after its latest available label.
    latest_year = int(known.year.max())
    future = data.loc[(data.year==latest_year+1) & data.actual.isna()].copy()
    if not future.empty:
        final = HistGradientBoostingRegressor(**PARAMS).fit(known[FEATURE_NAMES], known.actual)
        future["prediction"] = final.predict(future[FEATURE_NAMES])
        future["lower"] = future.prediction-radius;future["upper"] = future.prediction+radius
        future["train_end"] = latest_year
        result["next_year_research"] = records(future)
    return result
