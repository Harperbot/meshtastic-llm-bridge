import bridge


class FakeInterface:
    def __init__(self):
        self.sent_texts = []
        self.sent_alerts = []
        self.nodes = {}

    def sendText(self, text, destinationId="^all", **kwargs):
        self.sent_texts.append((text, destinationId))

    def sendAlert(self, text, destinationId="^all", **kwargs):
        self.sent_alerts.append((text, destinationId))

    def close(self):
        pass


def test_send_meshtastic_message_uses_interface_sendtext(monkeypatch):
    fake = FakeInterface()
    monkeypatch.setattr(bridge, "_interface", fake)
    monkeypatch.setattr(bridge.time, "sleep", lambda *_: None)

    bridge.send_meshtastic_message("hello", destination_id="!abc123")

    assert fake.sent_texts == [("hello", "!abc123")]


def test_send_meshtastic_message_chunks_long_text(monkeypatch):
    fake = FakeInterface()
    monkeypatch.setattr(bridge, "_interface", fake)
    monkeypatch.setattr(bridge.time, "sleep", lambda *_: None)

    long_text = "x" * 500
    bridge.send_meshtastic_message(long_text, destination_id="^all")

    assert len(fake.sent_texts) == 3  # 500 / 220 -> 3 chunks
    assert fake.sent_texts[0][0].startswith("(1/3)")


def test_get_node_location_reads_from_interface_nodes(monkeypatch):
    fake = FakeInterface()
    fake.nodes["!d2d2a4e4"] = {"position": {"latitude": 25.03, "longitude": 121.56}}
    monkeypatch.setattr(bridge, "_interface", fake)

    (lat, lon), error = bridge.get_node_location("d2d2a4e4")

    assert error is None
    assert lat == 25.03
    assert lon == 121.56


def test_get_node_location_missing_position_returns_error(monkeypatch):
    fake = FakeInterface()
    fake.nodes["!d2d2a4e4"] = {}
    monkeypatch.setattr(bridge, "_interface", fake)

    result, error = bridge.get_node_location("d2d2a4e4")

    assert result is None
    assert error is not None


def test_send_meshtastic_message_noop_when_interface_none(monkeypatch, capsys):
    monkeypatch.setattr(bridge, "_interface", None)

    bridge.send_meshtastic_message("hello", destination_id="!abc123")

    captured = capsys.readouterr()
    assert "尚未連線" in captured.err


def test_send_meshtastic_alert_noop_when_interface_none(monkeypatch, capsys):
    monkeypatch.setattr(bridge, "_interface", None)

    bridge.send_meshtastic_alert("urgent", destination_id="!abc123")

    captured = capsys.readouterr()
    assert "尚未連線" in captured.err


def test_send_meshtastic_alert_truncates_by_utf8_bytes_not_chars(monkeypatch):
    fake = FakeInterface()
    monkeypatch.setattr(bridge, "_interface", fake)

    long_chinese_text = "緊急警報請立即撤離" * 40  # far more than 220 bytes in UTF-8
    bridge.send_meshtastic_alert(long_chinese_text, destination_id="^all")

    assert len(fake.sent_alerts) == 1
    sent_text = fake.sent_alerts[0][0]
    assert len(sent_text.encode("utf-8")) <= bridge.MAX_MESHTASTIC_PAYLOAD


def test_on_receive_dispatches_to_handler(monkeypatch):
    calls = []
    monkeypatch.setattr(
        bridge, "handle_incoming_meshtastic_message",
        lambda sender_id, text: calls.append((sender_id, text)),
    )

    packet = {"decoded": {"text": "hello"}, "fromId": "!d2d2a4e4"}
    bridge._on_receive(packet, interface=None)

    assert calls == [("!d2d2a4e4", "hello")]
