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
