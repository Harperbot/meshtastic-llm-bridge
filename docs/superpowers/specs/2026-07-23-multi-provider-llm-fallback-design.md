# 設計文件：雲端多 Provider 備援 + 本地任意 OpenAI-compat Backend

**日期**：2026-07-23
**狀態**：待核准

## 背景與動機

`bridge.py` 目前的線上模式寫死呼叫 Google Gemini（`call_gemini_api_online`，個人環境用的服務），離線模式寫死 LM Studio→Ollama 兩階段 fallback（`call_local_llm`）。這個 repo 現在是公開專案（v0.2.0 已發布），公開使用情境下不該假設所有人都用 Gemini——應該讓使用者能接任意雲端服務，且能設定多家依序備援（其中一家失敗/沒設定就換下一家），本地端同理，能接任意 OpenAI-compatible 服務（不限於 LM Studio/Ollama）。

現有程式碼還有一個結構性問題：「工具呼叫→執行→餵回結果→第二次呼叫」的邏輯是在 `handle_incoming_meshtastic_message` 裡手動針對雲端/本地分別寫一份（格式還不同：雲端用 OpenAI 訊息陣列格式，本地本地端把工具結果塞進 prompt 字串），這次一併收斂掉。

## 範圍

**這次做**：
1. 雲端多 provider 有序備援清單（`CLOUD_LLM_1_*`、`CLOUD_LLM_2_*`...，動態掃描，缺 API key 自動跳過，呼叫失敗自動換下一家）
2. 內建雲端 provider 便利預設值：`openai`/`gemini`/`groq`/`mistral`/`openrouter`（皆為 OpenAI-compatible，只需填 API key）+ `anthropic`（原生 API，獨立處理）+ `custom`（任意 base_url）
3. 本地任意 OpenAI-compatible backend 有序清單（`LOCAL_LLM_1_*`、`LOCAL_LLM_2_*`...），不限定 LM Studio/Ollama，使用者自行填 base_url/model
4. Ollama 從官方 `ollama` Python 套件改用其 `/v1` OpenAI-compat endpoint，跟其他本地 backend 走同一套程式碼
5. 每個 provider 呼叫函式內部處理完整「呼叫→工具執行→第二次呼叫」流程，對外只回傳最終文字字串（成功）或 `raise`（失敗，觸發 fallback）
6. `handle_incoming_meshtastic_message` 簡化成呼叫統一的 fallback 迴圈，不再分雲端/本地兩套 tool-calling 處理邏輯
7. **不向下相容**：舊的 `GEMINI_API_KEY`/`GEMINI_MODEL_ONLINE`/`LOCAL_LLM_API_BASE`/`LOCAL_LLM_MODEL`/`LOCAL_LLM_OLLAMA_API_BASE`/`LOCAL_LLM_OLLAMA_MODEL` 全部移除，改用新命名（使用者已明確拍板直接改名不留舊變數）
8. README.md/README.zh-TW.md 更新設定說明，Harper 自己的 `china-model-ban` 規則不把中國 AI 實體服務（DeepSeek/Qwen/GLM 等）列入內建預設 provider 清單，但 `custom` 機制不限制使用者自行設定任意 base_url

**不在這次範圍**：
- Persistent chat history（既有 TODO，不擴大範圍）
- RAG（既有 TODO，不擴大範圍）
- 本地服務健康檢查/自動探測（使用者自己設定清單，不做自動掃描網路上有哪些服務在跑）

## 架構

### 設定機制：動態編號 slot 掃描

不用固定命名的 registry 綁死本地 backend 數量，改用「有序編號環境變數」，程式啟動時動態掃描 `CLOUD_LLM_{N}_*` / `LOCAL_LLM_{N}_*`（N=1,2,3...，直到某個編號完全沒有對應變數為止），組成有序清單。

**雲端**（每個 slot）：
- `CLOUD_LLM_{N}_PROVIDER`：`openai` | `gemini` | `groq` | `mistral` | `openrouter` | `anthropic` | `custom`
- `CLOUD_LLM_{N}_API_KEY`：必填（缺少則整個 slot 跳過，不計入清單）
- `CLOUD_LLM_{N}_MODEL`：必填
- `CLOUD_LLM_{N}_BASE_URL`：選填，`PROVIDER=custom` 時必填；其他 named provider 有內建預設值，填了就覆蓋預設值

內建 base_url 預設值（`CLOUD_PROVIDER_DEFAULTS` dict）：
```python
CLOUD_PROVIDER_DEFAULTS = {
    "openai": "https://api.openai.com/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "groq": "https://api.groq.com/openai/v1",
    "mistral": "https://api.mistral.ai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
}
```
`anthropic` 不在這個 dict 裡（用專屬的 `https://api.anthropic.com` 常數，走專屬函式）；`custom` 必須自己填 `BASE_URL`。

**本地**（每個 slot，無 PROVIDER 概念，全部走 OpenAI-compat）：
- `LOCAL_LLM_{N}_BASE_URL`：必填（缺少則整個 slot 跳過）
- `LOCAL_LLM_{N}_MODEL`：必填
- `LOCAL_LLM_{N}_API_KEY`：選填（大多本地服務不需要，留空傳 `"not-needed"` 給 OpenAI SDK）

### Provider 函式介面

所有 provider 函式簽名一致：

```python
def call_openai_compat_provider(provider_config: dict, prompt: str, chat_history: list) -> str:
    """回傳最終文字（已處理完工具呼叫往返）。失敗時 raise Exception。"""

def call_anthropic_provider(provider_config: dict, prompt: str, chat_history: list) -> str:
    """同上，Anthropic 原生 API 版本。"""
```

`provider_config` 是一個 dict：`{"base_url":..., "api_key":..., "model":...}`（雲端/本地共用同一個 shape，Anthropic 版本用 `api_key`/`model`，不需要 `base_url` 因為固定打官方 endpoint）。

### 工具呼叫收斂進 provider 函式內部

`call_openai_compat_provider`（涵蓋雲端 openai/gemini/groq/mistral/openrouter/custom + 全部本地 backend，因為都是同一套 OpenAI SDK 呼叫方式）：
1. 組 messages，`client.chat.completions.create(..., tools=llm_tools, tool_choice="auto")`
2. 若回傳 `message.tool_calls`：逐一 `execute_llm_tool_call(tool_call, is_online, LOCALIZATION)`，組回 `{"role":"tool","content":...}`，再呼叫一次拿最終文字
3. 回傳最終文字字串；任何步驟拋例外就讓它往外傳（不要 catch 後包成字串回傳，這樣 fallback 迴圈才抓得到）

`call_anthropic_provider`：
1. 組 Anthropic 訊息格式（`{"role":"user","content":prompt}`），工具 schema 轉換：`[{"name":t["function"]["name"], "description":t["function"]["description"], "input_schema":t["function"]["parameters"]} for t in llm_tools]`
2. `client.messages.create(model=..., messages=..., tools=anthropic_tools, max_tokens=200)`
3. 若 `response.stop_reason == "tool_use"`：從 `response.content` 找出 `type=="tool_use"` 的 block，用 `types.SimpleNamespace(function=types.SimpleNamespace(name=block.name, arguments=block.input))` 包裝成跟 OpenAI tool_call 一樣的 shape，餵給既有的 `execute_llm_tool_call`（不用改 `execute_llm_tool_call` 本身，它只依賴 `.function.name`/`.function.arguments`）
4. 組 `tool_result` content block 餵回去做第二次呼叫，取出最終文字（`response.content` 中 `type=="text"` 的 block）
5. 回傳最終文字字串；失敗則 raise

### Fallback 迴圈

```python
def call_llm_with_fallback(providers: list, prompt: str, chat_history: list) -> str:
    """依序嘗試 providers 清單，回傳第一個成功的結果；全部失敗則 raise 最後一個例外。"""
    last_error = None
    for provider in providers:
        try:
            if provider["kind"] == "anthropic":
                return call_anthropic_provider(provider, prompt, chat_history)
            return call_openai_compat_provider(provider, prompt, chat_history)
        except Exception as e:
            print(f"Provider {provider.get('label','?')} 失敗: {e}，嘗試下一家", file=sys.stderr)
            last_error = e
    raise RuntimeError(f"所有 LLM provider 皆失敗: {last_error}")
```

`handle_incoming_meshtastic_message` 呼叫端簡化為：
```python
    chat_history = []
    try:
        if internet_connected:
            final_response_text = call_llm_with_fallback(CLOUD_LLM_PROVIDERS, text_message, chat_history)
        else:
            final_response_text = call_llm_with_fallback(LOCAL_LLM_PROVIDERS, text_message, chat_history)
    except Exception as e:
        final_response_text = f"❌ 所有 LLM 服務皆無法回應: {e}"

    send_meshtastic_message(f"AI: {final_response_text}", destination_id=sender_id)
```

（原本手動處理 `response_message.tool_calls`/`_get_content` 的整段邏輯移除；`_get_content` 這個 helper 因此在新架構下不再需要，予以移除。）

## 錯誤處理

- 單一 provider 呼叫失敗（連線錯誤、API 錯誤、timeout）→ log 到 stderr，換下一家，不中斷整體流程
- 全部 provider 都失敗（清單本身是空的，或全部呼叫都拋例外）→ 統一組一則對使用者友善的錯誤訊息透過 Meshtastic 回覆，不讓例外往外傳炸到 `_on_receive` 的 catch-all（雖然 `_on_receive` 本身也有 try/except 兜底，但這裡應該給使用者明確回覆而不是靜默無回應）
- 清單為空（使用者完全沒設定任何 `CLOUD_LLM_*`/`LOCAL_LLM_*`）→ 啟動時印一則警告（不阻擋啟動，只是該模式永遠會回錯誤訊息）

## 測試

- provider slot 掃描邏輯（`_scan_provider_slots("CLOUD_LLM", ...)`）：正確組出有序清單、跳過缺 API key 的雲端 slot、跳過缺 base_url 的本地 slot、正確套用 named provider 的預設 base_url、`custom`/覆蓋值優先於預設值
- `call_llm_with_fallback`：第一家成功直接回傳（不呼叫第二家）、第一家失敗換第二家、全部失敗 raise
- `call_openai_compat_provider`：mock OpenAI client，驗證無工具呼叫的直接回傳路徑、有工具呼叫的兩階段呼叫路徑
- `call_anthropic_provider`：mock Anthropic client，驗證 tool schema 轉換正確（`input_schema` 而非 `parameters`）、tool_use block 正確轉接進 `execute_llm_tool_call`、無工具呼叫的直接回傳路徑

## 依賴

新增 `anthropic` Python SDK 依賴（官方 `pip install anthropic`）。README 安裝指令需要更新。

## 未決/後續項

- 本地服務健康檢查/自動探測（不在這次範圍）
- Persistent chat history / RAG（既有 TODO，維持現狀）
