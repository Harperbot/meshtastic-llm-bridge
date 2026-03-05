#!/usr/bin/env python3
# version: 1.2.0
"""
停車場查詢 skill — 全台 TDX 即時停車資料
用法:
  parking_query.py --lat 25.033 --lon 121.564 --mode realtime
  parking_query.py --url "https://maps.app.goo.gl/xxx" --mode future
"""

import os, sys, json, argparse, time, re
import requests
from math import radians, sin, cos, sqrt, atan2
from pathlib import Path

# ── TDX ───────────────────────────────────────────────────────────────────────
AUTH_URL = "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token"
API_BASE = "https://tdx.transportdata.tw/api/basic/v1/Parking"
TOKEN_CACHE = Path(__file__).parent / ".tdx_token_cache"

# ── 縣市邊界框 (lat_min, lat_max, lon_min, lon_max) ───────────────────────────
# 較小/精確的城市放前面，避免被大城市吞掉
CITIES = [
    ("Keelung",          25.06, 25.22, 121.62, 121.83),
    ("Hsinchu",          24.76, 24.87, 120.92, 121.07),
    ("Chiayi",           23.43, 23.52, 120.39, 120.54),
    ("Taipei",           24.96, 25.21, 121.50, 121.67),
    ("Taoyuan",          24.55, 25.08, 120.97, 121.46),
    ("Taichung",         24.01, 24.43, 120.51, 121.10),
    ("Tainan",           22.84, 23.48, 120.06, 120.78),
    ("Kaohsiung",        22.44, 23.16, 120.24, 120.73),
    ("NewTaipei",        24.59, 25.30, 121.20, 122.03),
    ("HsinchuCounty",    24.44, 25.06, 120.78, 121.42),
    ("MiaoliCounty",     24.10, 24.70, 120.63, 121.25),
    ("ChanghuaCounty",   23.82, 24.18, 120.32, 120.73),
    ("NantouCounty",     23.50, 24.25, 120.52, 121.47),
    ("YunlinCounty",     23.50, 23.82, 120.10, 120.73),
    ("ChiayiCounty",     23.14, 23.72, 120.10, 120.89),
    ("PingtungCounty",   21.90, 22.84, 120.42, 121.00),
    ("YilanCounty",      24.30, 24.99, 121.39, 121.97),
    ("HualienCounty",    23.16, 24.47, 121.24, 121.86),
    ("TaitungCounty",    22.22, 23.16, 120.74, 121.52),
]

def detect_city(lat, lon):
    for name, lat_min, lat_max, lon_min, lon_max in CITIES:
        if lat_min <= lat <= lat_max and lon_min <= lon <= lon_max:
            return name
    return None

# ── 距離計算 ──────────────────────────────────────────────────────────────────
def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    a = sin((lat2-lat1)/2)**2 + cos(lat1)*cos(lat2)*sin((lon2-lon1)/2)**2
    return R * 2 * atan2(sqrt(a), sqrt(1-a))

# ── TDX 認證 ──────────────────────────────────────────────────────────────────
def get_token():
    client_id = os.getenv("TDX_CLIENT_ID")
    client_secret = os.getenv("TDX_CLIENT_SECRET")
    if not client_id or not client_secret:
        sys.exit("❌ 未設定 TDX_CLIENT_ID / TDX_CLIENT_SECRET")

    if TOKEN_CACHE.exists():
        cached = json.loads(TOKEN_CACHE.read_text())
        if cached.get("expires_at", 0) > time.time() + 30:
            return cached["access_token"]

    r = requests.post(AUTH_URL, data={
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
    }, timeout=10)
    r.raise_for_status()
    resp = r.json()
    cache = {"access_token": resp["access_token"], "expires_at": time.time() + resp.get("expires_in", 3600)}
    TOKEN_CACHE.write_text(json.dumps(cache))
    return resp["access_token"]

def tdx_get(url, token, params=None):
    # $format 必須直接附在 URL 上，不能透過 params dict（會被 encode 成 %24format）
    sep = "&" if "?" in url else "?"
    full_url = url + sep + "$format=JSON"
    r = requests.get(full_url, headers={
        "Authorization": f"Bearer {token}",
        "Accept-Encoding": "gzip",
    }, params=params or {}, timeout=15)
    r.raise_for_status()
    return r.json()

def fetch_nearby(lat, lon, radius, token):
    """取得附近路外停車場靜態資料（TDX Advanced NearBy API，最大 1000m）
    注意：TDX 文件 typo，正確參數是 $spatialFilter（不是 $spatailFilter）
    """
    from requests import Request, Session
    s = Session()
    base = "https://tdx.transportdata.tw/api/advanced/v1/Parking/OffStreet/CarPark/NearBy"
    req = Request("GET", base, headers={
        "Authorization": f"Bearer {token}",
        "Accept-Encoding": "gzip",
    })
    p = req.prepare()
    p.url = f"{base}?$format=JSON&$spatialFilter=nearby({lat}, {lon}, {radius})"
    r = s.send(p, timeout=15)
    r.raise_for_status()
    return r.json()

def fetch_availability(city, token):
    from requests import Request, Session
    s = Session()
    url = f"https://tdx.transportdata.tw/api/basic/v1/Parking/OffStreet/ParkingAvailability/City/{city}"
    req = Request("GET", url, headers={
        "Authorization": f"Bearer {token}",
        "Accept-Encoding": "gzip",
    })
    p = req.prepare()
    p.url = url + "?$format=JSON"
    r = s.send(p, timeout=15)
    r.raise_for_status()
    return r.json()

# ── Nominatim 地址反解（URL 無座標時的 fallback）────────────────────────────
def geocode_nominatim(address):
    """逐步縮短地址直到 Nominatim 找到結果（過濾郵遞區號和國名）"""
    parts = [p.strip() for p in re.split(r'[,，]', address) if p.strip()]
    # 過濾純數字（郵遞區號）和國名
    parts = [p for p in parts if not re.match(r'^\d+$', p) and p.lower() not in ("taiwan",)]
    for n in range(len(parts), max(0, len(parts) - 3), -1):
        candidate = ", ".join(parts[:n])
        if not candidate:
            continue
        try:
            r = requests.get(
                "https://nominatim.openstreetmap.org/search",
                params={"q": candidate, "format": "json", "limit": 1},
                headers={"User-Agent": "OpenClaw-parking_query/1.0"},
                timeout=10,
            )
            results = r.json()
            if results:
                return float(results[0]["lat"]), float(results[0]["lon"])
        except Exception as e:
            print(f"DEBUG: Nominatim geocoding failed: {e}", file=sys.stderr)
            break
    return None, None

# ── Google Maps URL 解析 ──────────────────────────────────────────────────────
def resolve_google_url(url):
    from urllib.parse import unquote_plus

    # 短網址先 follow redirect（用 GET 才能完整 follow Google 的 redirect chain）
    if "goo.gl" in url or "maps.app.goo.gl" in url:
        try:
            r = requests.get(url, allow_redirects=True, stream=True,
                             headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            r.close()
            url = r.url
        except Exception as e:
            print(f"DEBUG: Short URL redirect failed: {e}", file=sys.stderr)
            pass

    # 依序嘗試各種座標格式
    for pattern in [
        r'@(-?\d+\.\d+),(-?\d+\.\d+)',         # @lat,lon
        r'll=(-?\d+\.\d+),(-?\d+\.\d+)',        # ll=lat,lon
        r'[?&]q=(-?\d+\.\d+),(-?\d+\.\d+)',    # q=lat,lon
        r'place/[^/]+/@(-?\d+\.\d+),(-?\d+\.\d+)',  # place/@lat,lon
    ]:
        m = re.search(pattern, url)
        if m:
            return float(m.group(1)), float(m.group(2))

    # URL 無座標（如 ?q=地址&ftid=...）→ 用 Nominatim 反解 q= 地址
    m = re.search(r'[?&]q=([^&]+)', url)
    if m:
        address = unquote_plus(m.group(1))
        if address and not re.match(r'^-?\d+\.?\d*,-?\d+\.?\d*$', address):
            return geocode_nominatim(address)

    return None, None

# ── 導航連結 ──────────────────────────────────────────────────────────────────
def nav_links(lat, lon):
    apple  = f"https://maps.apple.com/?daddr={lat},{lon}&dirflg=d"
    google = f"https://www.google.com/maps/dir/?api=1&destination={lat},{lon}&travelmode=driving"
    return apple, google

# ── 主邏輯 ────────────────────────────────────────────────────────────────────
def find_parking(lat, lon, mode):
    token = get_token()

    # NearBy API 最大 1000m，先試 500 再試 1000
    parks = []
    radius_used = 500
    for radius in [500, 1000]:
        raw = fetch_nearby(lat, lon, radius, token)
        # NearBy 回傳格式：直接陣列 或 {"CarParks": [...]}
        parks = raw if isinstance(raw, list) else raw.get("CarParks", [])
        if parks:
            radius_used = radius
            break

    if not parks:
        print("😔 附近 1 公里內找不到停車場")
        return

    # 即時空位：city-based availability
    city = detect_city(lat, lon) or "未知地區"
    avail_map = {}
    if mode == "realtime":
        # 台北/新北相鄰，若偵測到台北但找不到資料，一併查新北（反之亦然）
        cities_to_try = [city] if city != "未知地區" else []
        if city == "Taipei":
            cities_to_try.append("NewTaipei")
        elif city == "NewTaipei":
            cities_to_try.append("Taipei")
        for c in cities_to_try:
            try:
                for a in fetch_availability(c, token).get("ParkingAvailabilities", []):
                    avail_map[a["CarParkID"]] = a
            except Exception:
                pass

    results = []
    for p in parks:
        pos = p.get("CarParkPosition") or {}
        plat = pos.get("PositionLat")
        plon = pos.get("PositionLon")
        park_id = p.get("CarParkID", "")
        name = p.get("CarParkName", {}).get("Zh_tw", park_id)
        address = p.get("Address", "")
        if isinstance(address, dict):
            address = address.get("Zh_tw", "")
        dist = haversine(lat, lon, plat, plon) if plat and plon else 0

        if mode == "realtime":
            avail = avail_map.get(park_id)
            if not avail:
                continue
            spaces = avail.get("AvailableSpaces")
            if not spaces or spaces <= 0:
                continue
            results.append({"name": name, "dist": dist, "spaces": spaces,
                             "lat": plat or lat, "lon": plon or lon, "address": address})
        else:
            results.append({"name": name, "dist": dist,
                             "lat": plat or lat, "lon": plon or lon, "address": address})

    results.sort(key=lambda x: x["dist"])
    results = results[:5]

    if not results:
        suffix = "有空位的" if mode == "realtime" else ""
        print(f"😔 附近 1 公里內找不到{suffix}停車場")
        return

    radius_label = f"{radius_used} 公尺"
    if mode == "realtime":
        print(f"🅿️ 附近 {radius_label} 有空位的停車場（{city}）\n")
    else:
        print(f"🅿️ 附近 {radius_label} 停車場（{city}）\n")

    for i, r in enumerate(results, 1):
        apple, google = nav_links(r["lat"], r["lon"])
        print(f"### {i}. {r['name']}")
        if mode == "realtime":
            print(f"**空位**：`{r['spaces']}` 個 ｜ **距離**：`{int(r['dist'])}` 公尺")
        else:
            print(f"**距離**：`{int(r['dist'])}` 公尺")
        if r["address"]:
            print(f"📍 {r['address']}")
        
        # 轉換為 Markdown inline links，取代長網址
        print(f"[🍎 Apple Maps 導航]({apple}) ｜ [🗺️ Google Maps 導航]({google})")
        print()

# ── CLI ───────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--lat",  type=str, default="")
    parser.add_argument("--lon",  type=str, default="")
    parser.add_argument("--url",  type=str, default="")
    parser.add_argument("--mode", choices=["realtime", "future"], default="realtime")
    args = parser.parse_args()

    lat = float(args.lat) if args.lat.strip() else None
    lon = float(args.lon) if args.lon.strip() else None

    if args.url:
        lat, lon = resolve_google_url(args.url)
        if lat is None or lon is None:
            sys.exit("❌ 無法從 URL 解析座標，請直接傳送定位點或完整 Google Maps 網址")

    if lat is None or lon is None:
        sys.exit("❌ 請提供 --lat / --lon 或 --url")

    find_parking(lat, lon, args.mode)

if __name__ == "__main__":
    main()
