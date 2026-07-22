import bridge


def test_match_sos_command_bare():
    assert bridge._match_sos_command("SOS") == ""


def test_match_sos_command_with_message():
    assert bridge._match_sos_command("SOS 受困在二樓") == "受困在二樓"


def test_match_sos_command_case_insensitive():
    assert bridge._match_sos_command("sos help") == "help"


def test_match_sos_command_does_not_match_unrelated_text():
    assert bridge._match_sos_command("sosolution needed") is None
    assert bridge._match_sos_command("hello world") is None


def test_cooldown_allows_first_call_then_blocks_within_window(monkeypatch):
    fake_time = [1000.0]
    monkeypatch.setattr(bridge.time, "time", lambda: fake_time[0])
    last_ts_map = {}

    assert bridge._cooldown_allows("!abc", last_ts_map, 60) is True
    assert bridge._cooldown_allows("!abc", last_ts_map, 60) is False

    fake_time[0] += 61
    assert bridge._cooldown_allows("!abc", last_ts_map, 60) is True


def test_cooldown_is_per_node(monkeypatch):
    fake_time = [1000.0]
    monkeypatch.setattr(bridge.time, "time", lambda: fake_time[0])
    last_ts_map = {}

    assert bridge._cooldown_allows("!node1", last_ts_map, 60) is True
    assert bridge._cooldown_allows("!node2", last_ts_map, 60) is True  # 不同節點互不影響


def test_format_emergency_broadcast_with_known_location():
    text = bridge._format_emergency_broadcast(
        "sos", "!d2d2a4e4", (25.03, 121.56), "受困", "2026-07-22 10:00:00",
    )
    assert "🆘" in text
    assert "!d2d2a4e4" in text
    assert "25.03" in text
    assert "受困" in text


def test_format_emergency_broadcast_without_location():
    text = bridge._format_emergency_broadcast("sos", "!d2d2a4e4", None, "", "2026-07-22 10:00:00")
    assert "GPS 位置未知" in text


def test_handle_emergency_broadcast_calls_send_alert_for_sos(monkeypatch):
    sent = []
    monkeypatch.setattr(bridge, "get_node_location", lambda node_id: ((25.0, 121.0), None))
    monkeypatch.setattr(bridge, "send_meshtastic_alert", lambda text, destination_id: sent.append((text, destination_id)))
    monkeypatch.setattr(bridge, "_last_sos_ts", {})

    bridge._handle_emergency_broadcast("sos", "!d2d2a4e4", "受困")

    assert len(sent) == 1
    assert sent[0][1] == "^all"


def test_handle_emergency_broadcast_suppressed_within_cooldown(monkeypatch, capsys):
    sent = []
    monkeypatch.setattr(bridge, "get_node_location", lambda node_id: ((25.0, 121.0), None))
    monkeypatch.setattr(bridge, "send_meshtastic_alert", lambda text, destination_id: sent.append((text, destination_id)))
    monkeypatch.setattr(bridge, "_last_sos_ts", {"!d2d2a4e4": bridge.time.time()})

    bridge._handle_emergency_broadcast("sos", "!d2d2a4e4", "第二次")

    assert len(sent) == 0


def test_handle_emergency_broadcast_releases_cooldown_on_send_failure(monkeypatch):
    """傳送失敗（例如 reconnect window 造成的暫時性例外）不該讓 cooldown 卡住下一次真正的 SOS 重試。"""
    fake_time = [1000.0]
    monkeypatch.setattr(bridge.time, "time", lambda: fake_time[0])
    monkeypatch.setattr(bridge, "get_node_location", lambda node_id: ((25.0, 121.0), None))

    def _raise_alert(text, destination_id):
        raise RuntimeError("radio not connected")

    monkeypatch.setattr(bridge, "send_meshtastic_alert", _raise_alert)
    monkeypatch.setattr(bridge, "_last_sos_ts", {})

    bridge._handle_emergency_broadcast("sos", "!d2d2a4e4", "受困")

    # 傳送失敗後，cooldown 必須被釋放，node 不應殘留在 timestamp map 內
    assert "!d2d2a4e4" not in bridge._last_sos_ts

    # 因此立即重試也應被允許（不應被前一次失敗的嘗試卡住）
    assert bridge._cooldown_allows("!d2d2a4e4", bridge._last_sos_ts, 60) is True
