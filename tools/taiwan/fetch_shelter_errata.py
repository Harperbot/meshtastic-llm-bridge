#!/usr/bin/env python3
"""避難收容處所座標勘誤清單 ETL — 下載社群（WaytoSafety）勘誤試算表，
篩出尚未修正的「位置有誤」列，供 shelter_query.py 查詢時加註警告。
用法:
  fetch_shelter_errata.py                          # 從社群試算表下載
  fetch_shelter_errata.py --source-csv local.csv   # 從本地 CSV 轉換（測試/離線用）
"""
import argparse
import csv
import io
import json
from pathlib import Path

ERRATA_CSV_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "1l_Au7txDgsknhHKvhLksfSAzeMmSoaih3m4pMdqwrBU/export?format=csv"
)
OUTPUT_FILE = Path(__file__).parent / "shelter_errata.json"


def parse_errata_rows(csv_text: str) -> list:
    """篩出勘誤欄位精確等於「位置有誤」（尚未標記 [完成勘誤]）的列"""
    reader = csv.DictReader(io.StringIO(csv_text))
    errata = []
    for row in reader:
        if row.get("勘誤", "").strip() != "位置有誤":
            continue
        name = row.get("避難收容處所名稱 Shelter Name", "").strip()
        if not name:
            continue
        try:
            lat = float(row["緯度"])
            lon = float(row["經度"])
        except (KeyError, ValueError, TypeError):
            continue
        errata.append({"name": name, "lat": lat, "lon": lon})
    return errata


def fetch_csv_text(source_csv: str | None) -> str:
    if source_csv:
        with open(source_csv, encoding="utf-8") as f:
            return f.read()
    import requests
    resp = requests.get(ERRATA_CSV_URL, timeout=30)
    resp.raise_for_status()
    return resp.content.decode("utf-8")


def main():
    parser = argparse.ArgumentParser(description="避難所座標勘誤清單 ETL")
    parser.add_argument("--source-csv", help="從本地 CSV 檔轉換，不從網路下載")
    parser.add_argument("--output", default=str(OUTPUT_FILE), help="輸出 JSON 路徑")
    args = parser.parse_args()

    csv_text = fetch_csv_text(args.source_csv)
    errata = parse_errata_rows(csv_text)

    output_path = Path(args.output)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({"errata": errata}, f, ensure_ascii=False, indent=2)

    print(f"已寫入 {len(errata)} 筆座標勘誤紀錄至 {output_path}")


if __name__ == "__main__":
    main()
