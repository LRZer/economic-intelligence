"""Owned offline CPU backend: JSON prefixes in, three native quantiles out."""
from __future__ import annotations

import argparse
import contextlib
import ctypes
import hashlib
import json
import math
import os
from pathlib import Path
import socket
import sys
import time


def emit(payload):
    print(json.dumps(payload, ensure_ascii=False, allow_nan=False), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', required=True, type=Path)
    args = parser.parse_args()
    emit({'event': 'worker_started', 'pid': os.getpid(), 'parent_pid': os.getppid()})
    started = time.monotonic()
    path = args.model.resolve()
    if set(p.name for p in path.iterdir()) != {'README.md', 'config.json', 'model.safetensors'}:
        raise ValueError('Only fixed approved model files are permitted')
    expected = '920a3344726a8026c9335d38ae1a2bfa9b7d659c1b8fe0b0af8d5f775863422e'
    digest = hashlib.sha256()
    with (path / 'model.safetensors').open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    if digest.hexdigest() != expected:
        raise ValueError('Fixed official weight SHA-256 mismatch')
    # Anaconda base may resolve stale MSVC DLLs. Load existing system binaries
    # into this owned process only; no copying, installing or shared changes.
    system_preloads = []
    if os.name == 'nt':
        system32 = Path(os.environ['SystemRoot']) / 'System32'
        for name in ('vcruntime140.dll', 'vcruntime140_1.dll', 'msvcp140.dll', 'msvcp140_atomic_wait.dll', 'concrt140.dll'):
            candidate = system32 / name
            if candidate.is_file():
                ctypes.WinDLL(str(candidate))
                system_preloads.append({'name': name, 'sha256': hashlib.sha256(candidate.read_bytes()).hexdigest()})
    blocked_network_attempts = []
    def deny_connect(*args, **kwargs):
        blocked_network_attempts.append('blocked')
        raise RuntimeError('Model worker network access is disabled')
    socket.socket.connect = deny_connect
    with contextlib.redirect_stdout(sys.stderr):
        import torch
        from chronos import Chronos2Pipeline
        torch.set_num_threads(4)
        torch.set_num_interop_threads(1)
        torch.manual_seed(42)
        pipeline = Chronos2Pipeline.from_pretrained(
            str(path), device_map='cpu', dtype=torch.float32,
            local_files_only=True, trust_remote_code=False, use_safetensors=True,
        )
        pipeline.model.eval()
    parameters = list(pipeline.model.parameters())
    if any(p.device.type != 'cpu' or p.dtype != torch.float32 for p in parameters):
        raise ValueError('Backend escaped fixed CPU float32 policy')
    if not {0.1, 0.5, 0.9}.issubset(set(pipeline.quantiles)):
        raise ValueError('Fixed quantiles are not native training levels')
    emit({'event': 'model_ready', 'torch_version': torch.__version__, 'cpu_threads': torch.get_num_threads(),
          'interop_threads': torch.get_num_interop_threads(), 'device': 'cpu', 'dtype': 'float32',
          'parameter_count': sum(p.numel() for p in parameters), 'weights_sha256': digest.hexdigest(),
          'load_seconds': time.monotonic() - started, 'local_files_only': True,
          'trust_remote_code': False, 'use_safetensors': True, 'model_eval': not pipeline.model.training,
          'cross_learning': False, 'quantiles_native': True,
          'network_access_disabled': True, 'blocked_network_attempts': len(blocked_network_attempts),
          'existing_system_runtime_preloads': system_preloads})
    for line in sys.stdin:
        if len(line) > 32768:
            raise ValueError('Oversized backend request')
        request = json.loads(line)
        if request == {'operation': 'close'}:
            return
        if set(request) != {'operation', 'request_id', 'values'} or request['operation'] != 'predict':
            raise ValueError('Unsupported backend request; target labels not accepted')
        values = request['values']
        if not isinstance(values, list) or not 36 <= len(values) <= 60:
            raise ValueError('Fixed prefix length violated')
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
            raise ValueError('Invalid prefix value')
        started = time.monotonic()
        tensor = torch.tensor(values, dtype=torch.float32, device='cpu')
        with contextlib.redirect_stdout(sys.stderr), torch.inference_mode():
            quantiles, _ = pipeline.predict_quantiles(
                [tensor], prediction_length=1, quantile_levels=[0.1, 0.5, 0.9],
                batch_size=1, context_length=60, cross_learning=False, limit_prediction_length=True,
            )
        if len(quantiles) != 1 or tuple(quantiles[0].shape) != (1, 1, 3):
            raise ValueError('Unexpected fixed quantile output shape')
        result = quantiles[0][0, 0].tolist()
        if any(not math.isfinite(v) for v in result) or not result[0] <= result[1] <= result[2]:
            raise ValueError('Invalid native quantiles; no sorting or selective dropping')
        emit({'event': 'prediction', 'request_id': request['request_id'],
              'p10': result[0], 'p50': result[1], 'p90': result[2],
              'prefix_n': len(values), 'elapsed_seconds': time.monotonic() - started,
              'blocked_network_attempts': len(blocked_network_attempts)})


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        emit({'event': 'error', 'error_type': type(exc).__name__, 'detail': str(exc)[:1000]})
        raise SystemExit(2)
