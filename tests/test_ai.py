from unittest.mock import Mock, patch

from guanlan.ai import generate_brief


def test_ai_key_only_in_authorization_header(monkeypatch):
    monkeypatch.setenv("ENABLE_PAID_AI", "1")
    response = Mock()
    response.json.return_value = {"choices": [{"message": {"content": "经核查的摘要"}}]}
    with patch("guanlan.ai.requests.post", return_value=response) as post:
        result = generate_brief({"year": 2024, "growth": 3}, api_key="temporary-test-key")
    assert result == "经核查的摘要"
    args, kwargs = post.call_args
    assert args[0].startswith("https://api.deepseek.com/")
    assert kwargs["headers"]["Authorization"] == "Bearer temporary-test-key"
    assert "temporary-test-key" not in str(kwargs["json"])
