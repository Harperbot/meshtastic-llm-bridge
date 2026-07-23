import json
import types
from unittest.mock import MagicMock

import bridge


def _make_provider_config(label="test"):
    return {"label": label, "kind": "openai_compat", "base_url": "http://fake/v1", "api_key": "fake-key", "model": "fake-model"}


def test_llm_max_tokens_high_enough_for_reasoning_models():
    """max_tokens 太小(舊值 200)時, thinking/reasoning 類本地模型會把預算全花在內部思考,
    導致最終 content 是空字串(實測 gemma4:e2b-it-qat 對 Ollama /v1 端點的真實行為)"""
    assert bridge.LLM_MAX_TOKENS >= 800


def test_call_openai_compat_provider_uses_llm_max_tokens_constant(monkeypatch):
    fake_message = types.SimpleNamespace(content="這是回覆", tool_calls=None)
    fake_response = types.SimpleNamespace(choices=[types.SimpleNamespace(message=fake_message)])

    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = fake_response
    monkeypatch.setattr(bridge, "_build_openai_client", lambda base_url, api_key: fake_client)

    bridge.call_openai_compat_provider(_make_provider_config(), "test", [], is_online=True)

    assert fake_client.chat.completions.create.call_args.kwargs["max_tokens"] == bridge.LLM_MAX_TOKENS


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


def _make_anthropic_config():
    return {"label": "test-anthropic", "kind": "anthropic", "base_url": None, "api_key": "fake-anthropic-key", "model": "claude-sonnet-5"}


def test_call_anthropic_provider_returns_text_without_tool_use(monkeypatch):
    text_block = types.SimpleNamespace(type="text", text="這是 Claude 的回覆")
    fake_response = types.SimpleNamespace(stop_reason="end_turn", content=[text_block])

    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_response
    monkeypatch.setattr(bridge, "_build_anthropic_client", lambda api_key: fake_client)

    result = bridge.call_anthropic_provider(_make_anthropic_config(), "你好", [], is_online=True)

    assert result == "這是 Claude 的回覆"
    call_kwargs = fake_client.messages.create.call_args.kwargs
    assert call_kwargs["model"] == "claude-sonnet-5"
    tool_names = [t["name"] for t in call_kwargs["tools"]]
    assert "find_shelter" in tool_names
    # Anthropic 用 input_schema，不是 OpenAI 的 parameters
    shelter_tool = next(t for t in call_kwargs["tools"] if t["name"] == "find_shelter")
    assert "input_schema" in shelter_tool
    assert "parameters" not in shelter_tool


def test_call_anthropic_provider_executes_tool_use_and_returns_second_response(monkeypatch):
    tool_use_block = types.SimpleNamespace(
        type="tool_use", id="toolu_1", name="find_shelter", input={"lat": 25.0, "lon": 121.0}
    )
    first_response = types.SimpleNamespace(stop_reason="tool_use", content=[tool_use_block])

    text_block = types.SimpleNamespace(type="text", text="附近有避難所")
    second_response = types.SimpleNamespace(stop_reason="end_turn", content=[text_block])

    fake_client = MagicMock()
    fake_client.messages.create.side_effect = [first_response, second_response]
    monkeypatch.setattr(bridge, "_build_anthropic_client", lambda api_key: fake_client)

    captured_tool_call = {}
    def fake_execute(tc, is_online, loc):
        captured_tool_call["name"] = tc.function.name
        captured_tool_call["arguments"] = tc.function.arguments
        return {"tool_output": "測試避難所"}
    monkeypatch.setattr(bridge, "execute_llm_tool_call", fake_execute)

    result = bridge.call_anthropic_provider(_make_anthropic_config(), "附近避難所在哪", [], is_online=True)

    assert result == "附近有避難所"
    assert captured_tool_call["name"] == "find_shelter"
    assert captured_tool_call["arguments"] == {"lat": 25.0, "lon": 121.0}
    assert fake_client.messages.create.call_count == 2

    second_call_messages = fake_client.messages.create.call_args_list[1].kwargs["messages"]
    tool_result_msg = second_call_messages[-1]
    assert tool_result_msg["role"] == "user"
    tool_result_block = tool_result_msg["content"][0]
    assert tool_result_block["type"] == "tool_result"
    assert tool_result_block["tool_use_id"] == "toolu_1"


def test_call_anthropic_provider_raises_on_client_error(monkeypatch):
    fake_client = MagicMock()
    fake_client.messages.create.side_effect = RuntimeError("Anthropic API 錯誤")
    monkeypatch.setattr(bridge, "_build_anthropic_client", lambda api_key: fake_client)

    try:
        bridge.call_anthropic_provider(_make_anthropic_config(), "你好", [], is_online=True)
        assert False, "應該要 raise"
    except RuntimeError as e:
        assert "Anthropic API 錯誤" in str(e)


def test_call_llm_with_fallback_returns_first_success():
    providers = [{"kind": "openai_compat", "label": "p1"}, {"kind": "openai_compat", "label": "p2"}]

    def fake_openai_compat(provider, prompt, chat_history, is_online):
        return f"回覆來自 {provider['label']}"

    import bridge
    orig = bridge.call_openai_compat_provider
    bridge.call_openai_compat_provider = fake_openai_compat
    try:
        result = bridge.call_llm_with_fallback(providers, "test", [], is_online=True)
    finally:
        bridge.call_openai_compat_provider = orig

    assert result == "回覆來自 p1"


def test_call_llm_with_fallback_tries_next_on_failure(monkeypatch):
    providers = [
        {"kind": "openai_compat", "label": "p1"},
        {"kind": "anthropic", "label": "p2"},
    ]

    def fake_openai_compat(provider, prompt, chat_history, is_online):
        raise RuntimeError("p1 掛了")

    def fake_anthropic(provider, prompt, chat_history, is_online):
        return "來自 p2 的回覆"

    monkeypatch.setattr(bridge, "call_openai_compat_provider", fake_openai_compat)
    monkeypatch.setattr(bridge, "call_anthropic_provider", fake_anthropic)

    result = bridge.call_llm_with_fallback(providers, "test", [], is_online=True)

    assert result == "來自 p2 的回覆"


def test_call_llm_with_fallback_raises_when_all_fail(monkeypatch):
    providers = [{"kind": "openai_compat", "label": "p1"}]

    def fake_openai_compat(provider, prompt, chat_history, is_online):
        raise RuntimeError("全部都掛了")

    monkeypatch.setattr(bridge, "call_openai_compat_provider", fake_openai_compat)

    try:
        bridge.call_llm_with_fallback(providers, "test", [], is_online=True)
        assert False, "應該要 raise"
    except RuntimeError as e:
        assert "全部都掛了" in str(e)


def test_call_llm_with_fallback_empty_list_raises():
    try:
        bridge.call_llm_with_fallback([], "test", [], is_online=True)
        assert False, "應該要 raise"
    except RuntimeError:
        pass


def test_call_llm_with_fallback_does_not_leak_mutated_chat_history_between_providers(monkeypatch):
    """Task 3/4 review finding: call_openai_compat_provider / call_anthropic_provider both
    mutate the chat_history list object passed to them in place. If call_llm_with_fallback
    passes the SAME list object to every provider attempt, a provider that mutates its copy
    and then fails will pollute what the next provider sees. Each provider attempt must get
    a fresh copy of the original chat_history.
    """
    providers = [
        {"kind": "openai_compat", "label": "p1"},
        {"kind": "openai_compat", "label": "p2"},
    ]

    original_history = [{"role": "user", "content": "先前的訊息"}]
    received_by_p2 = {}

    def fake_p1(provider, prompt, chat_history, is_online):
        # simulate in-place mutation like the real provider functions do
        chat_history.append({"role": "assistant", "content": "p1 的部分回覆", "tool_calls": ["fake"]})
        raise RuntimeError("p1 掛了（工具呼叫階段失敗）")

    call_count = {"n": 0}

    def fake_p2(provider, prompt, chat_history, is_online):
        call_count["n"] += 1
        received_by_p2["history"] = list(chat_history)
        return "來自 p2 的回覆"

    # both providers are kind=openai_compat in this test, so monkeypatch that single dispatch point
    def dispatch(provider, prompt, chat_history, is_online):
        if provider["label"] == "p1":
            return fake_p1(provider, prompt, chat_history, is_online)
        return fake_p2(provider, prompt, chat_history, is_online)

    monkeypatch.setattr(bridge, "call_openai_compat_provider", dispatch)

    result = bridge.call_llm_with_fallback(providers, "test", original_history, is_online=True)

    assert result == "來自 p2 的回覆"
    # p2 must have received a clean copy matching the ORIGINAL history, not p1's mutated version
    assert received_by_p2["history"] == [{"role": "user", "content": "先前的訊息"}]
    # the caller's original list object must not have been mutated by p1's failed attempt either
    assert original_history == [{"role": "user", "content": "先前的訊息"}]
