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

import meshtastic.serial_interface
from pubsub import pub

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
            "name": "find_shelter",
            "description": "查詢指定座標附近的避難收容處所（不需網路，離線可用）",
            "parameters": {
                "type": "object",
                "properties": {
                    "lat": {"type": "number", "description": "緯度"},
                    "lon": {"type": "number", "description": "經度"}
                },
                "required": ["lat", "lon"]
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

# --- Meshtastic Python API 介面 ---
_interface = None
RECONNECT_DELAY_SECONDS = 10

# --- SOS/報平安 Cooldown ---
SOS_COOLDOWN_SECONDS = 60
SAFE_COOLDOWN_SECONDS = 60
_last_sos_ts = {}
_last_safe_ts = {}


def _cooldown_allows(node_id: str, last_ts_map: dict, cooldown_seconds: float) -> bool:
    """若不在 cooldown 內回傳 True 並更新時間戳；仍在 cooldown 內回傳 False 且不更新"""
    now = time.time()
    last = last_ts_map.get(node_id)
    if last is not None and (now - last) < cooldown_seconds:
        return False
    last_ts_map[node_id] = now
    return True


def _match_sos_command(text: str):
    """比對訊息是否為 SOS 指令，回傳附加訊息（可能為空字串）；不符合回傳 None"""
    t = text.strip()
    if len(t) >= 3 and t[:3].upper() == "SOS" and (len(t) == 3 or t[3] == " "):
        return t[3:].strip()
    return None


def _match_safe_command(text: str):
    """比對訊息是否為報平安指令，回傳附加訊息（可能為空字串）；不符合回傳 None"""
    t = text.strip()
    if len(t) >= 4 and t[:4].upper() == "SAFE" and (len(t) == 4 or t[4] == " "):
        return t[4:].strip()
    if t.startswith("平安") and (len(t) == 2 or t[2] in (" ", ":", "：")):
        return t[2:].strip(" :：")
    return None


def _format_emergency_broadcast(kind: str, sender_id: str, location, extra_text: str, timestamp: str) -> str:
    if location is None:
        loc_str = "GPS 位置未知"
    else:
        lat, lon = location
        loc_str = f"{lat:.5f},{lon:.5f}"

    prefix = "🆘 SOS" if kind == "sos" else "✅ 平安回報"
    text = f"{prefix} from {sender_id} @ {loc_str} [{timestamp}]"
    if extra_text:
        text += f" {extra_text}"
    return text


def _handle_emergency_broadcast(kind: str, sender_id: str, extra_text: str):
    """SOS/報平安共用的廣播流程：cooldown 檢查 -> 取 GPS -> 組訊息 -> 廣播"""
    last_ts_map = _last_sos_ts if kind == "sos" else _last_safe_ts
    cooldown = SOS_COOLDOWN_SECONDS if kind == "sos" else SAFE_COOLDOWN_SECONDS

    if not _cooldown_allows(sender_id, last_ts_map, cooldown):
        print(f"{kind.upper()} from {sender_id} 已被 cooldown 抑制（{cooldown} 秒內重複觸發）")
        return

    location, _err = get_node_location(sender_id)
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    broadcast_text = _format_emergency_broadcast(kind, sender_id, location, extra_text, timestamp)

    try:
        if kind == "sos":
            sent = send_meshtastic_alert(broadcast_text, destination_id="^all")
        else:
            sent = send_meshtastic_message(broadcast_text, destination_id="^all")
        if sent:
            print(f"{kind.upper()} 廣播成功: {broadcast_text}")
        else:
            # interface 尚未連線（例如 reconnect window 中），完全沒有嘗試發送，
            # 不能當成功：釋放 cooldown 讓下次可立即重試
            last_ts_map.pop(sender_id, None)
            print(f"❌ {kind.upper()} 廣播失敗：Meshtastic 介面尚未連線", file=sys.stderr)
    except Exception as e:
        last_ts_map.pop(sender_id, None)  # 傳送失敗，釋放 cooldown 讓下次可立即重試
        print(f"❌ {kind.upper()} 廣播失敗: {e}", file=sys.stderr)

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
    """透過 Meshtastic Python API 發送文字訊息，處理長訊息切分

    Returns:
        bool: True 表示已對已連線的 interface 送出（不代表 mesh 上真的送達）；
              False 表示 interface 尚未連線，完全沒有嘗試發送。
    """
    global _interface
    if _interface is None:
        print("❌ 無法發送：Meshtastic 介面尚未連線", file=sys.stderr)
        return False
    chunks = [text[i:i+MAX_MESHTASTIC_PAYLOAD] for i in range(0, len(text), MAX_MESHTASTIC_PAYLOAD)]
    dest = destination_id if destination_id else "^all"

    for i, chunk in enumerate(chunks):
        if len(chunks) > 1:
            chunk = f"({i+1}/{len(chunks)}) {chunk}"

        kwargs = {"destinationId": dest}
        if reply_id:
            kwargs["replyId"] = reply_id

        print(f"Sending Meshtastic text to {dest}: {chunk}")
        _interface.sendText(chunk, **kwargs)
        time.sleep(1)  # Avoid flooding the mesh

    return True


def send_meshtastic_alert(text, destination_id=None):
    """透過 Meshtastic Python API 發送 ALERT_APP 高優先權訊息（不分段，過長截斷，UTF-8 位元組安全）

    Returns:
        bool: True 表示已對已連線的 interface 送出（不代表 mesh 上真的送達）；
              False 表示 interface 尚未連線，完全沒有嘗試發送。
    """
    global _interface
    if _interface is None:
        print("❌ 無法發送：Meshtastic 介面尚未連線", file=sys.stderr)
        return False
    dest = destination_id if destination_id else "^all"
    truncated = text.encode("utf-8")[:MAX_MESHTASTIC_PAYLOAD].decode("utf-8", errors="ignore")
    print(f"Sending Meshtastic ALERT to {dest}: {truncated}")
    _interface.sendAlert(truncated, destinationId=dest)
    return True

def call_gemini_api_online(prompt, chat_history=None):
    """呼叫 Google Gemini API (在線模式) """
    from openai import OpenAI
    client = OpenAI(api_key=GEMINI_API_KEY, base_url="https://generativelanguage.googleapis.com/v1beta/openai/", default_headers={"x-goog-api-key": GEMINI_API_KEY})
    
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
    if isinstance(tool_args, str):
        tool_args = json.loads(tool_args)
    print(f"LLM 請求執行工具: {tool_name}，參數: {tool_args}")

    script_path = None
    if localization_setting == 'TW':
        if tool_name == "find_shelter":
            script_path = Path(__file__).parent / "tools" / "taiwan" / "shelter_query.py"

    if not script_path or not script_path.exists():
        return {"tool_output": f"❌ 找不到工具腳本或工具未配置: {tool_name}"}

    cmd = ["python3", str(script_path)]
    for arg, value in tool_args.items():
        cmd.extend([f"--{arg}", str(value)])

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return {"tool_output": result.stdout}
    except subprocess.CalledProcessError as e:
        return {"tool_output": f"❌ 工具執行錯誤: {e.stderr}"}
    except Exception as e:
        return {"tool_output": f"❌ 工具執行發生未預期錯誤: {e}"}

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


def get_node_location(node_id_to_find):
    """從 interface.nodes 讀取指定節點的 GPS 位置"""
    global _interface
    if _interface is None:
        return None, "Meshtastic interface not connected"

    node_id = node_id_to_find if node_id_to_find.startswith("!") else f"!{node_id_to_find}"
    node = _interface.nodes.get(node_id)
    if not node:
        return None, "Node not found or has no GPS data"

    position = node.get("position", {})
    lat = position.get("latitude")
    lon = position.get("longitude")
    if lat is None or lon is None or (lat == 0.0 and lon == 0.0):
        return None, "Node not found or has no GPS data"

    return (lat, lon), None

def _on_receive(packet, interface):
    """pypubsub callback：收到 Meshtastic 文字訊息時觸發"""
    try:
        decoded = packet.get("decoded", {})
        text = decoded.get("text")
        sender_id = packet.get("fromId")
        if text and sender_id:
            handle_incoming_meshtastic_message(sender_id, text)
    except Exception as e:
        print(f"處理收到訊息時發生錯誤: {e}", file=sys.stderr)

def _get_content(msg):
    """統一取得 LLM 回傳的文字內容，相容 object 和 dict 格式"""
    if isinstance(msg, dict):
        return msg.get("content", "")
    return getattr(msg, "content", "") or ""

# --- Main Logic ---

def handle_incoming_meshtastic_message(sender_id, text_message):
    """處理收到的 Meshtastic 訊息"""
    global internet_connected

    sos_extra = _match_sos_command(text_message)
    if sos_extra is not None:
        _handle_emergency_broadcast("sos", sender_id, sos_extra)
        return

    safe_extra = _match_safe_command(text_message)
    if safe_extra is not None:
        _handle_emergency_broadcast("safe", sender_id, safe_extra)
        return

    # --- GPS 感知天氣查詢 ---
    if "weather here" in text_message.lower() or "附近天氣" in text_message:
        print(f"偵測到 GPS 天氣查詢 from {sender_id}")
        location, error_msg = get_node_location(sender_id)
        if error_msg:
            send_meshtastic_message(f"❌ 無法獲取您的 GPS 位置: {error_msg}", destination_id=sender_id)
            return
        lat, lon = location

        weather_script = Path(__file__).parent / "tools" / "taiwan" / "weather_query.py"
        try:
            result = subprocess.run(
                ["python3", str(weather_script), "--lat", str(lat), "--lon", str(lon)],
                capture_output=True, text=True, check=True,
            )
            send_meshtastic_message(result.stdout, destination_id=sender_id)
        except Exception as e:
            send_meshtastic_message(f"❌ 天氣查詢失敗: {e}", destination_id=sender_id)
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

def _connect_with_retry():
    """持續嘗試連線 Meshtastic 裝置，成功前不返回"""
    global _interface
    while True:
        try:
            _interface = meshtastic.serial_interface.SerialInterface(devPath=MESHTASTIC_DEVICE_PATH)
            print("Meshtastic 介面已連線。")
            return
        except Exception as e:
            print(f"連線 Meshtastic 裝置失敗: {e}，{RECONNECT_DELAY_SECONDS} 秒後重試", file=sys.stderr)
            time.sleep(RECONNECT_DELAY_SECONDS)


def _reconnect():
    """關閉舊連線並重新連線，供 _on_connection_lost 在背景執行緒呼叫"""
    global _interface
    if _interface is not None:
        try:
            _interface.close()
        except Exception as e:
            print(f"關閉舊連線時發生錯誤（忽略，繼續重連）: {e}", file=sys.stderr)
    _interface = None
    _connect_with_retry()


def _on_connection_lost(interface):
    """pypubsub callback：偵測到 Meshtastic 連線中斷時觸發"""
    print("偵測到 Meshtastic 連線中斷，背景執行緒進行重新連線...", file=sys.stderr)
    threading.Thread(target=_reconnect, daemon=True).start()


def main_loop():
    print("Meshtastic LLM Bridge 已啟動（Python API 模式）。正在連線 Meshtastic 裝置...")
    print(f"本地工具路徑: {os.getcwd()}/tools/taiwan/")

    pub.subscribe(_on_receive, "meshtastic.receive.text")
    pub.subscribe(_on_connection_lost, "meshtastic.connection.lost")
    _connect_with_retry()

    while True:
        time.sleep(3600)

if __name__ == "__main__":
    # 啟動時先檢查一次網路
    check_internet_connection()
    
    # 在背景啟動警報檢查執行緒
    alert_thread = threading.Thread(target=alert_checker_thread, daemon=True)
    alert_thread.start()
    
    main_loop()
