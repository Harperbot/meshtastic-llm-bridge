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
- **本地知識庫 (RAG)**：在離線模式下，LLM 可以查詢本地 `knowledge_base/` 目錄中的文件（PDF、Markdown、文字檔），以提供更豐富的答案。這對於離網生存與參考至關重要。
- **智慧工具整合**：無縫整合 `find_parking` (停車查詢) 和 `query_surf_spots` (衝浪/天氣查詢) 工具。
  - **`find_parking`**：在有網路時運作；如果網路中斷，則回傳「離線」訊息。
  - **`query_surf_spots`**：離線時可提供一般浪點資訊與日出日落時間。即時潮汐、風況和颱風數據只有在有網路且配置 CWA API Key 時才可用。
- **Meshtastic 通訊**：利用 Meshtastic CLI 進行 LoRa 網狀網路的訊息收發。
- **訊息切分與分頁**：由於 LoRa 承載量有限，會自動將 LLM 的長回覆切分成多個 Meshtastic 封包，並加上分頁標示 (例如 `(1/3)`)。
- **資源最佳化**：專為低頻寬、低功耗的 Meshtastic 網路設計。
- **簡易設定**：作為一個獨立的 Python 腳本運行，透過 `.env` 檔案進行配置。

## 💡 為什麼選擇此專案？

大多數 LLM 解決方案完全依賴網際網路連線。**Meshtastic-LLM Bridge** 提供了無與倫比的韌性：
- **真正的離網 AI**：確保您即使在緊急情況或沒有網際網路的偏遠地區，也能持續獲得 AI 協助。
- **混合智慧**：完美結合兩種優勢：在線時使用強大的雲端 LLM，離線時自動切換到強固的本地 LLM。
- **個人知識中心**：將您的本地電腦變成 AI 的私人、可搜尋知識庫，並可透過 LoRa 存取。
- **開源與自訂化**：為您建構專屬的離網 AI 應用程式奠定基礎。

## 🖥️ 系統要求

- **作業系統**：Linux、macOS 或 Windows（透過 WSL2）。
- **Python**：v3.9 或更高版本。
- **Meshtastic 設備**：一個正常運作的 Meshtastic 設備，透過 USB 連接（或可配置為 TCP/IP）。
- **本地 LLM**：
  - **LM Studio** ([lmstudio.ai](https://lmstudio.ai/))：推薦給新手（圖形化介面）。下載模型後啟動本地伺服器。
  - **Ollama** ([ollama.ai](https://ollama.ai/))：命令列友善。安裝後運行一個模型（例如 `ollama run gemma:2b`）。

## 🔑 帳號與金鑰要求

### 必要項目
- **Google AI Studio**：取得 [Gemini API Key](https://aistudio.google.com/app/apikey)，用於在線模式（有免費額度）。

### 選用項目 (用於本地工具 / 特定功能)
- **TDX (交通部資料服務)**：用於台灣停車場查詢。
- **CWA (中央氣象署開放資料)**：用於台灣衝浪浪點天氣查詢。

## 🚀 安裝指南

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
pip install "meshtastic[cli]" requests python-dotenv openai ollama langchain-community pypdf unstructured chromadb
```

### 3. Meshtastic 設備設定
- 透過 USB 連接您的 Meshtastic 設備。
- 尋找設備路徑：執行 `meshtastic --info` (例如 macOS 上的 `/dev/cu.usbserial-0001`，Linux 上的 `/dev/ttyUSB0`)。

### 4. 本地 LLM 設定 (離線模式)

#### 選項 A: LM Studio (推薦給新手)
1. 下載並安裝 [LM Studio](https://lmstudio.ai/)。
2. 在 LM Studio 中，下載您偏好的 LLM（例如 `Nexusflow/Starling-LM-7B-beta-GGUF`）和一個 Embedding 模型（例如 `nomic-ai/nomic-embed-text-v1.5`）。
3. 前往 "Local Server" 分頁，點擊 "Start Server"。確保其運行在 `http://localhost:1234/v1`。

#### 選項 B: Ollama
1. 下載並安裝 [Ollama](https://ollama.ai/)。
2. 下載您偏好的 LLM（例如 `ollama run gemma:2b`）和一個 Embedding 模型（例如 `ollama run nomic-embed-text`）。
3. 確保 Ollama 伺服器正在運行（通常 `ollama run` 後會自動啟動）。

### 5. 配置 `.env` 檔案
複製範例設定檔：
```bash
cp .env.example .env
```
編輯 `.env` 並填入您的資訊：
```ini
# --- 一般設定 ---
MESHTASTIC_DEVICE_PATH=/dev/cu.usbserial-XXXX # <--- 重要：請更新為您的設備路徑！
MESHTASTIC_LONGNAME=YourMeshAINode
LOCALIZATION=TW # 設定為 'TW' 啟用台灣專屬工具，或移除以使用全球 LLM

# --- Google Gemini API (在線模式) ---
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL_ONLINE=gemini-1.5-pro-latest

# --- 本地 LLM (離線模式) ---
# LM Studio 設定 (如果啟用則優先)
LOCAL_LLM_API_BASE=http://localhost:1234/v1
LOCAL_LLM_MODEL=Nexusflow/Starling-LM-7B-beta-GGUF # 您在 LM Studio 下載的聊天模型名稱

# Ollama 設定 (如果 LM Studio 失敗或未配置，則為次要選項)
LOCAL_LLM_OLLAMA_API_BASE=http://localhost:11434/api
LOCAL_LLM_OLLAMA_MODEL=gemma:2b # 您在 Ollama 安裝的聊天模型名稱

# 本地 Embedding 模型 (用於 RAG - 檢索增強生成)
# Langchain 用於在離線時生成文件 Embedding。它會優先使用 LOCAL_EMBEDDING_API_BASE，然後才是 Ollama。
# 如果使用 LM Studio，API Base 通常與 LOCAL_LLM_API_BASE 相同。
# 如果使用 Ollama，請確保您已安裝 Embedding 模型（例如執行 'ollama run nomic-embed-text'）。
LOCAL_EMBEDDING_API_BASE=http://localhost:1234/v1 # 例如：LM Studio Embedding API 端點
LOCAL_EMBEDDING_MODEL=nomic-ai/nomic-embed-text-v1.5 # 例如：您下載的 Embedding 模型名稱
```

### 6. 建立您的本地知識庫 (用於離線 RAG)

將您的文件（例如：生存指南、手冊、維基百科匯出檔）放入 `./knowledge_base/` 目錄中。
支援格式：`.txt`、`.md`、`.pdf`。

每次新增/移除文件或更新 Embedding 模型後，請重新啟動 `bridge.py` 以重建向量資料庫。

## 🎮 使用方式

1. 確保您的 Meshtastic 設備已透過 USB 連接並開啟電源。
2. 確保您選擇的本地 LLM 伺服器 (LM Studio 或 Ollama) 正在運行。
3. 啟用 Python 虛擬環境：`source venv/bin/activate`
4. 運行橋接器：`python3 bridge.py`

現在，從您的 Meshtastic 手機應用程式向您的 AI 節點（例如 `YourMeshAINode`）發送訊息。橋接器會智慧地將您的查詢路由到 Gemini（在線時）或您的本地 LLM（離線時），並在離線時使用您的本地知識庫。

## 📡 系統架構

此橋接器採用混合智慧架構：
1. **Meshtastic CLI 監聽器**：透過 `meshtastic --listen` 持續監控傳入的 LoRa 訊息。
2. **網際網路連線檢查**：定期 ping 一個可靠的端點，以判斷在線/離線狀態。
3. **動態 LLM 分派**：
   - **在線**：將查詢路由到 Google Gemini API（透過 `openai` 客戶端與 `x-goog-api-key` 標頭）。
   - **離線**：嘗試連線到 LM Studio 的 OpenAI 相容 API，如果不可用則回退到 Ollama。
4. **本地 RAG 整合**：在離線模式下，查詢 `./knowledge_base/` 以獲取相關文件片段，並將此上下文注入到 LLM 的 Prompt 中。
5. **Meshtastic 回覆發送器**：將 LLM 回覆格式化為適合 Meshtastic 有限承載量的大小，切分並分頁長訊息，然後透過 `meshtastic --sendtext` 發送。

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
