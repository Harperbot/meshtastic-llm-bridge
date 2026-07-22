import os

import bridge


def _clear_provider_env(monkeypatch, prefix, max_n=5):
    suffixes = ["PROVIDER", "API_KEY", "MODEL", "BASE_URL"]
    for n in range(1, max_n + 1):
        for suffix in suffixes:
            monkeypatch.delenv(f"{prefix}_{n}_{suffix}", raising=False)


def test_scan_cloud_provider_slots_empty_when_nothing_set(monkeypatch):
    _clear_provider_env(monkeypatch, "CLOUD_LLM")
    assert bridge._scan_cloud_provider_slots() == []


def test_scan_cloud_provider_slots_named_provider_uses_default_base_url(monkeypatch):
    _clear_provider_env(monkeypatch, "CLOUD_LLM")
    monkeypatch.setenv("CLOUD_LLM_1_PROVIDER", "groq")
    monkeypatch.setenv("CLOUD_LLM_1_API_KEY", "gsk-test")
    monkeypatch.setenv("CLOUD_LLM_1_MODEL", "llama-3.3-70b")

    result = bridge._scan_cloud_provider_slots()

    assert len(result) == 1
    assert result[0]["kind"] == "openai_compat"
    assert result[0]["base_url"] == bridge.CLOUD_PROVIDER_DEFAULTS["groq"]
    assert result[0]["api_key"] == "gsk-test"
    assert result[0]["model"] == "llama-3.3-70b"


def test_scan_cloud_provider_slots_explicit_base_url_overrides_default(monkeypatch):
    _clear_provider_env(monkeypatch, "CLOUD_LLM")
    monkeypatch.setenv("CLOUD_LLM_1_PROVIDER", "openai")
    monkeypatch.setenv("CLOUD_LLM_1_API_KEY", "sk-test")
    monkeypatch.setenv("CLOUD_LLM_1_MODEL", "gpt-4o")
    monkeypatch.setenv("CLOUD_LLM_1_BASE_URL", "https://my-proxy.example.com/v1")

    result = bridge._scan_cloud_provider_slots()

    assert result[0]["base_url"] == "https://my-proxy.example.com/v1"


def test_scan_cloud_provider_slots_custom_requires_base_url(monkeypatch):
    _clear_provider_env(monkeypatch, "CLOUD_LLM")
    # slot 1: custom 缺 BASE_URL，應跳過
    monkeypatch.setenv("CLOUD_LLM_1_PROVIDER", "custom")
    monkeypatch.setenv("CLOUD_LLM_1_API_KEY", "key1")
    monkeypatch.setenv("CLOUD_LLM_1_MODEL", "some-model")
    # slot 2: 正常設定的 anthropic
    monkeypatch.setenv("CLOUD_LLM_2_PROVIDER", "anthropic")
    monkeypatch.setenv("CLOUD_LLM_2_API_KEY", "key2")
    monkeypatch.setenv("CLOUD_LLM_2_MODEL", "claude-sonnet-5")

    result = bridge._scan_cloud_provider_slots()

    assert len(result) == 1
    assert result[0]["kind"] == "anthropic"
    assert result[0]["model"] == "claude-sonnet-5"


def test_scan_cloud_provider_slots_missing_api_key_skipped_but_scan_continues(monkeypatch):
    _clear_provider_env(monkeypatch, "CLOUD_LLM")
    # slot 1: 缺 API_KEY，應跳過
    monkeypatch.setenv("CLOUD_LLM_1_PROVIDER", "openai")
    monkeypatch.setenv("CLOUD_LLM_1_MODEL", "gpt-4o")
    # slot 2: 完整設定
    monkeypatch.setenv("CLOUD_LLM_2_PROVIDER", "gemini")
    monkeypatch.setenv("CLOUD_LLM_2_API_KEY", "key2")
    monkeypatch.setenv("CLOUD_LLM_2_MODEL", "gemini-flash-latest")

    result = bridge._scan_cloud_provider_slots()

    assert len(result) == 1
    assert result[0]["model"] == "gemini-flash-latest"


def test_scan_cloud_provider_slots_stops_at_first_completely_empty_slot(monkeypatch):
    _clear_provider_env(monkeypatch, "CLOUD_LLM")
    monkeypatch.setenv("CLOUD_LLM_1_PROVIDER", "openai")
    monkeypatch.setenv("CLOUD_LLM_1_API_KEY", "key1")
    monkeypatch.setenv("CLOUD_LLM_1_MODEL", "gpt-4o")
    # slot 2 完全沒設定（掃描應在此停止）
    # slot 3 卻有設定 -> 不應該被讀到，因為 slot 2 是空的
    monkeypatch.setenv("CLOUD_LLM_3_PROVIDER", "groq")
    monkeypatch.setenv("CLOUD_LLM_3_API_KEY", "key3")
    monkeypatch.setenv("CLOUD_LLM_3_MODEL", "llama-3.3-70b")

    result = bridge._scan_cloud_provider_slots()

    assert len(result) == 1
    assert result[0]["model"] == "gpt-4o"


def test_scan_local_provider_slots_empty_when_nothing_set(monkeypatch):
    _clear_provider_env(monkeypatch, "LOCAL_LLM")
    assert bridge._scan_local_provider_slots() == []


def test_scan_local_provider_slots_no_api_key_needed(monkeypatch):
    _clear_provider_env(monkeypatch, "LOCAL_LLM")
    monkeypatch.setenv("LOCAL_LLM_1_BASE_URL", "http://localhost:1234/v1")
    monkeypatch.setenv("LOCAL_LLM_1_MODEL", "llama-3-8b")

    result = bridge._scan_local_provider_slots()

    assert len(result) == 1
    assert result[0]["kind"] == "openai_compat"
    assert result[0]["base_url"] == "http://localhost:1234/v1"
    assert result[0]["api_key"] == "not-needed"


def test_scan_local_provider_slots_multiple_backends_in_order(monkeypatch):
    _clear_provider_env(monkeypatch, "LOCAL_LLM")
    monkeypatch.setenv("LOCAL_LLM_1_BASE_URL", "http://localhost:1234/v1")
    monkeypatch.setenv("LOCAL_LLM_1_MODEL", "lmstudio-model")
    monkeypatch.setenv("LOCAL_LLM_2_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("LOCAL_LLM_2_MODEL", "ollama-model")

    result = bridge._scan_local_provider_slots()

    assert len(result) == 2
    assert result[0]["model"] == "lmstudio-model"
    assert result[1]["model"] == "ollama-model"


def test_scan_local_provider_slots_missing_model_skipped(monkeypatch):
    _clear_provider_env(monkeypatch, "LOCAL_LLM")
    monkeypatch.setenv("LOCAL_LLM_1_BASE_URL", "http://localhost:1234/v1")
    # 缺 MODEL
    monkeypatch.setenv("LOCAL_LLM_2_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("LOCAL_LLM_2_MODEL", "ollama-model")

    result = bridge._scan_local_provider_slots()

    assert len(result) == 1
    assert result[0]["model"] == "ollama-model"
