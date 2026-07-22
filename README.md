# Meshtastic-LLM Bridge 📡🧠

[繁體中文](README.zh-TW.md) | English

A resilient, standalone Python bridge connecting your Meshtastic device to powerful Large Language Models (LLMs). This project is designed for **"apocalypse-grade" off-grid communication**, allowing you to interact with AI even when the internet is down.

It intelligently switches between online (Google Gemini) and offline (Local LLMs like LM Studio or Ollama) modes, providing robust AI assistance in any scenario.

---

## ✨ Features

- **Dual-Mode LLM Integration**: Automatically detects internet connectivity.
  - **Online Mode**: Connects to Google Gemini API for powerful, internet-enabled AI responses.
  - **Offline Mode**: Seamlessly switches to local LLMs (LM Studio or Ollama) for off-grid AI capabilities.
- **GPS-Aware Weather Queries**: Send a simple command like `"weather here"` from your device, and the bridge will automatically use your node's GPS location to fetch the local weather forecast. No manual coordinates needed!
- **Government Alert Broadcast**: In online mode, the bridge actively monitors Taiwan's NCDR (National Science and Technology Center for Disaster Reduction) CAP feed. If a severe alert (earthquake, typhoon, air raid, etc.) is issued, it will be automatically broadcast to all devices on the mesh network (`^all`).
- **Robust LLM Response Handling**: Compatible with both object-style and dict-style LLM responses via unified `_get_content()` helper, ensuring stability across different OpenAI-compatible backends.
- **Meshtastic Communication**: Uses the Meshtastic Python API (`meshtastic.serial_interface.SerialInterface`) directly, subscribing to incoming messages via `pypubsub` and sending with `sendText`/`sendAlert`. Automatically detects and recovers from serial disconnects in the background.
- **Message Chunking & Pagination**: Automatically splits long LLM responses into multiple Meshtastic packets with pagination (`(1/3)`) due to LoRa's limited payload size.
- **Resource Optimization**: Designed for low-bandwidth, low-power Meshtastic networks.
- **Easy Setup**: Runs as a standalone Python script with `.env` configuration.

### Disaster Info Tools

- **Shelter Finder**: Ask about nearby emergency shelters (`find_shelter` LLM tool), backed by Taiwan's National Fire Agency shelter dataset (works offline, no internet required)
- **SOS Broadcast**: Send `SOS` (optionally followed by a message, e.g. `SOS trapped on 2nd floor`) to broadcast your GPS location and timestamp to the entire mesh via Meshtastic's `ALERT_APP` priority channel. Rate-limited to once per 60 seconds per node to prevent accidental flooding.
- **Safety Check-in**: Send `SAFE` or `平安` (optionally with a message) to broadcast that you're safe, same rate-limiting applies.

## 💡 Why this project?

Most LLM solutions rely entirely on internet connectivity. **Meshtastic-LLM Bridge** offers unparalleled resilience:
- **True Off-Grid AI**: Ensures you always have access to AI assistance, even in emergencies or remote locations without internet.
- **Hybrid Intelligence**: Leverages the best of both worlds: powerful cloud LLMs when online, and robust local LLMs when offline.
- **Open Source & Customizable**: A foundation for building your own specialized off-grid AI applications.

## 🖥️ System Requirements

- **OS**: Linux, macOS, or Windows (via WSL2).
- **Python**: v3.9 or higher.
- **Meshtastic Device**: A working Meshtastic device connected via USB (or configurable for TCP/IP).
- **Local LLM**: (Essential for offline chat and reasoning)
  - **LM Studio** ([lmstudio.ai](https://lmstudio.ai/)): Recommended for ease of use (GUI). Download a **chat model**, then start the local server.
  - **Ollama** ([ollama.ai](https://ollama.ai/)): Command-line friendly. Install a **chat model** (e.g., `ollama run gemma:2b`). Ensure the Ollama server is running.

## 🔑 Account & Key Requirements

### Mandatory
- **Google AI Studio**: Obtain your [Gemini API Key](https://aistudio.google.com/app/apikey) for online mode (free tier available).

### Optional (for local tools / specialized functions)
- **CWA Open Data**: For weather forecasts in Taiwan.

## 🚀 Installation

### 1. Clone the repository
```bash
git clone https://github.com/Harperbot/meshtastic-llm-bridge.git
cd meshtastic-llm-bridge
```

### 2. Prepare Python Environment
```bash
# Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate

# Install Python dependencies
pip install meshtastic[cli] requests python-dotenv openai ollama feedparser pytest
```

### 3. Meshtastic Device Setup
- Connect your Meshtastic device via USB.
- Find its path: `meshtastic --info` (e.g., `/dev/cu.usbserial-0001` on macOS, `/dev/ttyUSB0` on Linux).

### 4. Local LLM Setup (for Offline Mode)

#### Option A: LM Studio (Recommended for Beginners)
1. Download and install [LM Studio](https://lmstudio.ai/).
2. In LM Studio, download your preferred LLM (e.g., `Nexusflow/Starling-LM-7B-beta-GGUF`).
3. Go to the "Local Server" tab and click "Start Server". Ensure it's running on `http://localhost:1234/v1`.

#### Option B: Ollama
1. Download and install [Ollama](https://ollama.ai/).
2. Download your preferred LLM (e.g., `ollama run gemma:2b`).
3. Ensure the Ollama server is running (usually automatic after `ollama run`).

### 5. Configure Environment Variables

Create a `.env` file in the project root with:

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

## 🎮 Usage

1. Ensure your Meshtastic device is connected via USB and powered on.
2. Ensure your chosen Local LLM (LM Studio or Ollama) server is running.
3. Activate your Python virtual environment: `source venv/bin/activate`
4. Run the bridge: `python3 bridge.py`

Now, send messages to your AI node (e.g., `YourMeshAINode`) from your Meshtastic mobile app. The bridge will intelligently route your query to Gemini (online) or your local LLM (offline).

## 📡 Architecture

This bridge employs a hybrid intelligence architecture:
1. **Meshtastic Python API Listener**: Opens a persistent `SerialInterface` connection to the radio and subscribes to `meshtastic.receive.text` via `pypubsub`, so incoming LoRa messages are delivered directly to the bridge process (no CLI subprocess involved). A separate `meshtastic.connection.lost` subscription triggers automatic background reconnection if the serial link drops.
2. **Internet Connectivity Check**: Periodically pings a reliable endpoint to determine online/offline status.
3. **Dynamic LLM Dispatch**: 
   - **Online**: Routes queries to Google Gemini API (via `openai` client with `x-goog-api-key` header).
   - **Offline**: Attempts to connect to LM Studio's OpenAI-compatible API, falling back to Ollama if not available.
4. **Meshtastic Response Sender**: Formats LLM responses for Meshtastic's limited payload size, chunking and paginating long messages, then sends them via `interface.sendText()` (or `interface.sendAlert()` for high-priority SOS/alert broadcasts).

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
