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


def test_on_receive_dispatches_to_handler(monkeypatch):
    calls = []
    monkeypatch.setattr(
        bridge, "handle_incoming_meshtastic_message",
        lambda sender_id, text: calls.append((sender_id, text)),
    )

    packet = {"decoded": {"text": "hello"}, "fromId": "!d2d2a4e4"}
    bridge._on_receive(packet, interface=None)

    assert calls == [("!d2d2a4e4", "hello")]
