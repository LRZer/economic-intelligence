from __future__ import annotations

import hashlib
import html
import json
import logging
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from guanlan.catalog import country_label
from guanlan.data import DEFAULT_DATA_DIR, load_snapshot, snapshot_catalog, snapshot_paths

ROOT = Path(__file__).resolve().parents[3]
PALETTE = ["#146f7c", "#b95d42", "#526eaa", "#856298", "#557c50", "#967027"]
COUNTRY_COLORS = dict(zip(["CHN", "USA", "DEU", "JPN", "IND", "GBR"], PALETTE))
INDICATOR_COLORS = {"NY.GDP.MKTP.KD.ZG": "#146f7c", "FP.CPI.TOTL.ZG": "#b95d42",
                    "exports_usd": "#146f7c", "imports_usd": "#b95d42"}
SOURCE_NAMES = {"sector_latest":"行业研究估计", "sector_backtest":"行业研究评估", "sector_features":"宏观行业联合特征", "macro": "世界银行 WDI", "weo": "IMF WEO", "bis_policy": "BIS 政策利率",
                "bis_credit": "BIS 信贷", "bis_eer": "BIS 有效汇率", "baci_partner": "CEPII BACI 伙伴",
                "baci_chapter": "CEPII BACI 商品", "trade": "Comtrade 贸易样本",
                "us_monthly": "美国官方月度数据", "us_cycle_backtest": "美国模型回测"}


def log_failure(module: str, exc: Exception) -> str:
    """诊断留在服务端；界面仅提供追踪编号，不打印凭据或请求正文。"""
    folder = ROOT / "output"
    folder.mkdir(exist_ok=True)
    logger = logging.getLogger("guanlan.ui")
    if not logger.handlers:
        handler = logging.FileHandler(folder / "diagnostics.log", encoding="utf-8")
        logger.addHandler(handler)
        logger.setLevel(logging.ERROR)
    reference = hashlib.sha256(f"{module}:{type(exc).__name__}:{pd.Timestamp.now()}".encode()).hexdigest()[:10]
    logger.error("%s %s", reference, module, exc_info=(type(exc), exc, exc.__traceback__))
    return reference


@st.cache_data(show_spinner=False)
def cached_snapshot(stem: str, reference: str, data_mtime: int, meta_mtime: int):
    return load_snapshot(stem, snapshot_map={stem: reference})


class DataStore:
    """按页面需要加载。一个来源失败不会阻断其他来源。"""

    def __init__(self):
        self.loaded = {}
        self.errors = {}
        self.notified = set()
        try:
            self.references = snapshot_catalog()
        except Exception as exc:
            self.references = None
            self.catalog_error = log_failure("活动快照目录", exc)

    def get(self, stem: str, *, quiet=False):
        if stem not in self.loaded:
            try:
                if self.references is None:
                    raise ValueError("活动目录无法验证，拒绝静默回退到旧快照")
                reference = self.references.get(stem, stem)
                parquet, metadata = snapshot_paths(stem, DEFAULT_DATA_DIR, {stem: reference})
                self.loaded[stem] = cached_snapshot(stem, reference, parquet.stat().st_mtime_ns,
                                                    metadata.stat().st_mtime_ns)
            except Exception as exc:
                ref = log_failure(SOURCE_NAMES.get(stem, stem), exc)
                self.loaded[stem] = (pd.DataFrame(), {})
                self.errors[stem] = ("快照未安装" if isinstance(exc, FileNotFoundError) else "快照无法校验", ref)
        if stem in self.errors and not quiet and stem not in self.notified:
            self.notified.add(stem)
            status, ref = self.errors[stem]
            st.warning(f"{SOURCE_NAMES.get(stem, stem)}：{status}。其他已加载模块仍可使用。诊断编号 {ref}。")
            if st.button("重新加载此来源", key=f"retry_{stem}"):
                cached_snapshot.clear()
                st.rerun()
        return self.loaded[stem]

    def trade(self, *, quiet=False):
        return self.get("baci_partner", quiet=quiet)


def run_module(name, renderer):
    try:
        return renderer()
    except Exception as exc:
        ref = log_failure(name, exc)
        st.error(f"{name}暂时无法显示。可重新加载；已加载的其他内容仍然可用。诊断编号 {ref}。")
        if st.button("重试此模块", key=f"retry_module_{name}"):
            cached_snapshot.clear()
            st.rerun()


def date_label(meta):
    stamp = meta.get("downloaded_at_utc")
    if not stamp:
        return "未提供"
    return pd.to_datetime(stamp, utc=True).tz_convert("Asia/Shanghai").strftime("%Y-%m-%d")


def header(title, description=""):
    st.markdown(f'<div class="page-heading" translate="no"><h1>{html.escape(title)}</h1>'
                f'<p>{html.escape(description)}</p></div>', unsafe_allow_html=True)


def source_line(meta, detail=""):
    provider=meta.get('provider') or '未提供'
    provider={"World Bank WDI":"世界银行 WDI","Bank for International Settlements (BIS)":"国际清算银行 BIS",
              "IMF WEO DataMapper":"IMF WEO DataMapper","CEPII BACI":"CEPII BACI"}.get(provider,provider)
    if provider.startswith("BLS + Federal Reserve Board"):
        provider="BLS 与美联储理事会（直接官方来源）"
    st.caption(f"来源：{provider} · 已加载快照 {date_label(meta)}" +
               (f" · {detail}" if detail else ""))


def source_details(meta):
    with st.expander("查看数据版本与口径"):
        st.write(meta.get("scope") or meta.get("provider") or "来源未提供范围说明。")
        if meta.get("source_url"):
            st.markdown(f"[打开原始数据来源]({meta['source_url']})")
        st.caption(f"来源更新日期：{meta.get('source_last_updated') or '未提供'}；下载日期：{date_label(meta)}。")
        st.code(meta.get("parquet_sha256") or "快照校验值未提供", language=None)


def _restore(key, default):
    saved = f"saved_{key}"
    if key not in st.session_state:
        st.session_state[key] = st.session_state.get(saved, default)


def _remember(key):
    st.session_state[f"saved_{key}"] = st.session_state[key]


def select(label, options, key, default=None, *, format_func=str):
    options = list(options)
    default = default if default in options else options[0]
    _restore(key, default)
    if st.session_state[key] not in options:
        st.session_state[key] = default
    value = st.selectbox(label, options, key=key, format_func=format_func,
                         on_change=_remember, args=(key,))
    _remember(key)
    return value


def radio(label, options, key, default=None):
    default = default if default in options else options[0]
    _restore(key, default)
    if st.session_state[key] not in options:
        st.session_state[key] = default
    value = st.radio(label, options, horizontal=True, key=key, on_change=_remember, args=(key,))
    _remember(key)
    return value


def multi(label, options, key, defaults, *, format_func=str, limit=6):
    options = list(options)
    _restore(key, [x for x in defaults if x in options])
    st.session_state[key] = [x for x in st.session_state[key] if x in options]
    value = st.multiselect(label, options, key=key, format_func=format_func,
                           on_change=_remember, args=(key,))
    _remember(key)
    if not value or len(value) > limit:
        st.info(f"请选择 1—{limit} 项。")
        return []
    return value


def initial_query(key, default=""):
    return st.session_state.get("initial_query", {}).get(key, default)


def query_list(key, allowed, default):
    requested = list(dict.fromkeys(x for x in initial_query(key).split(",") if x in allowed))
    return requested or default


def sync_query(**values):
    """一次写入当前页面上下文；不再从旧 URL 覆盖正在交互的状态。"""
    values = {k: str(v) for k, v in values.items() if v is not None}
    if st.query_params.to_dict() != values:
        st.query_params.from_dict(values)


def macro_selection(store, page, *, country_label_text="经济体", year_label="数据年度"):
    macro, meta = store.get("macro")
    if macro.empty:
        return None
    names = macro.drop_duplicates("country_code").set_index("country_code").country_name.to_dict()
    countries = sorted(names, key=lambda c: country_label(c, names[c]))
    years = sorted(map(int, macro.year.unique()), reverse=True)
    inherited = st.session_state.get("research_selection", {})
    country_default = inherited.get("country", initial_query("country", "CHN"))
    year_default = inherited.get("year", initial_query("year", "2024"))
    try:
        year_default = int(year_default)
    except (ValueError, TypeError):
        year_default = 2024
    if f"saved_{page}_country" not in st.session_state and country_default not in countries:
        country_default_label=country_label(country_default, country_default)
        country_default="CHN" if "CHN" in countries else countries[0]
        st.info(f"{country_default_label}不在本页 WDI 快照的经济体集合中。当前选择 {country_label(country_default,names[country_default])}，请按研究任务选择。")
    if f"saved_{page}_year" not in st.session_state and year_default not in years:
        st.info(f"本页快照不包含 {year_default} 年，当前使用 {years[0]} 年。")
    a, b = st.columns([2, 1])
    with a:
        country = select(country_label_text, countries, f"{page}_country", country_default,
                         format_func=lambda c: country_label(c, names[c]))
    with b:
        year = select(year_label, years, f"{page}_year", year_default)
    st.session_state["research_selection"] = {"country": country, "year": year}
    return macro, meta, country, year, names


def color_for(identifier):
    if identifier in INDICATOR_COLORS:
        return INDICATOR_COLORS[identifier]
    if identifier in COUNTRY_COLORS:
        return COUNTRY_COLORS[identifier]
    return PALETTE[int(hashlib.sha256(identifier.encode()).hexdigest()[:8], 16) % len(PALETTE)]


def color_map(names):
    return {country_label(code, name): color_for(code) for code, name in names.items()}


def chart(fig, *, key=None):
    fig.update_layout(font=dict(family="Microsoft YaHei, Noto Sans SC, sans-serif", size=13, color="#405664"),
                      title_font=dict(size=16, color="#183642"), paper_bgcolor="white",
                      hoverlabel=dict(bgcolor="#193846", font=dict(color="white", size=13)))
    if fig.layout.plot_bgcolor is None:
        fig.update_layout(plot_bgcolor="white")
    if not any(t.type == "choropleth" for t in fig.data):
        fig.update_xaxes(tickfont=dict(size=12, color="#506673"), showgrid=False, linecolor="#cbd9de")
        fig.update_yaxes(tickfont=dict(size=12, color="#506673"), gridcolor="#e6edef", zerolinecolor="#a9bec6")
    st.plotly_chart(fig, width="stretch", key=key,
                    config={"displaylogo": False, "responsive": True,
                            "modeBarButtonsToRemove": ["lasso2d", "select2d", "autoScale2d"]})


def history_chart(frame, title, unit, names, *, indicator=None, height=380, selected_year=None, area=False):
    # 保留缺失记录，Plotly 在缺失期断线；不把过滤后的有效值连成完整历史。
    rows = frame.copy().sort_values(["country_code", "year"])
    rows["经济体"] = rows.country_code.map(lambda c: country_label(c, names.get(c, c)))
    colors = color_map(names)
    if indicator and rows.country_code.nunique() == 1:
        colors = {label: color_for(indicator) for label in rows["经济体"].unique()}
    fig = px.line(rows, x="year", y="value", color="经济体", color_discrete_map=colors, title=title)
    fig.update_traces(line_width=2.8, connectgaps=False,
                      hovertemplate=f"%{{x:.0f}} 年<br>%{{y:,.2f}} {unit}<extra>%{{fullData.name}}</extra>")
    fig.update_layout(height=height, margin=dict(l=30, r=22, t=55, b=45), yaxis_title=unit,
                      xaxis_title="", hovermode="x unified", legend=dict(orientation="h", y=-.16, title_text=""))
    fig.update_xaxes(tickformat="d")
    if rows.country_code.nunique() == 1:
        fig.update_layout(showlegend=False)
        if area:
            fig.update_traces(fill="tozeroy", fillcolor="rgba(20,111,124,.08)")
            fig.update_yaxes(rangemode="tozero")
        if selected_year is not None:
            point = rows.loc[(rows.year == selected_year) & rows.value.notna()]
            if not point.empty:
                value = float(point.value.iloc[0])
                accent = color_for(indicator or point.country_code.iloc[0])
                fig.add_vline(x=selected_year, line_color="#9bafb9", line_dash="dot", line_width=1)
                fig.add_trace(go.Scatter(x=[selected_year], y=[value], mode="markers", showlegend=False,
                                         marker=dict(size=10, color="white", line=dict(color=accent, width=3)),
                                         hovertemplate=f"{selected_year} 年：{value:.2f} {unit}<extra></extra>"))
    return fig


def csv_bytes(frame):
    return frame.to_csv(index=False).encode("utf-8-sig")


def download(frame, filename, label="下载当前数据 · CSV", meta=None):
    exported = frame.copy()
    if meta:
        for field in ("provider", "source_url", "parquet_sha256", "downloaded_at_utc"):
            exported[field] = meta.get(field)
    st.download_button(label, csv_bytes(exported), file_name=filename, mime="text/csv")


def number(value, precision=2, suffix="", missing="本期无有效值"):
    return missing if pd.isna(value) else f"{float(value):,.{precision}f}{suffix}"


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()
