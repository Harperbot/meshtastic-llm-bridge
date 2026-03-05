import os
import sys
import time
import requests
from dotenv import load_dotenv
from pathlib import Path
import json
import subprocess
import threading

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

# --- Global State ---
internet_connected = False
last_internet_check = 0
ONLINE_CHECK_INTERVAL = 60 # Check internet every 60 seconds

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

def call_gemini_api_online(prompt):
    """呼叫 Google Gemini API (在線模式) """
    from openai import OpenAI # Gemini API is compatible with OpenAI client
    client = OpenAI(api_key=GEMINI_API_KEY, base_url="https://generativelanguage.googleapis.com/v1beta/models/", default_headers={"x-goog-api-key": GEMINI_API_KEY})
    
    try:
        # TODO: Add tool_choice and function_call support
        response = client.chat.completions.create(
            model=GEMINI_MODEL_ONLINE,
            messages=[
                {"role": "user", "content": prompt}
            ],
            max_tokens=200, # Limit response for Meshtastic
            temperature=0.7,
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"❌ Gemini API 錯誤: {e}"

def call_local_llm(prompt):
    """呼叫本地 LLM (離線模式) - 嘗試 LM Studio, 若失敗則嘗試 Ollama"""
    # --- 嘗試 LM Studio --- #
    if LOCAL_LLM_API_BASE and LOCAL_LLM_MODEL:
        try:
            from openai import OpenAI
            client = OpenAI(base_url=LOCAL_LLM_API_BASE, api_key="not-needed") # LM Studio doesn't need API key
            response = client.chat.completions.create(
                model=LOCAL_LLM_MODEL,
                messages=[
                    {"role": "user", "content": prompt}
                ],
                max_tokens=200, # Limit response for Meshtastic
                temperature=0.7,
            )
            return f"[LM Studio] {response.choices[0].message.content}"
        except Exception as e:
            print(f"LM Studio 連線失敗或錯誤: {e}", file=sys.stderr)

    # --- 嘗試 Ollama --- #
    if LOCAL_LLM_OLLAMA_API_BASE and LOCAL_LLM_OLLAMA_MODEL:
        try:
            from ollama import Client
            client = Client(host=LOCAL_LLM_OLLAMA_API_BASE)
            response = client.chat(
                model=LOCAL_LLM_OLLAMA_MODEL,
                messages=[
                    {'role': 'user', 'content': prompt}
                ],
                options={'num_predict': 200} # Limit response for Meshtastic
            )
            return f"[Ollama] {response['message']['content']}"
        except Exception as e:
            print(f"Ollama 連線失敗或錯誤: {e}", file=sys.stderr)
    
    return "❌ 無法連線到任何本地 LLM (請檢查 LM Studio/Ollama 是否運行)"

# --- Main Logic ---

def handle_incoming_meshtastic_message(sender_id, text_message):
    global internet_connected

    # 1. 檢查網路狀態
    internet_status = "🟢 Online" if check_internet_connection() else "🔴 Offline"
    print(f"處理來自 {sender_id} 的訊息: '{text_message}' - 網路狀態: {internet_status}")

    response_text = ""
    prompt = text_message
    
    # --- 本地知識庫 (RAG) 處理 (新增功能) ---
    rag_context = ""
    if not internet_connected: # 只有離線時才進行本地 RAG
        print("離線模式下，進行本地知識庫檢索...")
        try:
            from langchain_community.document_loaders import TextLoader, PyPDFLoader, UnstructuredMarkdownLoader
            from langchain.text_splitter import RecursiveCharacterTextSplitter
            from langchain_community.embeddings import OllamaEmbeddings, OpenAIEmbeddings # For LM Studio/Ollama
            from langchain.vectorstores import Chroma
            
            KB_DIR = Path(__file__).parent / "knowledge_base"
            if not KB_DIR.exists() or not any(KB_DIR.iterdir()):
                rag_context = "[本地知識庫為空，無法檢索]"
            else:
                documents = []
                for f_path in KB_DIR.iterdir():
                    if f_path.suffix == ".txt":
                        loader = TextLoader(str(f_path))
                    elif f_path.suffix == ".md":
                        loader = UnstructuredMarkdownLoader(str(f_path))
                    elif f_path.suffix == ".pdf":
                        loader = PyPDFLoader(str(f_path))
                    else:
                        continue
                    documents.extend(loader.load())

                text_splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
                texts = text_splitter.split_documents(documents)

                # 選擇 Embedding 模型
                embeddings = None
                if LOCAL_LLM_API_BASE and LOCAL_LLM_MODEL: # 優先使用 LM Studio 的 OpenAI 相容 Embedding
                    embeddings = OpenAIEmbeddings(base_url=LOCAL_LLM_API_BASE, api_key="not-needed", model=LOCAL_LLM_MODEL)
                elif LOCAL_LLM_OLLAMA_API_BASE and LOCAL_LLM_OLLAMA_MODEL: # 其次 Ollama
                    embeddings = OllamaEmbeddings(base_url=LOCAL_LLM_OLLAMA_API_BASE, model=LOCAL_LLM_OLLAMA_MODEL)
                
                if embeddings:
                    vectorstore = Chroma.from_documents(texts, embeddings, persist_directory=str(KB_DIR / "chroma_db"))
                    retriever = vectorstore.as_retriever()
                    
                    # 執行檢索
                    retrieved_docs = retriever.invoke(prompt)
                    rag_context = "\n\n[本地資料參考]\n" + "\n---\n".join([doc.page_content for doc in retrieved_docs[:2]]) # 取前2個相關文檔
                else:
                    rag_context = "[未設定 Embedding 模型，無法進行 RAG]"
        except ImportError:
            rag_context = "[缺少 Langchain RAG 相關套件，請安裝：pip install langchain-community pypdf unstructured openai ollama chromadb]
"        except Exception as e:
            rag_context = f"[本地知識庫檢索錯誤: {e}]"

    # 2. 根據網路狀態選擇 LLM
    if internet_connected:
        print("使用 Google Gemini API (在線模式)...")
        # 在線模式，Gemini 會自行處理搜尋
        response_text = call_gemini_api_online(prompt)
    else:
        print("使用本地 LLM (離線模式)...")
        # 將檢索到的上下文加入 prompt
        llm_prompt = f"{prompt}\n\n{rag_context}"
        response_text = call_local_llm(llm_prompt)
    
    # 3. 發送回覆 (處理長度限制)
    send_meshtastic_message(f"AI: {response_text}", destination_id=sender_id)

def main_loop():
    print("Meshtastic LLM Bridge 已啟動。正在監聽 Meshtastic 設備...
")
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
    main_loop()
