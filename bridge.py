import os
import sys
import time
import requests
from dotenv import load_dotenv
from pathlib import Path
import json
import subprocess
import threading
import types

# Meshtastic CLI is assumed to be installed in the virtual environment
# import meshtastic.serial_interface
# from meshtastic import util

# --- Load Environment Variables ---
load_dotenv()

# --- Configuration ---
# General
MESHTASTIC_DEVICE_PATH = os.getenv("MESHTASTIC_DEVICE_PATH", "/dev/ttyUSB0") # e.g., /dev/ttyUSB0 on Linux, /dev/cu.usbserial-XXXX on macOS
MESHTASTIC_LONGNAME = os.getenv("MESHTASTIC_LONGNAME", "MeshtasticAI")
LOCALIZATION = os.getenv("LOCALIZATION", "TW")

# Google Gemini API (Online Mode)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL_ONLINE = os.getenv("GEMINI_MODEL_ONLINE", "gemini-1.5-pro-latest") # Use a strong model for online

# Local LLM (Offline Mode) - LM Studio or Ollama
LOCAL_LLM_API_BASE = os.getenv("LOCAL_LLM_API_BASE", "http://localhost:1234/v1") # LM Studio default
LOCAL_LLM_MODEL = os.getenv("LOCAL_LLM_MODEL", "model-name-from-lm-studio-or-ollama")
LOCAL_LLM_OLLAMA_API_BASE = os.getenv("LOCAL_LLM_OLLAMA_API_BASE", "http://localhost:11434/api")
LOCAL_LLM_OLLAMA_MODEL = os.getenv("LOCAL_LLM_OLLAMA_MODEL", "gemma:2b")

processed_alert_ids = set() # 用於儲存已處理過的警報 ID
NCDR_CAP_URL = "https://alerts.ncdr.nat.gov.tw/CAP/Atom.aspx"
ALERT_CHECK_INTERVAL = 60 # 每 60 秒檢查一次警報

# 網路狀態全域變數（需在 check_internet_connection 使用前初始化）
internet_connected = False
last_internet_check = 0.0
ONLINE_CHECK_INTERVAL = 30  # 秒

# LLM 工具宣告（OpenAI function calling 格式）
llm_tools = [
    {
        "type": "function",
        "function": {
            "name": "find_parking",
            "description": "查詢指定座標或地點附近的停車場空位（需要網路）",
            "parameters": {
                "type": "object",
                "properties": {
                    "lat": {"type": "number", "description": "緯度"},
                    "lon": {"type": "number", "description": "經度"},
                    "location_name": {"type": "string", "description": "地點名稱（與座標二擇一）"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "query_surf_spots",
            "description": "查詢台灣衝浪浪點潮汐、風況等資訊",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "浪點名稱或 'all' 列出全部"},
                    "lat": {"type": "number", "description": "緯度（用於搜尋附近浪點）"},
                    "lon": {"type": "number", "description": "經度（用於搜尋附近浪點）"}
                }
            }
        }
    }
]

def fetch_and_broadcast_ncdr_alerts():
    """抓取 NCDR 災害警報並透過 Meshtastic 廣播"""
    if not check_internet_connection():
        return # 離線模式下無法抓取
    
    import feedparser
    print("正在檢查 NCDR 災害警報...")
    try:
        feed = feedparser.parse(NCDR_CAP_URL)
        for entry in feed.entries:
            if entry.id not in processed_alert_ids:
                # 解析 CAP (Common Alerting Protocol) 格式
                severity = getattr(entry, 'cap_severity', '').lower()
                urgency = getattr(entry, 'cap_urgency', '').lower()
                event = getattr(entry, 'cap_event', '未知事件')

                # 只廣播嚴重/緊急的警報
                if severity in ["severe", "extreme"] and urgency in ["immediate", "expected"]:
                    title = getattr(entry, 'title', '無標題')
                    summary = getattr(entry, 'summary', '無摘要')
                    
                    # 格式化成簡短訊息
                    alert_text = f"🚨 緊急警報: [{event}] {title} - {summary}"
                    
                    print(f"偵測到新警報，進行廣播: {alert_text}")
                    send_meshtastic_message(alert_text, destination_id="^all")
                    processed_alert_ids.add(entry.id)
                    time.sleep(5) # 避免短時間內連續廣播
                    
    except Exception as e:
        print(f"抓取 NCDR 警報失敗: {e}", file=sys.stderr)

def alert_checker_thread():
    """背景執行緒，定期檢查警報"""
    while True:
        fetch_and_broadcast_ncdr_alerts()
        time.sleep(ALERT_CHECK_INTERVAL)

# --- Utility Functions ---
MAX_MESHTASTIC_PAYLOAD = 220 # Roughly 220 bytes for plain text on Meshtastic LoRa

def check_internet_connection():
    """檢查是否有網際網路連線"""
    global internet_connected, last_internet_check
    if time.time() - last_internet_check < ONLINE_CHECK_INTERVAL:
        return internet_connected

    try:
        requests.get("http://clients3.google.com/generate_204", timeout=5)
        internet_connected = True
    except requests.ConnectionError:
        internet_connected = False
    finally:
        last_internet_check = time.time()
    return internet_connected

def send_meshtastic_message(text, destination_id=None, reply_id=None):
    """透過 Meshtastic CLI 發送訊息，處理長訊息切分"""
    chunks = [text[i:i+MAX_MESHTASTIC_PAYLOAD] for i in range(0, len(text), MAX_MESHTASTIC_PAYLOAD)]

    for i, chunk in enumerate(chunks):
        cmd = ["meshtastic", "--sendtext", chunk]
        if destination_id:
            cmd.extend(["--dest", destination_id])
        if reply_id:
            cmd.extend(["--replyid", reply_id])
        
        # Add pagination for long messages
        if len(chunks) > 1:
            cmd[2] = f"({i+1}/{len(chunks)}) {chunk}"
        
        print(f"Sending Meshtastic: {' '.join(cmd)}")
        subprocess.run(cmd, capture_output=True, text=True)
        time.sleep(1) # Avoid flooding the mesh

def call_gemini_api_online(prompt, chat_history=None):
    """呼叫 Google Gemini API (在線模式) """
    from openai import OpenAI
    client = OpenAI(api_key=GEMINI_API_KEY, base_url="https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-pro-latest/", default_headers={"x-goog-api-key": GEMINI_API_KEY})
    
    messages = chat_history if chat_history else []
    messages.append({"role": "user", "content": prompt})

    try:
        response = client.chat.completions.create(
            model=GEMINI_MODEL_ONLINE,
            messages=messages,
            tools=llm_tools, # 傳遞工具宣告
            tool_choice="auto", # 讓 Gemini 自行決定是否使用工具
            max_tokens=200, 
            temperature=0.7,
        )
        return response.choices[0].message
    except Exception as e:
        return {"content": f"❌ Gemini API 錯誤: {e}"}

def call_local_llm(prompt, chat_history=None):
    """呼叫本地 LLM (離線模式) - 嘗試 LM Studio, 若失敗則嘗試 Ollama"""
    # 優先使用 LM Studio
    if LOCAL_LLM_API_BASE and LOCAL_LLM_MODEL:
        try:
            from openai import OpenAI
            client = OpenAI(base_url=LOCAL_LLM_API_BASE, api_key="not-needed")
            messages = chat_history if chat_history else []
            messages.append({"role": "user", "content": prompt})

            response = client.chat.completions.create(
                model=LOCAL_LLM_MODEL,
                messages=messages,
                tools=llm_tools,
                tool_choice="auto",
                max_tokens=200,
                temperature=0.7,
            )
            return {"content": f"[LM Studio] {response.choices[0].message.content}"}
        except Exception as e:
            print(f"LM Studio 連線失敗或錯誤: {e}", file=sys.stderr)

    # 其次 Ollama
    if LOCAL_LLM_OLLAMA_API_BASE and LOCAL_LLM_OLLAMA_MODEL:
        try:
            from ollama import Client
            client = Client(host=LOCAL_LLM_OLLAMA_API_BASE)
            messages = chat_history if chat_history else []
            messages.append({'role': 'user', 'content': prompt})

            response = client.chat(
                model=LOCAL_LLM_OLLAMA_MODEL,
                messages=messages,
                tools=llm_tools,
                tool_choice="auto",
                options={'num_predict': 200}
            )
            return {"content": f"[Ollama] {response['message']['content']}"}
        except Exception as e:
            print(f"Ollama 連線失敗或錯誤: {e}", file=sys.stderr)
    
    return {"content": "❌ 無法連線到任何本地 LLM (請檢查 LM Studio/Ollama 是否運行)"}

def execute_llm_tool_call(tool_call, is_online, localization_setting):
    """執行 LLM 的工具調用"""
    tool_name = tool_call.function.name
    tool_args = tool_call.function.arguments
    print(f"LLM 請求執行工具: {tool_name}，參數: {tool_args}")

    script_path = None
    if localization_setting == 'TW':
        if tool_name == "find_parking":
            script_path = Path(__file__).parent / "tools" / "taiwan" / "parking_query.py"
            if not is_online: # 停車查詢需要網路
                return {"tool_output": "❌ 停車查詢需要網路，目前離線無法使用。"}
        elif tool_name == "query_surf_spots":
            script_path = Path(__file__).parent / "tools" / "taiwan" / "surf_query.py"

    if not script_path or not script_path.exists():
        return {"tool_output": f"❌ 找不到工具腳本或工具未配置: {tool_name}"}
    
    cmd = ["python3", str(script_path)]
    for arg, value in tool_args.items():
        cmd.extend([f"--{arg}", str(value)])
    
    # 為衝浪查詢在離線時加上額外參數，讓它知道 CWA API 無法使用
    if tool_name == "query_surf_spots" and not is_online:
        cmd.extend(["--offline-cwa"])

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return {"tool_output": result.stdout}
    except subprocess.CalledProcessError as e:
        return {"tool_output": f"❌ 工具執行錯誤: {e.stderr}"}
    except Exception as e:
        return {"tool_output": f"❌ 工具執行發生未預期錯誤: {e}"}

def get_node_location(node_id_to_find):
    """執行 meshtastic --nodes 並解析輸出，獲取指定節點的 GPS 位置"""
    try:
        result = subprocess.run(["meshtastic", "--nodes"], capture_output=True, text=True, timeout=20)
        if result.returncode != 0:
            return None, "meshtastic --nodes command failed"
        
        lines = result.stdout.strip().split('\n')
        # Find header to locate columns dynamically
        header = [h.strip() for h in lines[0].split('|')]
        try:
            user_col = header.index("User")
            lat_col = header.index("Latitude")
            lon_col = header.index("Longitude")
        except ValueError:
            return None, "Could not parse --nodes header"

        for line in lines[2:]: # Skip header and separator
            cols = [c.strip() for c in line.split('|')]
            if len(cols) > user_col and node_id_to_find in cols[user_col]:
                lat = float(cols[lat_col])
                lon = float(cols[lon_col])
                if lat != 0.0 and lon != 0.0:
                    return (lat, lon), None
        
        return None, "Node not found or has no GPS data"
    except Exception as e:
        return None, str(e)

def _get_content(msg):
    """統一取得 LLM 回傳的文字內容，相容 object 和 dict 格式"""
    if isinstance(msg, dict):
        return msg.get("content", "")
    return getattr(msg, "content", "") or ""

# --- Main Logic ---

def handle_incoming_meshtastic_message(sender_id, text_message):
    """處理收到的 Meshtastic 訊息"""
    global internet_connected

    # --- GPS 感知天氣查詢 (新增功能) ---
    if "weather here" in text_message.lower() or "附近天氣" in text_message:
        print(f"偵測到 GPS 天氣查詢 from {sender_id}")
        (lat, lon), error_msg = get_node_location(sender_id)
        if error_msg:
            send_meshtastic_message(f"❌ 無法獲取您的 GPS 位置: {error_msg}", destination_id=sender_id)
            return

        _tc = types.SimpleNamespace(
            function=types.SimpleNamespace(name="query_surf_spots", arguments={"lat": lat, "lon": lon})
        )
        tool_result = execute_llm_tool_call(
            _tc,
            check_internet_connection(),
            LOCALIZATION
        )
        send_meshtastic_message(tool_result.get("tool_output", "查詢失敗"), destination_id=sender_id)
        return

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

def main_loop():
    print("Meshtastic LLM Bridge 已啟動。正在監聽 Meshtastic 設備...")
    print(f"本地工具路徑: {os.getcwd()}/tools/taiwan/")
    print("請確保您的 Meshtastic 設備已連接並開啟電源。")

    # 創建一個新的線程來處理 Meshtastic 輸出，防止阻塞
    # meshtastic --port <device_path> --setowner <long_name> --info --listen
    # For simplicity, we'll use subprocess.Popen to run meshtastic --listen
    # and parse its stdout.
    meshtastic_cmd = ["meshtastic", "--listen"]
    # Optional: Set owner and longname (only once)
    # meshtastic_setup_cmd = ["meshtastic", "--port", MESHTASTIC_DEVICE_PATH, 
    #                          "--setowner", MESHTASTIC_LONGNAME, "--info"]
    # subprocess.run(meshtastic_setup_cmd)

    process = subprocess.Popen(meshtastic_cmd, stdout=subprocess.PIPE, text=True, bufsize=1, universal_newlines=True)

    for line in process.stdout:
        if "text:" in line and "from:" in line:
            # Example line: "(MeshPacket id=...) from: !d2d2a4e4, text: Hello AI"
            parts = line.split(" ")
            sender_id = None
            message_text = []
            for i, part in enumerate(parts):
                if "from:" in part:
                    sender_id = part.replace("from:", "").replace("!", "").strip(",")
                elif "text:" in part:
                    message_text = parts[i+1:] # Get everything after "text:"
                    break
            
            if sender_id and message_text:
                handle_incoming_meshtastic_message(sender_id, " ".join(message_text).strip())

if __name__ == "__main__":
    # 啟動時先檢查一次網路
    check_internet_connection()
    
    # 在背景啟動警報檢查執行緒
    alert_thread = threading.Thread(target=alert_checker_thread, daemon=True)
    alert_thread.start()
    
    main_loop()
