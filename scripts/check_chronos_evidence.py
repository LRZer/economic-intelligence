"""Check the unique audit's frozen bytes and chronology; never run the model."""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    research = ROOT / 'research/chronos'
    evaluation = ROOT / 'evaluation/chronos-synth-v1'
    frozen = json.loads((research / 'preparation-freeze.json').read_text(encoding='utf-8'))
    for name, expected in frozen['files'].items():
        assert sha(research / name) == expected, 'Frozen preparation differs: ' + name
    manifest = json.loads((evaluation / 'delivery-manifest.json').read_text(encoding='utf-8'))
    for name, expected in manifest['files'].items():
        assert sha(ROOT / name) == expected, 'Unique audit evidence differs: ' + name
    execution = json.loads((evaluation / 'execution-source-freeze-actual-pid-erratum.json').read_text(encoding='utf-8'))
    for name, expected in execution['files'].items():
        assert sha(research / name.removeprefix('scripts/')) == expected
    packaged = (ROOT / 'src/guanlan/chronos_evaluation.py').read_text(encoding='utf-8')
    packaged = packaged.replace('    candidates = [(m, features(values, m), y) for m, y in values.items()]', '    training = [(m, features(values, m), y) for m, y in values.items()]')
    packaged = packaged.replace('for m, f, y in candidates if f is not None', 'for m, f, y in training if f is not None')
    assert packaged == (research / 'chronos_audit_core.py').read_text(encoding='utf-8')
    status = json.loads((evaluation / 'run-status.json').read_text(encoding='utf-8'))
    assert status['status'] == 'complete' and status['actual_model_predictions'] == 84 and status['completed_origins'] == 168
    assert status['worker_parent_verified_by_Windows'] and status['actual_model_worker_pid'] != status['launcher_pid']
    assert status['memory_sample_count'] >= 40 and status['max_memory_sample_gap_seconds'] < 1
    assert datetime.fromisoformat(execution['recorded_at_utc']) < datetime.fromisoformat(status['recorded_at_utc'])
    report = json.loads((evaluation / 'report.json').read_text(encoding='utf-8'))
    assert report['report_id'] == manifest['report_id'] and manifest['audit_attempts'] == 1
    assert not report['production_default_changed'] and not report['descriptive_retrospective_screen']
    events = [json.loads(line) for line in (evaluation / 'events.jsonl').read_text(encoding='utf-8').splitlines()]
    predictions = [e for e in events if e['event'] == 'prediction']
    assert len(predictions) == 84 and len({e['request_id'] for e in predictions}) == 84
    assert all(e['blocked_network_attempts'] == 0 for e in predictions)
    ready = next(e for e in events if e['event'] == 'model_ready')
    assert ready['network_access_disabled'] and ready['blocked_network_attempts'] == 0
    assert ready['local_files_only'] and ready['use_safetensors'] and not ready['trust_remote_code']
    assert ready['device'] == 'cpu' and ready['dtype'] == 'float32' and ready['parameter_count'] == 118985888
    assert sum(e['event'] == 'model_prefix_sent' for e in events) == 84
    assert all(e['no_target_actual_sent'] for e in events if e['event'] == 'model_prefix_sent')
    print(json.dumps({'status': 'passed', 'unique_actual_audit_predictions': 84, 'scientific_preparation_files': len(frozen['files']),
                      'evidence_files': len(manifest['files']), 'model_reexecuted': False, 'original_partial_preflights_retained': True,
                      'original_unmet_gate_retained': True, 'model_network_attempts': 0}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
