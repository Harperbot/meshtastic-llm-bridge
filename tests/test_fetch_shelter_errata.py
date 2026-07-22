import json

import fetch_shelter_errata

SAMPLE_CSV = (
    "Directory,勘誤,勘誤備註說明,序號,縣市 County,縣市及鄉鎮市區 County and Area,村里 Village,"
    "預計收容村里 Service Area,避難收容處所地址 Address,避難收容處所名稱 Shelter Name,"
    "適用災害類別 Disaster Categories,適合避難弱者安置 Shelter for Vulnerable People,"
    "室內 Indoor,室外 Outdoor,預計收容人數 Capacity,緯度,經度,管理人姓名,管理人電話,經緯度\n"
    ",位置有誤,備註,1,新竹縣,新竹縣,大隘村,大隘村,,五峰活動中心,水災,是,是,否,110,24.386,121.073,張兒,03-5851001,\n"
    ",[完成勘誤] 位置有誤,已修正,2,金門縣,金門縣,林湖村,林湖村,,林湖村辦公處,水災,是,是,否,30,24.4,118.2,林妙玲,082-364503,\n"
    ",只是漏字或多字,,3,苗栗縣,苗栗縣,,,,南坑村集會所,水災,否,否,否,20,24.6,121.0,葉貴霖,03-5805355,\n"
    ",,4,,,,,,,無勘誤標記的正常列,,,,,,,,,\n"
)


def test_parse_errata_rows_keeps_only_unresolved_location_errors():
    errata = fetch_shelter_errata.parse_errata_rows(SAMPLE_CSV)
    assert len(errata) == 1
    assert errata[0]["name"] == "五峰活動中心"
    assert errata[0]["lat"] == 24.386
    assert errata[0]["lon"] == 121.073


def test_main_creates_json_from_source_csv(tmp_path, monkeypatch):
    csv_path = tmp_path / "sample.csv"
    csv_path.write_text(SAMPLE_CSV, encoding="utf-8")
    output_path = tmp_path / "shelter_errata.json"

    monkeypatch.setattr(
        "sys.argv",
        ["fetch_shelter_errata.py", "--source-csv", str(csv_path), "--output", str(output_path)],
    )
    fetch_shelter_errata.main()

    data = json.loads(output_path.read_text(encoding="utf-8"))
    assert len(data["errata"]) == 1
    assert data["errata"][0]["name"] == "五峰活動中心"
