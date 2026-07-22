import bridge


def test_handle_message_online_uses_cloud_providers(monkeypatch):
    monkeypatch.setattr(bridge, "internet_connected", True)
    monkeypatch.setattr(bridge, "check_internet_connection", lambda: True)
    monkeypatch.setattr(bridge, "CLOUD_LLM_PROVIDERS", [{"kind": "openai_compat", "label": "cloud1"}])
    monkeypatch.setattr(bridge, "LOCAL_LLM_PROVIDERS", [{"kind": "openai_compat", "label": "local1"}])

    captured = {}
    def fake_fallback(providers, prompt, chat_history, is_online):
        captured["providers"] = providers
        captured["is_online"] = is_online
        return "雲端回覆"
    monkeypatch.setattr(bridge, "call_llm_with_fallback", fake_fallback)

    sent = []
    monkeypatch.setattr(bridge, "send_meshtastic_message", lambda text, destination_id=None: sent.append((text, destination_id)))

    bridge.handle_incoming_meshtastic_message("!node1", "隨便問個問題")

    assert captured["providers"] == [{"kind": "openai_compat", "label": "cloud1"}]
    assert captured["is_online"] is True
    assert sent == [("AI: 雲端回覆", "!node1")]


def test_handle_message_offline_uses_local_providers(monkeypatch):
    monkeypatch.setattr(bridge, "internet_connected", False)
    monkeypatch.setattr(bridge, "check_internet_connection", lambda: False)
    monkeypatch.setattr(bridge, "CLOUD_LLM_PROVIDERS", [{"kind": "openai_compat", "label": "cloud1"}])
    monkeypatch.setattr(bridge, "LOCAL_LLM_PROVIDERS", [{"kind": "openai_compat", "label": "local1"}])

    captured = {}
    def fake_fallback(providers, prompt, chat_history, is_online):
        captured["providers"] = providers
        captured["is_online"] = is_online
        return "本地回覆"
    monkeypatch.setattr(bridge, "call_llm_with_fallback", fake_fallback)

    sent = []
    monkeypatch.setattr(bridge, "send_meshtastic_message", lambda text, destination_id=None: sent.append((text, destination_id)))

    bridge.handle_incoming_meshtastic_message("!node1", "隨便問個問題")

    assert captured["providers"] == [{"kind": "openai_compat", "label": "local1"}]
    assert captured["is_online"] is False
    assert sent == [("AI: 本地回覆", "!node1")]


def test_handle_message_all_providers_fail_sends_friendly_error(monkeypatch):
    monkeypatch.setattr(bridge, "internet_connected", True)
    monkeypatch.setattr(bridge, "check_internet_connection", lambda: True)
    monkeypatch.setattr(bridge, "CLOUD_LLM_PROVIDERS", [{"kind": "openai_compat", "label": "cloud1"}])

    def fake_fallback(providers, prompt, chat_history, is_online):
        raise RuntimeError("所有 LLM provider 皆失敗: 連線逾時")
    monkeypatch.setattr(bridge, "call_llm_with_fallback", fake_fallback)

    sent = []
    monkeypatch.setattr(bridge, "send_meshtastic_message", lambda text, destination_id=None: sent.append((text, destination_id)))

    bridge.handle_incoming_meshtastic_message("!node1", "隨便問個問題")

    assert len(sent) == 1
    assert sent[0][1] == "!node1"
    assert "❌" in sent[0][0]
