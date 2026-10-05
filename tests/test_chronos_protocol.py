from dataclasses import replace
from pathlib import Path
import json,math,os

import pytest

from chronos_audit_core import (BASELINES, KEYS, PersistenceFixture, Quantiles, baseline_predictions,
                               build_plan, context_for, evaluate, fixture_rows, interval_diagnostics,
                               metric, paired_block_interval, score_origin, seasonal_scale, validate_rows)
from chronos_resource_guard import Budget, GIB, disk_resources, disk_stop_reason, run_fixture, stop_reason, windows_memory

ROOT=Path(__file__).resolve().parents[1]/'research/chronos'


@pytest.fixture
def protocol():return json.loads((ROOT/'protocol.json').read_text(encoding='utf-8'))


def one_series():return validate_rows(fixture_rows(),fixture=True)[KEYS[0]]


def test_locked_calendar_no_target_in_context_and_fixed_84_predictions(protocol):
    plan=build_plan(fixture_rows(),protocol,fixture=True)
    assert plan['origin_count']==168 and plan['chronos_predictions_planned']==84
    audit=[o for o in plan['origins'] if o['split']=='audit']
    assert {o['target'] for o in audit}=={f'2025-{m:02d}' for m in range(9,13)}|{f'2026-{m:02d}' for m in range(1,9)}
    assert all(o['context_end']<o['target'] and o['latest_context_publication']<o['issue_date']<o['target_publication'] for o in plan['origins'])
    context=context_for(one_series(),KEYS[0],'2025-09')
    assert len(context.values)==48 and context.periods[-1]=='2025-08'
    assert not hasattr(context,'actual') and isinstance(context.values,tuple)


@pytest.mark.parametrize('corruption',['duplicate','gap','nan','bool','source','published'])
def test_invalid_source_and_publication_stop(corruption,protocol):
    rows=fixture_rows()
    if corruption=='duplicate':rows.append(dict(rows[0]))
    elif corruption=='gap':rows.pop(2)
    elif corruption=='nan':rows[0]['value']=float('nan')
    elif corruption=='bool':rows[0]['value']=True
    elif corruption=='source':rows[0]['source_url']='https://unapproved.invalid/'
    else:rows[0]['published']='2027-01-01'
    with pytest.raises(ValueError):build_plan(rows,protocol,fixture=True)


def test_linear_independent_gold_strong_baselines_and_train_scale():
    context=context_for(one_series(),KEYS[0],'2025-09')
    result=baseline_predictions(context)
    # Generated y_i=i. The next index48 is independently known here.
    assert result['persistence']==47 and result['seasonal']==36 and result['drift']==48
    assert result['ridge_train_n']==36 and result['ridge_train_end']=='2025-08'
    assert seasonal_scale(context)==12
    record=score_origin(one_series(),KEYS[0],'2025-09',predictor=PersistenceFixture())
    assert metric([record],'persistence')['mae']==1
    assert metric([record],'seasonal')['mae']==12
    assert metric([record],'drift')['mae']==0
    assert metric([record],'persistence')['mase']==pytest.approx(1/12)
    interval=interval_diagnostics([record])
    assert interval['coverage']==1 and interval['nominal_coverage']==.8 and interval['mean_width']==2
    assert interval['pinball_loss']['0.5']==.5


def test_target_and_future_poison_never_changes_any_forecast_or_training_scale():
    original=one_series()
    poisoned=[dict(r) for r in original]
    for r in poisoned:
        if r['period']>='2025-09':r['value']+=100000.
    left=score_origin(original,KEYS[0],'2025-09',predictor=PersistenceFixture())
    right=score_origin(poisoned,KEYS[0],'2025-09',predictor=PersistenceFixture())
    assert left['predictions']==right['predictions'] and left['quantiles']==right['quantiles']
    assert left['context_sha256']==right['context_sha256'] and left['mase_scale']==right['mase_scale']
    assert left['actual']!=right['actual']


def test_zero_scale_is_undefined_not_epsilon_or_deleted(protocol):
    rows=fixture_rows(constant=True)
    grouped=validate_rows(rows,fixture=True)
    record=score_origin(grouped[KEYS[0]],KEYS[0],'2025-09',predictor=PersistenceFixture())
    result=metric([record],'challenger')
    assert result['mase'] is None and result['mase_undefined_n']==1 and result['mae']==0
    report=evaluate(rows,protocol,PersistenceFixture(),fixture=True)
    assert report['macro_equal_indicator_mase'] is None and not report['descriptive_retrospective_screen']
    assert report['failures_dropped']==0 and report['model_predictions']==84


@pytest.mark.parametrize('values',[(2.,1.,3.),(0.,math.inf,2.),(0.,float('nan'),2.),(False,1.,2.)])
def test_quantile_schema_fails_closed_without_sort_or_repair(values):
    with pytest.raises(ValueError):Quantiles(*values).validate()


def test_negative_fixture_retained_references_dev_only_and_all_model_records(protocol):
    seen=[]
    report=evaluate(fixture_rows(),protocol,PersistenceFixture(),fixture=True,progress=seen.append)
    assert report['status']=='fixture_only_complete' and report['not_economic_evidence']
    assert not report['descriptive_retrospective_screen'] and not report['production_default_changed']
    assert report['audit_references']==dict.fromkeys(KEYS,'drift')
    assert len(report['records']['audit'])==84 and len(report['records']['development'])==84
    assert all('challenger' not in r['predictions'] for r in report['records']['development'])
    assert all(set(r['predictions'])==set(BASELINES)|{'challenger'} for r in report['records']['audit'])
    assert report['development_challenger_predictions']==0
    assert len([e for e in seen if e['event']=='origin_finished'])==168
    assert paired_block_interval([1.]*12)==[1.,1.]
    assert paired_block_interval([1.]*11) is None


@pytest.mark.parametrize('field,value,expected',[
    ('available_bytes',int(1.4*GIB),'system_available_memory_below_floor'),
    ('working_set_bytes',3*GIB,'process_working_set_limit'),
    ('peak_working_set_bytes',3*GIB,'process_working_set_limit'),
    ('private_bytes',4*GIB,'process_private_commit_limit')])
def test_native_resource_thresholds(field,value,expected):
    memory={'available_bytes':5*GIB,'working_set_bytes':GIB,'peak_working_set_bytes':GIB,'private_bytes':GIB}
    memory[field]=value
    assert stop_reason(Budget(),1.,1.,'idle',memory)==expected


def test_wall_load_and_origin_time_limits():
    memory={'available_bytes':5*GIB,'working_set_bytes':GIB,'private_bytes':GIB}
    assert stop_reason(Budget(),1800.,0.,'idle',memory)=='global_wall_timeout'
    assert stop_reason(Budget(),121.,120.,'loading',memory)=='model_load_timeout'
    assert stop_reason(Budget(),50.,45.,'origin',memory)=='origin_timeout'
    assert stop_reason(Budget(),1.,1.,'idle',memory) is None


def test_disk_budget_thresholds_and_owned_file_accounting(tmp_path):
    (tmp_path/'evidence.txt').write_bytes(b'abc')
    observed=disk_resources(tmp_path)
    assert observed['logical_research_bytes']==3 and observed['free_bytes']>0
    assert disk_stop_reason({'free_bytes':7*GIB,'logical_research_bytes':0},starting=True)=='disk_free_below_start_threshold'
    assert disk_stop_reason({'free_bytes':2*GIB,'logical_research_bytes':0})=='disk_free_below_floor'
    assert disk_stop_reason({'free_bytes':10*GIB,'logical_research_bytes':6*GIB})=='research_disk_budget_exceeded'
    assert disk_stop_reason({'free_bytes':10*GIB,'logical_research_bytes':GIB},starting=True) is None


@pytest.mark.skipif(os.name!='nt',reason='Native Windows monitor targets the selected computer')
def test_native_probe_and_invalid_backend_never_starts_real_model(tmp_path,protocol):
    memory=windows_memory(os.getpid())
    assert memory['total_physical_bytes']>=memory['available_bytes']>0
    assert memory['peak_working_set_bytes']>=memory['working_set_bytes']>0
    with pytest.raises(ValueError,match='unauthorized'):run_fixture(protocol,tmp_path/'invalid',backend='chronos')
    assert not (tmp_path/'invalid').exists()


@pytest.mark.skipif(os.name!='nt',reason='Native Windows memory preflight')
def test_insufficient_start_memory_stops_before_fixture_worker(tmp_path,protocol):
    result=run_fixture(protocol,tmp_path/'insufficient',budget=replace(Budget(),start_available_bytes=100*GIB))
    assert result['status']=='stopped' and result['stop_reason']=='insufficient_start_memory'
    assert not (tmp_path/'insufficient/events.jsonl').exists() and not result['actual_model_executed']


@pytest.mark.skipif(os.name!='nt',reason='Native supervised worker targets selected Windows environment')
def test_supervised_fake_timeout_retains_partial_and_terminates_owned_worker(tmp_path,protocol):
    budget=replace(Budget(),start_available_bytes=0,min_available_bytes=0,max_wall_seconds=30.,
                   max_load_seconds=20.,max_origin_seconds=.3,poll_seconds=.02)
    result=run_fixture(protocol,tmp_path/'slow',backend='slow_fixture',budget=budget)
    assert result['status']=='stopped' and result['stop_reason']=='origin_timeout'
    assert 0<result['completed_origins']<168 and result['last_origin']['split']=='audit'
    assert (tmp_path/'slow/events.jsonl').is_file() and (tmp_path/'slow/run-status.json').is_file()
    assert not (tmp_path/'slow/fixture-report.json').exists()
    assert not result['actual_model_executed'] and result['worker_exit_code'] is not None
