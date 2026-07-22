import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "tools" / "taiwan"))
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
