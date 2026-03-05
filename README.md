# Meshtastic-LLM Bridge 📡🧠

[繁體中文](README.zh-TW.md) | English

A resilient, standalone Python bridge connecting your Meshtastic device to powerful Large Language Models (LLMs). This project is designed for **"apocalypse-grade" off-grid communication**, allowing you to interact with AI even when the internet is down.

It intelligently switches between online (Google Gemini) and offline (Local LLMs like LM Studio or Ollama) modes, providing robust AI assistance in any scenario.

---

## ✨ Features

- **Dual-Mode LLM Integration**: Automatically detects internet connectivity.
  - **Online Mode**: Connects to Google Gemini API for powerful, internet-enabled AI responses.
  - **Offline Mode**: Seamlessly switches to local LLMs (LM Studio or Ollama) for off-grid AI capabilities.
- **Local Knowledge Base (RAG)**: In offline mode, the LLM can query a local `knowledge_base/` of documents (PDFs, Markdown, text files) to provide informed answers.
- **Meshtastic Communication**: Utilizes the Meshtastic CLI for sending and receiving messages over LoRa mesh networks.
- **Message Chunking & Pagination**: Automatically splits long LLM responses into multiple Meshtastic packets with pagination (`(1/3)`) due to LoRa's limited payload size.
- **Resource Optimization**: Designed for low-bandwidth, low-power Meshtastic networks.
- **Easy Setup**: Runs as a standalone Python script with `.env` configuration.

## 💡 Why this project?

Most LLM solutions rely entirely on internet connectivity. **Meshtastic-LLM Bridge** offers unparalleled resilience:
- **True Off-Grid AI**: Ensures you always have access to AI assistance, even in emergencies or remote locations without internet.
- **Hybrid Intelligence**: Leverages the best of both worlds: powerful cloud LLMs when online, and robust local LLMs when offline.
- **Personal Knowledge Hub**: Turn your local computer into a private, searchable knowledge base for your AI, accessible via LoRa.
- **Open Source & Customizable**: A foundation for building your own specialized off-grid AI applications.

## 🖥️ System Requirements

- **OS**: Linux, macOS, or Windows (via WSL2).
- **Python**: v3.9 or higher.
- **Meshtastic Device**: A working Meshtastic device connected via USB (or configurable for TCP/IP).
- **Local LLM**: 
  - **LM Studio** ([lmstudio.ai](https://lmstudio.ai/)): Recommended for ease of use (GUI). Download a model and start the local server.
  - **Ollama** ([ollama.ai](https://ollama.ai/)): Command-line friendly. Install and run a model (e.g., `ollama run gemma:2b`).

## 🔑 Account & Key Requirements

### Mandatory
- **Google AI Studio**: Obtain your [Gemini API Key](https://aistudio.google.com/app/apikey) for online mode (free tier available).

### Optional (for local tools / specialized functions)
- **TDX (Transport Data eXchange)**: For parking queries in Taiwan.
- **CWA Open Data**: For surf spot weather in Taiwan.

## 🚀 Installation

### 1. Clone the repository
```bash
git clone https://github.com/yourusername/meshtastic-llm-bridge.git
cd meshtastic-llm-bridge
```

### 2. Prepare Python Environment
```bash
# Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate

# Install Python dependencies
pip install "meshtastic[cli]" requests python-dotenv openai ollama langchain-community pypdf unstructured chromadb
```

### 3. Meshtastic Device Setup
- Connect your Meshtastic device via USB.
- Find its path: `meshtastic --info` (e.g., `/dev/cu.usbserial-0001` on macOS, `/dev/ttyUSB0` on Linux).

### 4. Local LLM Setup (for Offline Mode)

#### Option A: LM Studio (Recommended for Beginners)
1. Download and install [LM Studio](https://lmstudio.ai/).
2. In LM Studio, download your preferred LLM (e.g., `Nexusflow/Starling-LM-7B-beta-GGUF`) and an Embedding model (e.g., `nomic-ai/nomic-embed-text-v1.5`).
3. Go to the "Local Server" tab and click "Start Server". Ensure it's running on `http://localhost:1234/v1`.

#### Option B: Ollama
1. Download and install [Ollama](https://ollama.ai/).
2. Download your preferred LLM (e.g., `ollama run gemma:2b`) and an Embedding model (e.g., `ollama run nomic-embed-text`).
3. Ensure the Ollama server is running (usually automatic after `ollama run`).

### 5. Configure `.env`
Copy the example file:
```bash
cp .env.example .env
```
Edit `.env` with your details:
```ini
# --- General Configuration ---
MESHTASTIC_DEVICE_PATH=/dev/cu.usbserial-XXXX # <--- IMPORTANT: Update this!
MESHTASTIC_LONGNAME=YourMeshAINode
LOCALIZATION=TW # Set to 'TW' for Taiwan-specific tools, or remove for global LLM

# --- Google Gemini API (Online Mode) ---
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL_ONLINE=gemini-1.5-pro-latest

# --- Local LLM (Offline Mode) ---
# LM Studio Configuration (Priority 1 if enabled)
LOCAL_LLM_API_BASE=http://localhost:1234/v1
LOCAL_LLM_MODEL=Nexusflow/Starling-LM-7B-beta-GGUF # Your downloaded chat model in LM Studio

# Ollama Configuration (Priority 2 if LM Studio fails or is not configured)
LOCAL_LLM_OLLAMA_API_BASE=http://localhost:11434/api
LOCAL_LLM_OLLAMA_MODEL=gemma:2b # Your installed Ollama chat model

# Local Embedding Model (for RAG - Retrieval Augmented Generation)
# Used by Langchain for generating document embeddings when offline.
# Prioritizes LM Studio if LOCAL_EMBEDDING_API_BASE is set, then Ollama.
# If using LM Studio, the API base is usually the same as LOCAL_LLM_API_BASE.
# If using Ollama, ensure you have an embedding model like 'nomic-embed-text' installed ('ollama run nomic-embed-text').
LOCAL_EMBEDDING_API_BASE=http://localhost:1234/v1 # e.g., LM Studio Embedding API
LOCAL_EMBEDDING_MODEL=nomic-ai/nomic-embed-text-v1.5 # e.g., your downloaded Embedding model
```

### 6. Build Your Local Knowledge Base (for Offline RAG)

Place your documents (e.g., survival guides, manuals, Wikipedia exports) into the `./knowledge_base/` directory.
Supported formats: `.txt`, `.md`, `.pdf`.

Each time you add/remove documents, or update the Embedding model, restart `bridge.py` to rebuild the vector database.

## 🎮 Usage

1. Ensure your Meshtastic device is connected via USB and powered on.
2. Ensure your chosen Local LLM (LM Studio or Ollama) server is running.
3. Activate your Python virtual environment: `source venv/bin/activate`
4. Run the bridge: `python3 bridge.py`

Now, send messages to your AI node (e.g., `YourMeshAINode`) from your Meshtastic mobile app. The bridge will intelligently route your query to Gemini (online) or your local LLM (offline), using your local knowledge base when offline.

## 📡 Architecture

This bridge employs a hybrid intelligence architecture:
1. **Meshtastic CLI Listener**: Continuously monitors incoming LoRa messages via `meshtastic --listen`.
2. **Internet Connectivity Check**: Periodically pings a reliable endpoint to determine online/offline status.
3. **Dynamic LLM Dispatch**: 
   - **Online**: Routes queries to Google Gemini API (via `openai` client with `x-goog-api-key` header).
   - **Offline**: Attempts to connect to LM Studio's OpenAI-compatible API, falling back to Ollama if not available.
4. **Local RAG Integration**: In offline mode, queries the `./knowledge_base/` for relevant document snippets using Langchain and local embeddings, injecting this context into the LLM prompt.
5. **Meshtastic Response Sender**: Formats LLM responses for Meshtastic's limited payload size, chunking and paginating long messages, then sends them via `meshtastic --sendtext`.

## 📝 Message Optimization for LoRa

Due to Meshtastic's low bandwidth, optimize your queries:
- **Be Concise**: Ask short, direct questions.
- **Use Keywords**: "Weather [City]", "Manual [Topic]", "Calc [Expression]".
- **Expect Summaries**: LLM responses will be limited to ~200 characters and may be paginated.

## 🔐 Security Considerations

- **Encrypted Communication**: All traffic between the bridge and Google/Local LLM APIs is secured (HTTPS/local IPC).
- **Physical Security**: Your Meshtastic device and local computer should be in a secure location.
- **Local LLM Trust**: Ensure you trust the local LLM models you download, as they run on your machine.

## 🤝 Contributing
Pull requests are welcome!

## 📜 License
MIT
