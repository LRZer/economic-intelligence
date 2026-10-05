import hashlib,importlib.util,json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('repository_audit',ROOT/'scripts/check_repository.py')
audit_module=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit_module)


def workspace(tmp_path):
    (tmp_path/'docs').mkdir();(tmp_path/'data').mkdir()
    data=tmp_path/'data/sample.json';data.write_text('{"value":1}',encoding='utf-8')
    manifest=tmp_path/'docs/data-file-manifest.json'
    manifest.write_text(json.dumps([{'file':'data/sample.json','bytes':data.stat().st_size,'sha256':hashlib.sha256(data.read_bytes()).hexdigest()}]),encoding='utf-8')
    return manifest,['docs/data-file-manifest.json','data/sample.json']


def test_audit_is_readonly_and_detects_changed_approved_data(tmp_path):
    manifest,names=workspace(tmp_path);before=manifest.read_bytes()
    assert audit_module.audit(tmp_path,names)['status']=='passed'
    (tmp_path/'data/sample.json').write_text('{"value":2}',encoding='utf-8')
    assert audit_module.audit(tmp_path,names)['status']=='failed' and manifest.read_bytes()==before


def test_only_exact_frozen_protocol_path_can_receive_explicit_exception(tmp_path,monkeypatch):
    _,names=workspace(tmp_path)
    protocol=tmp_path/audit_module.FROZEN_PROTOCOL;protocol.parent.mkdir(parents=True)
    protocol.write_text('D:\\Documents\\ChatGPT\\task',encoding='utf-8');names.append(audit_module.FROZEN_PROTOCOL)
    monkeypatch.setattr(audit_module,'FROZEN_SHA',hashlib.sha256(protocol.read_bytes()).hexdigest())
    assert audit_module.audit(tmp_path,names)['status']=='failed'
    assert audit_module.audit(tmp_path,names,allow_frozen_task_paths=True)['status']=='passed'
    protocol.write_text('D:\\Documents\\ChatGPT\\other',encoding='utf-8')
    assert audit_module.audit(tmp_path,names,allow_frozen_task_paths=True)['status']=='failed'


def test_jsonl_credentials_and_missing_sparse_files_fail_without_content_leak(tmp_path):
    _,names=workspace(tmp_path);log=tmp_path/'trace.jsonl'
    fake='sk-'+('a'*32);log.write_text(json.dumps({'fixture':fake}),encoding='utf-8')
    result=audit_module.audit(tmp_path,names+['trace.jsonl','missing.py'])
    assert result['status']=='failed' and len(result['issues'])==2 and fake not in json.dumps(result)
