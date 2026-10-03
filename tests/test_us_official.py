import csv
import io

import pandas as pd
import pytest

from guanlan.us_official import monthly_frame, parse_bls, parse_h15, parse_ip, RATE_CODES


def bls_payload():
    return {'status':'REQUEST_SUCCEEDED','message':[], 'Results':{'series':[
        {'seriesID':code,'data':[{'year':'2025','period':'M01','value':'4.5','footnotes':[{'text':'Preliminary','code':'P'}]},
                               {'year':'2025','period':'M13','value':'999'}]}
        for code in ['CUSR0000SA0','LNS14000000']]}}


def test_bls_excludes_annual_average_retains_notes_and_rejects_partial_response():
    payload=bls_payload()
    rows,notes=parse_bls(payload)
    assert len(rows)==2 and all(row['date']=='2025-01-01' for row in rows)
    assert len(notes)==2
    payload['Results']['series'][0]['data'][0]['value']='-'
    with pytest.raises(ValueError,match='缺失说明'):
        parse_bls(payload)
    payload['Results']['series'][0]['data'][0]['footnotes']=[{'text':'Data unavailable due to lapse in appropriations'}]
    assert parse_bls(payload)[0][0]['value'] is None
    payload['message']=['request truncated']
    with pytest.raises(ValueError,match='完整成功'):
        parse_bls(payload)


def h15_csv(value='4.2', unit='Percent:_Per_Year'):
    buffer=io.StringIO()
    writer=csv.writer(buffer)
    codes=list(RATE_CODES)
    writer.writerows([['Unit:',*[unit]*3],['Multiplier:',*['1']*3],
                     ['Unique Identifier:',*[f'H15/H15/{code}' for code in codes]],
                     ['Time Period',*codes],['2025-01',value,'ND','4.1'],['2025-03','4.0','4.2','4.3']])
    return buffer.getvalue().encode()


def test_h15_checks_identity_units_and_non_numeric_values_keeps_missing_calendar():
    result=monthly_frame(parse_h15(h15_csv()))
    assert len(result)==9
    assert result.loc[result.date==pd.Timestamp('2025-02-01'),'value'].isna().all()
    assert result.loc[(result.date==pd.Timestamp('2025-01-01'))&(result.series_code=='UST2Y'),'value'].isna().all()
    with pytest.raises(ValueError,match='单位'):
        parse_h15(h15_csv(unit='BasisPoints'))
    with pytest.raises(ValueError,match='无法解析'):
        parse_h15(h15_csv(value='broken'))


def test_ip_partial_latest_year_and_duplicates_are_not_silently_corrected():
    rows=parse_ip(b'"B50001: Total index"\n"B50001" 2026 101.0 102.0\n"B50002" 2026 888.0\n')
    assert len(rows)==2 and rows[-1]['date']=='2026-02-01'
    with pytest.raises(ValueError,match='重复'):
        monthly_frame(rows+rows)
    with pytest.raises(ValueError,match='没有'):
        parse_ip(b'wrong file')
