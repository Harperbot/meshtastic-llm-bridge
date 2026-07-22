# 設計文件：Python API 遷移 + 避難點/SOS/報平安整合

**日期**：2026-07-22
**狀態**：已核准，待寫實作計畫

## 背景與動機

`meshtastic-llm-bridge` 目前用 `subprocess.Popen(["meshtastic","--listen"])` 呼叫官方 CLI、手動 parse stdout 文字（`from:`/`text:` 欄位）收發 Meshtastic LoRa mesh 訊息。這是脆弱的整合方式：CLI 輸出格式變動就解析失敗、無斷線重連、無法使用官方 `ALERT_APP` 高優先權訊息類型。

同時，使用者已淘汰停車場/浪點查詢兩個 function-calling 工具，想改成「避難點查詢」；並延伸出「災難情境下還需要什麼」的評估，決定加入 SOS 求救廣播與報平安廣播。SOS 要用官方標準的 `ALERT_APP`/`Priority.ALERT` 訊息類型，而這個功能只存在於 Python API（CLI 沒有對應功能），因此把「subprocess→Python API 遷移」（原本獨立評估的 P0 優化項）與這次的新功能開發合併為同一個設計。

## 範圍

**這次做**：
1. `bridge.py` 核心收發層從 subprocess+CLI parsing 遷移到 `meshtastic.serial_interface.SerialInterface()` + pypubsub 事件模型
2. 新增 threaded 斷線重連
3. 避難收容處所查詢（取代 `find_parking`/`query_surf_spots`）
4. SOS 求救廣播（`ALERT_APP`/`Priority.ALERT`，固定關鍵字觸發，含 cooldown）
5. 報平安廣播（一般文字廣播，固定關鍵字觸發，含 cooldown）
6. 移除 `tools/taiwan/parking_query.py`、`tools/taiwan/surf_query.py` 及對應 bridge.py 程式碼
7. README/README.zh-TW.md 同步更新（含既有 drift 一併修正：clone URL、`.env.example`、`feedparser` 依賴缺漏）

**不在這次範圍（記錄為未來項）**：
- 防空避難設施查詢（民防用，18 縣市各自資料集格式不一，需要另外 ETL，列 Phase 2）
- Persistent chat history（既有 TODO，與本次功能無直接關聯，不擴大範圍）
- RAG knowledge base（既有 TODO，同上）
- MQTT transport（社群研究中提到的替代整合模式，非必要，暫不做）

## 架構：基礎層 + 功能層

新功能（SOS 尤其依賴 `sendAlert()`）建立在 Python API 遷移之上，因此先做基礎層、驗證現有功能不壞，再疊加新功能。

### 基礎層：subprocess+CLI → Python API

- 主 loop：`subprocess.Popen` + stdout parsing → `meshtastic.serial_interface.SerialInterface()` + `pub.subscribe(on_receive, "meshtastic.receive.text")`，callback 拿到結構化 packet dict（`fromId`、`decoded.text`），不再手動 split 字串
- `get_node_location()`：手動 parse `meshtastic --nodes` 表格輸出 → 直接讀 `interface.nodes` 字典結構取 GPS
- `send_meshtastic_message()`：`subprocess.run(["meshtastic","--sendtext",...])` → `interface.sendText()`；長訊息切分邏輯（`MAX_MESHTASTIC_PAYLOAD=220`）保留，只換底層傳送方式
- 新增斷線重連：`SerialInterface` 例外時 log → `close()` → 等待固定 interval → 重新 `SerialInterface()` → 重新 `pub.subscribe`；避免無限緊密重試迴圈（重試間隔遞增或固定 cooldown）

### 功能層 1：避難收容處所查詢

- 資料來源：消防署「避難收容處所點位檔」（data.gov.tw/dataset/73242，全國單一 CSV：地址/經緯度/容量/適用災害類型）
- `tools/taiwan/geo_utils.py`：抽出共用 `haversine()`（現有 `parking_query.py`/`surf_query.py` 重複定義的問題一併解決）
- `tools/taiwan/fetch_shelters.py`：一次性/手動重跑的 ETL script，CSV → 本地 `tools/taiwan/shelters.json`（模式與現有 `surf_query.py` 讀本地 JSON 一致，離線也能查）
- `tools/taiwan/shelter_query.py`：`--lat --lon [--n 3]`，用 haversine 排序回傳最近 N 個避難所（名稱/地址/容量/距離）
- `bridge.py` 的 `llm_tools` schema 新增 `find_shelter(lat, lon)`，沿用現有 LLM function-calling 觸發模式（跟天氣查詢一致，使用者自然語言問、LLM 判斷呼叫）

### 功能層 2：SOS 求救廣播

- 觸發：訊息以 `SOS`（不分大小寫）開頭，**不經 LLM**，程式直接判斷（避免高風險動作被 LLM 誤判意圖延遲或漏判）
- 流程：`get_node_location(sender_id)` 取 GPS（取不到時仍照送，訊息標「GPS 位置未知」，不因缺 GPS 放棄廣播）→ 組成訊息（節點+GPS+時間戳+可選附加文字）→ `interface.sendAlert(text, destination_id="^all")`（`ALERT_APP`/`Priority.ALERT`，跟一般文字訊息分開的官方高優先權類別）
- Cooldown：同一節點 60 秒內重複觸發直接忽略並 log suppressed（借鏡官方 Detection Sensor module 的 `minimumBroadcastSecs` 模式），in-memory dict 記錄 `last_sos_ts` per node

### 功能層 3：報平安廣播

- 觸發：訊息以 `SAFE` 或 `平安` 開頭，同樣不經 LLM
- 流程與 SOS 相同（GPS+時間戳+可選文字），但用 `interface.sendText(..., destination_id="^all")` 一般文字廣播，不佔用 `ALERT_APP` 頻道（報平安非緊急，不該與真正緊急訊息搶優先權/互相干擾）
- Cooldown 邏輯與 SOS 相同模式，但獨立計時（不共用同一個 timer/dict）

### 移除

- `tools/taiwan/parking_query.py`、`tools/taiwan/surf_query.py` 刪除
- `bridge.py`：`llm_tools` 中 `find_parking`/`query_surf_spots` 兩個 schema、`execute_llm_tool_call()` 對應分支刪除
- README.md / README.zh-TW.md：移除 parking/surf 段落，新增避難點/SOS/報平安說明；順手修正既有 drift（clone URL 指向不存在的內容、`.env.example` 缺檔、`feedparser` 依賴未列在安裝指令）

## 錯誤處理

- 斷線重連：exception → log → close → 固定 interval 後重試，重試需要上限或退避機制避免打壞序列埠或洗 log
- SOS/報平安：`sendAlert()`/`sendText()` 失敗（裝置離線等）必須 log 出來，不可靜默吞掉——生命安全相關訊息失敗使用者應該知道
- 現有 broad `except Exception` 吞錯直接塞回覆文字的模式（`call_gemini_api_online`/`call_local_llm`）不在本次範圍內修改，除非牽涉到本次改動的程式碼路徑

## 模型分工（依 `~/.claude/rules/harper-agent-orchestration-sop.md` §1）

| 角色 | 模型 | 負責 |
|---|---|---|
| 主控 (main) | 本 session（Sonnet 5，Claude Code 動態主控） | 派工、驗收、裁決、逐項抽驗 |
| Implementer | Sonnet | 實際寫 code，分批 dispatch |
| R1（對抗式 critic） | Sonnet | 每批完成後第一輪審查 |
| R2（獨立從零重推） | **Opus**（僅高複雜度批次） | P0 斷線重連狀態機、SOS/報平安 cooldown 邊界、`ALERT_APP` 接線正確性 |

按批複雜度分級：

| Batch | 複雜度 | Critic |
|---|---|---|
| `geo_utils.py` 抽取 / 避難點 ETL script | 低 | R1 一輪 |
| `shelter_query.py` + `llm_tools` schema 增刪 | 中 | R1 一輪 |
| README 同步 | 低 | R1 一輪 |
| P0：subprocess→`SerialInterface`+pub/sub 重構 | 高 | R1 + R2(Opus) |
| P0：threaded 斷線重連 | 高 | R1 + R2(Opus) |
| SOS/報平安：cooldown + `sendAlert()` 接線 | 高 | R1 + R2(Opus) |

R1 若回報「GO 0 finding 且無驗證痕跡」→ 觸發橡皮圖章護欄，換 R2(Opus) 複驗，不直接收工。

## 測試

單元測試（新寫/改動部分，不要求全專案覆蓋率）：
- `geo_utils.haversine` 正確性
- `shelter_query` 最近點排序
- SOS/報平安 cooldown（同節點重複觸發應被擋、超過 cooldown 後應放行）
- P0 斷線重連狀態機（mock interface 模擬例外→重連流程）

## 真實硬體驗證梯度

`^all` 廣播一旦誤觸會影響 mesh 範圍內所有裝置，不能只靠 mock 測試就上線。分級驗證（借鏡 Harper 既有「運行測試梯」慣例）：

| Tier | 內容 | 風險 | 時機 |
|---|---|---|---|
| 0 唯讀 | `SerialInterface()` 連線 + `pub.subscribe` + 讀 `interface.nodes`/`myInfo`，不發送 | 無 | P0 完成後第一步 |
| 1 安全收發 | 兩節點 direct message（非 `^all`）測 `sendText()`/`sendAlert()`，接收端確認內容/`portnum`/`priority` 正確 | 低 | P0 收發層驗證 |
| 2 斷線重連 | 實際拔插 USB 序列線，確認偵測斷線+自動重連成功+功能恢復 | 無 | P0 reconnect 驗證（純手動） |
| 3 SOS/報平安流程（direct message） | Node A 送 `SOS`/`SAFE` → Node B 確認內容/GPS/優先權正確；同節點 60 秒內重複觸發應被 cooldown 擋 | 低 | 新功能邏輯驗證 |
| 4 `^all` 廣播驗證 | 真實上 `^all`，確認全 mesh 廣播路徑正確——只做一次，選確定範圍內無其他 Meshtastic 使用者的時間點，使用者在場 | 中 | 最終上線前一次性 |
| 避難點查詢 | 固定座標離線測 `shelter_query.py` CLI，再串 LLM function-calling 走真實訊息流程 | 無 | 隨時 |

Tier 0-3 可重跑並適合寫進驗證腳本（Tier 2 拔線純手動）；Tier 4 需使用者人工在場謹慎執行，非常態測試。

## 未決/後續項（不在本次實作範圍，記錄供下次參考）

- 防空避難設施查詢（Phase 2，18 縣市 ETL）
- Persistent chat history / RAG knowledge base（既有 TODO，未擴大本次範圍）
- MQTT transport 作為第二種連線模式
- mesh 節點網路健康查詢（「附近還有誰在線」）
