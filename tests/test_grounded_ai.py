import json
from unittest.mock import Mock, patch
import pytest
import requests
from guanlan.ai import generate_grounded_brief

EVIDENCE = [{"id":"cpi:2024-01", "label":"CPI同比", "period":"2024-01", "value":.2,
             "unit":"%", "source_url":"https://www.stats.gov.cn/", "kind":"official_observation"}]


def response(brief):
    result = Mock(status_code=200)
    result.json.return_value = {"choices":[{"message":{"content":json.dumps(brief,ensure_ascii=False)}}]}
    return result


def valid():
    return {"summary":"读数需结合口径核查", "observations":[{"interpretation":"仅描述官方读数", "evidence_ids":["cpi:2024-01"]}],
            "limitations":["不解释原因，不作交易建议"]}


def test_default_offline_never_makes_paid_request(monkeypatch):
    monkeypatch.delenv('ENABLE_PAID_AI', raising=False)
    with patch('guanlan.ai.requests.post') as post, pytest.raises(ValueError,match='默认关闭'):
        generate_grounded_brief(EVIDENCE,api_key='unit-test-placeholder')
    post.assert_not_called()


def test_structured_grounding_whitelists_public_fields_and_rejects_fabricated_citations(monkeypatch):
    monkeypatch.setenv('ENABLE_PAID_AI','1')
    with patch('guanlan.ai.requests.post',return_value=response(valid())) as post:
        result=generate_grounded_brief([{**EVIDENCE[0], 'private_field':'do-not-send'}],api_key='unit-test-placeholder')
        payload=post.call_args.kwargs['json']
    assert result['observations'][0]['evidence_ids'] == ['cpi:2024-01']
    assert 'do-not-send' not in json.dumps(payload)
    assert 'unit-test-placeholder' not in json.dumps(payload)
    invalid=valid();invalid['observations'][0]['evidence_ids']=['invented']
    with patch('guanlan.ai.requests.post',return_value=response(invalid)),pytest.raises(ValueError,match='引用核验'):
        generate_grounded_brief(EVIDENCE,api_key='unit-test-placeholder')


def test_numeric_hallucination_and_network_failures_are_not_displayed(monkeypatch):
    monkeypatch.setenv('ENABLE_PAID_AI','1')
    invalid=valid();invalid['summary']='增长100%'
    with patch('guanlan.ai.requests.post',return_value=response(invalid)),pytest.raises(ValueError):
        generate_grounded_brief(EVIDENCE,api_key='unit-test-placeholder')
    with patch('guanlan.ai.requests.post',side_effect=requests.Timeout('sensitive-detail')) as post:
        with pytest.raises(RuntimeError) as error:
            generate_grounded_brief(EVIDENCE,api_key='unit-test-placeholder')
    assert 'sensitive-detail' not in str(error.value)
    assert post.call_count == 1


def test_rate_limit_retry_is_bounded_and_mocked(monkeypatch):
    monkeypatch.setenv('ENABLE_PAID_AI','1')
    with patch('guanlan.ai.requests.post',side_effect=[Mock(status_code=429),response(valid())]) as post,patch('guanlan.ai.time.sleep'):
        generate_grounded_brief(EVIDENCE,api_key='unit-test-placeholder')
    assert post.call_count==2
