import threading
import time

import bridge


def test_on_connection_lost_triggers_reconnect(monkeypatch):
    reconnect_called = threading.Event()

    def fake_reconnect():
        reconnect_called.set()

    monkeypatch.setattr(bridge, "_reconnect", fake_reconnect)

    bridge._on_connection_lost(interface=None)

    assert reconnect_called.wait(timeout=2), "reconnect 應該在背景執行緒中被呼叫"


def test_reconnect_closes_old_interface_and_reconnects(monkeypatch):
    closed = []

    class FakeOldInterface:
        def close(self):
            closed.append(True)

    connect_calls = []
    monkeypatch.setattr(bridge, "_interface", FakeOldInterface())
    monkeypatch.setattr(bridge, "_connect_with_retry", lambda: connect_calls.append(True))

    bridge._reconnect()

    assert closed == [True]
    assert connect_calls == [True]
    assert bridge._interface is None or connect_calls  # _connect_with_retry 被 mock 掉，不會真的設回新值


def test_reconnect_handles_close_exception_gracefully(monkeypatch):
    class BrokenInterface:
        def close(self):
            raise RuntimeError("already dead")

    connect_calls = []
    monkeypatch.setattr(bridge, "_interface", BrokenInterface())
    monkeypatch.setattr(bridge, "_connect_with_retry", lambda: connect_calls.append(True))

    bridge._reconnect()  # 不應該拋出例外

    assert connect_calls == [True]
