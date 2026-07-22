# Meshtastic-LLM Bridge 📡🧠

**版本：** v0.2.0

[English](README.md) | 繁體中文

一個具備韌性、獨立運作的 Python 橋接器，旨在將您的 Meshtastic 設備連接到強大的大型語言模型 (LLMs)。此專案專為**「末日等級」的離網通訊**設計，讓您即使在沒有網際網路的情況下，也能與 AI 互動。

它會智慧地在在線（雲端 LLM 供應商，例如 OpenAI、Gemini、Groq、Mistral、OpenRouter、Anthropic，或任何自訂端點）和離線（透過任意 OpenAI 相容後端運作的本地 LLM，例如 LM Studio 或 Ollama）模式之間切換，在任何情境下提供可靠的 AI 協助。

---

## ✨ 核心功能

- **多供應商 LLM 容錯備援**：可設定任意數量的雲端 LLM 供應商（OpenAI、Gemini、Groq、Mistral、OpenRouter、Anthropic，或任何自訂的 OpenAI 相容端點），並依序排列成備援清單——若其中一個失敗，橋接器會自動嘗試下一個。離線本地 LLM 後端（LM Studio、Ollama，或任何自架的 OpenAI 相容伺服器）也採用相同的備援機制。
- **GPS 感知天氣查詢**：從您的 Meshtastic 設備發送 `weather here` 或 `附近天氣`，橋接器會自動使用您設備回傳的 GPS 位置來查詢當地天氣預報，無需手動輸入座標！
- **政府災防告警廣播**：在「在線模式」下，橋接器會主動監控台灣**國家災害防救科技中心 (NCDR)** 的共通示警平台 (CAP) Feed。一旦有嚴重災害（地震、颱風、空襲等）發布，它會自動將警報廣播給網狀網路中的所有設備 (`^all`)。
- **Meshtastic 通訊**：直接使用 Meshtastic Python API（`meshtastic.serial_interface.SerialInterface`），透過 `pypubsub` 訂閱收到的訊息，並以 `sendText`/`sendAlert` 發送。連線中斷時會在背景自動偵測並重新連線。
- **訊息切分與分頁**：由於 LoRa 承載量有限，會自動將 LLM 的長回覆切分成多個 Meshtastic 封包，並加上分頁標示 (例如 `(1/3)`)。
- **資源最佳化**：專為低頻寬、低功耗的 Meshtastic 網路設計。
- **簡易設定**：作為一個獨立的 Python 腳本運行，透過 `.env` 檔案進行配置。

### 🆘 災防資訊工具

- **避難所查詢**：詢問附近的緊急避難所（`find_shelter` LLM 工具），資料來源為台灣**內政部消防署**避難收容處所資料集（離線可用，無需網路連線）。查詢結果會比對社群維護的座標勘誤清單（[WaytoSafety](https://g0v.hackmd.io/@waytosafety/home/)，g0v [數位韌性松 DigiResiThon](https://g0v.hackmd.io/@paulpengtw/DigiResiTh0n-home) 專案之一），若官方座標已知有誤會加註警告
- **SOS 廣播**：發送 `SOS`（可加上訊息，例如 `SOS 受困二樓`），會透過 Meshtastic 的 `ALERT_APP` 優先頻道，將您的 GPS 位置與時間戳記廣播給整個網狀網路。為防止誤觸洗版，每個節點每 60 秒限發一次。
- **報平安**：發送 `SAFE` 或 `平安`（可加上訊息），廣播您目前平安無虞，套用相同的速率限制機制。

## 💡 為什麼選擇此專案？

大多數 LLM 解決方案完全依賴網際網路連線。**Meshtastic-LLM Bridge** 提供了無與倫比的韌性：
- **真正的離網 AI**：確保您即使在緊急情況或沒有網際網路的偏遠地區，也能持續獲得 AI 協助。
- **混合智慧**：完美結合兩種優勢：在線時使用強大的雲端 LLM，離線時自動切換到強固的本地 LLM。
- **開源與自訂化**：為您建構專屬的離網 AI 應用程式奠定基礎。

## 🖥️ 系統要求

- **作業系統**：Linux、macOS 或 Windows（透過 WSL2）。
- **Python**：v3.9 或更高版本。
- **Meshtastic 設備**：一個正常運作的 Meshtastic 設備，透過 USB 連接（或可配置為 TCP/IP）。
- **本地 LLM**（選用，離線聊天與推理用）：任何 OpenAI 相容伺服器皆可，例如：
  - **LM Studio** ([lmstudio.ai](https://lmstudio.ai/))：推薦給新手（圖形化介面）。下載一個**聊天模型**，然後啟動本地伺服器。
  - **Ollama** ([ollama.ai](https://ollama.ai/))：命令列友善。安裝一個**聊天模型**（例如 `ollama run gemma:2b`）。確保 Ollama 伺服器正在運行。

## 🔑 帳號與金鑰需求

### 在線／雲端模式
- 至少一組雲端 LLM 供應商的 API 金鑰，例如 [OpenAI](https://platform.openai.com/api-keys)、[Google AI Studio（Gemini）](https://aistudio.google.com/app/apikey)、[Groq](https://console.groq.com/keys)、[Mistral](https://console.mistral.ai/)、[OpenRouter](https://openrouter.ai/keys) 或 [Anthropic](https://console.anthropic.com/)——其中多家皆提供免費額度。

### 離線／本地模式
- 一個本地的 OpenAI 相容 LLM 伺服器（LM Studio、Ollama 或類似服務）——不需要 API 金鑰。

### 選用項目 (用於本地工具 / 特定功能)
- **CWA (中央氣象署開放資料)**：用於台灣天氣預報查詢。

## 🚀 新手友善啟動指南 (一步步教學)

如果您從未玩過硬體或寫過程式，請按照以下步驟操作：

### 第一步：準備環境
1. **安裝軟體**：前往 [nodejs.org](https://nodejs.org/) 與 [python.org](https://www.python.org/) 下載並安裝。
2. **連接硬體**：將您的 Meshtastic 設備用 USB 線接到電腦。
3. **確認路徑**：開啟終端機，輸入 `ls /dev/cu.usb*` (Mac) 或 `ls /dev/ttyUSB*` (Linux)，會看到一串像 `/dev/cu.usbserial-1410` 的文字，這就是您的設備路徑。

### 第二步：取得免費金鑰
1. **雲端 LLM 金鑰**：任選一家取得 API Key 即可，例如 [Google AI Studio（Gemini）](https://aistudio.google.com/app/apikey)、[OpenAI](https://platform.openai.com/api-keys)、[Groq](https://console.groq.com/keys)、[Mistral](https://console.mistral.ai/)、[OpenRouter](https://openrouter.ai/keys) 或 [Anthropic](https://console.anthropic.com/)——多家皆提供免費額度（詳見上方「帳號與金鑰需求」）。若只打算用本地 LLM 離線運作，可略過這步，不需要任何雲端金鑰。
2. **您的使用者 ID**：在 Telegram 搜尋 `@userinfobot` 並傳訊息給它，拿到您的數字 ID (用於警報廣播)。

### 第三步：設定與執行
1. **下載程式碼**：點擊網頁綠色按鈕 `Code` -> `Download ZIP` 並解壓縮。
2. **進入資料夾**：開啟終端機，輸入 `cd `（後面有一個空格），然後將資料夾**直接拖進**終端機視窗，按下 Enter。
3. **建立虛擬環境**：輸入以下三行指令：
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install meshtastic[cli] requests python-dotenv openai anthropic feedparser pytest
   ```
4. **設定金鑰**：建立一個名為 `.env` 的檔案，把您的金鑰與設備路徑填進去。
5. **啟動本地大腦**：開啟 LM Studio，下載模型並點擊 **Start Server**。
6. **啟動橋接器**：輸入 `python3 bridge.py` 即可啟動！

---

## 🚀 安裝指南 (開發者適用)

### 1. 複製專案
```bash
git clone https://github.com/yourusername/meshtastic-llm-bridge.git
cd meshtastic-llm-bridge
```

### 2. 準備 Python 環境
```bash
# 建立並啟用虛擬環境
python3 -m venv venv
source venv/bin/activate

# 安裝 Python 依賴套件
pip install meshtastic[cli] requests python-dotenv openai anthropic feedparser pytest
```

### 3. Meshtastic 設備設定
- 透過 USB 連接您的 Meshtastic 設備。
- 尋找設備路徑：執行 `meshtastic --info` (例如 macOS 上的 `/dev/cu.usbserial-0001`，Linux 上的 `/dev/ttyUSB0`)。

### 4. 本地 LLM 設定 (離線模式)

#### 選項 A: LM Studio (推薦給新手)
1. 下載並安裝 [LM Studio](https://lmstudio.ai/)。
2. 在 LM Studio 中，下載您偏好的 LLM（例如 `Nexusflow/Starling-LM-7B-beta-GGUF`）。
3. 前往 "Local Server" 分頁，點擊 "Start Server"。確保其運行在 `http://localhost:1234/v1`。

#### 選項 B: Ollama
1. 下載並安裝 [Ollama](https://ollama.ai/)。
2. 下載您偏好的 LLM（例如 `ollama run gemma:2b`）。
3. 確保 Ollama 伺服器正在運行（通常 `ollama run` 後會自動啟動）。

### 5. 配置環境變數

在專案根目錄建立一個 `.env` 檔案，內容如下：

```
MESHTASTIC_DEVICE_PATH=/dev/ttyUSB0
MESHTASTIC_LONGNAME=MeshtasticAI
LOCALIZATION=TW

# 雲端 LLM 供應商（依序備援清單，編號 slot——想加幾組都可以）
# provider 可填：openai | gemini | groq | mistral | openrouter | anthropic | custom
CLOUD_LLM_1_PROVIDER=openai
CLOUD_LLM_1_API_KEY=sk-your-key-here
CLOUD_LLM_1_MODEL=gpt-4o
# CLOUD_LLM_1_BASE_URL=            # 只有 provider=custom，或想覆蓋內建預設值時才需要填

CLOUD_LLM_2_PROVIDER=anthropic
CLOUD_LLM_2_API_KEY=sk-ant-your-key-here
CLOUD_LLM_2_MODEL=claude-sonnet-5

# 本地 LLM 後端（依序備援清單，任何 OpenAI 相容伺服器皆可）
LOCAL_LLM_1_BASE_URL=http://localhost:1234/v1   # 例如 LM Studio
LOCAL_LLM_1_MODEL=your-local-model-name

LOCAL_LLM_2_BASE_URL=http://localhost:11434/v1  # 例如 Ollama 的 OpenAI 相容端點
LOCAL_LLM_2_MODEL=your-ollama-model-name

CWA_API_KEY=your_cwa_key_here
```

只有您實際填寫的 slot 會被使用——沒填齊或整組留空的編號 slot 會被跳過，橋接器會自動嘗試下一組。雲端與本地兩份清單都支援任意數量的備援項目。

## 🎮 使用方式

1. 確保您的 Meshtastic 設備已透過 USB 連接並開啟電源。
2. 若您會依賴離線／本地模式，請確保本地 LLM 伺服器正在運行。
3. 啟用 Python 虛擬環境：`source venv/bin/activate`
4. 運行橋接器：`python3 bridge.py`

現在，從您的 Meshtastic 手機應用程式向您的 AI 節點（例如 `YourMeshAINode`）發送訊息。橋接器會依序嘗試您設定的雲端供應商（在線時）或本地供應商（離線時），直到其中一組成功回應為止。

## 📡 系統架構

此橋接器採用混合智慧架構：
1. **Meshtastic Python API 監聽器**：與收發機建立持續的 `SerialInterface` 連線，並透過 `pypubsub` 訂閱 `meshtastic.receive.text`，讓傳入的 LoRa 訊息直接送達橋接器程序（不經過任何 CLI 子程序）。另有 `meshtastic.connection.lost` 訂閱，一旦序列埠連線中斷即自動在背景重新連線。
2. **網際網路連線檢查**：定期 ping 一個可靠的端點，以判斷在線/離線狀態。
3. **動態 LLM 分派與依序備援**：
   - **在線**：依序嘗試每一組已設定的雲端供應商（`CLOUD_LLM_1`、`CLOUD_LLM_2`……）——OpenAI、Gemini、Groq、Mistral、OpenRouter、Anthropic，或任何自訂的 OpenAI 相容端點——若某一組失敗即自動改用下一組。
   - **離線**：依序嘗試每一組已設定的本地供應商（`LOCAL_LLM_1`、`LOCAL_LLM_2`……），對象可以是任何 OpenAI 相容後端（例如 LM Studio、Ollama），若某個後端無法連線即自動改用下一組。
4. **Meshtastic 回覆發送器**：將 LLM 回覆格式化為適合 Meshtastic 有限承載量的大小，切分並分頁長訊息，然後透過 `interface.sendText()` 發送（緊急 SOS/告警廣播則使用高優先權的 `interface.sendAlert()`）。

## 📝 LoRa 訊息最佳化建議

由於 Meshtastic 的低頻寬特性，請最佳化您的查詢：
- **保持簡潔**：提出簡短、直接的問題。
- **使用關鍵字**：「天氣 [城市]」、「手冊 [主題]」、「計算 [表達式]」。
- **預期摘要**：LLM 的回覆將限制在約 200 字元內，並可能進行分頁。

## 🔐 安全性考量

- **通訊加密**：橋接器與雲端 / 本地 LLM API 之間的所有通訊均已加密（HTTPS/本地 IPC）。
- **實體安全**：您的 Meshtastic 設備和本地電腦應放置在安全位置。
- **本地 LLM 信任**：請確保您信任您下載的本地 LLM 模型，因為它們在您的機器上運行。

## 🤝 貢獻指南
歡迎提交 Pull Requests！

## 📜 授權條款
MIT
