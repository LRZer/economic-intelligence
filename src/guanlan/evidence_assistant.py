"""Restricted offline research assistant: lexical retrieval + deterministic tools.

No LLM, key lookup, filesystem access, eval/SQL, or network in this module.
Gold/evaluation files are deliberately outside this application's imports.
"""
from __future__ import annotations

import csv
import html
import io
import json
import math
import re
import unicodedata

from sklearn.feature_extraction.text import TfidfVectorizer

from china_macro.catalog import INDICATORS
from guanlan.forecast import MODEL_KEYS, month_id, period_label
from guanlan.monthly_review import _inputs, build_monthly_review, canonical, digest, BASELINES

VERSION = "restricted-assistant-v1"
TOOLS = ("observation", "difference", "mean", "extrema", "evaluation", "forecast")
ALIASES = {
    "cpi_yoy": ["CPI同比", "居民消费价格同比", "消费价格同比"],
    "cpi_mom": ["CPI环比", "居民消费价格环比", "消费价格环比"],
    "ppi_yoy": ["PPI同比", "工业生产者出厂价格同比", "出厂价格同比"],
    "ppi_mom": ["PPI环比", "工业生产者出厂价格环比", "出厂价格环比"],
    "manufacturing_pmi": ["制造业PMI", "制造业采购经理指数"],
    "manufacturing_new_orders_pmi": ["制造业新订单", "新订单PMI", "制造业新订单PMI"],
    "nonmanufacturing_pmi": ["非制造业PMI", "非制造业商务活动指数"],
}
PROTOTYPES = {
    "observation": "查询官方观察读数 最新最近一期 当前公布值 数据是多少 具体数值 报告发布的读数 查一笔某月记录",
    "difference": "对比两个时期读数 算差值 较上月去年同月变化 相比差多少 两期落差 高低幅度 增减几点 变动多少百分点",
    "mean": "计算窗口平均读数 算术均值 平均数 区间均值 一段时间平均水平 连续几个月求均数",
    "extrema": "寻找区间最高最低读数 最大最小值 峰值谷值 极值 高点低点 哪月最高哪月最低",
    "evaluation": "审计预测模型 固定留出回测 模型比较基线 MAE误差 研究门槛 默认参考 通过优势没有 验证模型是否胜过简单方法",
    "forecast": "下一期下期 下一个统计期 预测研究估计 展示基线参考与Ridge实验估计 下一月模型预测值 尚未公布的研究预测",
}
REASONS = {
    "empty_question": "请输入一个研究问题。",
    "oversize_question": "问题超过400字，请缩小到一个指标和一个计算任务。",
    "unsafe_request": "请求包含凭据、文件、外部URL或越权指令；本助手只读取批准的公共数据，拒绝执行。",
    "unsupported_claim": "现有观察与统计模型不足以证明经济原因、交易策略或收益结论，拒绝生成该结论。",
    "historical_vintage": "当前数据为修订快照，没有当时首次发布版本，无法回答历史实时可得性。",
    "unsupported_indicator": "只支持中国七个已审核月度指标；该指标或问题不在本阶段范围内。",
    "ambiguous_indicator": "请明确一个指标及同比/环比口径；不能混合多个指标或猜测口径。",
    "ambiguous_period": "请明确本任务所需的一个期别或两个比较/窗口端点。",
    "ambiguous_operation": "一次只支持一个明确运算；请将均值、差值、最大和最小分开提问。",
    "invalid_period": "期别不是有效自然月，请使用YYYY-MM或YYYY年M月。",
    "missing_observation": "请求期别没有同口径官方观察；不把预测、最近记录或插值当作已发布数据。",
    "invalid_window": "窗口须为2—24个连续自然月，起点不得晚于终点，缺月不补。",
    "unsupported_operation": "无法可靠确定批准的计算工具，请改写为读数、差值、均值、极值、模型对照或下一期估计。",
    "historical_model": "模型审计只针对当前固定快照，不为历史问题重新选择留出、训练或参考方法。",
    "insufficient_model": "样本或必要自然月滞后不足，无法提供该模型结论。",
}


def normalize(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text)).lower()


class EvidenceStore:
    def __init__(self, rows: list[dict]):
        self.rows: dict[str, list[dict]] = {}
        self.specs = {}
        self.models: dict[str, dict] = {}
        for key in MODEL_KEYS:
            part = [r for r in rows if r.get("key") == key]
            if not part:
                continue
            definition = INDICATORS[key]
            spec = {"key": key, "name": definition[0], "basis": definition[2], "unit": definition[3]}
            self.specs[key], self.rows[key] = _inputs(spec, part)
        if not self.rows:
            raise ValueError("没有批准的月度来源")
        self.source_rows = [row for key in sorted(self.rows) for row in self.rows[key]]
        self.snapshot_hash = digest(self.source_rows)
        self.index = {f"obs:{r['key']}:{r['period']}": {"id": f"obs:{r['key']}:{r['period']}",
                      "kind": "official_observation", **r} for r in self.source_rows}
        self.intent_vectorizer = TfidfVectorizer(analyzer="char", ngram_range=(2, 4), sublinear_tf=True)
        self.intent_matrix = self.intent_vectorizer.fit_transform([normalize(PROTOTYPES[t]) for t in TOOLS])
        self.source_ids = list(self.index)
        self.evidence_vectorizer = TfidfVectorizer(analyzer="char", ngram_range=(2, 4), sublinear_tf=True)
        descriptions = [f"{r['period']} {' '.join(ALIASES[r['key']])} {self.specs[r['key']]['basis']} 官方观察" for r in self.index.values()]
        self.evidence_matrix = self.evidence_vectorizer.fit_transform(descriptions)

    def model(self, key: str) -> dict:
        if key not in self.models:
            self.models[key] = build_monthly_review(self.specs[key], self.rows[key])["model"]
        return self.models[key]

    def retrieve(self, key: str, periods: list[str], question: str) -> tuple[list[dict], dict]:
        ids = [f"obs:{key}:{period}" for period in periods]
        if any(eid not in self.index for eid in ids):
            raise ValueError("missing_observation")
        scores = (self.evidence_matrix @ self.evidence_vectorizer.transform([normalize(question)]).T).toarray().ravel()
        score_map = dict(zip(self.source_ids, scores))
        ranked = sorted(ids, key=lambda eid: (-float(score_map[eid]), eid))
        return [self.index[eid] for eid in ids], {"method": "hard_indicator_and_period_filter_then_char_tfidf",
                "selected_ids": ids, "ranking": [{"id": eid, "score": round(float(score_map[eid]), 6)} for eid in ranked]}


def _route(question: str, store: EvidenceStore, policy: str, threshold: float) -> tuple[str | None, dict]:
    q = normalize(question)
    if policy == "keyword":
        if any(x in q for x in ("下期", "下一期", "预测值")): tool = "forecast"
        elif any(x in q for x in ("mae", "门槛", "基线", "回测")): tool = "evaluation"
        elif any(x in q for x in ("平均", "均值")): tool = "mean"
        elif any(x in q for x in ("最高", "最低")): tool = "extrema"
        elif any(x in q for x in ("差值", "相比", "变化")): tool = "difference"
        else: tool = "observation"
        return tool, {"policy": "keyword", "method": "predeclared_keyword_baseline"}
    if policy != "tfidf" or not 0 <= threshold <= 1:
        raise ValueError("路由参数无效")
    scores = (store.intent_matrix @ store.intent_vectorizer.transform([q]).T).toarray().ravel()
    best = int(scores.argmax())
    ranking = sorted([(TOOLS[i], round(float(score), 6)) for i, score in enumerate(scores)], key=lambda row: -row[1])
    # An explicit arithmetic operator must not be overridden by lexical similarity.
    # This development-stage constraint fixes the observed "差值" routing failure.
    if "差值" in q:
        return "difference", {"policy":"tfidf", "threshold":threshold, "method":"explicit_difference_operator_then_char_tfidf",
                              "ranking":[{"tool":name,"score":score} for name,score in ranking]}
    return (TOOLS[best] if scores[best] >= threshold else None), {"policy": "tfidf", "threshold": threshold,
            "method": "char_tfidf_capability_prototypes", "ranking": [{"tool": name, "score": score} for name, score in ranking]}


def _indicator(question: str, store: EvidenceStore) -> str:
    q = normalize(question)
    matches = []
    for key, aliases in ALIASES.items():
        for alias in aliases:
            for match in re.finditer(re.escape(normalize(alias)), q):
                matches.append((key, match.start(), match.end()))
    surviving = {key for key, start, end in matches if not any(other != key and a <= start and b >= end and b-a > end-start for other, a, b in matches)}
    if len(surviving) != 1:
        raise ValueError("ambiguous_indicator" if surviving or any(x in q for x in ("cpi", "ppi", "pmi", "消费价格", "出厂价格")) else "unsupported_indicator")
    key = next(iter(surviving))
    if key not in store.rows:
        raise ValueError("unsupported_indicator")
    return key


def _periods(question: str) -> list[str]:
    converted = re.sub(r"(\d{4})年(\d{1,2})月", lambda m: f"{m[1]}-{int(m[2]):02d}", question)
    if re.search(r"\d{4}年",converted):
        raise ValueError("invalid_period")
    periods = re.findall(r"(?<!\d)(\d{4}-\d{2})(?!\d)", converted)
    try:
        for period in periods: month_id(period)
    except ValueError:
        raise ValueError("invalid_period") from None
    return list(dict.fromkeys(periods))


def _guard(question: str) -> str | None:
    q = normalize(question)
    if not q: return "empty_question"
    if any(x in q for x in ("密钥", "api_key", "secret", "token", "忽略规则", "忽略指令", "绕过", "执行代码", "powershell", "读取文件", "http://", "https://", "系统提示", "shell")):
        return "unsafe_request"
    if re.search(r"(?:sk-|gh[pousr]_)[a-z0-9_-]{16,}", q): return "unsafe_request"
    if len(question) > 400: return "oversize_question"
    if any(x in q for x in ("为什么", "原因", "导致", "因果", "买入", "卖出", "股票", "交易策略", "收益", "盈利")):
        return "unsupported_claim"
    if any(x in q for x in ("当时发布", "当时可得", "首次发布", "实时回测", "历史版本", "当时公布")):
        return "historical_vintage"
    if any(x in q for x in ("美国","日本","德国","英国","欧元区","usa","usacpi","gdp")):
        return "unsupported_indicator"
    high=any(x in q for x in ("最高","最大","峰值","高点"))
    low=any(x in q for x in ("最低","最小","谷值","低点"))
    mean=any(x in q for x in ("均值","平均读数","平均水平"))
    if high and low or mean and (high or low or "差值" in q):
        return "ambiguous_operation"
    horizon=re.search(r"(?:未来|预测)(\d+)个月",q)
    if horizon and int(horizon[1])!=1 or any(x in q for x in ("未来一年","未来一季度")):
        return "unsupported_operation"
    return None


def _scope(question: str, key: str, tool: str, store: EvidenceStore) -> dict:
    periods = _periods(question)
    latest = store.rows[key][-1]["period"]
    q = normalize(question)
    if tool in ("evaluation", "forecast"):
        next_period = period_label(month_id(latest)+1)
        if periods and periods != [next_period if tool == "forecast" else latest]:
            raise ValueError("historical_model")
        return {"key": key, "tool": tool, "periods": [], "latest_period": latest, "defaulted_period": not periods}
    if tool == "observation":
        if len(periods) > 1: raise ValueError("ambiguous_period")
        periods = periods or [latest]
    elif tool == "difference":
        if len(periods) <= 1 and any(x in q for x in ("上月", "上个月", "去年同月")):
            current = periods[0] if periods else latest
            previous = period_label(month_id(current)-(12 if "去年同月" in q else 1))
            periods = [previous, current]
        if len(periods) != 2: raise ValueError("ambiguous_period")
        periods = sorted(periods)
    elif tool in ("mean", "extrema"):
        window = re.search(r"(?:近|最近)(\d{1,2})个月", q)
        if not periods and window:
            n = int(window[1])
            periods = [period_label(month_id(latest)-n+1), latest]
        if len(periods) != 2: raise ValueError("ambiguous_period")
        start, end = map(month_id, periods)
        if not 2 <= end-start+1 <= 24: raise ValueError("invalid_window")
        periods = [period_label(month) for month in range(start, end+1)]
    return {"key": key, "tool": tool, "periods": periods, "latest_period": latest,
            "defaulted_period": not _periods(question), "direction": "min" if any(x in q for x in ("最低", "最小", "谷值", "低点")) else "max"}


def answer_question(question: str, store: EvidenceStore, *, policy: str = "tfidf", threshold: float = .08) -> dict:
    if not isinstance(question, str): raise ValueError("问题必须是文本")
    reason = _guard(question)
    display_question = "[敏感或越权内容已省略]" if reason == "unsafe_request" else "[超长问题已省略]" if reason == "oversize_question" else question
    base = {"version": VERSION, "question": display_question, "snapshot_hash": store.snapshot_hash,
            "policy": policy, "threshold": threshold, "network_requests": 0, "llm_used": False,
            "limitations": ["字符TF-IDF与受限工具的离线助手，不是生成式大模型。", "当前修订快照不证明历史实时可得，不作因果或投资判断。"]}
    scope: dict | None = None
    routing: dict = {}
    try:
        if reason: raise ValueError(reason)
        key = _indicator(question, store)
        tool, routing = _route(question, store, policy, threshold)
        if tool is None: raise ValueError("unsupported_operation")
        scope = _scope(question, key, tool, store)
        spec = store.specs[key]
        numbers: dict = {}
        details: dict = {}
        evidence, retrieval = store.retrieve(key, scope["periods"], question)
        if tool in ("evaluation", "forecast"):
            model = store.model(key)
            if model["status"] != "evaluated": raise ValueError("insufficient_model")
            eid = f"model:{key}:{model['snapshot_hash']}"
            ids = [f"obs:{key}:{r['period']}" for r in store.rows[key]]
            evidence = [{"id": eid, "kind": "model_evaluation", "key": key, "model_snapshot_hash": model["snapshot_hash"],
                         "version": model["version"], "source_ids": ids, "model": model}]
            retrieval = {"method": "fixed_model_by_indicator", "selected_ids": [eid]}
            if tool == "evaluation":
                scores = model["metrics"]["test"]
                numbers = {"ridge_mae": scores["ridge"]["mae"], "persistence_mae": scores["persistence"]["mae"],
                           "seasonal_mae": scores["seasonal"]["mae"], "test_n": model["test_n"]}
                details = {"gate_passed": model["passes_research_gate"], "default_method": model["baseline"],
                           "test_start": model["test_start"]}
                text = f"{spec['name']}固定留出：Ridge MAE {numbers['ridge_mae']:.3f}，上一月值 {numbers['persistence_mae']:.3f}，去年同月值 {numbers['seasonal_mae']:.3f}。研究门槛{'通过但须独立验证' if details['gate_passed'] else '未通过'}；默认参考为开发验证期选定的{BASELINES[model['baseline']]}，不按留出重选。"
            else:
                forecast = model.get("forecast")
                if not forecast: raise ValueError("insufficient_model")
                numbers = {"reference": forecast["baseline"], "experimental": forecast["ridge"]}
                details = {"target_period": forecast["period"], "train_end": forecast["train_end"], "default_method": model["baseline"],
                           "gate_passed": model["passes_research_gate"]}
                text = f"{forecast['period']}研究估计：默认基线 {numbers['reference']:.3f}%，Ridge实验 {numbers['experimental']:.3f}%。尚非官方观察；实验模型{'通过固定门槛但需验证' if details['gate_passed'] else '未通过固定研究门槛'}，不作交易建议。"
        elif tool == "observation":
            numbers = {"value": evidence[0]["value"]}
            text = f"{evidence[0]['period']} {spec['name']}（{spec['basis']}）官方读数 {numbers['value']:g}%。"
        elif tool == "difference":
            numbers = {"reference": evidence[0]["value"], "current": evidence[1]["value"], "delta": evidence[1]["value"]-evidence[0]["value"]}
            unit = "指数百分点" if "pmi" in key else "百分点"
            details = {"unit": unit}
            text = f"{scope['periods'][1]}读数 {numbers['current']:g}% 减 {scope['periods'][0]}读数 {numbers['reference']:g}% = {numbers['delta']:+.3f} {unit}。这是读数差，不是重新计算的增长率。"
        elif tool == "mean":
            numbers = {"mean": math.fsum(r["value"] for r in evidence)/len(evidence), "n": len(evidence)}
            text = f"{scope['periods'][0]}至{scope['periods'][-1]}共 {numbers['n']} 个连续自然月，{spec['name']}读数的算术均值 {numbers['mean']:.3f}%。不解释为累计增长或价格水平。"
        else:
            value = (min if scope["direction"] == "min" else max)(r["value"] for r in evidence)
            numbers = {"value": value, "n": len(evidence)}
            details = {"direction": scope["direction"], "extreme_periods": [r["period"] for r in evidence if r["value"] == value]}
            text = f"{scope['periods'][0]}至{scope['periods'][-1]}，{spec['name']}读数{'最低' if scope['direction']=='min' else '最高'}为 {value:g}%；期别 {'、'.join(details['extreme_periods'])}。并列值全部保留。"
        trace = {"tool": tool, "arguments": scope, "evidence_ids": [r["id"] for r in evidence], "numbers": numbers, "details": details}
        result = {**base, "status": "answered", "reason": None, "scope": scope, "routing": routing, "retrieval": retrieval,
                  "answer": text, "numbers": numbers, "details": details, "evidence": evidence, "trace": trace}
    except ValueError as error:
        code = str(error)
        if code not in REASONS: raise
        result = {**base, "status": "clarify" if code in {"ambiguous_indicator", "ambiguous_period", "ambiguous_operation", "unsupported_operation", "empty_question"} else "refused",
                  "reason": code, "scope": scope, "routing": routing, "retrieval": {}, "answer": REASONS[code],
                  "numbers": {}, "details": {}, "evidence": [], "trace": None}
    return {**result, "answer_id": digest(result)}


def export_answer(answer: dict, store: EvidenceStore) -> dict[str, bytes]:
    if answer["answer_id"] != digest({k: v for k, v in answer.items() if k != "answer_id"}) or answer["snapshot_hash"] != store.snapshot_hash:
        raise ValueError("答案身份不一致")
    report = {"schema_version": VERSION, "answer": answer, "source_rows": store.source_rows}
    report["report_id"] = digest(report)
    encoded = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
    sources = []
    provenance = "外部计划来源未核验；数值由本地工具计算，未证明LLM业务质量。" if "tool_plan" in answer else "离线字符检索与确定性工具，未调用LLM。"
    for row in answer["evidence"]:
        if row["kind"] == "official_observation":
            sources.append(f'<li><a href="{html.escape(row["source_url"],quote=True)}">{html.escape(row["period"])}官方原文</a>：{row["value"]:g}%</li>')
        else:
            sources.append('<li>当前固定快照的本地模型回测；完整输入和指标见审计JSON。</li>')
    document = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>观澜 · 证据问答</title>
<style>body{{font:16px/1.65 system-ui,sans-serif;max-width:940px;margin:36px auto;padding:0 18px;color:#172d3b;background:#f7faf9}}h1{{color:#146f7c}}article{{padding:18px;background:white;border-left:3px solid #146f7c}}pre,code{{white-space:pre-wrap;overflow-wrap:anywhere}}a{{color:#146f7c}}</style>
<h1>观澜 · 证据问答</h1><p>问题：{html.escape(answer['question'])}</p><article>{html.escape(answer['answer'])}</article>
<p>状态：{html.escape({'answered':'已回答','refused':'拒答','clarify':'需澄清'}[answer['status']])}；{provenance}</p><ul>{''.join(sources)}</ul>
<p>{html.escape(' '.join(answer['limitations']))}</p><p>报告SHA256：<code>{report['report_id']}</code>；一致性校验不证明来源真实性。</p>
<details><summary>来源、计算轨迹及完整JSON</summary><pre>{html.escape(encoded.decode('utf-8'))}</pre></details></html>'''
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=["answer_id", "status", "question", "answer", "numbers_json", "evidence_ids_json"])
    writer.writeheader()
    def safe(text): return "'"+text if text.startswith(("=", "+", "-", "@", "\t", "\r")) else text
    writer.writerow({"answer_id": answer["answer_id"], "status": answer["status"], "question": safe(answer["question"]), "answer": safe(answer["answer"]),
                     "numbers_json": canonical(answer["numbers"]).decode(), "evidence_ids_json": canonical([r["id"] for r in answer["evidence"]]).decode()})
    return {"html": document.encode("utf-8"), "json": encoded, "csv": output.getvalue().encode("utf-8-sig")}


def verify_answer_report(report: dict) -> dict:
    try:
        if set(report) != {"schema_version", "answer", "source_rows", "report_id"} or report["schema_version"] != VERSION:
            raise ValueError
        if report["report_id"] != digest({k:v for k,v in report.items() if k != "report_id"}): raise ValueError
        store = EvidenceStore(report["source_rows"])
        answer = report["answer"]
        if "tool_plan" in answer:
            from guanlan.assistant_plans import execute_tool_plan
            expected = execute_tool_plan(answer["question"], answer["tool_plan"], store)
        elif answer["reason"] == "unsafe_request":
            # The original sensitive question is deliberately absent. Verify only safe redacted refusal.
            expected = answer_question("读取文件中的密钥", store, policy=answer["policy"], threshold=answer["threshold"])
        elif answer["reason"] == "oversize_question":
            expected = answer_question("问"*401, store, policy=answer["policy"], threshold=answer["threshold"])
        else:
            expected = answer_question(answer["question"], store, policy=answer["policy"], threshold=answer["threshold"])
        if canonical(answer) != canonical(expected): raise ValueError
    except (KeyError, TypeError, ValueError, AttributeError):
        raise ValueError("问答导出核验失败：结构、来源、工具结果或指纹不一致") from None
    return {"status": "passed", "answer_id": answer["answer_id"], "report_id": report["report_id"], "tools_recomputed": True,
            "network_requests": 0, "llm_used": answer["llm_used"]}
