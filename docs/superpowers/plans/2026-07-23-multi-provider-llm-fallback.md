# Multi-Provider LLM Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `bridge.py` 的線上/離線 LLM 呼叫從寫死的 Gemini / LM Studio→Ollama，改成雲端多 provider 有序備援清單 + 本地任意 OpenAI-compat backend 清單，並把工具呼叫往返邏輯收斂進每個 provider 函式內部。

**Architecture:** 動態編號環境變數 slot 掃描（`CLOUD_LLM_{N}_*`/`LOCAL_LLM_{N}_*`）組出有序清單；`call_openai_compat_provider`/`call_anthropic_provider` 各自處理完整「呼叫→工具執行→第二次呼叫」流程並回傳純文字（失敗則 raise）；`call_llm_with_fallback` 依序嘗試清單直到成功。

**Tech Stack:** Python 3.14、`openai` SDK（既有）、新增 `anthropic` SDK。

## Global Constraints

- **不向下相容**：`GEMINI_API_KEY`/`GEMINI_MODEL_ONLINE`/`LOCAL_LLM_API_BASE`/`LOCAL_LLM_MODEL`/`LOCAL_LLM_OLLAMA_API_BASE`/`LOCAL_LLM_OLLAMA_MODEL` 全部移除，不留 fallback
- 雲端 provider 命名：`openai`/`gemini`/`groq`/`mistral`/`openrouter`（OpenAI-compat，有內建預設 base_url）、`anthropic`（原生 API，獨立函式）、`custom`（任意 OpenAI-compat，必填 base_url）
- 本地 provider 一律視為 OpenAI-compat（不分 LM Studio/Ollama/llama.cpp/vLLM，使用者自己填 base_url）
- provider 函式（`call_openai_compat_provider`/`call_anthropic_provider`）失敗必須 `raise`，不可吞掉例外包成字串回傳（fallback 迴圈依賴例外判斷失敗）
- `MAX_MESHTASTIC_PAYLOAD`/`send_meshtastic_message`/`send_meshtastic_alert`/`get_node_location`/SOS/報平安/避難點/天氣查詢邏輯不在本次改動範圍，維持現狀
- 新增/改動程式碼都要有對應單元測試；**測試一律 mock LLM client，絕不在自動化測試中打真實 API**（會燒真金額度）
- 每個 Task 完成後 `git commit`
- 目前在 `main` branch（v0.2.0 之後），這次先建 feature branch 進行

## 過程中發現的重要 bug（已納入 Task 1，非既有計畫外)

複查 `execute_llm_tool_call` 與 OpenAI SDK 原始型別時發現：`tool_call.function.arguments` 在真實 OpenAI-compatible API 回應中是 **JSON 字串**（`openai` SDK 的 `Function.arguments: str`），但 `execute_llm_tool_call` 目前直接對它呼叫 `.items()`，只有在測試用手動建構的 `types.SimpleNamespace(..., arguments={"lat":...})`（dict）情況下才不會炸。也就是說**現有的避難點查詢工具呼叫，一旦接上真實雲端 API，會在 `tool_args.items()` 這行丟出 `AttributeError` 而整個崩潰**——這條路徑至今從未被真實 API 呼叫驗證過。必須在建構新 provider 函式之前先修好，否則新架構會把這個 bug 原封不動地繼續帶著走。

---

### Task 1: 修復 `execute_llm_tool_call` 的 JSON 字串參數相容性 bug

**複雜度：低。Critic：R1 一輪。**

**Files:**
- Modify: `bridge.py`（`execute_llm_tool_call` 函式，目前約第 314-338 行，執行前用 `grep -n "^def execute_llm_tool_call"` 確認實際行號）
- Test: `tests/test_bridge_tool_dispatch.py`（既有檔案，擴充）

**Interfaces:**
- Produces: `execute_llm_tool_call` 現在同時接受 `tool_call.function.arguments` 為 dict（既有手動建構呼叫，如 weather-here）或 JSON 字串（真實 OpenAI-compat API 回應），供 Task 3/4 的 provider 函式使用

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_bridge_tool_dispatch.py` 檔案末端追加：

```python
def test_execute_llm_tool_call_parses_json_string_arguments(monkeypatch, tmp_path):
    """真實 OpenAI-compat API 回應的 arguments 是 JSON 字串，不是 dict"""
    captured_cmd = {}

    class FakeCompletedProcess:
        stdout = "測試避難所（0.1km）- 測試地址 容量約10人"

    def fake_run(cmd, capture_output, text, check):
        captured_cmd["cmd"] = cmd
        return FakeCompletedProcess()

    monkeypatch.setattr(bridge.subprocess, "run", fake_run)

    tool_call = types.SimpleNamespace(
        function=types.SimpleNamespace(
            name="find_shelter", arguments='{"lat": 25.03, "lon": 121.56}'
        )
    )
    result = bridge.execute_llm_tool_call(tool_call, is_online=True, localization_setting="TW")

    assert "--lat" in captured_cmd["cmd"]
    assert "25.03" in captured_cmd["cmd"]
    assert result["tool_output"] == FakeCompletedProcess.stdout
```

（`types` 已在該測試檔案頂部 import，若沒有請確認並補上 `import types`。）

- [ ] **Step 2: 執行測試確認失敗**

Run: `cd ~/ai-projects/projects/meshtastic-llm-bridge && venv/bin/python3 -m pytest tests/test_bridge_tool_dispatch.py::test_execute_llm_tool_call_parses_json_string_arguments -v`
Expected: FAIL，`AttributeError: 'str' object has no attribute 'items'`

- [ ] **Step 3: 修復 `execute_llm_tool_call`**

找到 `execute_llm_tool_call` 函式（目前開頭類似）：
```python
def execute_llm_tool_call(tool_call, is_online, localization_setting):
    """執行 LLM 的工具調用"""
    tool_name = tool_call.function.name
    tool_args = tool_call.function.arguments
    print(f"LLM 請求執行工具: {tool_name}，參數: {tool_args}")
```

改為：
```python
def execute_llm_tool_call(tool_call, is_online, localization_setting):
    """執行 LLM 的工具調用"""
    tool_name = tool_call.function.name
    tool_args = tool_call.function.arguments
    if isinstance(tool_args, str):
        tool_args = json.loads(tool_args)
    print(f"LLM 請求執行工具: {tool_name}，參數: {tool_args}")
```

（`json` 已在檔案頂部 import，不需新增 import。）

- [ ] **Step 4: 執行測試確認通過**

Run: `venv/bin/python3 -m pytest tests/test_bridge_tool_dispatch.py -v`
Expected: 全部 passed（含既有測試 + 新增這條）

- [ ] **Step 5: Commit**

```bash
git checkout -b feature/multi-provider-llm-fallback
git add bridge.py tests/test_bridge_tool_dispatch.py
git commit -m "fix: execute_llm_tool_call handle JSON-string tool arguments from real OpenAI-compat APIs"
```

（此 Task 建立 feature branch，後續 Task 都在這個 branch 上進行。）

---

### Task 2: Provider 設定 slot 掃描

**複雜度：低。Critic：R1 一輪。**

**Files:**
- Modify: `bridge.py`（移除舊 Gemini/Local LLM 設定區塊，加入新的 slot 掃描邏輯，目前約第 27-35 行）
- Test: `tests/test_bridge_provider_config.py`（新檔案）

**Interfaces:**
- Produces: `bridge._scan_cloud_provider_slots() -> list[dict]`、`bridge._scan_local_provider_slots() -> list[dict]`、模組層級 `CLOUD_LLM_PROVIDERS`/`LOCAL_LLM_PROVIDERS`（呼叫上述兩函式的結果），供 Task 5（fallback 迴圈）使用。每個 dict shape：`{"label": str, "kind": "openai_compat"|"anthropic", "base_url": str|None, "api_key": str, "model": str}`

- [ ] **Step 1: 寫失敗測試**

Create `tests/test_bridge_provider_config.py`:

```python
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
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `venv/bin/python3 -m pytest tests/test_bridge_provider_config.py -v`
Expected: FAIL，`AttributeError: module 'bridge' has no attribute '_scan_cloud_provider_slots'`

- [ ] **Step 3: 移除舊設定、加入新的 slot 掃描邏輯**

在 `bridge.py` 中，找到目前的（約第 27-35 行）：
```python
# Google Gemini API (Online Mode)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL_ONLINE = os.getenv("GEMINI_MODEL_ONLINE", "gemini-flash-latest") # Use a strong model for online (rolling alias, 2026-06-17 後自動指向 3.x)

# Local LLM (Offline Mode) - LM Studio or Ollama
LOCAL_LLM_API_BASE = os.getenv("LOCAL_LLM_API_BASE", "http://localhost:1234/v1") # LM Studio default
LOCAL_LLM_MODEL = os.getenv("LOCAL_LLM_MODEL", "llama4-scout-openclaw:iq2")
LOCAL_LLM_OLLAMA_API_BASE = os.getenv("LOCAL_LLM_OLLAMA_API_BASE", "http://0.0.0.0:11434/api")
LOCAL_LLM_OLLAMA_MODEL = os.getenv("LOCAL_LLM_OLLAMA_MODEL", "gpt-oss-openclaw:20b")
```

整段替換為：
```python
# --- LLM Provider 設定（雲端多家備援 + 本地任意 OpenAI-compat backend）---
CLOUD_PROVIDER_DEFAULTS = {
    "openai": "https://api.openai.com/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "groq": "https://api.groq.com/openai/v1",
    "mistral": "https://api.mistral.ai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
}


def _scan_cloud_provider_slots() -> list:
    """掃描 CLOUD_LLM_{N}_* 環境變數（N=1,2,3...），組出有序 provider 清單。
    某編號完全沒有任何對應變數時停止掃描；設定不完整的 slot 會被跳過但繼續往下一個編號找。
    """
    providers = []
    n = 1
    while True:
        provider_name = os.getenv(f"CLOUD_LLM_{n}_PROVIDER")
        api_key = os.getenv(f"CLOUD_LLM_{n}_API_KEY")
        model = os.getenv(f"CLOUD_LLM_{n}_MODEL")
        base_url = os.getenv(f"CLOUD_LLM_{n}_BASE_URL")

        if provider_name is None and api_key is None and model is None and base_url is None:
            break

        if not provider_name or not api_key or not model:
            print(f"⚠️ CLOUD_LLM_{n}_* 設定不完整，跳過", file=sys.stderr)
            n += 1
            continue

        kind = "anthropic" if provider_name == "anthropic" else "openai_compat"
        resolved_base_url = base_url or CLOUD_PROVIDER_DEFAULTS.get(provider_name)
        if kind == "openai_compat" and not resolved_base_url:
            print(f"⚠️ CLOUD_LLM_{n}_PROVIDER={provider_name} 缺少 BASE_URL，跳過", file=sys.stderr)
            n += 1
            continue

        providers.append({
            "label": f"cloud#{n}:{provider_name}",
            "kind": kind,
            "base_url": resolved_base_url,
            "api_key": api_key,
            "model": model,
        })
        n += 1
    return providers


def _scan_local_provider_slots() -> list:
    """掃描 LOCAL_LLM_{N}_* 環境變數（N=1,2,3...），組出有序本地 provider 清單。
    不限定特定服務名稱，任意 OpenAI-compatible 本地服務皆可設定。
    """
    providers = []
    n = 1
    while True:
        base_url = os.getenv(f"LOCAL_LLM_{n}_BASE_URL")
        model = os.getenv(f"LOCAL_LLM_{n}_MODEL")
        api_key = os.getenv(f"LOCAL_LLM_{n}_API_KEY")

        if base_url is None and model is None and api_key is None:
            break

        if not base_url or not model:
            print(f"⚠️ LOCAL_LLM_{n}_* 設定不完整，跳過", file=sys.stderr)
            n += 1
            continue

        providers.append({
            "label": f"local#{n}",
            "kind": "openai_compat",
            "base_url": base_url,
            "api_key": api_key or "not-needed",
            "model": model,
        })
        n += 1
    return providers


CLOUD_LLM_PROVIDERS = _scan_cloud_provider_slots()
LOCAL_LLM_PROVIDERS = _scan_local_provider_slots()

if not CLOUD_LLM_PROVIDERS:
    print("⚠️ 未設定任何 CLOUD_LLM_*_PROVIDER，線上模式將無法使用", file=sys.stderr)
if not LOCAL_LLM_PROVIDERS:
    print("⚠️ 未設定任何 LOCAL_LLM_*_BASE_URL，離線模式將無法使用", file=sys.stderr)
```

- [ ] **Step 4: 執行測試確認通過**

Run: `venv/bin/python3 -m pytest tests/test_bridge_provider_config.py -v`
Expected: 10 passed

- [ ] **Step 5: 執行全部既有測試確認無回歸（此時 `call_gemini_api_online`/`call_local_llm` 還引用著已刪除的 `GEMINI_API_KEY` 等變數，預期會在 import 階段就 `NameError`——這是本 Task 故意先留著的中間狀態，Task 5 會處理）**

Run: `venv/bin/python3 -m pytest tests/ -v 2>&1 | tail -30`
Expected: **可能會有 `NameError: name 'GEMINI_API_KEY' is not defined'` 之類的 collection error**——若發生，這是預期中的暫時狀態（因為 `call_gemini_api_online`/`call_local_llm` 函式本體還沒被移除，但只有在被呼叫時才會觸發 NameError，函式定義本身不會在 import 時報錯，所以理論上不會出現 collection error）。若真的出現非預期的 collection error，先確認是不是這個已知原因，若是則記錄下來，繼續往下個 Task 走（Task 5 會移除這兩個函式）。

- [ ] **Step 6: Commit**

```bash
git add bridge.py tests/test_bridge_provider_config.py
git commit -m "feat: add dynamic slot scanning for cloud/local LLM provider lists"
```

---

### Task 3: `call_openai_compat_provider`（通用 OpenAI-compatible 呼叫，含工具往返）

**複雜度：高。Critic：R1 + R2(Opus)。**

**Files:**
- Modify: `bridge.py`（新增函式，放在 `execute_llm_tool_call` 之前或之後皆可，建議放在原本 `call_gemini_api_online` 的位置，之後 Task 5 會整段替換掉）
- Test: `tests/test_bridge_llm_providers.py`（新檔案）

**Interfaces:**
- Consumes: `execute_llm_tool_call`（Task 1 已修復 JSON 字串相容性）、`llm_tools`（既有模組層級變數）
- Produces: `call_openai_compat_provider(provider_config: dict, prompt: str, chat_history: list, is_online: bool) -> str`，成功回傳最終文字，失敗 `raise`。供 Task 5（fallback 迴圈）使用，雲端與本地 provider 共用同一支函式

- [ ] **Step 1: 寫失敗測試**

Create `tests/test_bridge_llm_providers.py`:

```python
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
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `venv/bin/python3 -m pytest tests/test_bridge_llm_providers.py -v`
Expected: FAIL，`AttributeError: module 'bridge' has no attribute 'call_openai_compat_provider'`（以及 `_build_openai_client`）

- [ ] **Step 3: 寫實作**

在 `bridge.py` 中新增（放在 `execute_llm_tool_call` 函式之後）：

```python
def _build_openai_client(base_url, api_key):
    """獨立包一層方便測試 monkeypatch，避免每個呼叫點都要 import+建構"""
    from openai import OpenAI
    return OpenAI(base_url=base_url, api_key=api_key)


def call_openai_compat_provider(provider_config, prompt, chat_history, is_online):
    """呼叫任意 OpenAI-compatible provider（雲端具名服務或本地任意 backend 共用）。
    成功回傳最終文字；失敗 raise（供 fallback 迴圈捕捉）。
    """
    client = _build_openai_client(provider_config["base_url"], provider_config["api_key"])
    messages = chat_history if chat_history is not None else []
    messages.append({"role": "user", "content": prompt})

    response = client.chat.completions.create(
        model=provider_config["model"],
        messages=messages,
        tools=llm_tools,
        tool_choice="auto",
        max_tokens=200,
        temperature=0.7,
    )
    message = response.choices[0].message

    if not message.tool_calls:
        return message.content or ""

    messages.append({
        "role": "assistant",
        "content": message.content,
        "tool_calls": message.tool_calls,
    })
    for tool_call in message.tool_calls:
        output = execute_llm_tool_call(tool_call, is_online, LOCALIZATION)
        print(f"工具 {tool_call.function.name} 執行結果: {output}")
        messages.append({
            "role": "tool",
            "tool_call_id": tool_call.id,
            "content": json.dumps(output),
        })

    second_response = client.chat.completions.create(
        model=provider_config["model"],
        messages=messages,
        tools=llm_tools,
        tool_choice="auto",
        max_tokens=200,
        temperature=0.7,
    )
    return second_response.choices[0].message.content or ""
```

- [ ] **Step 4: 執行測試確認通過**

Run: `venv/bin/python3 -m pytest tests/test_bridge_llm_providers.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add bridge.py tests/test_bridge_llm_providers.py
git commit -m "feat: add call_openai_compat_provider shared by all OpenAI-compatible cloud/local backends"
```

**R1+R2 提醒**：審查重點——(a) `chat_history` 是可變 list，`messages.append(...)` 直接 mutate 傳入的 list，這是既有程式碼就有的模式（沿用不算新問題），但要確認新架構下不會因為 fallback 迴圈重複呼叫多個 provider 而共用同一個被污染過的 `chat_history` list 導致第二個 provider 收到第一個 provider 失敗留下的殘留訊息（**這是 Task 5 wiring 時才會真正組裝呼叫，R1/R2 在這個 Task 先確認函式本身職責邊界清楚，實際跨 provider 共用風險留給 Task 5 的 critic 覆核**）(b) `tool_call_id` 正確對應（每個 tool_call 都要有自己的 `tool_call_id`，不能像舊 Gemini 版本那樣把所有工具結果塞進一則沒有 id 的訊息）。

---

### Task 4: 安裝 `anthropic` 依賴 + `call_anthropic_provider`

**複雜度：高。Critic：R1 + R2(Opus)。**

**Files:**
- Modify: `bridge.py`（新增 `import types`（頂部）+ `call_anthropic_provider` 函式）
- Modify: `venv`（安裝 `anthropic` 套件）
- Test: `tests/test_bridge_llm_providers.py`（擴充既有檔案）

**Interfaces:**
- Consumes: `execute_llm_tool_call`（Task 1）、`llm_tools`
- Produces: `call_anthropic_provider(provider_config: dict, prompt: str, chat_history: list, is_online: bool) -> str`，介面與 `call_openai_compat_provider` 一致，供 Task 5 使用

- [ ] **Step 1: 安裝依賴**

```bash
cd ~/ai-projects/projects/meshtastic-llm-bridge
venv/bin/pip install anthropic
```

- [ ] **Step 2: 寫失敗測試**

在 `tests/test_bridge_llm_providers.py` 檔案末端追加：

```python
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
```

- [ ] **Step 3: 執行測試確認失敗**

Run: `venv/bin/python3 -m pytest tests/test_bridge_llm_providers.py -v -k anthropic`
Expected: FAIL，`AttributeError: module 'bridge' has no attribute 'call_anthropic_provider'`

- [ ] **Step 4: 加入 `import types`**

在 `bridge.py` 檔案最上方的 import 區塊（目前 `import threading` 之後）加入：
```python
import types
```

- [ ] **Step 5: 寫實作**

在 `bridge.py` 中，緊接在 `call_openai_compat_provider` 之後新增：

```python
def _build_anthropic_client(api_key):
    """獨立包一層方便測試 monkeypatch"""
    from anthropic import Anthropic
    return Anthropic(api_key=api_key)


def call_anthropic_provider(provider_config, prompt, chat_history, is_online):
    """呼叫 Anthropic 原生 API（非 OpenAI-compatible，獨立處理 tool schema 與訊息格式）。
    成功回傳最終文字；失敗 raise。
    """
    client = _build_anthropic_client(provider_config["api_key"])
    messages = chat_history if chat_history is not None else []
    messages.append({"role": "user", "content": prompt})

    anthropic_tools = [
        {
            "name": t["function"]["name"],
            "description": t["function"]["description"],
            "input_schema": t["function"]["parameters"],
        }
        for t in llm_tools
    ]

    response = client.messages.create(
        model=provider_config["model"],
        max_tokens=200,
        messages=messages,
        tools=anthropic_tools,
    )

    if response.stop_reason != "tool_use":
        return "".join(block.text for block in response.content if block.type == "text")

    assistant_content = []
    tool_use_blocks = []
    for block in response.content:
        if block.type == "text":
            assistant_content.append({"type": "text", "text": block.text})
        elif block.type == "tool_use":
            assistant_content.append({"type": "tool_use", "id": block.id, "name": block.name, "input": block.input})
            tool_use_blocks.append(block)
    messages.append({"role": "assistant", "content": assistant_content})

    tool_result_blocks = []
    for block in tool_use_blocks:
        fake_tool_call = types.SimpleNamespace(
            function=types.SimpleNamespace(name=block.name, arguments=block.input)
        )
        output = execute_llm_tool_call(fake_tool_call, is_online, LOCALIZATION)
        print(f"工具 {block.name} 執行結果: {output}")
        tool_result_blocks.append({
            "type": "tool_result",
            "tool_use_id": block.id,
            "content": json.dumps(output),
        })
    messages.append({"role": "user", "content": tool_result_blocks})

    second_response = client.messages.create(
        model=provider_config["model"],
        max_tokens=200,
        messages=messages,
        tools=anthropic_tools,
    )
    return "".join(block.text for block in second_response.content if block.type == "text")
```

- [ ] **Step 6: 執行測試確認通過**

Run: `venv/bin/python3 -m pytest tests/test_bridge_llm_providers.py -v`
Expected: 全部 passed（Task 3 的 4 個 + 本 Task 的 3 個）

- [ ] **Step 7: Commit**

```bash
git add bridge.py tests/test_bridge_llm_providers.py
git commit -m "feat: add call_anthropic_provider with tool schema translation"
```

（`anthropic` 套件安裝不需要獨立 commit，`pip install` 不影響 git tracked 檔案；README 依賴清單更新在 Task 7 一併處理。）

**R1+R2 提醒**：審查重點——(a) `execute_llm_tool_call` 期望 `tool_call.function.arguments` 是 dict 或 JSON 字串（Task 1 已修復），這裡傳入的是 Anthropic `block.input`（已經是 dict，不是字串）——確認 `isinstance(tool_args, str)` 判斷不會誤傷這個 dict 輸入路徑 (b) `assistant_content`/`tool_result_blocks` 的 content block 格式是否符合 Anthropic API 規格（`tool_result` 必須放在 `role: "user"` 訊息裡，不是 `role: "tool"`——這跟 OpenAI 的慣例不同，容易搞混）(c) `max_tokens=200` 是否足夠（既有 OpenAI 路徑也是 200，維持一致，但 Anthropic 的 `max_tokens` 是必填參數不是選填，確認沒有漏放）。

---

### Task 5: `call_llm_with_fallback` + 接線進 `handle_incoming_meshtastic_message`，移除舊函式

**複雜度：高。Critic：R1 + R2(Opus)。**

**背景**：這是最後把所有東西接起來的 Task，同時移除 `call_gemini_api_online`/`call_local_llm`/`_get_content`（不再需要）。這個 Task 完成後，`bridge.py` 才會恢復成可以正常 import/執行的完整狀態（Task 2 之後到這個 Task 之前，舊函式引用著已刪除的變數，屬中間過渡態，不影響測試因為那兩個函式在測試中從未被呼叫）。

**Files:**
- Modify: `bridge.py`（新增 `call_llm_with_fallback`、改寫 `handle_incoming_meshtastic_message` 第 3 段 LLM 處理流程、移除 `call_gemini_api_online`/`call_local_llm`/`_get_content`）
- Test: `tests/test_bridge_llm_providers.py`（擴充：fallback 迴圈）、`tests/test_bridge_tool_dispatch.py` 或新測試檔（`handle_incoming_meshtastic_message` 的 LLM 分派層級測試）

**Interfaces:**
- Consumes: `call_openai_compat_provider`（Task 3）、`call_anthropic_provider`（Task 4）、`CLOUD_LLM_PROVIDERS`/`LOCAL_LLM_PROVIDERS`（Task 2）
- Produces: `call_llm_with_fallback(providers: list, prompt: str, chat_history: list, is_online: bool) -> str`

- [ ] **Step 1: 寫失敗測試（fallback 迴圈）**

在 `tests/test_bridge_llm_providers.py` 檔案末端追加：

```python
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
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `venv/bin/python3 -m pytest tests/test_bridge_llm_providers.py -v -k fallback`
Expected: FAIL，`AttributeError: module 'bridge' has no attribute 'call_llm_with_fallback'`

- [ ] **Step 3: 寫 `call_llm_with_fallback` 實作**

在 `bridge.py` 中，緊接在 `call_anthropic_provider` 之後新增：

```python
def call_llm_with_fallback(providers, prompt, chat_history, is_online):
    """依序嘗試 providers 清單，回傳第一個成功的結果；全部失敗則 raise。"""
    last_error = None
    for provider in providers:
        try:
            if provider["kind"] == "anthropic":
                return call_anthropic_provider(provider, prompt, chat_history, is_online)
            return call_openai_compat_provider(provider, prompt, chat_history, is_online)
        except Exception as e:
            print(f"Provider {provider.get('label', '?')} 失敗: {e}，嘗試下一家", file=sys.stderr)
            last_error = e
    raise RuntimeError(f"所有 LLM provider 皆失敗: {last_error}")
```

- [ ] **Step 4: 執行測試確認通過**

Run: `venv/bin/python3 -m pytest tests/test_bridge_llm_providers.py -v`
Expected: 全部 passed

- [ ] **Step 5: 寫失敗測試（`handle_incoming_meshtastic_message` 接線層級）**

Create `tests/test_bridge_message_dispatch.py`:

```python
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
```

- [ ] **Step 6: 執行測試確認失敗**

Run: `venv/bin/python3 -m pytest tests/test_bridge_message_dispatch.py -v`
Expected: FAIL（此時 `handle_incoming_meshtastic_message` 還是舊邏輯，`call_llm_with_fallback` 不會被呼叫到，`sent` 內容跟預期不符或直接因為舊函式引用已刪除變數而拋例外）

- [ ] **Step 7: 改寫 `handle_incoming_meshtastic_message`，移除舊函式**

找到 `bridge.py` 中的 `call_gemini_api_online`、`call_local_llm`、`_get_content` 三個函式（目前約第 250-312 行 `call_gemini_api_online`/`call_local_llm`，約第 370-374 行 `_get_content`），**整段刪除**（三個函式都不再需要）。

找到 `handle_incoming_meshtastic_message` 函式中「原有 LLM 處理流程」那一段（目前約第 412-459 行）：
```python
    # --- 原有 LLM 處理流程 ---
    internet_status = "🟢 Online" if check_internet_connection() else "🔴 Offline"
    print(f"處理來自 {sender_id} 的訊息: '{text_message}' - 網路狀態: {internet_status}")

    chat_history = [] # TODO: Implement persistent chat history for context
    
    response_message = None
    tool_outputs = []

    # 2. 根據網路狀態選擇 LLM 並進行第一次呼叫
    if internet_connected:
        print("使用 Google Gemini API (在線模式)...")
        response_message = call_gemini_api_online(text_message, chat_history)
    else:
        print("使用本地 LLM (離線模式)...")
        rag_context = ""
        # TODO: Integrate RAG here as part of the local LLM call or as a separate step
        llm_prompt = text_message # Placeholder
        response_message = call_local_llm(llm_prompt, chat_history)
    
    # 3. 處理 LLM 的回覆
    final_response_text = ""

    if hasattr(response_message, 'tool_calls') and response_message.tool_calls:
        for tool_call in response_message.tool_calls:
            output = execute_llm_tool_call(tool_call, internet_connected, LOCALIZATION)
            tool_outputs.append(output)
            print(f"工具 {tool_call.function.name} 執行結果: {output}")
        
        # 將工具輸出回傳給 LLM 進行第二次呼叫，獲取最終答案
        if internet_connected:
            second_response = call_gemini_api_online(
                "", # Prompt can be empty for tool response
                chat_history + [
                    {"role": "assistant", "content": None, "tool_calls": response_message.tool_calls},
                    {"role": "tool", "content": json.dumps(tool_outputs)}
                ]
            )
            final_response_text = _get_content(second_response)
        else:
            local_tool_prompt = f"你剛才執行了工具，結果是: {json.dumps(tool_outputs)}。請根據此結果回答我的問題，並保持簡潔。\n原始問題: {text_message}"
            second_response = call_local_llm(local_tool_prompt, chat_history)
            final_response_text = _get_content(second_response)
    else:
        final_response_text = _get_content(response_message)

    # 4. 發送最終回覆 (處理長度限制)
    send_meshtastic_message(f"AI: {final_response_text}", destination_id=sender_id)
```

整段替換為：
```python
    # --- 原有 LLM 處理流程 ---
    internet_status = "🟢 Online" if check_internet_connection() else "🔴 Offline"
    print(f"處理來自 {sender_id} 的訊息: '{text_message}' - 網路狀態: {internet_status}")

    chat_history = []  # TODO: Implement persistent chat history for context

    try:
        if internet_connected:
            final_response_text = call_llm_with_fallback(CLOUD_LLM_PROVIDERS, text_message, chat_history, True)
        else:
            final_response_text = call_llm_with_fallback(LOCAL_LLM_PROVIDERS, text_message, chat_history, False)
    except Exception as e:
        final_response_text = f"❌ 所有 LLM 服務皆無法回應: {e}"

    # 發送最終回覆 (處理長度限制)
    send_meshtastic_message(f"AI: {final_response_text}", destination_id=sender_id)
```

- [ ] **Step 8: 執行測試確認通過**

Run: `venv/bin/python3 -m pytest tests/test_bridge_message_dispatch.py -v`
Expected: 3 passed

- [ ] **Step 9: 執行全部測試確認無回歸**

Run: `venv/bin/python3 -m pytest tests/ -v`
Expected: 全部 passed（此時 `bridge.py` 應該已完全恢復可正常 import/運作的狀態）

- [ ] **Step 10: 手動確認 `bridge.py` import 不再報錯（純語法/引用檢查，不連真實硬體）**

```bash
venv/bin/python3 -c "import bridge; print('import 成功'); print('CLOUD_LLM_PROVIDERS:', bridge.CLOUD_LLM_PROVIDERS); print('LOCAL_LLM_PROVIDERS:', bridge.LOCAL_LLM_PROVIDERS)"
```
Expected: 印出 `import 成功`，兩個清單目前應該都是空的（因為還沒設定任何 `CLOUD_LLM_*`/`LOCAL_LLM_*` 環境變數），並在 stderr 印出兩則「未設定」警告

- [ ] **Step 11: Commit**

```bash
git add bridge.py tests/test_bridge_message_dispatch.py
git commit -m "feat: add call_llm_with_fallback, wire into message handler, remove legacy Gemini/local-LLM functions"
```

**R1+R2 提醒**：審查重點——(a) `chat_history` 在 `call_llm_with_fallback` 迴圈中若第一個 provider 失敗、換第二個 provider 時，是否帶著第一個 provider 已經 mutate 過的 `chat_history`（可能已被 append 了 `role:user` 甚至部分 `role:assistant`/`role:tool` 訊息）——這是 Task 3 review 提醒過的風險，這裡要真的驗證：目前傳入 `call_llm_with_fallback` 的 `chat_history` 是 `handle_incoming_meshtastic_message` 建立的新 `[]`，同一個 list 物件會被傳給每個 provider 嘗試；若 provider A 失敗前已經 append 了訊息，provider B 收到的 `chat_history` 就不是乾淨的初始狀態。**這是需要 R1/R2 明確判斷是否為必須修的 bug**：概念上第一個 provider 若在「呼叫 API 前」就失敗（例如 client 建構失敗）不會 mutate，但若在「工具呼叫的第二次呼叫」失敗，`chat_history` 已經被加了 assistant/tool 訊息，換下一個 provider 時這些屬於「上一個 provider 的內部狀態」的訊息就會污染下一個 provider 的第一次呼叫。(b) `except Exception as e: final_response_text = f"❌ ...": ` 這個 catch-all 是否會不小心蓋掉 SOS/報平安/天氣/避難點等其他已經 `return` 掉的分支（不應該，因為那些分支在函式更前面已經 `return`，但仍要確認沒有漏放的 `return`）。

---

### Task 6: README 更新

**複雜度：低。Critic：R1 一輪。**

**Files:**
- Modify: `README.md`
- Modify: `README.zh-TW.md`

- [ ] **Step 1: 確認目前 README 提及舊變數的位置**

```bash
grep -n "GEMINI_API_KEY\|GEMINI_MODEL_ONLINE\|LOCAL_LLM_API_BASE\|LOCAL_LLM_MODEL\|LOCAL_LLM_OLLAMA\|LM Studio\|Ollama" README.md README.zh-TW.md
```

- [ ] **Step 2: 更新 README.md 的環境變數段落**

找到「Environment Variables」段落（v0.2.0 時新增的），把舊的 `GEMINI_*`/`LOCAL_LLM_*` 變數列表整段替換為：

```markdown
### Environment Variables

Create a `.env` file in the project root with:

```
MESHTASTIC_DEVICE_PATH=/dev/ttyUSB0
MESHTASTIC_LONGNAME=MeshtasticAI
LOCALIZATION=TW

# Cloud LLM providers (ordered fallback list, numbered slots — add as many as you like)
# provider: openai | gemini | groq | mistral | openrouter | anthropic | custom
CLOUD_LLM_1_PROVIDER=openai
CLOUD_LLM_1_API_KEY=sk-your-key-here
CLOUD_LLM_1_MODEL=gpt-4o
# CLOUD_LLM_1_BASE_URL=            # only needed for provider=custom, or to override the built-in default

CLOUD_LLM_2_PROVIDER=anthropic
CLOUD_LLM_2_API_KEY=sk-ant-your-key-here
CLOUD_LLM_2_MODEL=claude-sonnet-5

# Local LLM backends (ordered fallback list, any OpenAI-compatible server)
LOCAL_LLM_1_BASE_URL=http://localhost:1234/v1   # e.g. LM Studio
LOCAL_LLM_1_MODEL=your-local-model-name

LOCAL_LLM_2_BASE_URL=http://localhost:11434/v1  # e.g. Ollama's OpenAI-compat endpoint
LOCAL_LLM_2_MODEL=your-ollama-model-name

CWA_API_KEY=your_cwa_key_here
```

Only the slots you actually fill in get used — an incomplete or entirely absent numbered slot is skipped, and the bridge tries the next one. Both the cloud and local lists support any number of fallback entries.
```

同時在「Features」段落把 Gemini-specific 的敘述改成通用敘述，找到類似「Dual-Mode LLM Integration」的 bullet，改為：
```markdown
- **Multi-Provider LLM Fallback**: Configure any number of cloud LLM providers (OpenAI, Gemini, Groq, Mistral, OpenRouter, Anthropic, or any custom OpenAI-compatible endpoint) as an ordered fallback list — if one fails, the bridge automatically tries the next. Same fallback mechanism for local/offline LLM backends (LM Studio, Ollama, or any self-hosted OpenAI-compatible server).
```

- [ ] **Step 3: 對 README.zh-TW.md 做同樣的修正**（環境變數段落換成中文對照版本，Features 段落改成通用敘述的繁中版）

- [ ] **Step 4: 確認測試仍全部通過（README 修改不影響測試，跑一次確保沒有不小心動到程式碼）**

Run: `venv/bin/python3 -m pytest tests/ -v`
Expected: 全部 passed

- [ ] **Step 5: Commit**

```bash
git add README.md README.zh-TW.md
git commit -m "docs: update README for multi-provider LLM fallback (cloud + local)"
```

---

## Self-Review（依 writing-plans 檢查清單）

1. **Spec coverage**：對照設計文件（`docs/superpowers/specs/2026-07-23-multi-provider-llm-fallback-design.md`）逐段檢查——
   - 動態編號 slot 掃描 → Task 2
   - 內建雲端 provider 預設值 → Task 2（`CLOUD_PROVIDER_DEFAULTS`）
   - Anthropic 獨立處理 → Task 4
   - 本地任意 OpenAI-compat backend → Task 2（`_scan_local_provider_slots` 不限定服務名稱）
   - Ollama 改用 `/v1` → 使用者自行在 `LOCAL_LLM_{N}_BASE_URL` 填 Ollama 的 `/v1` endpoint 即可，不需要程式碼特殊處理（因為本地全部走通用 OpenAI-compat，這點已經自然達成，不需要獨立 Task）
   - 工具呼叫收斂進 provider 函式 → Task 3（openai_compat）+ Task 4（anthropic）
   - Fallback 迴圈 → Task 5
   - 移除舊 Gemini/LM Studio/Ollama 專屬程式碼 → Task 5（含 `call_gemini_api_online`/`call_local_llm`/`_get_content` 刪除）
   - 不向下相容（舊環境變數失效）→ Task 2（整段替換，不留 fallback 讀取）
   - README 更新 → Task 6
   - **額外發現並修復**：`execute_llm_tool_call` 對 JSON 字串 `arguments` 的相容性 bug → Task 1（設計文件當初沒發現，實作研究階段才挖出來）
2. **Placeholder scan**：全文檢查無 TBD/TODO（既有的 persistent chat history/RAG TODO 保留不動，屬於既有、非本次範圍的標記，不是本計畫新增的佔位符）
3. **Type consistency**：`call_openai_compat_provider(provider_config, prompt, chat_history, is_online)` 與 `call_anthropic_provider(provider_config, prompt, chat_history, is_online)` 簽名在 Task 3/4/5 全程一致；`call_llm_with_fallback(providers, prompt, chat_history, is_online)` 呼叫兩者時參數順序一致；provider dict shape（`label`/`kind`/`base_url`/`api_key`/`model`）在 Task 2/3/4/5 全程一致

---

## 真實 API 驗證（人工執行，非自動化 Task，比照 v0.2.0 硬體驗證梯度的精神）

自動化測試全程 mock LLM client，不會打到真實 API。全部 Task 完成後，若要驗證真實串接，建議：

1. 在 `.env` 設定至少一組真實雲端 provider（例如你自己的 OpenAI 或 Gemini API key），啟動 bridge，透過 Meshtastic 裝置送一則一般訊息，確認能收到 AI 回覆
2. 設定一組**必定會失敗**的雲端 provider 放在清單第一位（例如故意填錯的 API key）、真實可用的放第二位，驗證 fallback 真的會自動換下一家並成功回覆（同時觀察 log 印出「Provider ... 失敗...嘗試下一家」）
3. 若你有 Anthropic API key，測試一次 `CLOUD_LLM_N_PROVIDER=anthropic`，確認能正常回覆
4. 問一個會觸發 `find_shelter` 工具呼叫的問題（例如「附近有避難所嗎」+ 你的節點有 GPS），確認工具呼叫在真實 API 下能正常往返（這條路徑驗證 Task 1 修的 bug 真的解決了，不會在真實 API 下 crash）
5. 本地端：至少設定一組真實跑起來的本地 OpenAI-compat 服務（LM Studio 或 Ollama `/v1`），關閉網路（或直接把 `CLOUD_LLM_*` 清空），確認離線模式能正常運作
