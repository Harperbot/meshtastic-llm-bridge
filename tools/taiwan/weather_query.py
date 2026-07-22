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
