"""Supervise the authorized fixed experiment without modifying its protocol."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time


EXPECTED_PROTOCOL = 'cd1abcfa04b3d3183cfbd4cb0a365f62aca3d90503b85d09136a4ae21d712261'
EXPECTED_DATA = '90e4e0d4237d2c414578c29786c9585bddbc27192cdd7c65c937f563326bb6c2'


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Session:
    def __init__(self, root, prep, output, budget, windows_memory, disk_resources, disk_stop_reason, stop_reason):
        self.root, self.output, self.budget = root, output, budget
        self.windows_memory, self.disk_resources = windows_memory, disk_resources
        self.disk_stop_reason, self.stop_reason = disk_stop_reason, stop_reason
        self.initial = windows_memory(os.getpid())
        self.initial_disk = disk_resources(root)
        if self.initial['available_bytes'] < budget.start_available_bytes:
            raise RuntimeError('Insufficient start RAM')
        if disk_stop_reason(self.initial_disk, starting=True):
            raise RuntimeError('Disk start budget is not met')
        output.mkdir(parents=True, exist_ok=False)
        self.started = time.monotonic(); self.phase_started = self.started; self.phase = 'loading'
        self.reason = None; self.minimum_available = self.initial['available_bytes']
        self.peak_ws = 0; self.peak_private = 0; self.complete_records = 0; self.model_predictions = 0
        self.prediction_seconds = []; self.ready = None; self.memory_samples = 0; self.max_memory_sample_gap = 0.; self.max_disk_scan_seconds = 0.
        self.done = threading.Event(); self.responses = queue.Queue(); self.last_origin = None; self.closed = False
        self.events = (output / 'events.jsonl').open('w', encoding='utf-8')
        self.stderr = (output / 'backend-diagnostics.log').open('w', encoding='utf-8')
        env = {key: os.environ[key] for key in ('SystemRoot', 'WINDIR', 'SystemDrive', 'COMSPEC', 'PATH', 'PATHEXT') if key in os.environ}
        env.update(TEMP=str(root / 'temp'), TMP=str(root / 'temp'), PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1',
                   HF_HOME=str(root / 'hf-cache'), HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_HUB_DISABLE_PROGRESS_BARS='1',
                   TRANSFORMERS_VERBOSITY='error', CUDA_VISIBLE_DEVICES='', ENABLE_PAID_AI='0', AUTO_REFRESH='0',
                   OMP_NUM_THREADS='4', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1')
        self.process = subprocess.Popen([str(root / '.venv/Scripts/python.exe'), '-B', str(root / 'scripts/chronos_cpu_backend.py'),
                                         '--model', str(root / 'model')], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=self.stderr, text=True, encoding='utf-8', bufsize=1, env=env)
        self.worker = None
        self.reader = threading.Thread(target=self.read_output, daemon=True); self.reader.start()
        from chronos_owned_process import OwnedProcess
        event = self.receive('worker_started')
        actual_pid = event['pid']
        expected_parent = self.process.pid if actual_pid != self.process.pid else os.getpid()
        if event['parent_pid'] != expected_parent:
            self.process.terminate(); raise RuntimeError('Unexpected model worker parent')
        self.worker = OwnedProcess(actual_pid, expected_parent)
        self.log(event)
        self.monitor = threading.Thread(target=self.watch_resources, daemon=True); self.monitor.start()
        self.disk_monitor = threading.Thread(target=self.watch_disk, daemon=True); self.disk_monitor.start()
        try:
            self.ready = self.receive('model_ready')
        except Exception as exc:
            self.finish(status='incomplete', error='loading: ' + type(exc).__name__ + ': ' + str(exc)[:300])
            raise
        self.log(self.ready); self.phase = 'idle'; self.phase_started = time.monotonic()

    def read_output(self):
        try:
            for line in self.process.stdout:
                self.responses.put(json.loads(line))
        except (ValueError, OSError) as exc:
            self.responses.put({'event': 'error', 'error_type': type(exc).__name__, 'detail': 'Invalid backend stdout protocol'})
        finally:
            self.responses.put({'event': 'backend_eof'})

    def watch_resources(self):
        last_log = self.started; last_memory = self.started
        with (self.output / 'resource-samples.jsonl').open('w', encoding='utf-8') as log:
            while not self.done.wait(self.budget.poll_seconds):
                if self.process.poll() is not None:
                    return
                try:
                    if not self.worker.alive():
                        return
                    backend = self.windows_memory(self.worker.pid)
                    host = self.windows_memory(os.getpid())
                    combined = {key: backend[key] + host[key] for key in ('working_set_bytes', 'peak_working_set_bytes', 'private_bytes')}
                    combined['available_bytes'] = backend['available_bytes']
                    self.minimum_available = min(self.minimum_available, combined['available_bytes'])
                    self.peak_ws = max(self.peak_ws, combined['peak_working_set_bytes'])
                    self.peak_private = max(self.peak_private, combined['private_bytes'])
                    now = time.monotonic()
                    self.memory_samples += 1
                    self.max_memory_sample_gap = max(self.max_memory_sample_gap, now - last_memory)
                    last_memory = now
                    reason = self.stop_reason(self.budget, now - self.started, now - self.phase_started, self.phase, combined)
                    if now - last_log >= 5:
                        log.write(json.dumps({'elapsed': now - self.started, 'phase': self.phase, 'combined_host_backend': combined}) + '\n')
                        log.flush(); last_log = now
                    if reason:
                        self.reason = reason; self.terminate_owned(); return
                except (OSError, RuntimeError):
                    if self.process.poll() is not None:
                        return
                    self.reason = 'resource_probe_failed'; self.terminate_owned(); return

    def watch_disk(self):
        while not self.done.wait(5.):
            if self.process.poll() is not None:
                return
            started = time.monotonic()
            try:
                resources = self.disk_resources(self.root)
                self.max_disk_scan_seconds = max(self.max_disk_scan_seconds, time.monotonic() - started)
                reason = self.disk_stop_reason(resources)
            except (OSError, RuntimeError):
                reason = 'disk_probe_failed'
            if reason and self.process.poll() is None:
                self.reason = self.reason or reason; self.terminate_owned(); return

    def terminate_owned(self):
        if self.worker is not None:
            self.worker.terminate()
        if self.process.poll() is None:
            self.process.terminate()

    def log(self, event):
        self.events.write(json.dumps({**event, 'supervisor_elapsed_seconds': time.monotonic() - self.started}, ensure_ascii=False, allow_nan=False) + '\n')
        self.events.flush()

    def receive(self, expected):
        while True:
            if self.reason:
                raise RuntimeError(self.reason)
            try:
                event = self.responses.get(timeout=.25)
            except queue.Empty:
                if self.process.poll() is not None:
                    raise RuntimeError('Backend exited before response')
                continue
            if event.get('event') != expected:
                self.log(event)
                raise RuntimeError('Backend error: ' + str(event.get('error_type', event.get('event'))))
            return event

    def predict(self, context):
        from chronos_audit_core import Quantiles
        if self.phase != 'origin':
            self.phase = 'origin'; self.phase_started = time.monotonic()
        identifier = f'{context.indicator}:{context.target_period}:{context.source_rows_hash}'
        self.log({'event': 'model_prefix_sent', 'request_id': identifier, 'prefix_n': len(context.values),
                  'context_end': context.periods[-1], 'no_target_actual_sent': True})
        self.process.stdin.write(json.dumps({'operation': 'predict', 'request_id': identifier, 'values': list(context.values)}, allow_nan=False) + '\n')
        self.process.stdin.flush()
        event = self.receive('prediction')
        if event['request_id'] != identifier or event['prefix_n'] != len(context.values):
            raise RuntimeError('Backend response bound to different context')
        result = Quantiles(event['p10'], event['p50'], event['p90']); result.validate()
        self.model_predictions += 1; self.prediction_seconds.append(event['elapsed_seconds']); self.log(event)
        return result

    def progress(self, event):
        if self.reason:
            raise RuntimeError(self.reason)
        self.log(event)
        if event['event'] == 'origin_started':
            self.phase = 'origin'; self.phase_started = time.monotonic()
            self.last_origin = {key: event[key] for key in ('key', 'target', 'split')}
        elif event['event'] == 'origin_finished':
            self.complete_records += 1; self.phase = 'idle'
            if self.complete_records % 12 == 0:
                print(json.dumps({'completed_origins': self.complete_records, 'actual_model_predictions': self.model_predictions,
                                  'elapsed_seconds': time.monotonic() - self.started}), flush=True)

    def finish(self, *, status, error=None):
        if self.process.poll() is None:
            if status == 'complete':
                try:
                    self.process.stdin.write('{"operation":"close"}\n'); self.process.stdin.flush()
                    self.process.wait(timeout=10)
                except (OSError, subprocess.TimeoutExpired):
                    self.reason = self.reason or 'owned_backend_exit_timeout'
                    self.terminate_owned()
            else:
                self.terminate_owned()
        self.done.set(); self.monitor.join(timeout=3); self.disk_monitor.join(timeout=3)
        self.process.wait(timeout=10); self.reader.join(timeout=3)
        self.events.close(); self.stderr.close()
        worker_pid = self.worker.pid if self.worker is not None else None
        if self.worker is not None:
            self.worker.close()
        if self.reason or self.process.returncode != 0:
            status = 'incomplete'
        self.closed = True
        result = {'status': status, 'recorded_at_utc': datetime.now(timezone.utc).isoformat(),
                  'stop_reason': self.reason or error, 'elapsed_seconds': time.monotonic() - self.started,
                  'budget': asdict(self.budget), 'initial_resources': self.initial, 'initial_disk': self.initial_disk,
                  'final_disk': self.disk_resources(self.root), 'resource_probe_scope': 'entire isolated D research root; aggregate host and owned model worker memory',
                  'sampled_peak_combined_working_set_bytes': self.peak_ws, 'sampled_peak_combined_private_bytes': self.peak_private,
                  'minimum_available_bytes': self.minimum_available, 'worker_exit_code': self.process.returncode,
                  'actual_model_worker_pid': worker_pid, 'launcher_pid': self.process.pid, 'worker_parent_verified_by_Windows': True,
                  'memory_sample_count': self.memory_samples, 'max_memory_sample_gap_seconds': self.max_memory_sample_gap,
                  'max_disk_scan_seconds': self.max_disk_scan_seconds, 'disk_monitor_independent_from_memory': True,
                  'completed_origins': self.complete_records, 'actual_model_predictions': self.model_predictions,
                  'last_origin': self.last_origin, 'model_ready': self.ready,
                  'prediction_seconds': self.prediction_seconds, 'paid_api_called': False, 'data_uploaded': False,
                  'production_default_changed': False, 'protocol_changed': False}
        dump(self.output / 'run-status.json', result)
        return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--preparation', type=Path, required=True)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--mode', choices=['real-model-fixture', 'audit'], required=True)
    parser.add_argument('--fixture-label', choices=['initial', 'runtime-repair', 'monitor-repair', 'pid-repair'], default='initial')
    args = parser.parse_args()
    root, prep, project = args.root.resolve(), args.preparation.resolve(), args.project.resolve()
    if sha(prep / 'protocol.json') != EXPECTED_PROTOCOL:
        raise RuntimeError('Frozen protocol changed')
    frozen = json.loads((prep / 'preparation-freeze.json').read_text(encoding='utf-8'))
    for name, expected in frozen['files'].items():
        if sha(prep / name) != expected:
            raise RuntimeError('Frozen preparation source changed: ' + name)
    if sha(project / 'src/china_macro/demo_data.json') != EXPECTED_DATA:
        raise RuntimeError('Frozen official data changed')
    if json.loads((root / 'metadata/model-file-lock.json').read_text(encoding='utf-8')).get('status') != 'verified_fixed_files':
        raise RuntimeError('Fixed model download has not passed verification')
    fixture_folder = 'real-model-fixture' if args.fixture_label == 'initial' else 'real-model-fixture-' + args.fixture_label
    if args.mode == 'audit':
        fixture = json.loads((root / 'reports' / fixture_folder / 'run-status.json').read_text(encoding='utf-8'))
        if fixture.get('status') != 'complete' or fixture.get('actual_model_predictions') != 2:
            raise RuntimeError('Actual-model fixture has not passed')
    sys.path.insert(0, str(prep))
    from chronos_audit_core import Context, digest, evaluate
    from chronos_resource_guard import Budget, windows_memory, disk_stop_reason, stop_reason
    from chronos_runtime_resources import disk_resources
    protocol = json.loads((prep / 'protocol.json').read_text(encoding='utf-8'))
    output = root / 'reports' / (fixture_folder if args.mode == 'real-model-fixture' else 'audit-v1')
    # Output creation is exclusive; no automatic retry or selective rerun.
    session = None
    try:
        session = Session(root, prep, output, Budget(**protocol['resource_budget']), windows_memory, disk_resources, disk_stop_reason, stop_reason)
        session.identity = 'autogluon/chronos-2-synth@' + protocol['model']['revision']
        if args.mode == 'real-model-fixture':
            records = []
            for label, values in [('flat', [2.] * 36), ('linear-seasonal', [5 + .1 * i + math.sin(i * math.pi / 6) for i in range(48)])]:
                context = Context('synthetic:' + label, 'fixture', 'fixture', tuple(str(i) for i in range(len(values))), tuple(values), digest(values))
                result = session.predict(context)
                records.append({'synthetic_label': label, 'context_n': len(values), 'quantiles': asdict(result)})
            dump(output / 'fixture-predictions.json', {'status': 'synthetic_real_model_smoke_only', 'not_economic_evidence': True, 'records': records})
        else:
            document = json.loads((project / 'src/china_macro/demo_data.json').read_text(encoding='utf-8'))
            report = evaluate(document['rows'], protocol, session, fixture=False, progress=session.progress)
            if session.reason or session.model_predictions != 84 or session.complete_records != 168:
                raise RuntimeError('Incomplete audit; no complete scientific report emitted')
            dump(output / 'report.json', report)
            session.log({'event': 'complete', 'report_id': report['report_id']})
        status = session.finish(status='complete')
        if status['status'] != 'complete':
            raise RuntimeError('Supervised backend did not exit cleanly')
        print(json.dumps(status, ensure_ascii=False, indent=2), flush=True)
    except Exception as exc:
        if session is not None and not session.closed:
            status = session.finish(status='incomplete', error=type(exc).__name__ + ': ' + str(exc)[:300])
            print(json.dumps(status, ensure_ascii=False, indent=2), flush=True)
        elif output.exists():
            dump(output / 'startup-failure.json', {'status': 'incomplete', 'error_type': type(exc).__name__, 'detail': str(exc)[:300], 'automatic_retry': False})
        raise


if __name__ == '__main__':
    main()
