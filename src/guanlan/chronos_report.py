"""Offline integrity and independent metric checks for the fixed model audit.

This module never downloads or loads foundation-model weights. Replaying saved
quantiles validates data, baselines and scores, not model-execution provenance.
"""
from __future__ import annotations

import csv
import hashlib
import html
from importlib.resources import files
import io
import json
import math
from typing import Any

from .chronos_evaluation import BASELINES, KEYS, Quantiles, digest, evaluate

MODEL_ID = 'autogluon/chronos-2-synth'
REVISION = '3607918a9fd027d5c465d8213e46b98e2c041cea'
WEIGHTS_SHA = '920a3344726a8026c9335d38ae1a2bfa9b7d659c1b8fe0b0af8d5f775863422e'
PROTOCOL_SHA = 'cd1abcfa04b3d3183cfbd4cb0a365f62aca3d90503b85d09136a4ae21d712261'
DATA_SHA = '90e4e0d4237d2c414578c29786c9585bddbc27192cdd7c65c937f563326bb6c2'
LABELS = {'cpi_yoy': 'CPI 同比', 'ppi_yoy': 'PPI 同比', 'cpi_mom': 'CPI 环比', 'ppi_mom': 'PPI 环比',
          'manufacturing_pmi': '制造业 PMI', 'manufacturing_new_orders_pmi': '制造业新订单 PMI',
          'nonmanufacturing_pmi': '非制造业商务活动指数'}
METHODS = {'persistence': '上期值', 'seasonal': '去年同月值', 'drift': '历史端点漂移',
           'ridge': '固定 Ridge', 'challenger': 'Chronos-2-Synth'}


def strict_json(raw: bytes) -> dict[str, Any]:
    if not raw or len(raw) > 2 * 1024 * 1024:
        raise ValueError('Empty or oversized audit JSON')
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError('Duplicate JSON key')
            result[key] = value
        return result
    def invalid(value):
        raise ValueError('Non-finite JSON constant')
    value = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_constant=invalid)
    if not isinstance(value, dict):
        raise ValueError('Audit JSON must be an object')
    return value


def close(left: Any, right: Any) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return math.isfinite(left) and math.isfinite(right) and math.isclose(left, right, rel_tol=1e-9, abs_tol=1e-10)
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(close(left[key], right[key]) for key in left)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(close(a, b) for a, b in zip(left, right))
    return type(left) is type(right) and left == right


def verify_report(report: dict, protocol: dict, source: bytes) -> dict:
    if hashlib.sha256(source).hexdigest() != DATA_SHA:
        raise ValueError('Official source differs from the frozen snapshot')
    if report.get('report_id') != digest({k: v for k, v in report.items() if k != 'report_id'}):
        raise ValueError('Audit report fingerprint mismatch')
    if report.get('backend_identity') != MODEL_ID + '@' + REVISION or report.get('protocol_id') != digest(protocol):
        raise ValueError('Audit model/protocol identity mismatch')
    if report.get('status') != 'retrospective_complete' or report.get('not_economic_evidence') is not False:
        raise ValueError('A synthetic or partial result cannot be accepted as the real audit')
    if report.get('production_default_changed') is not False or report.get('fine_tuning') is not False:
        raise ValueError('Unexpected scientific policy')
    records = report.get('records')
    if not isinstance(records, dict) or set(records) != {'development', 'audit'}:
        raise ValueError('Missing complete paired records')
    for split in records:
        if not isinstance(records[split], list) or len(records[split]) != 84:
            raise ValueError('Audit/development completeness differs from fixed plan')
    saved = {}
    for row in records['audit']:
        identity = row['key'], row['target']
        if identity in saved:
            raise ValueError('Duplicate model origin')
        if not isinstance(row.get('quantiles'), dict) or set(row['quantiles']) != {'p10', 'p50', 'p90'}:
            raise ValueError('Three native quantiles required')
        result = Quantiles(**row['quantiles']); result.validate()
        saved[identity] = result
    class Replay:
        identity = MODEL_ID + '@' + REVISION
        def predict(self, context):
            return saved[(context.indicator, context.target_period)]
    rebuilt = evaluate(strict_json(source)['rows'], protocol, Replay(), fixture=False)
    expected = {k: v for k, v in rebuilt.items() if k != 'report_id'}
    supplied = {k: v for k, v in report.items() if k != 'report_id'}
    if not close(supplied, expected):
        raise ValueError('Stored data, chronology, baseline, scores or gate differ from independent recomputation')
    return {'status': 'passed', 'report_id': report['report_id'], 'paired_audit_origins': 84,
            'baseline_refit_origins': 168, 'new_model_predictions': 0,
            'mode': 'saved_quantile_replay_with_independent_baseline_and_metric_recomputation',
            'limit': 'Checks completeness and consistency; does not independently prove weights were executed.',
            'production_default_changed': False}


def load_packaged_audit() -> tuple[dict, dict, dict]:
    folder = files('guanlan').joinpath('resources/chronos-synth-v1')
    manifest = strict_json(folder.joinpath('manifest.json').read_bytes())
    content = {}
    for filename in ('report.json', 'protocol.json', 'provenance.json'):
        raw = folder.joinpath(filename).read_bytes()
        if hashlib.sha256(raw).hexdigest() != manifest['files'][filename]:
            raise ValueError('Packaged audit artifact checksum mismatch')
        content[filename] = strict_json(raw)
    if manifest['files']['protocol.json'] != PROTOCOL_SHA:
        raise ValueError('Packaged protocol differs from pre-execution physical freeze')
    source = files('china_macro').joinpath('demo_data.json').read_bytes()
    verify_report(content['report.json'], content['protocol.json'], source)
    return content['report.json'], content['protocol.json'], content['provenance.json']


def csv_rows(report: dict, *, key: str | None = None) -> list[dict]:
    if key is not None and key not in KEYS:
        raise ValueError('Unknown audit indicator')
    rows = []
    for split in ('development', 'audit'):
        for record in report['records'][split]:
            if key is not None and record['key'] != key:
                continue
            rows.append({'split': split, 'indicator': record['key'], 'period': record['target'], 'actual': record['actual'],
                         **record['predictions'], **(record['quantiles'] or {'p10': None, 'p50': None, 'p90': None}),
                         'mase_training_scale': record['mase_scale'], 'context_n': record['context_n'],
                         'context_end': record['context_end'], 'ridge_train_n': record['ridge_train_n'],
                         'ridge_train_end': record['ridge_train_end'], 'context_sha256': record['context_sha256'],
                         'report_id': report['report_id']})
    return rows


def export_audit(report: dict, protocol: dict, provenance: dict) -> dict[str, bytes]:
    output = io.StringIO(newline='')
    rows = csv_rows(report)
    fields = ['split', 'indicator', 'period', 'actual', *BASELINES, 'challenger', 'p10', 'p50', 'p90',
              'mase_training_scale', 'context_n', 'context_end', 'ridge_train_n', 'ridge_train_end', 'context_sha256', 'report_id']
    writer = csv.DictWriter(output, fieldnames=fields); writer.writeheader(); writer.writerows(rows)
    macro = report['macro_equal_indicator_mase']
    summary = ''.join(f'<tr><td>{html.escape(METHODS[k])}</td><td>{v:.6f}</td></tr>' for k, v in macro.items())
    body = ''.join(f'<tr><td>{html.escape(LABELS[k])}</td><td>{METHODS[report["audit_references"][k]]}</td><td>{report["audit_metrics"][k]["challenger"]["mae"]:.6f}</td><td>{report["audit_metrics"][k]["challenger"]["mase"]:.6f}</td><td>{report["interval_diagnostics"][k]["coverage"]:.1%}</td></tr>' for k in KEYS)
    verdict = '通过描述性回顾门槛，仍需前瞻验证' if report['descriptive_retrospective_screen'] else '未通过描述性回顾门槛'
    document = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Chronos-2-Synth 固定协议审计</title><style>body{{font:16px/1.65 system-ui,sans-serif;max-width:960px;margin:32px auto;padding:0 18px;color:#172d3b;overflow-wrap:anywhere}}h1{{font-size:28px}}.note{{padding:16px;background:#f2f5f3;border-left:4px solid #146f7c}}table{{border-collapse:collapse;width:100%;font-size:14px}}th,td{{padding:10px;text-align:left;border-bottom:1px solid #d7dfdd}}.scroll{{overflow-x:auto;max-width:100%}}.scroll table{{min-width:620px}}.scroll td:nth-child(n+3){{white-space:nowrap}}code{{overflow-wrap:anywhere}}li{{margin:6px 0}}</style>
<h1>时序基础模型 · 固定协议审计</h1><p>7 个官方月度指标 · 2025-09 至 2026-08 · 84 个真实模型预测</p>
<p class="note">{verdict}。生产默认参考保持原研究基线。当前修订版历史快照已被查看，此为回顾实验，不是盲测或实时版本评估。80% 分位数带未经经济数据校准，不保证未来覆盖。</p>
<h2>等权宏观 MASE</h2><p>每个指标先按该期历史前缀的季节差值归一化，再对七项等权；不混合百分比与指数点的原始 MAE。</p><table><tr><th>方法</th><th>宏观 MASE</th></tr>{summary}</table>
<h2>逐指标核查</h2><p>窄屏下表格可横向滚动核查各列。</p><div class="scroll"><table><tr><th>指标</th><th>开发期选定参考</th><th>模型 MAE</th><th>模型 MASE</th><th>80% 带实际覆盖</th></tr>{body}</table></div>
<h2>方法与局限</h2><ul><li>固定官方权重，CPU float32；单指标单步，batch=1，不微调、不用外部协变量或跨指标学习。</li><li>四个基线使用相同历史前缀；开发期只选参考，不运行 Chronos、不调整参数。</li><li>Chronos 审计预测仅收到 48—59 个此前观测；开发期基线使用 36—47 个。目标实际值在预测后加入评分。</li><li>三月循环块 2000 次、seed42 的 95% 区间仅为小样本描述；不用于宣称普遍优势。</li><li>缺少逐期首次发布版本；2026 年口径变化与此前时期的差异另列切片。</li></ul>
<p>模型：{MODEL_ID}@{REVISION}<br>权重 SHA-256：<code>{WEIGHTS_SHA}</code><br>报告指纹：<code>{report['report_id']}</code></p><p>离线 JSON 包与 CSV 保留全部 168 条开发/审计记录；指标重算不需要下载模型。</p></html>'''
    payload = {'version': 'chronos-synth-review-v1', 'report': report, 'protocol': protocol, 'provenance': provenance,
               'verification_limit': '数据和指标可离线重算；模型执行的依据是另存的本机运行记录与文件哈希。'}
    return {'json': json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False).encode('utf-8'),
            'csv': output.getvalue().encode('utf-8-sig'), 'html': document.encode('utf-8')}
