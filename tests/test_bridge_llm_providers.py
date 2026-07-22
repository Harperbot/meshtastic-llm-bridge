import json
import types
from unittest.mock import MagicMock

import bridge


def _make_provider_config(label="test"):
    return {"label": label, "kind": "openai_compat", "base_url": "http://fake/v1", "api_key": "fake-key", "model": "fake-model"}


def test_call_openai_compat_provider_returns_text_without_tool_calls(monkeypatch):
    fake_message = types.SimpleNamespace(content="這是回覆", tool_calls=None)
    fake_response = types.SimpleNamespace(choices=[types.SimpleNamespace(message=fake_message)])

    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = fake_response

    monkeypatch.setattr(bridge, "_build_openai_client", lambda base_url, api_key: fake_client)

    result = bridge.call_openai_compat_provider(_make_provider_config(), "你好", [], is_online=True)

    assert result == "這是回覆"
    fake_client.chat.completions.create.assert_called_once()
    call_kwargs = fake_client.chat.completions.create.call_args.kwargs
    assert call_kwargs["model"] == "fake-model"
    assert call_kwargs["tools"] == bridge.llm_tools


def test_call_openai_compat_provider_executes_tool_call_and_returns_second_response(monkeypatch):
    tool_call = types.SimpleNamespace(
        id="call_1",
        function=types.SimpleNamespace(name="find_shelter", arguments=json.dumps({"lat": 25.0, "lon": 121.0})),
    )
    first_message = types.SimpleNamespace(content=None, tool_calls=[tool_call])
    first_response = types.SimpleNamespace(choices=[types.SimpleNamespace(message=first_message)])

    second_message = types.SimpleNamespace(content="附近有避難所", tool_calls=None)
    second_response = types.SimpleNamespace(choices=[types.SimpleNamespace(message=second_message)])

    fake_client = MagicMock()
    fake_client.chat.completions.create.side_effect = [first_response, second_response]
    monkeypatch.setattr(bridge, "_build_openai_client", lambda base_url, api_key: fake_client)
    monkeypatch.setattr(bridge, "execute_llm_tool_call", lambda tc, is_online, loc: {"tool_output": "測試避難所"})

    result = bridge.call_openai_compat_provider(_make_provider_config(), "附近避難所在哪", [], is_online=True)

    assert result == "附近有避難所"
    assert fake_client.chat.completions.create.call_count == 2
    second_call_messages = fake_client.chat.completions.create.call_args_list[1].kwargs["messages"]
    tool_messages = [m for m in second_call_messages if m.get("role") == "tool"]
    assert len(tool_messages) == 1
    assert tool_messages[0]["tool_call_id"] == "call_1"
    assert json.loads(tool_messages[0]["content"]) == {"tool_output": "測試避難所"}


def test_call_openai_compat_provider_raises_on_client_error(monkeypatch):
    fake_client = MagicMock()
    fake_client.chat.completions.create.side_effect = RuntimeError("連線失敗")
    monkeypatch.setattr(bridge, "_build_openai_client", lambda base_url, api_key: fake_client)

    try:
        bridge.call_openai_compat_provider(_make_provider_config(), "你好", [], is_online=True)
        assert False, "應該要 raise"
    except RuntimeError as e:
        assert "連線失敗" in str(e)


def test_call_openai_compat_provider_passes_is_online_to_tool_execution(monkeypatch):
    tool_call = types.SimpleNamespace(
        id="call_1",
        function=types.SimpleNamespace(name="find_shelter", arguments=json.dumps({"lat": 25.0, "lon": 121.0})),
    )
    first_message = types.SimpleNamespace(content=None, tool_calls=[tool_call])
    first_response = types.SimpleNamespace(choices=[types.SimpleNamespace(message=first_message)])
    second_message = types.SimpleNamespace(content="OK", tool_calls=None)
    second_response = types.SimpleNamespace(choices=[types.SimpleNamespace(message=second_message)])

    fake_client = MagicMock()
    fake_client.chat.completions.create.side_effect = [first_response, second_response]
    monkeypatch.setattr(bridge, "_build_openai_client", lambda base_url, api_key: fake_client)

    captured = {}
    def fake_execute(tc, is_online, loc):
        captured["is_online"] = is_online
        return {"tool_output": "ok"}
    monkeypatch.setattr(bridge, "execute_llm_tool_call", fake_execute)

    bridge.call_openai_compat_provider(_make_provider_config(), "test", [], is_online=False)

    assert captured["is_online"] is False
