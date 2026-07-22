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
