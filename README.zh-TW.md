# Meshtastic-LLM Bridge 📡🧠

[English](README.md) | 繁體中文

一個具備韌性、獨立運作的 Python 橋接器，旨在將您的 Meshtastic 設備連接到強大的大型語言模型 (LLMs)。此專案專為**「末日等級」的離網通訊**設計，讓您即使在沒有網際網路的情況下，也能與 AI 互動。

它會智慧地在在線（Google Gemini）和離線（LM Studio 或 Ollama 等本地 LLM）模式之間切換，在任何情境下提供可靠的 AI 協助。

---

## ✨ 核心功能

- **雙模式 LLM 整合**：自動偵測網際網路連線狀態。
  - **在線模式**：連接到 Google Gemini API，提供強大、需要網路的 AI 回覆。
  - **離線模式**：無縫切換到本地 LLMs (LM Studio 或 Ollama)，提供離網 AI 能力。
- **GPS 感知天氣查詢**：從您的 Meshtastic 設備發送 `weather here` 或 `附近天氣`，橋接器會自動使用您設備回傳的 GPS 位置來查詢當地天氣預報，無需手動輸入座標！
- **政府災防告警廣播**：在「在線模式」下，橋接器會主動監控台灣**國家災害防救科技中心 (NCDR)** 的共通示警平台 (CAP) Feed。一旦有嚴重災害（地震、颱風、空襲等）發布，它會自動將警報廣播給網狀網路中的所有設備 (`^all`)。
- **Meshtastic 通訊**：利用 Meshtastic CLI 進行 LoRa 網狀網路的訊息收發。
- **訊息切分與分頁**：由於 LoRa 承載量有限，會自動將 LLM 的長回覆切分成多個 Meshtastic 封包，並加上分頁標示 (例如 `(1/3)`)。
- **資源最佳化**：專為低頻寬、低功耗的 Meshtastic 網路設計。
- **簡易設定**：作為一個獨立的 Python 腳本運行，透過 `.env` 檔案進行配置。

### 🆘 災防資訊工具

- **避難所查詢**：詢問附近的緊急避難所（`find_shelter` LLM 工具），資料來源為台灣**內政部消防署**避難收容處所資料集（離線可用，無需網路連線）
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
- **本地 LLM**：(離線聊天與推理的核心)
  - **LM Studio** ([lmstudio.ai](https://lmstudio.ai/))：推薦給新手（圖形化介面）。下載一個**聊天模型**，然後啟動本地伺服器。
  - **Ollama** ([ollama.ai](https://ollama.ai/))：命令列友善。安裝一個**聊天模型**（例如 `ollama run gemma:2b`）。確保 Ollama 伺服器正在運行。

## 🔑 帳號與金鑰需求

### 必要項目
- **Google AI Studio**：取得 [Gemini API Key](https://aistudio.google.com/app/apikey)，用於在線模式（有免費額度）。

### 選用項目 (用於本地工具 / 特定功能)
- **CWA (中央氣象署開放資料)**：用於台灣天氣預報查詢。

## 🚀 新手友善啟動指南 (一步步教學)

如果您從未玩過硬體或寫過程式，請按照以下步驟操作：

### 第一步：準備環境
1. **安裝軟體**：前往 [nodejs.org](https://nodejs.org/) 與 [python.org](https://www.python.org/) 下載並安裝。
2. **連接硬體**：將您的 Meshtastic 設備用 USB 線接到電腦。
3. **確認路徑**：開啟終端機，輸入 `ls /dev/cu.usb*` (Mac) 或 `ls /dev/ttyUSB*` (Linux)，會看到一串像 `/dev/cu.usbserial-1410` 的文字，這就是您的設備路徑。

### 第二步：取得免費金鑰
1. **Gemini 金鑰**：登入 [Google AI Studio](https://aistudio.google.com/app/apikey) 建立 API Key。
2. **您的使用者 ID**：在 Telegram 搜尋 `@userinfobot` 並傳訊息給它，拿到您的數字 ID (用於警報廣播)。

### 第三步：設定與執行
1. **下載程式碼**：點擊網頁綠色按鈕 `Code` -> `Download ZIP` 並解壓縮。
2. **進入資料夾**：開啟終端機，輸入 `cd `（後面有一個空格），然後將資料夾**直接拖進**終端機視窗，按下 Enter。
3. **建立虛擬環境**：輸入以下三行指令：
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install meshtastic[cli] requests python-dotenv openai ollama feedparser pytest
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
pip install meshtastic[cli] requests python-dotenv openai ollama feedparser pytest
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
GEMINI_API_KEY=your_key_here
GEMINI_MODEL_ONLINE=gemini-flash-latest
LOCAL_LLM_API_BASE=http://localhost:1234/v1
LOCAL_LLM_MODEL=your-local-model-name
LOCAL_LLM_OLLAMA_API_BASE=http://localhost:11434/api
LOCAL_LLM_OLLAMA_MODEL=your-ollama-model-name
CWA_API_KEY=your_cwa_key_here
```

## 🎮 使用方式

1. 確保您的 Meshtastic 設備已透過 USB 連接並開啟電源。
2. 確保您選擇的本地 LLM 伺服器 (LM Studio 或 Ollama) 正在運行。
3. 啟用 Python 虛擬環境：`source venv/bin/activate`
4. 運行橋接器：`python3 bridge.py`

現在，從您的 Meshtastic 手機應用程式向您的 AI 節點（例如 `YourMeshAINode`）發送訊息。橋接器會智慧地將您的查詢路由到 Gemini（在線時）或您的本地 LLM（離線時）。

## 📡 系統架構

此橋接器採用混合智慧架構：
1. **Meshtastic CLI 監聽器**：透過 `meshtastic --listen` 持續監控傳入的 LoRa 訊息。
2. **網際網路連線檢查**：定期 ping 一個可靠的端點，以判斷在線/離線狀態。
3. **動態 LLM 分派**：
   - **在線**：將查詢路由到 Google Gemini API（透過 `openai` 客戶端與 `x-goog-api-key` 標頭）。
   - **離線**：嘗試連線到 LM Studio 的 OpenAI 相容 API，如果不可用則回退到 Ollama。
4. **Meshtastic 回覆發送器**：將 LLM 回覆格式化為適合 Meshtastic 有限承載量的大小，切分並分頁長訊息，然後透過 `meshtastic --sendtext` 發送。

## 📝 LoRa 訊息最佳化建議

由於 Meshtastic 的低頻寬特性，請最佳化您的查詢：
- **保持簡潔**：提出簡短、直接的問題。
- **使用關鍵字**：「天氣 [城市]」、「手冊 [主題]」、「計算 [表達式]」。
- **預期摘要**：LLM 的回覆將限制在約 200 字元內，並可能進行分頁。

## 🔐 安全性考量

- **通訊加密**：橋接器與 Google / 本地 LLM API 之間的所有通訊均已加密（HTTPS/本地 IPC）。
- **實體安全**：您的 Meshtastic 設備和本地電腦應放置在安全位置。
- **本地 LLM 信任**：請確保您信任您下載的本地 LLM 模型，因為它們在您的機器上運行。

## 🤝 貢獻指南
歡迎提交 Pull Requests！

## 📜 授權條款
MIT
