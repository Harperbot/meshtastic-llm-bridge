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
