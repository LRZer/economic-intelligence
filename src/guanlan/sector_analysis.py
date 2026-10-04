"""Research views over frozen scores; no model fitting or holdout retuning."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .sector_risk import METHODS, NUMERIC

FEATURE_UNITS = {key:'%' for key in NUMERIC}
FEATURE_UNITS.update(log_export='ln（美元）', previous_growth='比值（1=100%）', partner_hhi='0—1',
                     top5_share='份额（0—1）', partner_gdp_coverage='份额（0—1）')


def cohort_for_year(latest: pd.DataFrame, backtest: pd.DataFrame, year: int) -> pd.DataFrame:
    if year < 2023:
        raise ValueError('交互研究限于固定留出或待核验年份，开发期不作部署历史展示')
    parts = [frame.loc[frame.year == year] for frame in [backtest, latest] if not frame.empty]
    result = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    if result.empty:
        raise ValueError('所选研究年没有已验证估计')
    if result.duplicated(['year', 'country_code', 'hs2']).any():
        raise ValueError('研究样本存在重复国家行业键')
    if not ((result.feature_year == year - 1) & (result.weight_year == year - 1)
            & (result.macro_year == year - 1) & (result.train_end < year)).all():
        raise ValueError('研究视图的输入或训练时点无效')
    probabilities = result[METHODS].to_numpy(dtype=float)
    if not np.isfinite(probabilities).all() or ((probabilities < 0) | (probabilities > 1)).any():
        raise ValueError('研究估计概率无效')
    return result


def comparison_frame(cohort: pd.DataFrame, country: str, hs2: str, lens: str) -> pd.DataFrame:
    if lens not in {'country', 'industry'}:
        raise ValueError('对照范围无效')
    peers = cohort.loc[cohort.country_code == country] if lens == 'country' else cohort.loc[cohort.hs2 == hs2]
    if peers.empty or not ((peers.country_code == country) & (peers.hs2 == hs2)).any():
        raise ValueError('当前行业不在对照范围内')
    peers = peers.copy().sort_values(['country_code', 'hs2'])
    peers['selected'] = (peers.country_code == country) & (peers.hs2 == hs2)
    peers['covered_export_share'] = peers.lag_export_usd / peers.lag_export_usd.sum()
    peers['model_disagreement_pp'] = (peers.joint_hgb - peers.logistic) * 100
    return peers


def historical_event_context(features: pd.DataFrame, hs2: str, year: int) -> dict:
    """Country-cluster bootstrap of prior event incidence, never a prediction CI."""
    known = features.loc[(features.hs2 == hs2) & (features.year >= 2019)
                         & (features.year < year) & features.outcome.notna()].copy()
    if known.empty:
        raise ValueError('所选行业没有训练期历史标签')
    if known.duplicated(['year', 'country_code', 'hs2']).any() or not known.outcome.isin([0, 1]).all():
        raise ValueError('训练期历史标签重复或无效')
    grouped = known.groupby('country_code').outcome.agg(['sum', 'count'])
    interval = None
    if len(grouped) >= 2:
        indexes = np.random.default_rng(42).integers(0, len(grouped), size=(2000, len(grouped)))
        rates = grouped['sum'].to_numpy()[indexes].sum(axis=1) / grouped['count'].to_numpy()[indexes].sum(axis=1)
        interval = np.quantile(rates, [.025, .975]).tolist()
    events = int(known.outcome.sum())
    return {'hs2': hs2, 'target_year': year, 'last_label_year': int(known.year.max()),
            'n': len(known), 'countries': len(grouped), 'events': events,
            'event_rate': events / len(known), 'smoothed_sector_rate': (events + 2) / (len(known) + 4),
            'historical_event_rate_cluster_interval_95': interval, 'draws': 2000, 'seed': 42,
            'limits': '训练期同行历史事件率的国家整组抽样区间；不是个体模型预测置信区间，不保证未来发生率或概率校准。'}


def feature_peer_profile(row: dict, peers: pd.DataFrame) -> pd.DataFrame:
    records = []
    for feature in NUMERIC:
        values = peers[feature].dropna().astype(float)
        if not np.isfinite(values).all():
            raise ValueError('对照特征含无穷值')
        value = row[feature]
        valid = len(values) > 0 and pd.notna(value) and np.isfinite(value)
        rank = float(((values < value).sum() + .5 * (values == value).sum()) / len(values)) if valid else None
        records.append({'feature': feature, 'unit': FEATURE_UNITS[feature], 'selected_value': float(value) if pd.notna(value) else None,
                        'peer_median': float(values.median()) if len(values) else None,
                        'midrank_percentile': rank, 'n_non_missing': len(values),
                        'peer_constant': bool(values.nunique() == 1)})
    return pd.DataFrame(records)


def validate_context(context: dict, row: dict) -> None:
    if context.get('target_year') != int(row['year']) or context.get('country_code') != row['country_code'] or context.get('hs2') != row['hs2']:
        raise ValueError('研究对照与导出范围不一致')
    if context.get('lens') not in {'country', 'industry'}:
        raise ValueError('研究对照范围无效')
    peers = context.get('peers', [])
    if not peers or len(peers) != context.get('peer_count') or len({(p['country_code'], p['hs2']) for p in peers}) != len(peers):
        raise ValueError('研究对照样本为空、重复或数量不一致')
    if not any(p['country_code'] == row['country_code'] and p['hs2'] == row['hs2'] for p in peers):
        raise ValueError('当前选择不在研究对照样本中')
    for peer in peers:
        if (peer['year'] != row['year'] or peer['train_end'] >= row['year']
                or any(peer[k] != row['year'] - 1 for k in ['feature_year', 'weight_year', 'macro_year'])):
            raise ValueError('研究对照存在时间泄漏')
        if context['lens'] == 'country' and peer['country_code'] != row['country_code']:
            raise ValueError('国家行业对照范围不一致')
        if context['lens'] == 'industry' and peer['hs2'] != row['hs2']:
            raise ValueError('跨国同行对照范围不一致')
    incidence = context.get('training_event_context', {})
    if incidence.get('last_label_year', row['year']) >= row['year'] or incidence.get('target_year') != row['year'] or incidence.get('hs2') != row['hs2']:
        raise ValueError('历史发生率使用了不符合范围或时点的标签')
    if abs(incidence['smoothed_sector_rate'] - row['sector_rate']) > 1e-10:
        raise ValueError('训练历史发生率与固定对照快照不一致')


def validate_partner_evidence(row: dict, partners: pd.DataFrame) -> None:
    if partners.empty or partners.partner_code.duplicated().any():
        raise ValueError('伙伴证据为空或重复')
    amounts = partners.trade_usd.to_numpy(dtype=float)
    if not np.isfinite(amounts).all() or (amounts < 0).any() or amounts.sum() <= 0:
        raise ValueError('伙伴证据金额无效')
    if not np.isclose(amounts.sum(), row['lag_export_usd'], rtol=1e-10):
        raise ValueError('伙伴网络与行业规模来自不同数据版本')
    values = partners.gdp_growth.to_numpy(dtype=float)
    present = np.isfinite(values)
    coverage = float(amounts[present].sum() / amounts.sum())
    if coverage <= 0 or not np.isclose(coverage, row['partner_gdp_coverage'], atol=1e-10):
        raise ValueError('伙伴GDP覆盖与固定模型输入不一致，拒绝混用快照')
    growth = float(np.dot(amounts[present], values[present]) / amounts[present].sum())
    if not np.isclose(growth, row['partner_gdp'], atol=1e-9):
        raise ValueError('伙伴GDP与固定模型输入不一致，拒绝混用快照')
