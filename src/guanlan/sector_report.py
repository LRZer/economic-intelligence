"""Bounded exposure scenarios and self-contained, escaped research exports."""
from __future__ import annotations

import html
import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from .sector_risk import METHODS


def scenario(partners: pd.DataFrame, shocks: dict[str,float]) -> dict:
    if partners.empty or partners.partner_code.duplicated().any():
        raise ValueError('伙伴集合为空或含重复键')
    amounts=partners.trade_usd.to_numpy(dtype=float)
    if not np.isfinite(amounts).all() or (amounts<0).any() or amounts.sum()<=0:
        raise ValueError('伙伴贸易金额无效')
    unknown=set(shocks)-set(partners.partner_code)
    if unknown:
        raise ValueError('情景包含当前行业不存在的伙伴')
    if any(not np.isfinite(v) or abs(v)>10 for v in shocks.values()):
        raise ValueError('GDP情景冲击须为有限的-10至10个百分点')
    table=partners.copy()
    table['weight']=table.trade_usd/table.trade_usd.sum()
    table['gdp_shock_pp']=table.partner_code.map(shocks).fillna(0.)
    table['exposure_pp']=table.weight*table.gdp_shock_pp
    return {'weighted_gdp_shock_pp':float(table.exposure_pp.sum()),
            'definition':'上一年行业出口权重乘伙伴GDP百分点冲击之和，未指定伙伴的冲击为0',
            'limits':'仅为条件暴露指数；无贸易弹性假设，不计算出口损失、不改变已评估模型概率、不表示因果效应',
            'partners':clean_records(table)}


def clean_records(frame: pd.DataFrame) -> list[dict]:
    return frame.astype(object).where(pd.notna(frame),None).to_dict('records')


def export_bundle(row: dict,partners: pd.DataFrame,history: pd.DataFrame,research: dict,shock: dict) -> dict[str,bytes]:
    required=['country_code','hs2','year','feature_year','weight_year','macro_year','train_end',*METHODS]
    if any(k not in row for k in required):
        raise ValueError('研究导出缺少预测或训练边界')
    if not (row['train_end']<row['year'] and row['feature_year']<row['year']
            and row['weight_year']<row['year'] and row['macro_year']<row['year']):
        raise ValueError('导出存在时间泄漏')
    scope={'country_code':row['country_code'],'hs2':row['hs2'],'target_year':int(row['year'])}
    if not history.empty and not ((history.country_code==row['country_code'])&(history.hs2==row['hs2'])).all():
        raise ValueError('导出历史与选择范围不一致')
    safe_row=clean_records(pd.DataFrame([row]))[0]
    payload={'scope':scope,'created_at_utc':datetime.now(timezone.utc).isoformat(),
             'research_estimate':safe_row,'partners':clean_records(partners),'history':clean_records(history),
             'scenario':shock,'protocol_sha256':research.get('protocol_sha256'),
             'dataset_hash':research.get('dataset_hash'),'raw_zip_sha256':research.get('network_source',{}).get('raw_zip_sha256'),
             'model_params':research.get('params'),'features':research.get('features'),
             'selected_reference_on_validation':research.get('selected_reference_on_validation'),
             'default_reference':research.get('default_reference'),
             'validation':research.get('validation'),'test':research.get('test'),
             'evaluation_scope':'全部合格国家—HS2留出样本；同一国家行业历史单独列示',
             'yearly_metrics':research.get('yearly_metrics'),'quality':research.get('quality'),
             'calibration':research.get('calibration'),
             'unseen_country_development_2022':research.get('unseen_country_development_2022'),
             'paired_country_brier_difference_95':research.get('paired_country_brier_difference_95'),
             'passes_research_gate':research.get('passes_research_gate'),
             'source_urls':['https://www.cepii.fr/CEPII/fr/bdd_modele/bdd_modele_item.asp?id=37',
                            'https://data.worldbank.org/'],'limitations':research.get('limits')}
    encoded=json.dumps(payload,ensure_ascii=False,indent=2,allow_nan=False)
    names={'global_rate':'全样本历史事件率','sector_rate':'同业历史事件率','logistic':'逻辑回归对照',
           'joint_hgb':'宏观×网络树模型','trade_only_hgb':'仅贸易与集中度消融'}
    probabilities=pd.DataFrame([{'方法':names[m],'下行概率':f'{row[m]:.2%}'} for m in METHODS]).to_html(index=False,escape=True)
    shown_partners=partners.copy()
    shown_partners['trade_usd']=shown_partners.trade_usd.map(lambda v:f'{v/1e9:,.3f}')
    if 'share' in shown_partners:shown_partners['share']=shown_partners['share'].map(lambda v:f'{v:.2%}')
    if 'gdp_growth' in shown_partners:shown_partners['gdp_growth']=shown_partners['gdp_growth'].map(lambda v:'未提供' if pd.isna(v) else f'{v:.2f}')
    shown_partners=shown_partners.rename(columns={'partner_code':'伙伴代码','trade_usd':'出口额（十亿美元）','share':'出口权重','gdp_growth':'GDP增速（%）'})
    columns=[c for c in ['year','lag_export_usd','export_usd','outcome','sector_rate','logistic','joint_hgb','train_end'] if c in history]
    shown_history=history[columns].copy()
    for field in ['sector_rate','logistic','joint_hgb']:
        if field in shown_history:shown_history[field]=shown_history[field].map(lambda v:f'{v:.2%}')
    for field in ['lag_export_usd','export_usd']:
        if field in shown_history:shown_history[field]=shown_history[field].map(lambda v:f'{v/1e9:,.3f}')
    shown_history=shown_history.rename(columns={'year':'目标年','lag_export_usd':'上年出口（十亿美元）','export_usd':'当年出口（十亿美元）',
                                              'outcome':'下行标签','sector_rate':'同业率','logistic':'逻辑回归','joint_hgb':'宏观网络','train_end':'训练截止年'})
    results=pd.DataFrame([{'方法':names[m],'Brier':research.get('test',{}).get(m,{}).get('brier'),
                          'ROC-AUC':research.get('test',{}).get(m,{}).get('roc_auc')} for m in METHODS])
    validation_reference=names.get(research.get('selected_reference_on_validation','global_rate'),'全样本历史事件率')
    title=html.escape(f"{row['country_code']} · HS{row['hs2']} · {row['year']}年行业研究")
    escaped_evidence=html.escape(encoded)
    document=f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><style>body{{font-family:system-ui,sans-serif;max-width:1100px;margin:48px auto;padding:0 24px;color:#172d3b;background:#f7faf9}}h1,h2{{color:#146f7c}}table{{border-collapse:collapse;width:100%;background:white}}td,th{{padding:10px;border-bottom:1px solid #dae5e4;text-align:left}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:white;padding:18px}}.note{{padding:18px;background:#edf4f2;border-left:4px solid #146f7c}}.table-wrap{{overflow-x:auto}}details{{margin:16px 0}}summary{{cursor:pointer;color:#146f7c}}@media(max-width:600px){{body{{margin:24px auto;padding:0 16px}}td,th{{padding:7px;font-size:13px}}}}</style>
<h1>观澜 · {title}</h1><p class="note">固定修订历史快照的研究估计。下行指次年出口较上年下降至少10%。无首次公开版本验证。GDP情景只表示暴露，不能推导因果损失或投资收益。</p>
<h2>研究估计与对照</h2>{probabilities}<p>贸易权重年 {int(row['weight_year'])} · 宏观年 {int(row['macro_year'])} · 最后训练标签年 {int(row['train_end'])}</p>
<h2>评估与条件情景</h2><p>默认参考按开发期规则选定为：{html.escape(validation_reference)}。以下是全部合格国家—行业留出样本的固定对照，不是单一行业分数；必须结合逻辑回归、消融、开发期与地理稳定性一起核查，不能仅凭优于历史事件率宣称全面领先。</p><div class="table-wrap">{results.to_html(index=False,escape=True,float_format=lambda v:f'{v:.6f}',na_rep='未提供')}</div>
<p>条件GDP冲击暴露：{shock['weighted_gdp_shock_pp']:+.3f}个百分点。{html.escape(shock['limits'])}</p>
<h2>行业伙伴证据</h2><div class="table-wrap">{shown_partners.head(15).to_html(index=False,escape=True)}</div><details><summary>展开全部伙伴统计表</summary><div class="table-wrap">{shown_partners.to_html(index=False,escape=True)}</div></details>
<h2>同一国家—行业历史</h2><div class="table-wrap">{shown_history.to_html(index=False,escape=True,na_rep='未提供')}</div><p>简明表保留训练边界；完整原值与特征在JSON证据中。</p>
<h2>可复核证据及模型协议</h2><details><summary>展开完整 JSON 证据</summary><pre>{escaped_evidence}</pre></details></html>'''
    return {'json':encoded.encode('utf-8'),'html':document.encode('utf-8'),
            'csv':pd.DataFrame([safe_row]).to_csv(index=False).encode('utf-8-sig')}
