import json
import os
import queue
from pathlib import Path
import subprocess
import sys
import threading

import pytest

from chronos_owned_process import OwnedProcess, parent_pid
from chronos_runtime_resources import disk_resources


def test_fast_full_tree_accounting_counts_nested_bytes_and_refuses_escape(tmp_path):
    (tmp_path / 'nested').mkdir()
    (tmp_path / 'one.bin').write_bytes(b'abc')
    (tmp_path / 'nested/two.bin').write_bytes(b'12345')
    result = disk_resources(tmp_path)
    assert result['logical_research_bytes'] == 8 and result['free_bytes'] > 0
    try:
        (tmp_path / 'escape').symlink_to(tmp_path.parent, target_is_directory=True)
    except OSError:
        return  # Windows accounts may not hold symlink creation privileges.
    with pytest.raises(RuntimeError, match='symlink|reparse'):
        disk_resources(tmp_path)


@pytest.mark.skipif(os.name != 'nt', reason='Verifies native Windows launcher/actual child ownership')
def test_actual_venv_worker_handle_rejects_wrong_parent_and_stops_only_owned_child():
    code = "import json,os,time; print(json.dumps({'pid':os.getpid(),'parent':os.getppid()}),flush=True); time.sleep(20)"
    process = subprocess.Popen([sys.executable, '-B', '-c', code], stdout=subprocess.PIPE, text=True, encoding='utf-8')
    responses = queue.Queue()
    reader = threading.Thread(target=lambda: responses.put(process.stdout.readline()), daemon=True); reader.start()
    owned = None
    try:
        event = json.loads(responses.get(timeout=10))
        expected = process.pid if event['pid'] != process.pid else os.getpid()
        assert event['parent'] == expected and parent_pid(event['pid']) == expected
        with pytest.raises(RuntimeError, match='verified child'):
            OwnedProcess(event['pid'], expected + 1)
        owned = OwnedProcess(event['pid'], expected)
        assert owned.alive()
        owned.terminate()
        assert process.wait(timeout=5) != 0 and not owned.alive()
    finally:
        if owned is not None:
            if owned.alive(): owned.terminate()
            owned.close()
        if process.poll() is None: process.terminate()
        process.wait(timeout=5)
        process.stdout.close()
