"""Every HTTP response and credential in these tests is synthetic."""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

from scripts import deepseek_live_check as check
from guanlan import ai

FAKE_KEY = 'sk-' + 'x' * 32


def body():
    return {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps({
        'summary': '这是合成材料连接测试',
        'observations': [{'interpretation': '仅验证材料引用', 'evidence_ids': ['smoke-test']}],
        'limitations': ['不是官方经济观察']} , ensure_ascii=False)}}],
        'usage': {'prompt_tokens': 300, 'completion_tokens': 80, 'total_tokens': 380,
                  'private': FAKE_KEY, 'prompt_cache_hit_tokens': True}, 'unused_raw': FAKE_KEY}


@pytest.fixture
def harness(monkeypatch, tmp_path):
    monkeypatch.setattr(check, 'ROOT', tmp_path)
    key_file = tmp_path / 'api_key.md'
    key_file.write_text(FAKE_KEY, encoding='utf-8')
    monkeypatch.setattr(check.sys, 'stdin', SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr('builtins.input', lambda prompt: '')
    monkeypatch.setenv('ENABLE_PAID_AI', '0')
    post = Mock(return_value=Mock(status_code=200, json=Mock(return_value=body())))
    monkeypatch.setattr(ai.requests, 'post', post)
    return tmp_path, key_file, post


def report(root):
    return json.loads((root / 'reports/deepseek-live-check.json').read_text(encoding='utf-8'))


def guard_key_reads(monkeypatch, key_file):
    original = Path.read_text
    def guarded(path, *args, **kwargs):
        if path == key_file:
            raise AssertionError('Key file must not be read before local confirmation')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'read_text', guarded)


def test_default_preview_never_reads_key_or_makes_request(harness, monkeypatch):
    root, key_file, post = harness
    guard_key_reads(monkeypatch, key_file)
    assert check.main(['--key-file', str(key_file)]) == 0
    post.assert_not_called()
    result = json.loads((root / 'reports/deepseek-preflight.json').read_text(encoding='utf-8'))
    assert result['mode'] == 'offline_preview' and result['status'] == 'not_run'
    assert result['key_file_exists'] and not result['key_file_content_read']
    payload = result['request_preview']
    assert payload['model'] == 'deepseek-flash' and payload['thinking'] == {'type': 'disabled'}
    assert payload['max_tokens'] == 512 and payload['response_format'] == {'type': 'json_object'}
    assert json.loads(payload['messages'][1]['content']) == check.EVIDENCE
    assert not (root / 'reports/deepseek-live-check.json').exists()


def test_noninteractive_live_is_blocked_without_key_read(harness, monkeypatch):
    root, key_file, post = harness
    monkeypatch.setattr(check.sys, 'stdin', SimpleNamespace(isatty=lambda: False))
    guard_key_reads(monkeypatch, key_file)
    assert check.main(['--live', '--key-file', str(key_file)]) == 2
    post.assert_not_called()
    assert not (root / 'reports/deepseek-live-check.json').exists()


def test_cancellation_never_reads_key_or_reserves_request(harness, monkeypatch):
    root, key_file, post = harness
    monkeypatch.setattr('builtins.input', lambda prompt: 'cancel')
    guard_key_reads(monkeypatch, key_file)
    assert check.main(['--live', '--key-file', str(key_file)]) == 2
    post.assert_not_called()
    assert report(root)['reason'] == 'user_cancelled'
    assert not (root / 'reports/deepseek-live-attempt.json').exists()


@pytest.mark.parametrize('failure',['missing','empty','ambiguous'])
def test_bad_key_file_does_not_send_or_reserve(harness,failure):
    root,key_file,post=harness
    if failure=='missing':key_file.unlink()
    else:key_file.write_text('' if failure=='empty' else FAKE_KEY+'\n'+'sk-'+'y'*32,encoding='utf-8')
    assert check.main(['--live','--key-file',str(key_file)])==2
    post.assert_not_called()
    result=report(root)
    assert result['key_file_read_attempted'] and not result['key_file_parse_succeeded']
    assert not result['live_request_attempted'] and not result['may_have_been_billed']
    assert not (root/'reports/deepseek-live-attempt.json').exists()


def test_synthetic_user_trigger_only_header_no_secret_persistence(harness, monkeypatch, capsys):
    root, key_file, post = harness
    before = key_file.read_bytes()
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'unrelated-existing-test-setting')
    assert check.main(['--live', '--key-file', str(key_file)]) == 0
    assert post.call_count == 1
    args, kwargs = post.call_args
    assert args == (ai.DEEPSEEK_URL,)
    assert kwargs['headers']['Authorization'] == 'Bearer ' + FAKE_KEY
    assert kwargs['allow_redirects'] is False
    assert kwargs['json']['model'] == 'deepseek-flash'
    assert kwargs['json']['max_tokens'] == 512 and kwargs['json']['thinking'] == {'type': 'disabled'}
    assert json.loads(kwargs['json']['messages'][1]['content']) == check.EVIDENCE
    assert FAKE_KEY not in json.dumps(kwargs['json'])
    result = report(root)
    assert result['status'] == 'passed' and result['validation_passed'] and result['request_attempts'] == 1
    assert result['usage'] == {'prompt_tokens': 300, 'completion_tokens': 80, 'total_tokens': 380}
    saved = ''.join(p.read_text(encoding='utf-8') for p in (root / 'reports').iterdir())
    assert FAKE_KEY not in saved + capsys.readouterr().out
    assert '这是合成材料连接测试' not in saved
    assert key_file.read_bytes() == before
    assert check.os.environ['ENABLE_PAID_AI'] == '0'
    assert check.os.environ['DEEPSEEK_API_KEY'] == 'unrelated-existing-test-setting'


def test_repeated_or_noninteractive_run_preserves_receipt_and_sends_once(harness, monkeypatch):
    root, key_file, post = harness
    assert check.main(['--live', '--key-file', str(key_file)]) == 0
    before = (root / 'reports/deepseek-live-check.json').read_bytes()
    guard_key_reads(monkeypatch, key_file)
    assert check.main(['--live', '--key-file', str(key_file)]) == 2
    monkeypatch.setattr(check.sys, 'stdin', SimpleNamespace(isatty=lambda: False))
    assert check.main(['--live', '--key-file', str(key_file)]) == 2
    assert post.call_count == 1
    assert (root / 'reports/deepseek-live-check.json').read_bytes() == before


def test_concurrent_reservation_loser_does_not_send_or_overwrite(harness, monkeypatch):
    root, key_file, post = harness
    attempt = root / 'reports/deepseek-live-attempt.json'
    output = root / 'reports/deepseek-live-check.json'
    original = Path.open
    def concurrent_open(path, *args, **kwargs):
        if path == attempt and args and args[0] == 'x':
            output.write_text('{"owner":"another-confirmed-window"}',encoding='utf-8')
            raise FileExistsError
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path,'open',concurrent_open)
    assert check.main(['--live','--key-file',str(key_file)]) == 2
    post.assert_not_called()
    assert json.loads(output.read_text()) == {'owner':'another-confirmed-window'}
    assert check.os.environ['ENABLE_PAID_AI'] == '0'


@pytest.mark.parametrize('status,category', [(400,'invalid_request'), (401,'authentication'),
    (402,'balance'), (429,'rate_limit'), (500,'upstream'), (302,'upstream')])
def test_http_errors_and_redirect_never_retry_or_disclose_response(harness, status, category, capsys):
    root, key_file, post = harness
    post.return_value = Mock(status_code=status, json=Mock(side_effect=AssertionError('Error body must not be read')))
    assert check.main(['--live', '--key-file', str(key_file)]) == 2
    assert post.call_count == 1 and post.call_args.kwargs['allow_redirects'] is False
    post.return_value.json.assert_not_called()
    result = report(root)
    assert result['reason'] == category and result['http_status'] == status
    assert result['may_have_been_billed']
    assert FAKE_KEY not in (root / 'reports/deepseek-live-check.json').read_text() + capsys.readouterr().out


@pytest.mark.parametrize('failure', [requests.Timeout, requests.ConnectionError])
def test_transport_error_is_ambiguous_not_retried_or_logged(harness, failure, capsys):
    root, key_file, post = harness
    post.side_effect = failure(FAKE_KEY)
    assert check.main(['--live', '--key-file', str(key_file)]) == 2
    assert post.call_count == 1 and report(root)['reason'] == 'transport'
    assert report(root)['may_have_been_billed'] and report(root)['request_attempts'] == 1
    assert FAKE_KEY not in (root / 'reports/deepseek-live-check.json').read_text() + capsys.readouterr().out


@pytest.mark.parametrize('malformation', ['root_list','empty_choices','length','invalid_json','unknown_id','invalid_item'])
def test_success_http_with_invalid_model_output_is_not_passed(harness, malformation):
    root, key_file, post = harness
    payload = body()
    if malformation == 'root_list': payload = []
    elif malformation == 'empty_choices': payload['choices'] = []
    elif malformation == 'length': payload['choices'][0]['finish_reason'] = 'length'
    elif malformation == 'invalid_json': payload['choices'][0]['message']['content'] = 'not-json'
    else:
        brief = json.loads(payload['choices'][0]['message']['content'])
        if malformation == 'unknown_id': brief['observations'][0]['evidence_ids'] = ['not-provided']
        else: brief['observations'] = ['not-an-object']
        payload['choices'][0]['message']['content'] = json.dumps(brief)
    post.return_value.json.return_value = payload
    assert check.main(['--live', '--key-file', str(key_file)]) == 2
    assert not report(root)['validation_passed'] and post.call_count == 1


@pytest.mark.parametrize('kind', ['plain','assignment','heading','ambiguous','missing','oversize'])
def test_key_file_parser_only_temporary_read_of_selected_synthetic_key(tmp_path, kind):
    path = tmp_path / 'api_key.md'
    other = 'sk-' + 'y' * 32
    contents = {'plain': FAKE_KEY, 'assignment': 'DEEPSEEK_API_KEY="' + FAKE_KEY + '"',
                'heading': '# OpenAI\n' + other + '\n# DeepSeek\n```\n' + FAKE_KEY + '\n```',
                'ambiguous': FAKE_KEY + '\n' + other, 'oversize': FAKE_KEY + ' ' * 66000}
    if kind != 'missing':path.write_text(contents[kind],encoding='utf-8')
    if kind in ('ambiguous','missing','oversize'):
        with pytest.raises(check.KeyFileError): check.read_key_for_user_triggered_test(path)
    else:
        before = path.read_bytes()
        assert check.read_key_for_user_triggered_test(path) == FAKE_KEY
        assert path.read_bytes() == before


def test_request_parameters_checked_before_network(monkeypatch):
    post = Mock()
    monkeypatch.setattr(ai.requests, 'post', post)
    for tokens in [0,1201,True]:
        with pytest.raises(ValueError): ai.build_grounded_payload(check.EVIDENCE,max_tokens=tokens)
    for attempts in [0,3,True]:
        with pytest.raises(ValueError): ai._post({},'synthetic-test-key',max_attempts=attempts)
    post.assert_not_called()


def test_legacy_china_entry_is_paid_opt_in_before_key_or_http(monkeypatch):
    from china_macro import app
    monkeypatch.setenv('ENABLE_PAID_AI','0')
    monkeypatch.setenv('DEEPSEEK_API_KEY','synthetic-existing-key')
    dashboard = Mock(side_effect=AssertionError('No paid analysis should start'))
    post = Mock()
    monkeypatch.setattr(app,'dashboard',dashboard)
    monkeypatch.setattr(app.requests,'post',post)
    assert not app._analyze()['ok']
    dashboard.assert_not_called()
    post.assert_not_called()


def test_legacy_china_request_uses_official_bounded_parameters(monkeypatch,tmp_path):
    from china_macro import app
    monkeypatch.setenv('ENABLE_PAID_AI','1')
    monkeypatch.setenv('DEEPSEEK_API_KEY',FAKE_KEY)
    monkeypatch.delenv('DEEPSEEK_MODEL',raising=False)
    monkeypatch.setattr(app,'DB_PATH',tmp_path/'macro.sqlite3')
    monkeypatch.setattr(app,'ROOT',tmp_path)
    app.initialize()
    fake={'latest':{'fixture':1},'catalog':[{'key':'fixture','name':'合成材料','basis':'test','unit':'test'}],
          'quality':{'metrics':[{'key':'fixture','coverage_pct':100,'missing':0}]},
          'reader_summary':{'changes':{}},'snapshot_hash':'synthetic-snapshot',
          'series':{'fixture':[{'period':'TEST','value':1,'source_url':'https://api-docs.deepseek.com/'}]}}
    monkeypatch.setattr(app,'dashboard',lambda:fake)
    post=Mock(return_value=Mock(status_code=200,json=Mock(return_value={'choices':[{'finish_reason':'stop','message':{'content':'合成摘要'}}]})))
    monkeypatch.setattr(app.requests,'post',post)
    assert app._analyze()['ok']
    assert post.call_count==1 and post.call_args.args==(ai.DEEPSEEK_URL,)
    parameters=post.call_args.kwargs
    assert parameters['allow_redirects'] is False
    assert parameters['json']['model']=='deepseek-flash'
    assert parameters['json']['thinking']=={'type':'disabled'} and parameters['json']['max_tokens']==2000
    assert FAKE_KEY not in json.dumps(parameters['json'])
