"""Verify published experiment bytes without re-running the first sealed experiment."""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def main():
    directory=ROOT/'evaluation/assistant-v1'
    frozen=json.loads((directory/'source-freeze.json').read_text(encoding='utf-8'))
    manifest=json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
    marker=json.loads((directory/'sealed-attempt.json').read_text(encoding='utf-8'))
    for name,expected in frozen['files'].items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==expected, f'Frozen source differs: {name}'
    for split in ('development','sealed'):
        for kind in ('questions','gold'):
            expected=manifest[split]['question_sha256' if kind=='questions' else 'gold_sha256']
            assert hashlib.sha256((directory/f'{split}-{kind}.json').read_bytes()).hexdigest()==expected
    assert manifest['protocol_sha256']==frozen['files']['docs/ASSISTANT_EVAL_PROTOCOL.md']
    assert marker['runs_allowed']==1
    assert datetime.fromisoformat(frozen['recorded_at_utc'])<=datetime.fromisoformat(marker['requested_at_utc'])
    result=json.loads((directory/'sealed-evaluation.json').read_text(encoding='utf-8'))
    assert result['source_freeze']==frozen['files'] and result['threshold']==frozen['threshold']
    assert result['gold_received_by_worker'] is False and result['network_requests']==0 and result['llm_used'] is False
    print(json.dumps({'status':'passed','frozen_files':len(frozen['files']),'question_and_gold_sets':4,
                      'original_sealed_cases':result['case_count'],'sealed_reexecuted':False,'credentials_read':False}))


if __name__=='__main__':main()
