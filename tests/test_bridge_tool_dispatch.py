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


def test_execute_llm_tool_call_parses_json_string_arguments(monkeypatch, tmp_path):
    """真實 OpenAI-compat API 回應的 arguments 是 JSON 字串，不是 dict"""
    captured_cmd = {}

    class FakeCompletedProcess:
        stdout = "測試避難所（0.1km）- 測試地址 容量約10人"

    def fake_run(cmd, capture_output, text, check):
        captured_cmd["cmd"] = cmd
        return FakeCompletedProcess()

    monkeypatch.setattr(bridge.subprocess, "run", fake_run)

    tool_call = types.SimpleNamespace(
        function=types.SimpleNamespace(
            name="find_shelter", arguments='{"lat": 25.03, "lon": 121.56}'
        )
    )
    result = bridge.execute_llm_tool_call(tool_call, is_online=True, localization_setting="TW")

    assert "--lat" in captured_cmd["cmd"]
    assert "25.03" in captured_cmd["cmd"]
    assert result["tool_output"] == FakeCompletedProcess.stdout
