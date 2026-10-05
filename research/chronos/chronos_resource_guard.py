"""Native read-only Windows resource probe and fixture-only supervised worker."""
from __future__ import annotations

from dataclasses import dataclass, asdict
import ctypes
import json
import multiprocessing as mp
import os
from pathlib import Path
import queue
import shutil
import time

from chronos_audit_core import Context, Quantiles, PersistenceFixture, evaluate, fixture_rows

GIB = 1024 ** 3


@dataclass(frozen=True)
class Budget:
    cpu_threads: int = 4
    interop_threads: int = 1
    blas_threads: int = 1
    batch_size: int = 1
    max_wall_seconds: float = 1800.
    max_load_seconds: float = 120.
    max_origin_seconds: float = 45.
    start_available_bytes: int = 4 * GIB
    min_available_bytes: int = int(1.5 * GIB)
    max_working_set_bytes: int = int(2.5 * GIB)
    max_private_bytes: int = 3 * GIB
    poll_seconds: float = .25


def disk_resources(owned_root: Path) -> dict:
    root = owned_root.resolve()
    size = 0
    for path in root.rglob('*'):
        if not path.resolve().is_relative_to(root):
            raise RuntimeError('Research file resolves outside owned directory')
        if path.is_file():
            size += path.stat().st_size
    return {'free_bytes': shutil.disk_usage(root).free, 'logical_research_bytes': size}


def disk_stop_reason(resources: dict, *, starting: bool = False) -> str | None:
    if resources['free_bytes'] < (8 * GIB if starting else 3 * GIB):
        return 'disk_free_below_start_threshold' if starting else 'disk_free_below_floor'
    if resources['logical_research_bytes'] > 5 * GIB:
        return 'research_disk_budget_exceeded'
    return None


def windows_memory(pid: int) -> dict:
    if os.name != "nt":
        raise RuntimeError("This native resource monitor is validated only on Windows")
    class MemoryStatus(ctypes.Structure):
        _fields_ = [("length", ctypes.c_uint32), ("load", ctypes.c_uint32)] + [
            (name, ctypes.c_uint64) for name in ["total_phys", "avail_phys", "total_page", "avail_page", "total_virtual", "avail_virtual", "avail_extended"]]
    class ProcessMemory(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_uint32), ("faults", ctypes.c_uint32)] + [
            (name, ctypes.c_size_t) for name in ["peak_ws", "ws", "peak_paged", "paged", "peak_nonpaged", "nonpaged", "pagefile", "peak_pagefile", "private"]]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(MemoryStatus)]
    kernel.GlobalMemoryStatusEx.restype = ctypes.c_int
    kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel.CloseHandle.restype = ctypes.c_int
    psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(ProcessMemory), ctypes.c_uint32]
    psapi.GetProcessMemoryInfo.restype = ctypes.c_int
    status = MemoryStatus();status.length = ctypes.sizeof(status)
    if not kernel.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise RuntimeError("System memory probe failed")
    handle = kernel.OpenProcess(0x0400 | 0x0010, False, pid)
    if not handle:
        raise RuntimeError("Owned process memory probe failed")
    counters = ProcessMemory();counters.cb = ctypes.sizeof(counters)
    try:
        if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
            raise RuntimeError("Owned process counters unavailable")
    finally:
        kernel.CloseHandle(handle)
    return {"total_physical_bytes": int(status.total_phys), "available_bytes": int(status.avail_phys),
            "working_set_bytes": int(counters.ws), "peak_working_set_bytes": int(counters.peak_ws),
            "private_bytes": int(counters.private)}


def stop_reason(budget: Budget, elapsed: float, phase_elapsed: float, phase: str, memory: dict) -> str | None:
    if elapsed >= budget.max_wall_seconds:
        return "global_wall_timeout"
    if phase == "loading" and phase_elapsed >= budget.max_load_seconds:
        return "model_load_timeout"
    if phase == "origin" and phase_elapsed >= budget.max_origin_seconds:
        return "origin_timeout"
    if memory["available_bytes"] < budget.min_available_bytes:
        return "system_available_memory_below_floor"
    if max(memory["working_set_bytes"], memory.get("peak_working_set_bytes", 0)) > budget.max_working_set_bytes:
        return "process_working_set_limit"
    if memory["private_bytes"] > budget.max_private_bytes:
        return "process_private_commit_limit"
    return None


class SlowFixture(PersistenceFixture):
    identity = "synthetic_slow_fixture_not_chronos"

    def predict(self, context: Context) -> Quantiles:
        time.sleep(1.)
        return super().predict(context)


class CrossedFixture(PersistenceFixture):
    identity = "synthetic_invalid_fixture_not_chronos"

    def predict(self, context: Context) -> Quantiles:
        return Quantiles(2., 1., 3.)


def fixture_worker(events, protocol: dict, backend: str) -> None:
    # Fixed local classes only. There is no dynamic import or real-model entry.
    factories = {"persistence_fixture": PersistenceFixture, "slow_fixture": SlowFixture, "crossed_fixture": CrossedFixture}
    try:
        predictor = factories[backend]()
        events.put({"event": "model_ready", "identity": predictor.identity, "fixture_only": True})
        result = evaluate(fixture_rows(), protocol, predictor, fixture=True, progress=events.put)
        events.put({"event": "complete", "report": result})
    except Exception as exc:
        events.put({"event": "error", "error_type": type(exc).__name__, "fixture_only": True})


def run_fixture(protocol: dict, output: Path, *, backend: str = "persistence_fixture", budget: Budget | None = None) -> dict:
    if backend not in {"persistence_fixture", "slow_fixture", "crossed_fixture"}:
        raise ValueError("Actual-model execution is unavailable and unauthorized")
    output.mkdir(parents=True, exist_ok=False)
    # Fixture monitoring deliberately does not certify actual-model capacity.
    budget = budget or Budget(start_available_bytes=0, min_available_bytes=0)
    initial = windows_memory(os.getpid())
    initial_disk = disk_resources(output)
    disk_reason = disk_stop_reason(initial_disk, starting=True)
    if disk_reason:
        result = {'status': 'stopped', 'stop_reason': disk_reason, 'fixture_only': True,
                  'actual_model_executed': False, 'initial_disk': initial_disk}
        (output / 'run-status.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        return result
    if initial["available_bytes"] < budget.start_available_bytes:
        result = {"status": "stopped", "stop_reason": "insufficient_start_memory", "fixture_only": True,
                  "actual_model_executed": False, "budget": asdict(budget), "initial_resources": initial}
        (output / "run-status.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result
    os.environ.update(OMP_NUM_THREADS=str(budget.cpu_threads), OPENBLAS_NUM_THREADS=str(budget.blas_threads),
                      MKL_NUM_THREADS=str(budget.blas_threads), HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
                      ENABLE_PAID_AI="0", AUTO_REFRESH="0")
    ctx = mp.get_context("spawn")
    events = ctx.Queue(maxsize=128)
    process = ctx.Process(target=fixture_worker, args=(events, protocol, backend))
    started = time.monotonic();phase_started = started;phase = "loading"
    process.start()
    if process.pid is None:
        raise RuntimeError('Owned worker has no process ID')
    reason = None;report = None;completed = 0;last_origin = None;error_type = None
    peaks = {"working_set_bytes": 0, "peak_working_set_bytes": 0, "private_bytes": 0}
    minimum_available = initial["available_bytes"]
    last_disk_check = started
    with (output / "events.jsonl").open("w", encoding="utf-8") as log:
        while True:
            received = False
            try:
                event = events.get(timeout=budget.poll_seconds)
                received = True
                log.write(json.dumps(event if event["event"] != "complete" else {"event": "complete", "report_id": event["report"]["report_id"]}, ensure_ascii=False) + "\n");log.flush()
                if event["event"] == "model_ready":
                    phase = "idle";phase_started = time.monotonic()
                elif event["event"] == "origin_started":
                    phase = "origin";phase_started = time.monotonic();last_origin = {k: event[k] for k in ["key", "target", "split"]}
                elif event["event"] == "origin_finished":
                    phase = "idle";completed += 1
                elif event["event"] == "complete":
                    report = event["report"];break
                elif event["event"] == "error":
                    reason = "backend_or_evaluation_error";error_type = event["error_type"];break
            except queue.Empty:
                received = False
            if not process.is_alive():
                if received:
                    continue  # Drain queued completion/error before diagnosing exit.
                reason = "worker_exited_without_complete_report";break
            try:
                memory = windows_memory(process.pid)
            except RuntimeError:
                if not process.is_alive():
                    continue
                reason = "resource_probe_failed";break
            for field in peaks:peaks[field] = max(peaks[field], memory[field])
            minimum_available = min(minimum_available, memory["available_bytes"])
            now = time.monotonic()
            reason = stop_reason(budget, now - started, now - phase_started, phase, memory)
            if not reason and now - last_disk_check >= 5.:
                try:
                    reason = disk_stop_reason(disk_resources(output))
                except (OSError, RuntimeError):
                    reason = 'disk_probe_failed'
                last_disk_check = now
            if reason:
                break
    if process.is_alive() and report is None:
        process.terminate()  # Only the worker created immediately above.
    process.join(timeout=3.)
    if process.is_alive():
        process.terminate();process.join(timeout=3.)
    events.close()
    if report is not None:
        (output / "fixture-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    result = {"status": "fixture_complete" if report else "stopped", "fixture_only": True,
              "actual_model_executed": False, "stop_reason": reason, "error_type": error_type,
              "completed_origins": completed, "expected_origins": 168,
              "last_origin": last_origin, "elapsed_seconds": time.monotonic() - started,
              "budget": asdict(budget), "initial_resources": initial, "sampled_peaks": peaks,
              "initial_disk": initial_disk, "disk_probe_scope": "owned fixture output only; future real runner must monitor its full isolated research root",
              "minimum_available_bytes": minimum_available, "worker_exit_code": process.exitcode,
              "production_default_changed": False,
              "limits": "Fixture observations and fake quantiles only; no real model capacity or predictive result validated."}
    (output / "run-status.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return result
