from copy import deepcopy
import csv
from importlib.resources import files
import io
import math

import pytest

from guanlan.chronos_report import (DATA_SHA, KEYS, MODEL_ID, REVISION, csv_rows, digest, export_audit,
                                    load_packaged_audit, strict_json, verify_report)


@pytest.fixture(scope='module')
def bundle():
    report, protocol, provenance = load_packaged_audit()
    return report, protocol, provenance, files('china_macro').joinpath('demo_data.json').read_bytes()


def test_real_audit_independent_arithmetic_full_pairs_prefix_and_default(bundle):
    report, protocol, provenance, source = bundle
    assert report['backend_identity'] == MODEL_ID + '@' + REVISION
    assert len(report['records']['audit']) == len(report['records']['development']) == 84
    assert report['development_challenger_predictions'] == 0 and not report['production_default_changed']
    assert all(r['context_end'] < r['target'] and r['ridge_train_end'] < r['target'] for split in report['records'].values() for r in split)
    for key in KEYS:
        records = [r for r in report['records']['audit'] if r['key'] == key]
        errors = [abs(r['quantiles']['p50'] - r['actual']) for r in records]
        assert report['audit_metrics'][key]['challenger']['mae'] == pytest.approx(math.fsum(errors) / 12)
        assert report['audit_metrics'][key]['challenger']['mase'] == pytest.approx(math.fsum(e / r['mase_scale'] for e, r in zip(errors, records)) / 12)
        assert report['interval_diagnostics'][key]['coverage'] == sum(r['quantiles']['p10'] <= r['actual'] <= r['quantiles']['p90'] for r in records) / 12
        minimum = min(protocol['baselines'], key=lambda b: report['development_metrics'][key][b]['mae'])
        assert report['audit_references'][key] == minimum
    assert report['macro_equal_indicator_mase']['challenger'] == pytest.approx(math.fsum(report['audit_metrics'][k]['challenger']['mase'] for k in KEYS) / 7)
    assert provenance['audit_model_predictions'] == 84 and provenance['protocol_sha256']
    assert verify_report(report, protocol, source)['new_model_predictions'] == 0


@pytest.mark.parametrize('corruption', ['score', 'actual', 'context', 'baseline', 'gate', 'crossed', 'missing', 'duplicate', 'fixture', 'default', 'model', 'development-leak'])
def test_report_tampering_rejected_even_after_attacker_updates_fingerprint(bundle, corruption):
    report, protocol, _, source = bundle
    altered = deepcopy(report)
    first = altered['records']['audit'][0]
    if corruption == 'score': altered['macro_equal_indicator_mase']['challenger'] = 0.
    elif corruption == 'actual': first['actual'] += 100.
    elif corruption == 'context': first['context_end'] = first['target']
    elif corruption == 'baseline': first['predictions']['ridge'] += 100.
    elif corruption == 'gate': altered['descriptive_retrospective_screen'] = not altered['descriptive_retrospective_screen']
    elif corruption == 'crossed': first['quantiles']['p10'] = first['quantiles']['p90'] + 1.
    elif corruption == 'missing': altered['records']['audit'].pop()
    elif corruption == 'duplicate': altered['records']['audit'][1] = deepcopy(first)
    elif corruption == 'fixture': altered['status'] = 'fixture_only_complete'
    elif corruption == 'default': altered['production_default_changed'] = True
    elif corruption == 'model': altered['backend_identity'] = 'another-model'
    else: altered['records']['development'][0]['predictions']['challenger'] = 0.
    altered['report_id'] = digest({k: v for k, v in altered.items() if k != 'report_id'})
    with pytest.raises((ValueError, KeyError, TypeError)):
        verify_report(altered, protocol, source)


def test_changed_source_and_duplicate_nonfinite_or_large_json_refused(bundle):
    report, protocol, _, source = bundle
    with pytest.raises(ValueError): verify_report(report, protocol, source + b' ')
    for raw in [b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}', b'[]', b'', b' ' * (2 * 1024 * 1024 + 1)]:
        with pytest.raises(ValueError): strict_json(raw)
    with pytest.raises(ValueError): csv_rows(report, key='unapproved')


def test_complete_offline_exports_keep_negative_results_no_scripts_or_remote_assets(bundle):
    report, protocol, provenance, source = bundle
    result = export_audit(report, protocol, provenance)
    decoded = strict_json(result['json'])
    assert verify_report(decoded['report'], decoded['protocol'], source)['status'] == 'passed'
    csv_records = list(csv.DictReader(io.StringIO(result['csv'].decode('utf-8-sig'))))
    assert len(csv_records) == 168 and len({(r['split'], r['indicator'], r['period']) for r in csv_records}) == 168
    assert sum(bool(r['challenger']) for r in csv_records) == 84
    assert all(r['report_id'] == report['report_id'] for r in csv_records)
    assert '<script' not in result['html'].decode().lower() and 'src=' not in result['html'].decode().lower()
    assert report['report_id'].encode() in result['html']
    assert export_audit(report, protocol, provenance) == result
