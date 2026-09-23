import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.owntone.ws import OwnToneWS


class FakeWS:
    def __init__(self):
        self.closed = False
        self.sent_close = 0
        self.sent = []

    async def send(self, message):
        self.sent.append(message)

    async def close(self):
        self.sent_close += 1
        self.closed = True

    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration


async def test_reconnect_closes_old_socket_before_replacing():
    ws1 = FakeWS()
    ws2 = FakeWS()
    sockets = [ws2]

    async def fake_connect(url):
        return sockets.pop(0)

    owntone_ws = OwnToneWS(connect_fn=fake_connect, backoff_base=0.01, backoff_cap=0.02)
    owntone_ws._ws = ws1
    await owntone_ws._reconnect()

    assert ws1.closed is True
    assert owntone_ws._ws is ws2


async def test_notify_listeners_called_and_unsubscribe_works():
    received = []
    owntone_ws = OwnToneWS(connect_fn=AsyncMock())
    unsubscribe = owntone_ws.on_notify(lambda n: received.append(n))

    owntone_ws._dispatch(["player", "queue"])
    assert received == [["player", "queue"]]

    unsubscribe()
    owntone_ws._dispatch(["player"])
    assert received == [["player", "queue"]]


async def test_reconnect_subscribes_to_the_events_the_backend_reacts_to():
    # OwnTone pushes nothing until the client sends a {"notify": [...]} subscription.
    ws = FakeWS()

    async def fake_connect(url):
        return ws

    owntone_ws = OwnToneWS(connect_fn=fake_connect)
    await owntone_ws._reconnect()

    assert [json.loads(m) for m in ws.sent] == [{"notify": ["player", "queue", "outputs", "volume"]}]


async def test_default_connect_requests_the_notify_subprotocol(monkeypatch):
    calls = []

    async def fake_websockets_connect(url, **kwargs):
        calls.append((url, kwargs))
        return FakeWS()

    monkeypatch.setattr("app.owntone.ws.websockets.connect", fake_websockets_connect)
    await OwnToneWS._default_connect("ws://owntone:3688")

    assert calls == [("ws://owntone:3688", {"subprotocols": ["notify"]})]
