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
    import urllib3
    # opdadm.moi.gov.tw 憑證缺 Subject Key Identifier，Python 3.14 嚴格模式拒連
    # （同 tools/taiwan 舊碼 CWA cwa_get() 遇過的同類政府網站憑證問題）
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    resp = requests.get(SHELTER_CSV_URL, timeout=30, verify=False)
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
