"""Direct BLS and Federal Reserve Board monthly data; no intermediary data feed."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import requests

BLS_URL = 'https://api.bls.gov/publicAPI/v2/timeseries/data/'
IP_URL = 'https://www.federalreserve.gov/releases/g17/Current/ipdisk/ip_sa.txt'
H15_URL = 'https://www.federalreserve.gov/datadownload/Output.aspx'
H15_PARAMS = {'rel': 'H15', 'series': 'd7e27b7b09a3a7feae95b9c61781fcd8',
              'lastobs': '1000', 'from': '', 'to': '', 'filetype': 'csv',
              'label': 'include', 'layout': 'seriescolumn', 'type': 'package'}
BLS_CODES = {'CUSR0000SA0': 'CPI_SA', 'LNS14000000': 'UNEMP_SA'}
RATE_CODES = {'RIFSPFF_N.M': 'EFFR', 'RIFLGFCY02_N.M': 'UST2Y', 'RIFLGFCY10_N.M': 'UST10Y'}
SERIES = {
    'CPI_SA': {'name': '全城市消费者价格指数', 'unit': '1982—1984=100', 'origin': '美国劳工统计局', 'native_code': 'CUSR0000SA0', 'seasonal_adjustment': 'SA', 'source_url': 'https://www.bls.gov/cpi/'},
    'UNEMP_SA': {'name': 'U-3失业率', 'unit': '%', 'origin': '美国劳工统计局', 'native_code': 'LNS14000000', 'seasonal_adjustment': 'SA', 'source_url': 'https://www.bls.gov/cps/'},
    'IP_SA': {'name': '总工业产出指数', 'unit': '2017=100', 'origin': '美联储理事会', 'native_code': 'B50001', 'seasonal_adjustment': 'SA', 'source_url': 'https://www.federalreserve.gov/releases/g17/'},
    'EFFR': {'name': '有效联邦基金利率（月均）', 'unit': '% / 年', 'origin': '美联储理事会', 'native_code': 'RIFSPFF_N.M', 'seasonal_adjustment': 'NSA', 'source_url': 'https://www.federalreserve.gov/releases/h15/'},
    'UST2Y': {'name': '2年期国债固定期限市场收益率（月均）', 'unit': '% / 年', 'origin': '美联储理事会', 'native_code': 'RIFLGFCY02_N.M', 'seasonal_adjustment': 'NSA', 'source_url': 'https://www.federalreserve.gov/releases/h15/'},
    'UST10Y': {'name': '10年期国债固定期限市场收益率（月均）', 'unit': '% / 年', 'origin': '美联储理事会', 'native_code': 'RIFLGFCY10_N.M', 'seasonal_adjustment': 'NSA', 'source_url': 'https://www.federalreserve.gov/releases/h15/'},
}
POLICIES = {
    'bls-copyright.html': 'https://www.bls.gov/bls/linksite.htm',
    'bls-api-terms.html': 'https://www.bls.gov/developers/termsOfService.htm',
    'fed-disclaimer.html': 'https://www.federalreserve.gov/disclaimer.htm',
    'g17-series-documentation.txt': 'https://www.federalreserve.gov/releases/g17/Current/ipdisk/g17tab1.txt',
}


def numeric(value: object) -> float | None:
    token = str(value).strip()
    if token in {'ND', 'NA', '.', '', 'None'}:
        return None
    try:
        result = float(token)
    except ValueError as exc:
        raise ValueError('官方序列含无法解析的非缺失数值') from exc
    if not math.isfinite(result):
        raise ValueError('官方序列含非有限数值')
    return result


def monthly_frame(rows: list[dict]) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=['date', 'series_code', 'value'])
    if frame.empty:
        raise ValueError('官方序列为空')
    frame['date'] = pd.to_datetime(frame.date, errors='coerce')
    if frame.date.isna().any() or (frame.date.dt.day != 1).any():
        raise ValueError('官方月度期别无效')
    if frame.duplicated(['date', 'series_code']).any():
        raise ValueError('官方月度序列有重复期别')
    output = []
    for code, part in frame.groupby('series_code', sort=True):
        calendar = pd.DataFrame({'date': pd.date_range(part.date.min(), part.date.max(), freq='MS')})
        part = calendar.merge(part[['date', 'value']], on='date', validate='one_to_one', how='left')
        part['series_code'] = code
        output.append(part[['date', 'series_code', 'value']])
    return pd.concat(output, ignore_index=True).sort_values(['series_code', 'date']).reset_index(drop=True)


def parse_bls(payload: dict) -> tuple[list[dict], list[dict]]:
    if payload.get('status') != 'REQUEST_SUCCEEDED' or payload.get('message'):
        raise ValueError('BLS请求未完整成功；拒绝使用被截断或限流的结果')
    result = payload.get('Results', {})
    if isinstance(result, list):
        result = result[0] if len(result) == 1 else {}
    series = result.get('series', [])
    if {s.get('seriesID') for s in series} != set(BLS_CODES):
        raise ValueError('BLS响应的序列集合与请求不一致')
    rows, footnotes = [], []
    for item in series:
        code = BLS_CODES[item['seriesID']]
        for row in item['data']:
            period = row['period']
            if period == 'M13':
                continue  # annual average must never become a monthly observation
            if period not in {f'M{i:02}' for i in range(1, 13)}:
                raise ValueError('BLS月度期别无效')
            date = f"{int(row['year']):04}-{int(period[1:]):02}-01"
            value = row['value']
            if value == '-':
                if not any('data unavailable' in note.get('text', '').lower() for note in row.get('footnotes', [])):
                    raise ValueError('BLS缺失符号没有官方缺失说明')
                value = None
            rows.append({'date': date, 'series_code': code, 'value': numeric(value)})
            for note in row.get('footnotes', []):
                if note.get('text'):
                    footnotes.append({'date': date, 'series_code': code, **note})
    return rows, footnotes


def parse_ip(content: bytes) -> list[dict]:
    rows = []
    for line in content.decode('utf-8-sig').splitlines():
        tokens = line.split()
        if not tokens or tokens[0] != '"B50001"':
            continue
        if not 3 <= len(tokens) <= 14 or not tokens[1].isdigit():
            raise ValueError('G.17总工业产出行结构异常')
        for month, value in enumerate(tokens[2:], 1):
            rows.append({'date': f'{int(tokens[1]):04}-{month:02}-01', 'series_code': 'IP_SA', 'value': numeric(value)})
    if not rows:
        raise ValueError('G.17没有B50001总指数')
    return rows


def parse_h15(content: bytes) -> list[dict]:
    lines = list(csv.reader(io.StringIO(content.decode('utf-8-sig'))))
    header_index = next((i for i, line in enumerate(lines) if line and line[0] == 'Time Period'), None)
    if header_index is None:
        raise ValueError('H.15没有月度表头')
    header = lines[header_index]
    if len(set(header)) != len(header) or not set(RATE_CODES).issubset(header):
        raise ValueError('H.15序列代码缺失或重复')
    metadata = {line[0].strip().rstrip(':').strip(): line for line in lines[:header_index] if line}
    for native in RATE_CODES:
        idx = header.index(native)
        if (metadata.get('Multiplier', [])[idx] != '1' or
                not metadata.get('Unit', [])[idx].startswith('Percent') or
                metadata.get('Unique Identifier', [])[idx] != f'H15/H15/{native}'):
            raise ValueError('H.15单位、倍数或序列身份改变')
    rows = []
    for line in lines[header_index+1:]:
        if not line:
            continue
        if len(line) != len(header):
            raise ValueError('H.15数据行结构异常')
        for native, code in RATE_CODES.items():
            date = pd.Period(line[0], freq='M').start_time
            if line[0] != date.strftime('%Y-%m'):
                raise ValueError('H.15不是自然月期别')
            rows.append({'date': date, 'series_code': code, 'value': numeric(line[header.index(native)])})
    return rows


def fetch_us_monthly(start_year: int = 1990, raw_directory: Path | None = None) -> tuple[pd.DataFrame, dict]:
    now = datetime.now(timezone.utc)
    if start_year < 1954 or start_year > now.year - 11:
        raise ValueError('美国模型起始年份须在1954至当前年份前11年之间')
    session = requests.Session()
    session.headers['User-Agent'] = 'GuanlanEconomicIntelligence/1.0 (public macroeconomic research)'
    manifest = []

    def request(name: str, url: str, payload: dict | None = None, params: dict | None = None) -> bytes:
        if payload is None:
            response = session.get(url, params=params, timeout=(10, 60))
        else:
            response = session.post(url, json=payload, timeout=(10, 60))
        response.raise_for_status()
        if any(urlparse(r.url).hostname not in {'api.bls.gov', 'www.bls.gov', 'www.federalreserve.gov'} for r in [*response.history, response]):
            raise ValueError('官方源重定向至未获准提供方')
        if not response.content or len(response.content) > 10_000_000:
            raise ValueError('官方源为空或超过预期大小')
        info = {'file': name, 'url': response.url, 'request_json': payload,
                'retrieved_at_utc': datetime.now(timezone.utc).isoformat(),
                'sha256': hashlib.sha256(response.content).hexdigest(), 'bytes': len(response.content)}
        manifest.append(info)
        if raw_directory is not None:
            raw_directory.mkdir(parents=True, exist_ok=True)
            (raw_directory / name).write_bytes(response.content)
        return response.content

    rows, footnotes = [], []
    # Anonymous BLS calls: 2 series and <=10 years per request, no registration key.
    for start in range(start_year, now.year+1, 10):
        end = min(start+9, now.year)
        payload = {'seriesid': list(BLS_CODES), 'startyear': str(start), 'endyear': str(end)}
        part, notes = parse_bls(json.loads(request(f'bls-{start}-{end}.json', BLS_URL, payload)))
        if any(not start <= pd.Timestamp(row['date']).year <= end for row in part):
            raise ValueError('BLS响应期别超出请求边界')
        rows.extend(part)
        footnotes.extend(notes)
    rows.extend(parse_ip(request('g17-ip-sa.txt', IP_URL)))
    rows.extend(parse_h15(request('h15-monthly.csv', H15_URL, params=H15_PARAMS)))
    policy_fetch_failures = []
    for name, url in POLICIES.items():
        try:
            request(name, url)
        except requests.RequestException as exc:
            # Policy pages may block this downloader; no retries or bypasses.
            # Verified policy links and the documented review remain available.
            policy_fetch_failures.append({'url': url, 'error_type': type(exc).__name__,
                                          'status': exc.response.status_code if exc.response is not None else None})
    frame = monthly_frame(rows)
    # Do not include placeholder future months in the current year's G.17 row.
    frame = frame.loc[(frame.date.dt.year >= start_year) & (frame.date < pd.Timestamp(now.date()).replace(day=1))].copy()
    parts = []
    for code, part in frame.groupby('series_code'):
        observed = part.loc[part.value.notna(), 'date']
        if len(observed) < 120:
            raise ValueError(f'{code}有效观测少于120个月')
        parts.append(part.loc[part.date <= observed.max()])
    frame = pd.concat(parts, ignore_index=True)
    meta = {'provider': 'BLS + Federal Reserve Board (direct official sources)',
            'source_url': 'https://www.federalreserve.gov/releases/',
            'downloaded_at_utc': datetime.now(timezone.utc).isoformat(),
            'series': SERIES, 'start_year': start_year, 'rows': len(frame),
            'observed_values': int(frame.value.notna().sum()), 'frequency': 'monthly',
            'latest_observation': {code: part.loc[part.value.notna(), 'date'].max().date().isoformat() for code, part in frame.groupby('series_code')},
            'missing_months': {code: part.loc[part.value.isna(), 'date'].dt.strftime('%Y-%m').tolist() for code, part in frame.groupby('series_code')},
            'raw_manifest': manifest, 'bls_footnotes': footnotes,
            'policy_urls': POLICIES, 'policy_fetch_failures': policy_fetch_failures,
            'source_disclaimer': 'BLS.gov cannot vouch for the data or analyses derived from these data after the data have been retrieved from BLS.gov.',
            'method': 'BLS monthly SA observations; G.17 B50001 SA; H.15 official monthly averages, no local daily aggregation or interpolation.',
            'release_date_limit': 'Per-observation first publication dates and real-time vintages are not supplied; retrieval time is not a release date.'}
    if raw_directory is not None:
        (raw_directory / 'manifest.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    return frame, meta
