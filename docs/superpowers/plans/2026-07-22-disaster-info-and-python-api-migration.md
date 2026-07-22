# Python API 遷移 + 避難點/SOS/報平安 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `meshtastic-llm-bridge` 從 subprocess+CLI-parsing 遷移到官方 Python API，並在此基礎上新增避難點查詢、SOS 求救廣播、報平安廣播，取代已淘汰的停車場/浪點查詢功能。

**Architecture:** `bridge.py` 收發層改用 `meshtastic.serial_interface.SerialInterface()` + pypubsub 事件模型（不再 parse CLI stdout）；新增 threaded 斷線重連；新功能建在這層之上：避難點查詢走既有 LLM function-calling 模式，SOS 用官方 `ALERT_APP`（`sendAlert()`），報平安用一般文字廣播，兩者皆有 per-node cooldown 防洗版。

**Tech Stack:** Python 3.14、`meshtastic` 2.7.8（已安裝於 venv，pypubsub 4.0.7 隨附）、pytest（需新裝）、`requests`（CWA 開放資料）。

## Global Constraints

- 所有 subprocess 呼叫 `meshtastic` CLI 的地方最終都要換成 `SerialInterface` Python API 呼叫（本次唯一保留的 subprocess 用法：呼叫 `tools/taiwan/*.py` 獨立工具腳本本身，那是既有架構模式，不在遷移範圍）
- `MAX_MESHTASTIC_PAYLOAD = 220`（bytes）維持不變，長訊息切分邏輯保留
- SOS 用 `interface.sendAlert()`（`ALERT_APP`/`Priority.ALERT`），報平安用 `interface.sendText()`（一般文字），兩者都廣播到 `destinationId="^all"`
- SOS/報平安 cooldown 各自 60 秒（`SOS_COOLDOWN_SECONDS` / `SAFE_COOLDOWN_SECONDS`），per-node 獨立計時，兩種訊息類型的計時器互不共用
- 新增/改動的程式碼都要有對應單元測試；不要求整專案覆蓋率
- 每個 Task 完成後 `git commit`（訊息用 conventional commits 格式，繁體中文本文 + 英文 type 前綴）
- 這是本地 git repo，已接 `origin` = `https://github.com/Harperbot/meshtastic-llm-bridge`（公開），但**本次計畫的所有 commit 先留在本機，等全部 Task 完成才一次 push**（user 已明確表示）

---

## 前置：測試環境準備

`venv/bin/python3 -m pytest` 目前不存在，需先安裝：

```bash
cd ~/ai-projects/projects/meshtastic-llm-bridge
venv/bin/pip install pytest
```

建立 `tests/conftest.py` 讓測試能 import `bridge.py` 與 `tools/taiwan/*.py`（目前都不是套件，靠 `sys.path` 插入）：

**Files:**
- Create: `tests/conftest.py`

```python
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "taiwan"))
```

這個檔案在 Task 1 一起建立並 commit（不需要獨立 Task，屬於測試基礎設施）。

---

### Task 1: 抽出共用 `geo_utils.py`（haversine）

**複雜度：低。Critic：R1 一輪。**

**Files:**
- Create: `tools/taiwan/geo_utils.py`
- Create: `tests/conftest.py`（見上方前置章節內容）
- Test: `tests/test_geo_utils.py`

**Interfaces:**
- Produces: `geo_utils.haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float`（回傳公尺），供 Task 3/4/9 使用

- [ ] **Step 1: 安裝 pytest 並建立 conftest**

```bash
cd ~/ai-projects/projects/meshtastic-llm-bridge
venv/bin/pip install pytest
mkdir -p tests
```

Create `tests/conftest.py`:

```python
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "taiwan"))
```

- [ ] **Step 2: 寫失敗測試**

Create `tests/test_geo_utils.py`:

```python
import math

from geo_utils import haversine


def test_haversine_zero_distance_same_point():
    assert haversine(25.033, 121.565, 25.033, 121.565) == 0.0


def test_haversine_equator_one_degree():
    # 赤道上經度差 1 度的弧長有精確解析解: R * radians(1)
    expected = 6371000 * math.radians(1)
    result = haversine(0.0, 0.0, 0.0, 1.0)
    assert abs(result - expected) < 1.0  # 誤差 1 公尺內
```

- [ ] **Step 3: 執行測試確認失敗**

Run: `cd ~/ai-projects/projects/meshtastic-llm-bridge && venv/bin/python3 -m pytest tests/test_geo_utils.py -v`
Expected: FAIL，錯誤訊息 `ModuleNotFoundError: No module named 'geo_utils'`

- [ ] **Step 4: 寫最小實作**

Create `tools/taiwan/geo_utils.py`:

```python
"""共用地理計算工具"""
import math


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """計算兩經緯度座標間的球面距離（公尺）"""
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
```

- [ ] **Step 5: 執行測試確認通過**

Run: `venv/bin/python3 -m pytest tests/test_geo_utils.py -v`
Expected: 2 passed

- [ ] **Step 6: Commit**

```bash
git add tests/conftest.py tests/test_geo_utils.py tools/taiwan/geo_utils.py
git commit -m "feat: add shared geo_utils.haversine + test scaffold"
```

---

### Task 2: 抽出獨立 `weather_query.py`（縣市風況/天氣+颱風警報）

**複雜度：中。Critic：R1 一輪。**

**背景**：現有「weather here」功能透過假造的 `query_surf_spots` tool call 找最近衝浪浪點、再顯示該浪點所在縣市的天氣——但 `tools/taiwan/taiwan_surf_spots.json` 這個浪點資料庫檔案在 repo 裡從未存在過（`git log --all -- "*taiwan_surf_spots*"` 無結果），所以這個功能目前是完全壞的（`load_spots()` 會拋 `FileNotFoundError`）。這次抽出後會修好它，且不再依賴浪點資料。潮汐（tide）功能綁在個別浪點的測站 ID 上無法泛化，本次不保留。

**Files:**
- Create: `tools/taiwan/weather_query.py`
- Test: `tests/test_weather_query.py`

**Interfaces:**
- Produces: `weather_query.detect_county(lat, lon) -> str | None`、`weather_query.format_weather(county, wind, typhoon) -> str`，供 Task 5（bridge.py 接線）使用

- [ ] **Step 1: 寫失敗測試**

Create `tests/test_weather_query.py`:

```python
import weather_query


def test_detect_county_taipei():
    assert weather_query.detect_county(25.033, 121.564) == "臺北市"


def test_detect_county_out_of_taiwan_range():
    assert weather_query.detect_county(0.0, 0.0) is None


def test_format_weather_without_api_key(monkeypatch):
    monkeypatch.setattr(weather_query, "get_cwa_key", lambda: None)
    result = weather_query.format_weather("臺北市", None, None)
    assert "CWA_API_KEY" in result


def test_format_weather_with_wind_data(monkeypatch):
    monkeypatch.setattr(weather_query, "get_cwa_key", lambda: "fake-key")
    wind = {"wind_dir": "東北風", "beaufort": "3", "wind_speed": "5.2", "weather": "多雲"}
    result = weather_query.format_weather("臺北市", wind, None)
    assert "東北風" in result
    assert "多雲" in result


def test_format_weather_includes_typhoon_when_present(monkeypatch):
    monkeypatch.setattr(weather_query, "get_cwa_key", lambda: "fake-key")
    result = weather_query.format_weather("臺北市", None, "🌀 颱風 測試颱風｜距台灣 500km")
    assert "測試颱風" in result
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `venv/bin/python3 -m pytest tests/test_weather_query.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'weather_query'`

- [ ] **Step 3: 寫最小實作**

Create `tools/taiwan/weather_query.py`:

```python
#!/usr/bin/env python3
"""縣市天氣/風況/颱風警報查詢 — 依 GPS 座標對應所在縣市，查詢 CWA 開放資料
用法: weather_query.py --lat 25.033 --lon 121.564
"""
import argparse
import os
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from geo_utils import haversine

CWA_BASE = "https://opendata.cwa.gov.tw/api/v1/rest/datastore"

# 縣市邊界框 (中文名稱, lat_min, lat_max, lon_min, lon_max)
# 較小/精確的城市放前面，避免被大城市邊界框吞掉
COUNTIES = [
    ("基隆市", 25.06, 25.22, 121.62, 121.83),
    ("新竹市", 24.76, 24.87, 120.92, 121.07),
    ("嘉義市", 23.43, 23.52, 120.39, 120.54),
    ("臺北市", 24.96, 25.21, 121.50, 121.67),
    ("桃園市", 24.55, 25.08, 120.97, 121.46),
    ("臺中市", 24.01, 24.43, 120.51, 121.10),
    ("臺南市", 22.84, 23.48, 120.06, 120.78),
    ("高雄市", 22.44, 23.16, 120.24, 120.73),
    ("新北市", 24.59, 25.30, 121.20, 122.03),
    ("新竹縣", 24.44, 25.06, 120.78, 121.42),
    ("苗栗縣", 24.10, 24.70, 120.63, 121.25),
    ("彰化縣", 23.82, 24.18, 120.32, 120.73),
    ("南投縣", 23.50, 24.25, 120.52, 121.47),
    ("雲林縣", 23.50, 23.82, 120.10, 120.73),
    ("嘉義縣", 23.14, 23.72, 120.10, 120.89),
    ("屏東縣", 21.90, 22.84, 120.42, 121.00),
    ("宜蘭縣", 24.30, 24.99, 121.39, 121.97),
    ("花蓮縣", 23.16, 24.47, 121.24, 121.86),
    ("臺東縣", 22.22, 23.16, 120.74, 121.52),
]


def detect_county(lat: float, lon: float) -> str | None:
    """依經緯度邊界框判斷所在縣市"""
    for name, lat_min, lat_max, lon_min, lon_max in COUNTIES:
        if lat_min <= lat <= lat_max and lon_min <= lon <= lon_max:
            return name
    return None


def get_cwa_key() -> str | None:
    return os.environ.get("CWA_API_KEY")


def cwa_get(dataset: str, params: dict) -> dict | None:
    key = get_cwa_key()
    if not key:
        return None
    try:
        params = dict(params)
        params["Authorization"] = key
        r = requests.get(f"{CWA_BASE}/{dataset}", params=params, timeout=8)
        d = r.json()
        return d if d.get("success") == "true" else None
    except Exception:
        return None


def get_wind_weather(county: str) -> dict | None:
    """查縣市風速/風向/天氣現象"""
    data = cwa_get("F-D0047-091", {"elementName": "WindSpeed,WindDirection,Weather"})
    if not data:
        return None
    try:
        for lg in data["records"]["Locations"]:
            for loc in lg["Location"]:
                if county in loc["LocationName"] or loc["LocationName"] in county:
                    result = {}
                    for el in loc["WeatherElement"]:
                        t0 = el["Time"][0]
                        val = t0.get("ElementValue", [])
                        name = el["ElementName"]
                        if name == "風速" and val:
                            result["wind_speed"] = val[0].get("WindSpeed", "")
                            result["beaufort"] = val[0].get("BeaufortScale", "")
                        elif name == "風向" and val:
                            result["wind_dir"] = val[0].get("WindDirection", "")
                        elif name == "天氣現象" and val:
                            result["weather"] = val[0].get("Weather", "")
                    return result if result else None
    except Exception:
        pass
    return None


def get_typhoon_info() -> str | None:
    """回傳目前活動颱風資訊。無颱風/距台灣遠回 None"""
    data = cwa_get("W-C0034-005", {})
    if not data:
        return None
    try:
        cyclones = data["records"]["TropicalCyclones"]["TropicalCyclone"]
        alerts = []
        for tc in cyclones:
            name_zh = tc.get("CwaTyphoonName", "") or tc.get("TyphoonName", "")
            ty_no = tc.get("CwaTyNo", "")
            fixes = tc.get("AnalysisData", {}).get("Fix", [])
            if isinstance(fixes, dict):
                fixes = [fixes]
            if not fixes:
                continue
            last = fixes[-1]
            lat = float(last.get("CoordinateLatitude", 0))
            lon = float(last.get("CoordinateLongitude", 0))
            max_wind = last.get("MaxWindSpeed", "")
            direction = last.get("MovingDirection", "")
            speed = last.get("MovingSpeed", "")
            dist_km = haversine(lat, lon, 23.5, 121.0) / 1000
            intensity, emoji = ("颱風", "🌀") if ty_no else ("熱帶低壓", "🌬️")
            if dist_km < 2000:
                alerts.append(
                    f"{emoji} {intensity} {name_zh}｜距台灣 {dist_km:.0f}km｜"
                    f"最大風速 {max_wind}m/s｜往{direction}移動 {speed}km/h"
                )
        return "\n".join(alerts) if alerts else None
    except Exception:
        return None


def format_weather(county: str, wind: dict | None, typhoon: str | None) -> str:
    lines = [f"📍 {county} 天氣狀況"]
    if not get_cwa_key():
        lines.append("⚠️ 即時天氣數據未設定（需要 CWA_API_KEY 環境變數）")
    elif wind is None:
        lines.append("⚠️ 目前無法取得該縣市天氣資料")
    else:
        wind_dir = wind.get("wind_dir", "未知")
        beaufort = wind.get("beaufort", "")
        speed = wind.get("wind_speed", "")
        weather = wind.get("weather", "")
        lines.append(f"💨 風況：{wind_dir} {beaufort}級（{speed}m/s）")
        if weather:
            lines.append(f"⛅ 天氣：{weather}")
    if typhoon:
        lines.append(typhoon)
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="縣市天氣/風況/颱風警報查詢")
    parser.add_argument("--lat", type=float, required=True)
    parser.add_argument("--lon", type=float, required=True)
    args = parser.parse_args()

    county = detect_county(args.lat, args.lon)
    if not county:
        print("⚠️ 無法辨識座標所在縣市（可能超出台灣本島範圍）")
        return

    wind = get_wind_weather(county)
    typhoon = get_typhoon_info()
    print(format_weather(county, wind, typhoon))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 執行測試確認通過**

Run: `venv/bin/python3 -m pytest tests/test_weather_query.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add tools/taiwan/weather_query.py tests/test_weather_query.py
git commit -m "feat: extract standalone weather_query.py (fixes broken weather-here feature)"
```

---

### Task 3: 避難收容處所 ETL（`fetch_shelters.py`）

**複雜度：低。Critic：R1 一輪。**

**資料來源確認**（已實測）：消防署「避難收容處所點位檔」直接下載 URL（data.gov.tw dataset 73242 的 resourceDownloadUrl，已驗證回應 200、UTF-8 with BOM CSV、5973 筆資料）：
`https://opdadm.moi.gov.tw/api/v1/no-auth/resource/api/dataset/ED6CF735-6C03-4573-A882-72C1BEC799CB/resource/54550E2F-4567-4C8F-BD2E-E54E9D0386B8/download`

欄位（已實測確認）：`序號,縣市及鄉鎮市區,村里,避難收容處所地址,經度,緯度,避難收容處所名稱,預計收容村里,預計收容人數,適用災害類別,管理人姓名,管理人電話,室內,室外,適合避難弱者安置`

**Files:**
- Create: `tools/taiwan/fetch_shelters.py`
- Test: `tests/test_fetch_shelters.py`

**Interfaces:**
- Produces: `fetch_shelters.parse_csv_rows(csv_text: str) -> list[dict]`，每個 dict 含 `name/address/city_district/village/lat/lon/capacity/disaster_types`，供 Task 4 讀取的 `shelters.json` 使用相同 schema

- [ ] **Step 1: 寫失敗測試**

Create `tests/test_fetch_shelters.py`:

```python
import json

import fetch_shelters

SAMPLE_CSV = (
    "序號,縣市及鄉鎮市區,村里,避難收容處所地址,經度,緯度,避難收容處所名稱,"
    "預計收容村里,預計收容人數,適用災害類別,管理人姓名,管理人電話,室內,室外,適合避難弱者安置\n"
    "1,新竹縣,,,121.073,24.386,五峰活動中心,大隘村,110,\"水災,震災\",張兒,03-5851001,是,否,是\n"
    "2,金門縣,林湖村,東林24號,,,林湖村辦公處,林湖村,30,\"水災\",林妙玲,082-364503,是,否,是\n"
)


def test_parse_csv_rows_skips_missing_coordinates():
    shelters = fetch_shelters.parse_csv_rows(SAMPLE_CSV)
    assert len(shelters) == 1
    assert shelters[0]["name"] == "五峰活動中心"
    assert shelters[0]["lat"] == 24.386
    assert shelters[0]["lon"] == 121.073
    assert shelters[0]["capacity"] == "110"


def test_main_creates_json_from_source_csv(tmp_path, monkeypatch):
    csv_path = tmp_path / "sample.csv"
    csv_path.write_text(SAMPLE_CSV, encoding="utf-8")
    output_path = tmp_path / "shelters.json"

    monkeypatch.setattr(
        "sys.argv",
        ["fetch_shelters.py", "--source-csv", str(csv_path), "--output", str(output_path)],
    )
    fetch_shelters.main()

    data = json.loads(output_path.read_text(encoding="utf-8"))
    assert len(data["shelters"]) == 1
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `venv/bin/python3 -m pytest tests/test_fetch_shelters.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'fetch_shelters'`

- [ ] **Step 3: 寫最小實作**

Create `tools/taiwan/fetch_shelters.py`:

```python
#!/usr/bin/env python3
"""避難收容處所資料 ETL — 下載消防署開放資料轉存本地 JSON
用法:
  fetch_shelters.py                          # 從官方來源下載
  fetch_shelters.py --source-csv local.csv   # 從本地 CSV 轉換（測試/離線用）
"""
import argparse
import csv
import io
import json
import sys
from pathlib import Path

SHELTER_CSV_URL = (
    "https://opdadm.moi.gov.tw/api/v1/no-auth/resource/api/dataset/"
    "ED6CF735-6C03-4573-A882-72C1BEC799CB/resource/"
    "54550E2F-4567-4C8F-BD2E-E54E9D0386B8/download"
)
OUTPUT_FILE = Path(__file__).parent / "shelters.json"


def parse_csv_rows(csv_text: str) -> list:
    """把消防署避難收容處所 CSV 轉成標準化 dict list，略過經緯度無法解析的列"""
    reader = csv.DictReader(io.StringIO(csv_text))
    shelters = []
    skipped = 0
    for row in reader:
        try:
            lat = float(row["緯度"])
            lon = float(row["經度"])
        except (KeyError, ValueError, TypeError):
            skipped += 1
            continue
        shelters.append({
            "name": row.get("避難收容處所名稱", "").strip(),
            "address": row.get("避難收容處所地址", "").strip(),
            "city_district": row.get("縣市及鄉鎮市區", "").strip(),
            "village": row.get("村里", "").strip(),
            "lat": lat,
            "lon": lon,
            "capacity": row.get("預計收容人數", "").strip(),
            "disaster_types": row.get("適用災害類別", "").strip(),
        })
    if skipped:
        print(f"警告: {skipped} 筆資料因經緯度無法解析被略過", file=sys.stderr)
    return shelters


def fetch_csv_text(source_csv: str | None) -> str:
    if source_csv:
        with open(source_csv, encoding="utf-8-sig") as f:
            return f.read()
    import requests
    resp = requests.get(SHELTER_CSV_URL, timeout=30)
    resp.raise_for_status()
    return resp.content.decode("utf-8-sig")


def main():
    parser = argparse.ArgumentParser(description="避難收容處所資料 ETL")
    parser.add_argument("--source-csv", help="從本地 CSV 檔轉換，不從網路下載")
    parser.add_argument("--output", default=str(OUTPUT_FILE), help="輸出 JSON 路徑")
    args = parser.parse_args()

    csv_text = fetch_csv_text(args.source_csv)
    shelters = parse_csv_rows(csv_text)

    output_path = Path(args.output)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({"shelters": shelters}, f, ensure_ascii=False, indent=2)

    print(f"已寫入 {len(shelters)} 筆避難所資料至 {output_path}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 執行測試確認通過**

Run: `venv/bin/python3 -m pytest tests/test_fetch_shelters.py -v`
Expected: 2 passed

- [ ] **Step 5: 實際跑一次真實下載，產生 `shelters.json`**

```bash
venv/bin/python3 tools/taiwan/fetch_shelters.py
```

Expected: 印出 `已寫入 5973 筆避難所資料至 .../tools/taiwan/shelters.json`（實際筆數可能因資料更新略有變動）

- [ ] **Step 6: Commit（含產生的 shelters.json，讓 shelter_query.py 開箱即用）**

```bash
git add tools/taiwan/fetch_shelters.py tests/test_fetch_shelters.py tools/taiwan/shelters.json
git commit -m "feat: add fetch_shelters.py ETL + committed shelters.json snapshot"
```

---

### Task 4: 避難點查詢（`shelter_query.py`）

**複雜度：中。Critic：R1 一輪。**

**Files:**
- Create: `tools/taiwan/shelter_query.py`
- Test: `tests/test_shelter_query.py`

**Interfaces:**
- Consumes: `geo_utils.haversine`（Task 1）
- Produces: `shelter_query.find_nearest(lat, lon, shelters, n) -> list[tuple[float, dict]]`、`shelter_query.format_results(results) -> str`，供 Task 5 的 `execute_llm_tool_call` 分支透過 subprocess 呼叫本檔案的 `main()` CLI

- [ ] **Step 1: 寫失敗測試**

Create `tests/test_shelter_query.py`:

```python
import shelter_query

SAMPLE_SHELTERS = [
    {"name": "近點", "address": "地址A", "city_district": "", "lat": 25.0, "lon": 121.0, "capacity": "10"},
    {"name": "遠點", "address": "地址B", "city_district": "", "lat": 26.0, "lon": 122.0, "capacity": "20"},
]


def test_find_nearest_orders_by_distance():
    results = shelter_query.find_nearest(25.0, 121.0, SAMPLE_SHELTERS, n=2)
    assert results[0][1]["name"] == "近點"
    assert results[0][0] == 0.0
    assert results[1][1]["name"] == "遠點"


def test_find_nearest_respects_n_limit():
    results = shelter_query.find_nearest(25.0, 121.0, SAMPLE_SHELTERS, n=1)
    assert len(results) == 1


def test_format_results_empty():
    assert shelter_query.format_results([]) == "附近查無避難收容處所資料。"


def test_format_results_includes_name_and_distance():
    results = [(1500.0, SAMPLE_SHELTERS[0])]
    text = shelter_query.format_results(results)
    assert "近點" in text
    assert "1.5km" in text
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `venv/bin/python3 -m pytest tests/test_shelter_query.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'shelter_query'`

- [ ] **Step 3: 寫最小實作**

Create `tools/taiwan/shelter_query.py`:

```python
#!/usr/bin/env python3
"""避難收容處所查詢 — 依 GPS 座標查詢最近的避難所
用法: shelter_query.py --lat 25.033 --lon 121.564 [--n 3]
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from geo_utils import haversine

SHELTERS_FILE = Path(__file__).parent / "shelters.json"


def load_shelters(path: Path = SHELTERS_FILE) -> list:
    with open(path, encoding="utf-8") as f:
        return json.load(f)["shelters"]


def find_nearest(lat: float, lon: float, shelters: list, n: int = 3) -> list:
    scored = [(haversine(lat, lon, s["lat"], s["lon"]), s) for s in shelters]
    scored.sort(key=lambda x: x[0])
    return scored[:n]


def format_results(results: list) -> str:
    if not results:
        return "附近查無避難收容處所資料。"
    lines = []
    for distance_m, s in results:
        distance_km = distance_m / 1000
        location = s["address"] or s["city_district"]
        lines.append(f"{s['name']}（{distance_km:.1f}km）- {location} 容量約{s['capacity']}人")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="避難收容處所查詢")
    parser.add_argument("--lat", type=float, required=True)
    parser.add_argument("--lon", type=float, required=True)
    parser.add_argument("--n", type=int, default=3)
    parser.add_argument("--shelters-file", default=str(SHELTERS_FILE))
    args = parser.parse_args()

    if not Path(args.shelters_file).exists():
        print("❌ 避難所資料尚未建立，請先執行 fetch_shelters.py")
        sys.exit(1)

    shelters = load_shelters(Path(args.shelters_file))
    results = find_nearest(args.lat, args.lon, shelters, args.n)
    print(format_results(results))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 執行測試確認通過**

Run: `venv/bin/python3 -m pytest tests/test_shelter_query.py -v`
Expected: 4 passed

- [ ] **Step 5: 用真實資料手動驗證一次**

```bash
venv/bin/python3 tools/taiwan/shelter_query.py --lat 25.033 --lon 121.565 --n 3
```

Expected: 印出台北市附近 3 個避難所名稱/距離/容量，非錯誤訊息

- [ ] **Step 6: Commit**

```bash
git add tools/taiwan/shelter_query.py tests/test_shelter_query.py
git commit -m "feat: add shelter_query.py nearest-shelter lookup"
```

---

### Task 5: bridge.py 接線 — 移除 parking/surf、加入 find_shelter、修好 weather-here

**複雜度：中。Critic：R1 一輪。**

**Files:**
- Modify: `bridge.py:44-76`（`llm_tools` schema）
- Modify: `bridge.py:217-249`（`execute_llm_tool_call`）
- Modify: `bridge.py:292-309`（weather-here 處理段落）
- Test: `tests/test_bridge_tool_dispatch.py`

**Interfaces:**
- Consumes: `tools/taiwan/shelter_query.py`（Task 4）、`tools/taiwan/weather_query.py`（Task 2）作為 subprocess 目標腳本
- Produces: `execute_llm_tool_call` 新分支 `find_shelter`，供 Task 9/10 之後的手動驗證流程間接使用（本身不影響 SOS/報平安)

- [ ] **Step 1: 寫失敗測試（驗證新 schema 與分支存在、舊的已移除）**

Create `tests/test_bridge_tool_dispatch.py`:

```python
import types
from pathlib import Path

import bridge


def test_llm_tools_no_longer_contains_parking_or_surf():
    names = {t["function"]["name"] for t in bridge.llm_tools}
    assert "find_parking" not in names
    assert "query_surf_spots" not in names
    assert "find_shelter" in names


def test_execute_llm_tool_call_finds_shelter_script(monkeypatch, tmp_path):
    captured_cmd = {}

    class FakeCompletedProcess:
        stdout = "測試避難所（0.1km）- 測試地址 容量約10人"

    def fake_run(cmd, capture_output, text, check):
        captured_cmd["cmd"] = cmd
        return FakeCompletedProcess()

    monkeypatch.setattr(bridge.subprocess, "run", fake_run)

    tool_call = types.SimpleNamespace(
        function=types.SimpleNamespace(
            name="find_shelter", arguments={"lat": 25.03, "lon": 121.56}
        )
    )
    result = bridge.execute_llm_tool_call(tool_call, is_online=True, localization_setting="TW")

    assert "shelter_query.py" in captured_cmd["cmd"][1]
    assert "--lat" in captured_cmd["cmd"]
    assert result["tool_output"] == FakeCompletedProcess.stdout


def test_execute_llm_tool_call_unknown_tool_returns_error():
    tool_call = types.SimpleNamespace(
        function=types.SimpleNamespace(name="not_a_real_tool", arguments={})
    )
    result = bridge.execute_llm_tool_call(tool_call, is_online=True, localization_setting="TW")
    assert "❌" in result["tool_output"]
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `venv/bin/python3 -m pytest tests/test_bridge_tool_dispatch.py -v`
Expected: FAIL（`find_shelter` 尚不存在於 `llm_tools`，`find_parking`/`query_surf_spots` 仍存在）

- [ ] **Step 3: 修改 `llm_tools` schema**

在 `bridge.py` 中，把第 44-76 行整段（`llm_tools = [...]`，含 `find_parking` 和 `query_surf_spots` 兩個工具定義）替換為：

```python
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
```

- [ ] **Step 4: 修改 `execute_llm_tool_call`**

把第 217-249 行整個函式替換為：

```python
def execute_llm_tool_call(tool_call, is_online, localization_setting):
    """執行 LLM 的工具調用"""
    tool_name = tool_call.function.name
    tool_args = tool_call.function.arguments
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
```

- [ ] **Step 5: 修好 weather-here（改叫 `weather_query.py`，不再依賴已刪除的 surf 工具）**

在 `bridge.py` 中，把第 292-309 行（`handle_incoming_meshtastic_message` 開頭的「GPS 感知天氣查詢」段落）替換為：

```python
    # --- GPS 感知天氣查詢 ---
    if "weather here" in text_message.lower() or "附近天氣" in text_message:
        print(f"偵測到 GPS 天氣查詢 from {sender_id}")
        (lat, lon), error_msg = get_node_location(sender_id)
        if error_msg:
            send_meshtastic_message(f"❌ 無法獲取您的 GPS 位置: {error_msg}", destination_id=sender_id)
            return

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
```

（注意：`types` 模組的 import 若無其他用途會變成未使用——先保留 import，Task 9 會用到 `types.SimpleNamespace` 建構測試 fixture，且目前既有程式碼其他地方沒有用到 `types`，這裡先不動 import 語句，等全部 Task 完成後在最後 README/清理步驟一併檢查未使用 import。）

- [ ] **Step 6: 執行測試確認通過**

Run: `venv/bin/python3 -m pytest tests/test_bridge_tool_dispatch.py -v`
Expected: 3 passed

- [ ] **Step 7: Commit**

```bash
git add bridge.py tests/test_bridge_tool_dispatch.py
git commit -m "feat: replace parking/surf LLM tools with find_shelter, fix broken weather-here"
```

---

### Task 6: 刪除 parking/surf 工具腳本 + README 同步

**複雜度：低。Critic：R1 一輪。**

**Files:**
- Delete: `tools/taiwan/parking_query.py`
- Delete: `tools/taiwan/surf_query.py`
- Modify: `README.md`
- Modify: `README.zh-TW.md`

- [ ] **Step 1: 確認沒有其他程式碼還引用這兩個檔案**

```bash
grep -rn "parking_query\|surf_query" bridge.py tools/ tests/ 2>/dev/null
```

Expected: 無輸出（Task 5 已經移除所有引用）

- [ ] **Step 2: 刪除檔案**

```bash
git rm tools/taiwan/parking_query.py tools/taiwan/surf_query.py
```

- [ ] **Step 3: 修改 README.md**

在 `README.md` 中：
1. 移除任何描述「停車場查詢」「衝浪浪點查詢」「Local Knowledge Base (RAG)」的段落（RAG 段落移除是因為它描述的功能從未實作，這是既有 drift，不在本次功能範圍但既然在動 README 一併修正）
2. 新增避難點/SOS/報平安功能說明：

```markdown
### Disaster Info Tools

- **Shelter Finder**: Ask about nearby emergency shelters (`find_shelter` LLM tool), backed by Taiwan's National Fire Agency shelter dataset (works offline, no internet required)
- **SOS Broadcast**: Send `SOS` (optionally followed by a message, e.g. `SOS trapped on 2nd floor`) to broadcast your GPS location and timestamp to the entire mesh via Meshtastic's `ALERT_APP` priority channel. Rate-limited to once per 60 seconds per node to prevent accidental flooding.
- **Safety Check-in**: Send `SAFE` or `平安` (optionally with a message) to broadcast that you're safe, same rate-limiting applies.
```

3. 修正 clone URL（若指向錯誤內容）— 確認目前寫的是 `https://github.com/Harperbot/meshtastic-llm-bridge.git`，這確實是正確的 remote，維持不動
4. 在安裝指令段落補上缺漏的 `feedparser` 依賴：

找到目前的 pip install 指令行，改為：

```
pip install meshtastic[cli] requests python-dotenv openai ollama feedparser pytest
```

（移除 `langchain-community pypdf unstructured chromadb`，這些是從未實作的 RAG 功能依賴，一併清除）

5. 加上 `.env.example` 提及的段落改為直接列出所需環境變數（因為 `.env.example` 實際不存在，不該叫使用者 `cp` 一個不存在的檔案）：

```markdown
### Environment Variables

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
```

- [ ] **Step 4: 對 README.zh-TW.md 做同樣的修正**（段落對應翻譯，同樣移除 parking/surf/RAG，新增避難點/SOS/報平安中文說明，修正 `.env`/依賴清單）

- [ ] **Step 5: 確認測試仍全部通過（刪檔不應影響任何測試）**

Run: `venv/bin/python3 -m pytest tests/ -v`
Expected: 全部 passed（Task 1-5 累計的測試數）

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "chore: remove deprecated parking/surf tools, sync README with current features"
```

---

### Task 7: P0 — bridge.py 收發層遷移到 Python API

**複雜度：高。Critic：R1 + R2(Opus)。**

**背景**：這是本次風險最高的改動，直接換掉核心收發機制。改動前後都要跑 Step 6 的既有功能回歸測試。真實硬體驗證見文件末「真實硬體驗證」章節 Tier 0-1。

**Files:**
- Modify: `bridge.py`（imports、`send_meshtastic_message`、`get_node_location`、`main_loop`）
- Test: `tests/test_bridge_python_api.py`

**Interfaces:**
- Produces: 模組層級 `bridge._interface`（`SerialInterface` 實例或 `None`）、`bridge._on_receive(packet, interface)` callback，供 Task 8 的重連邏輯與 Task 9/10 的 SOS/報平安直接呼叫 `send_meshtastic_message`/`get_node_location`

- [ ] **Step 1: 寫失敗測試（用假的 interface 物件驗證邏輯，不連真實硬體）**

Create `tests/test_bridge_python_api.py`:

```python
import bridge


class FakeInterface:
    def __init__(self):
        self.sent_texts = []
        self.sent_alerts = []
        self.nodes = {}

    def sendText(self, text, destinationId="^all", **kwargs):
        self.sent_texts.append((text, destinationId))

    def sendAlert(self, text, destinationId="^all", **kwargs):
        self.sent_alerts.append((text, destinationId))

    def close(self):
        pass


def test_send_meshtastic_message_uses_interface_sendtext(monkeypatch):
    fake = FakeInterface()
    monkeypatch.setattr(bridge, "_interface", fake)
    monkeypatch.setattr(bridge.time, "sleep", lambda *_: None)

    bridge.send_meshtastic_message("hello", destination_id="!abc123")

    assert fake.sent_texts == [("hello", "!abc123")]


def test_send_meshtastic_message_chunks_long_text(monkeypatch):
    fake = FakeInterface()
    monkeypatch.setattr(bridge, "_interface", fake)
    monkeypatch.setattr(bridge.time, "sleep", lambda *_: None)

    long_text = "x" * 500
    bridge.send_meshtastic_message(long_text, destination_id="^all")

    assert len(fake.sent_texts) == 3  # 500 / 220 -> 3 chunks
    assert fake.sent_texts[0][0].startswith("(1/3)")


def test_get_node_location_reads_from_interface_nodes(monkeypatch):
    fake = FakeInterface()
    fake.nodes["!d2d2a4e4"] = {"position": {"latitude": 25.03, "longitude": 121.56}}
    monkeypatch.setattr(bridge, "_interface", fake)

    (lat, lon), error = bridge.get_node_location("d2d2a4e4")

    assert error is None
    assert lat == 25.03
    assert lon == 121.56


def test_get_node_location_missing_position_returns_error(monkeypatch):
    fake = FakeInterface()
    fake.nodes["!d2d2a4e4"] = {}
    monkeypatch.setattr(bridge, "_interface", fake)

    result, error = bridge.get_node_location("d2d2a4e4")

    assert result is None
    assert error is not None


def test_on_receive_dispatches_to_handler(monkeypatch):
    calls = []
    monkeypatch.setattr(
        bridge, "handle_incoming_meshtastic_message",
        lambda sender_id, text: calls.append((sender_id, text)),
    )

    packet = {"decoded": {"text": "hello"}, "fromId": "!d2d2a4e4"}
    bridge._on_receive(packet, interface=None)

    assert calls == [("!d2d2a4e4", "hello")]
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `venv/bin/python3 -m pytest tests/test_bridge_python_api.py -v`
Expected: FAIL（`bridge._interface`/`bridge._on_receive` 尚不存在，`send_meshtastic_message`/`get_node_location` 仍是舊的 subprocess 版本）

- [ ] **Step 3: 修改 imports**

在 `bridge.py` 檔案最上方，把第 1-14 行替換為：

```python
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
```

- [ ] **Step 4: 加入 `_interface` 全域變數與連線函式**

在 `bridge.py` 中，`MAX_MESHTASTIC_PAYLOAD = 220` 那一行（原第 117 行）之前插入：

```python
# --- Meshtastic Python API 介面 ---
_interface = None
RECONNECT_DELAY_SECONDS = 10
```

- [ ] **Step 5: 替換 `send_meshtastic_message`**

把原本第 134-151 行的 `send_meshtastic_message` 函式替換為：

```python
def send_meshtastic_message(text, destination_id=None, reply_id=None):
    """透過 Meshtastic Python API 發送文字訊息，處理長訊息切分"""
    global _interface
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


def send_meshtastic_alert(text, destination_id=None):
    """透過 Meshtastic Python API 發送 ALERT_APP 高優先權訊息（不分段，過長截斷）"""
    global _interface
    dest = destination_id if destination_id else "^all"
    truncated = text[:MAX_MESHTASTIC_PAYLOAD]
    print(f"Sending Meshtastic ALERT to {dest}: {truncated}")
    _interface.sendAlert(truncated, destinationId=dest)
```

- [ ] **Step 6: 替換 `get_node_location`**

把原本第 251-278 行的 `get_node_location` 函式替換為：

```python
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
```

- [ ] **Step 7: 加入 `_on_receive` callback，替換 `main_loop`**

在 `get_node_location` 之後、`_get_content` 之前插入：

```python
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
```

把原本第 360-391 行的 `main_loop` 函式替換為：

```python
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


def main_loop():
    print("Meshtastic LLM Bridge 已啟動（Python API 模式）。正在連線 Meshtastic 裝置...")
    print(f"本地工具路徑: {os.getcwd()}/tools/taiwan/")

    pub.subscribe(_on_receive, "meshtastic.receive.text")
    _connect_with_retry()

    while True:
        time.sleep(3600)
```

（`_connect_with_retry` 這裡先只涵蓋初次連線；斷線後的重連訂閱在 Task 8 補上 `meshtastic.connection.lost` 處理。）

- [ ] **Step 8: 執行測試確認通過**

Run: `venv/bin/python3 -m pytest tests/test_bridge_python_api.py -v`
Expected: 5 passed

- [ ] **Step 9: 執行全部既有測試，確認 Task 1-6 沒有回歸**

Run: `venv/bin/python3 -m pytest tests/ -v`
Expected: 全部 passed

- [ ] **Step 10: Commit**

```bash
git add bridge.py tests/test_bridge_python_api.py
git commit -m "refactor: migrate subprocess+CLI parsing to meshtastic Python API (SerialInterface + pubsub)"
```

**R1+R2 提醒**：此批次審查重點——(a) `send_meshtastic_message`/`send_meshtastic_alert` 是否正確使用 `destinationId`（非 `destination_id`，Python API 參數名是 camelCase）(b) `get_node_location` 的 node id 格式（`!` 前綴）處理是否與 `_on_receive` 傳入 `handle_incoming_meshtastic_message` 的 `sender_id`（已含 `!` 前綴，因為直接來自 `packet["fromId"]`）一致——**這裡有個真實風險點：`packet["fromId"]` 本身已經是 `!xxxxxxxx` 格式，而 `get_node_location` 目前的實作若收到已經帶 `!` 的字串會被 `node_id_to_find.startswith("!")` 正確識別不重複加，但呼叫端（weather-here/SOS/報平安）傳入的 `sender_id` 到底帶不帶 `!` 需要跨函式交叉檢查，R1 必須逐一追蹤 `sender_id` 從 `_on_receive` 產生到傳入 `get_node_location`/`send_meshtastic_message(destination_id=sender_id)` 的每一站，確認格式全程一致**。

---

### Task 8: P0 — 斷線重連邏輯

**複雜度：高。Critic：R1 + R2(Opus)。**

**Files:**
- Modify: `bridge.py`（`main_loop`、新增 `_on_connection_lost`/`_reconnect`）
- Test: `tests/test_bridge_reconnect.py`

**Interfaces:**
- Consumes: `bridge._connect_with_retry`（Task 7）
- Produces: `bridge._on_connection_lost(interface)`，訂閱 `meshtastic.connection.lost` 事件

- [ ] **Step 1: 寫失敗測試**

Create `tests/test_bridge_reconnect.py`:

```python
import threading
import time

import bridge


def test_on_connection_lost_triggers_reconnect(monkeypatch):
    reconnect_called = threading.Event()

    def fake_reconnect():
        reconnect_called.set()

    monkeypatch.setattr(bridge, "_reconnect", fake_reconnect)

    bridge._on_connection_lost(interface=None)

    assert reconnect_called.wait(timeout=2), "reconnect 應該在背景執行緒中被呼叫"


def test_reconnect_closes_old_interface_and_reconnects(monkeypatch):
    closed = []

    class FakeOldInterface:
        def close(self):
            closed.append(True)

    connect_calls = []
    monkeypatch.setattr(bridge, "_interface", FakeOldInterface())
    monkeypatch.setattr(bridge, "_connect_with_retry", lambda: connect_calls.append(True))

    bridge._reconnect()

    assert closed == [True]
    assert connect_calls == [True]
    assert bridge._interface is None or connect_calls  # _connect_with_retry 被 mock 掉，不會真的設回新值


def test_reconnect_handles_close_exception_gracefully(monkeypatch):
    class BrokenInterface:
        def close(self):
            raise RuntimeError("already dead")

    connect_calls = []
    monkeypatch.setattr(bridge, "_interface", BrokenInterface())
    monkeypatch.setattr(bridge, "_connect_with_retry", lambda: connect_calls.append(True))

    bridge._reconnect()  # 不應該拋出例外

    assert connect_calls == [True]
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `venv/bin/python3 -m pytest tests/test_bridge_reconnect.py -v`
Expected: FAIL，`AttributeError: module 'bridge' has no attribute '_on_connection_lost'`

- [ ] **Step 3: 寫最小實作**

在 `bridge.py` 的 `_connect_with_retry` 函式之後、`main_loop` 之前插入：

```python
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
```

修改 `main_loop`，在 `pub.subscribe(_on_receive, "meshtastic.receive.text")` 之後加一行：

```python
def main_loop():
    print("Meshtastic LLM Bridge 已啟動（Python API 模式）。正在連線 Meshtastic 裝置...")
    print(f"本地工具路徑: {os.getcwd()}/tools/taiwan/")

    pub.subscribe(_on_receive, "meshtastic.receive.text")
    pub.subscribe(_on_connection_lost, "meshtastic.connection.lost")
    _connect_with_retry()

    while True:
        time.sleep(3600)
```

- [ ] **Step 4: 執行測試確認通過**

Run: `venv/bin/python3 -m pytest tests/test_bridge_reconnect.py -v`
Expected: 3 passed

- [ ] **Step 5: 執行全部既有測試確認無回歸**

Run: `venv/bin/python3 -m pytest tests/ -v`
Expected: 全部 passed

- [ ] **Step 6: Commit**

```bash
git add bridge.py tests/test_bridge_reconnect.py
git commit -m "feat: add threaded reconnect on meshtastic.connection.lost"
```

**R1+R2 提醒**：審查重點——(a) `_reconnect` 若被連續觸發多次（例如短時間內反覆斷線）是否會疊加多個背景執行緒同時嘗試連線造成競爭；目前實作沒有防重入鎖，**這是已知限制，R2 需明確判斷是否為本次可接受的範圍**（真實硬體斷線通常不會在毫秒等級內重複觸發多次 `connection.lost`，但邏輯上沒有防護）。若 R2 認為需要修，選項是加一個 `threading.Lock` 防止 `_reconnect` 重入。(b) `_connect_with_retry` 是無限重試迴圈，若裝置永久拔除會無限重試且每次間隔 10 秒印 log——確認這是可接受的行為（不做退避或上限，因為斷線重連本來就該一直嘗試到裝置回來）。

---

### Task 9: SOS 求救廣播

**複雜度：高。Critic：R1 + R2(Opus)。**

**Files:**
- Modify: `bridge.py`（新增 cooldown/格式化/觸發邏輯，接進 `handle_incoming_meshtastic_message`）
- Test: `tests/test_bridge_emergency.py`

**Interfaces:**
- Consumes: `bridge.get_node_location`（Task 7）、`bridge.send_meshtastic_alert`（Task 7）
- Produces: `bridge._match_sos_command(text) -> str | None`、`bridge._cooldown_allows(node_id, last_ts_map, cooldown_seconds) -> bool`（Task 10 共用）

- [ ] **Step 1: 寫失敗測試**

Create `tests/test_bridge_emergency.py`:

```python
import bridge


def test_match_sos_command_bare():
    assert bridge._match_sos_command("SOS") == ""


def test_match_sos_command_with_message():
    assert bridge._match_sos_command("SOS 受困在二樓") == "受困在二樓"


def test_match_sos_command_case_insensitive():
    assert bridge._match_sos_command("sos help") == "help"


def test_match_sos_command_does_not_match_unrelated_text():
    assert bridge._match_sos_command("sosolution needed") is None
    assert bridge._match_sos_command("hello world") is None


def test_cooldown_allows_first_call_then_blocks_within_window(monkeypatch):
    fake_time = [1000.0]
    monkeypatch.setattr(bridge.time, "time", lambda: fake_time[0])
    last_ts_map = {}

    assert bridge._cooldown_allows("!abc", last_ts_map, 60) is True
    assert bridge._cooldown_allows("!abc", last_ts_map, 60) is False

    fake_time[0] += 61
    assert bridge._cooldown_allows("!abc", last_ts_map, 60) is True


def test_cooldown_is_per_node(monkeypatch):
    fake_time = [1000.0]
    monkeypatch.setattr(bridge.time, "time", lambda: fake_time[0])
    last_ts_map = {}

    assert bridge._cooldown_allows("!node1", last_ts_map, 60) is True
    assert bridge._cooldown_allows("!node2", last_ts_map, 60) is True  # 不同節點互不影響


def test_format_emergency_broadcast_with_known_location():
    text = bridge._format_emergency_broadcast(
        "sos", "!d2d2a4e4", (25.03, 121.56), "受困", "2026-07-22 10:00:00",
    )
    assert "🆘" in text
    assert "!d2d2a4e4" in text
    assert "25.03" in text
    assert "受困" in text


def test_format_emergency_broadcast_without_location():
    text = bridge._format_emergency_broadcast("sos", "!d2d2a4e4", None, "", "2026-07-22 10:00:00")
    assert "GPS 位置未知" in text


def test_handle_emergency_broadcast_calls_send_alert_for_sos(monkeypatch):
    sent = []
    monkeypatch.setattr(bridge, "get_node_location", lambda node_id: ((25.0, 121.0), None))
    monkeypatch.setattr(bridge, "send_meshtastic_alert", lambda text, destination_id: sent.append((text, destination_id)))
    monkeypatch.setattr(bridge, "_last_sos_ts", {})

    bridge._handle_emergency_broadcast("sos", "!d2d2a4e4", "受困")

    assert len(sent) == 1
    assert sent[0][1] == "^all"


def test_handle_emergency_broadcast_suppressed_within_cooldown(monkeypatch, capsys):
    sent = []
    monkeypatch.setattr(bridge, "get_node_location", lambda node_id: ((25.0, 121.0), None))
    monkeypatch.setattr(bridge, "send_meshtastic_alert", lambda text, destination_id: sent.append((text, destination_id)))
    monkeypatch.setattr(bridge, "_last_sos_ts", {"!d2d2a4e4": bridge.time.time()})

    bridge._handle_emergency_broadcast("sos", "!d2d2a4e4", "第二次")

    assert len(sent) == 0
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `venv/bin/python3 -m pytest tests/test_bridge_emergency.py -v`
Expected: FAIL（`_match_sos_command`/`_cooldown_allows`/`_format_emergency_broadcast`/`_handle_emergency_broadcast`/`_last_sos_ts` 都不存在）

- [ ] **Step 3: 寫最小實作**

在 `bridge.py` 中，`_interface = None` / `RECONNECT_DELAY_SECONDS = 10` 那段全域變數之後（Task 7 加入的位置）插入：

```python
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
    if t.startswith("平安"):
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
            send_meshtastic_alert(broadcast_text, destination_id="^all")
        else:
            send_meshtastic_message(broadcast_text, destination_id="^all")
        print(f"{kind.upper()} 廣播成功: {broadcast_text}")
    except Exception as e:
        print(f"❌ {kind.upper()} 廣播失敗: {e}", file=sys.stderr)
```

在 `handle_incoming_meshtastic_message` 函式最開頭（`global internet_connected` 那行之後、GPS 感知天氣查詢之前）插入：

```python
    sos_extra = _match_sos_command(text_message)
    if sos_extra is not None:
        _handle_emergency_broadcast("sos", sender_id, sos_extra)
        return

    safe_extra = _match_safe_command(text_message)
    if safe_extra is not None:
        _handle_emergency_broadcast("safe", sender_id, safe_extra)
        return
```

- [ ] **Step 4: 執行測試確認通過**

Run: `venv/bin/python3 -m pytest tests/test_bridge_emergency.py -v`
Expected: 10 passed

- [ ] **Step 5: 執行全部既有測試確認無回歸**

Run: `venv/bin/python3 -m pytest tests/ -v`
Expected: 全部 passed

- [ ] **Step 6: Commit**

```bash
git add bridge.py tests/test_bridge_emergency.py
git commit -m "feat: add SOS emergency broadcast via ALERT_APP with per-node cooldown"
```

**R1+R2 提醒**：審查重點——(a) `_match_sos_command("SOS")` 與 `_match_sos_command("SOSxyz")` 的邊界（`t[3] == " "` 判斷式確保後者不誤判，R1 需實際跑一次確認）(b) GPS 缺失時是否真的仍然廣播（`_format_emergency_broadcast` 在 `location is None` 時的行為，不能因為拿不到 GPS 就整個放棄廣播——這是規格明確要求的「生命安全優先」）(c) cooldown map 用全域可變字典，多節點/多次呼叫的執行緒安全性（目前 `handle_incoming_meshtastic_message` 是否可能被多執行緒同時呼叫？需確認 pypubsub 的 callback 派發是否為單一 `publishingThread` 序列化執行——若是，則不需要額外加鎖；R2 需查證這點而非假設）。

---

### Task 10: 報平安廣播

**複雜度：高。Critic：R1 + R2(Opus)。**

**背景**：核心邏輯（cooldown、GPS 取得、廣播流程）已在 Task 9 的 `_handle_emergency_broadcast` 中一併實作為共用函式（`kind="safe"` 分支）。這個 Task 只需要確認觸發路徑正確、測試涵蓋 `safe` 分支，因為 Task 9 的實作已經是通用設計。

**Files:**
- Test: `tests/test_bridge_emergency.py`（擴充，非新檔案）

**Interfaces:**
- Consumes: `bridge._handle_emergency_broadcast`（Task 9，`kind="safe"` 分支）、`bridge._match_safe_command`（Task 9 已實作）

- [ ] **Step 1: 補充測試（`safe` 分支專屬案例，`_match_safe_command` 的中英文觸發與 `_handle_emergency_broadcast` 使用 `send_meshtastic_message` 而非 `send_meshtastic_alert`）**

在 `tests/test_bridge_emergency.py` 檔案末端追加：

```python
def test_match_safe_command_english():
    assert bridge._match_safe_command("SAFE") == ""
    assert bridge._match_safe_command("SAFE 我在家") == "我在家"


def test_match_safe_command_chinese():
    assert bridge._match_safe_command("平安") == ""
    assert bridge._match_safe_command("平安 我很好") == "我很好"


def test_match_safe_command_does_not_match_unrelated_text():
    assert bridge._match_safe_command("safety first") is None
    assert bridge._match_safe_command("hello") is None


def test_handle_emergency_broadcast_calls_send_text_for_safe_not_alert(monkeypatch):
    text_sent = []
    alert_sent = []
    monkeypatch.setattr(bridge, "get_node_location", lambda node_id: ((25.0, 121.0), None))
    monkeypatch.setattr(bridge, "send_meshtastic_message", lambda text, destination_id: text_sent.append((text, destination_id)))
    monkeypatch.setattr(bridge, "send_meshtastic_alert", lambda text, destination_id: alert_sent.append((text, destination_id)))
    monkeypatch.setattr(bridge, "_last_safe_ts", {})

    bridge._handle_emergency_broadcast("safe", "!d2d2a4e4", "我在家")

    assert len(text_sent) == 1
    assert len(alert_sent) == 0
    assert text_sent[0][1] == "^all"


def test_sos_and_safe_cooldowns_are_independent(monkeypatch):
    fake_time = [1000.0]
    monkeypatch.setattr(bridge.time, "time", lambda: fake_time[0])
    monkeypatch.setattr(bridge, "_last_sos_ts", {})
    monkeypatch.setattr(bridge, "_last_safe_ts", {})

    assert bridge._cooldown_allows("!node1", bridge._last_sos_ts, bridge.SOS_COOLDOWN_SECONDS) is True
    # 同一節點在同一時間點觸發報平安，不受 SOS cooldown 影響（獨立計時器）
    assert bridge._cooldown_allows("!node1", bridge._last_safe_ts, bridge.SAFE_COOLDOWN_SECONDS) is True
```

- [ ] **Step 2: 執行測試（此時應該已經全部通過，因為 Task 9 的實作已涵蓋 `safe` 分支邏輯——若有失敗代表 Task 9 實作有缺口，需回頭修正）**

Run: `venv/bin/python3 -m pytest tests/test_bridge_emergency.py -v`
Expected: 全部 passed（含新增的 6 個測試）

- [ ] **Step 3: 手動確認 `handle_incoming_meshtastic_message` 中 SOS/報平安觸發順序正確（SOS 先判斷，避免「SOS SAFE」這種邊界字串被報平安誤判——目前 `_match_sos_command` 用 `SOS` 前綴判斷，`_match_safe_command` 用 `SAFE`/`平安` 前綴判斷，兩者字首不重疊，不會衝突，這步是確認而非修改）**

Run:
```bash
venv/bin/python3 -c "
import bridge
assert bridge._match_sos_command('SOS SAFE house') == 'SAFE house'
assert bridge._match_safe_command('SOS SAFE house') is None
print('OK: no ambiguity between SOS and SAFE prefixes')
"
```
Expected: 印出 `OK: no ambiguity between SOS and SAFE prefixes`

- [ ] **Step 4: 執行全部測試確認無回歸**

Run: `venv/bin/python3 -m pytest tests/ -v`
Expected: 全部 passed

- [ ] **Step 5: Commit**

```bash
git add tests/test_bridge_emergency.py
git commit -m "test: add dedicated coverage for safe/report-safe broadcast branch"
```

**R1+R2 提醒**：這個 Task 本身沒有新的生產程式碼（複用 Task 9 的 `_handle_emergency_broadcast`），但複雜度標高是因為**要驗證 Task 9 寫的「共用邏輯」在 `safe` 分支真的正確**（尤其是 send_meshtastic_message vs send_meshtastic_alert 的分流，以及兩個 cooldown map 真的獨立不互相污染）。若 Step 2 測試失敗，代表 Task 9 的 R1+R2 審查有漏網之魚，須回頭修 Task 9 而非在此另開一套邏輯。

---

## Self-Review（依 writing-plans 檢查清單）

1. **Spec coverage**：對照設計文件（`docs/superpowers/specs/2026-07-22-disaster-info-and-python-api-migration-design.md`）逐段檢查——
   - P0 Python API 遷移 → Task 7
   - P0 斷線重連 → Task 8
   - 避難點查詢 → Task 3（ETL）+ Task 4（query）+ Task 5（bridge.py 接線）
   - SOS 求救廣播 → Task 9
   - 報平安廣播 → Task 10
   - 移除 parking/surf → Task 6（含 Task 5 先移除程式碼引用）
   - README 同步（含既有 drift：clone URL/`.env.example`/`feedparser`）→ Task 6
   - 模型分工/複雜度分級 → 已標注在每個 Task 標題（低/中/高 + Critic 指派）
   - 真實硬體驗證梯度 → 見下方獨立章節（不属於自動化 Task，是執行時的人工 runbook）
   - Weather-here 依賴衝突（設計文件未涵蓋，實作研究時發現）→ Task 2 補上並記錄背景
   - **未涵蓋（依設計文件本就排除，非漏項）**：防空避難設施 Phase 2、persistent chat history、RAG、MQTT——皆為設計文件明確列出的「不在這次範圍」項目
2. **Placeholder scan**：全文檢查無 TBD/TODO/「之後再補」；Task 10 因複用 Task 9 邏輯而步驟較短，但每步都有實際指令與明確驗證輸出，不是佔位符
3. **Type consistency**：`_cooldown_allows(node_id, last_ts_map, cooldown_seconds)` 簽名在 Task 9/10 全程一致；`send_meshtastic_message(text, destination_id=None, reply_id=None)` 與 `send_meshtastic_alert(text, destination_id=None)` 的參數命名（底線命名，對應內部再轉成 API 的 `destinationId` camelCase）在 Task 7/9/10 全程一致；`get_node_location` 回傳 `(lat, lon), error` 的 tuple 形狀在 Task 7/9 全程一致

---

## 真實硬體驗證（Tier 0-4，人工執行，非自動化 Task）

以下每一層都要你（使用者）親自操作硬體，我沒有辦法自動化實體 USB 拔插或確認範圍內是否有其他 Meshtastic 使用者。全部 Task 完成、自動化測試都綠燈後再開始。

### Tier 0：唯讀連線驗證（Task 7 完成後）

```bash
cd ~/ai-projects/projects/meshtastic-llm-bridge
venv/bin/python3 -c "
import meshtastic.serial_interface
iface = meshtastic.serial_interface.SerialInterface()
print('連線成功，節點數:', len(iface.nodes))
print('本機節點資訊:', iface.myInfo)
iface.close()
"
```
Expected: 印出節點數與本機資訊，無例外拋出

### Tier 1：安全收發驗證（Task 7 完成後，需要 2 台裝置）

在裝置 A 執行 `python3 bridge.py`，從裝置 B 對裝置 A 的節點 ID 發送 direct message（用官方 App 或 CLI `meshtastic --sendtext "test" --dest !<nodeA_id>`），確認裝置 A 的 log 印出收到訊息並觸發 LLM 回覆流程。

### Tier 2：斷線重連驗證（Task 8 完成後，純手動）

裝置 A 執行 `python3 bridge.py` 期間，實際拔掉 USB 序列線，確認 log 印出「偵測到 Meshtastic 連線中斷」，插回後確認 log 印出重新連線成功且後續訊息能正常處理，**不需要重啟整個 daemon**。

### Tier 3：SOS/報平安完整流程驗證（Task 9/10 完成後，仍走 direct message）

從裝置 B 對裝置 A 的節點發送 `SOS test` direct message（`meshtastic --sendtext "SOS test" --dest !<nodeA_id>`），確認：
1. 裝置 A 的 log 印出 SOS 廣播成功
2. 用官方 App 或第三台裝置確認真的收到了廣播內容（若只有 2 台裝置，可以在裝置 A 自己的 log 確認 `sendAlert` 被呼叫且 `destinationId="^all"`，暫時信任 log）
3. 60 秒內從裝置 B 再發一次 `SOS test2`，確認裝置 A log 印出「已被 cooldown 抑制」
4. 等 61 秒後再發一次，確認正常廣播（cooldown 已過期）

### Tier 4：`^all` 真實廣播驗證（僅做一次，需你在場、確認範圍內無其他 Meshtastic 使用者）

真的觸發一次 `^all` 廣播的 SOS 與報平安，確認全 mesh 廣播路徑正確。這步不要當常態測試重跑。

---

## 全部完成後

確認 Tier 0-4 都驗證過、`venv/bin/python3 -m pytest tests/ -v` 全綠、`git log --oneline` 看到 Task 1-10 的 10+ 個 commit 後，跟 user 確認一次要不要把本機 `main` 分支 push 到 `origin`（公開 repo，push 前需要明確詢問，不自動推）。
