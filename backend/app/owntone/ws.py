import asyncio
import json
import logging
from typing import Callable

import websockets

from app.owntone.client import get_ws_url

log = logging.getLogger(__name__)

Listener = Callable[[list[str]], None]


class OwnToneWS:
    def __init__(
        self,
        connect_fn=None,
        backoff_base: float = 1.0,
        backoff_cap: float = 30.0,
    ):
        self._connect_fn = connect_fn or self._default_connect
        self._backoff_base = backoff_base
        self._backoff_cap = backoff_cap
        self._ws = None
        self._listeners: set[Listener] = set()
        self._task: asyncio.Task | None = None
        self._stopped = False

    @staticmethod
    async def _default_connect(url: str):
        return await websockets.connect(url)

    def on_notify(self, fn: Listener) -> Callable[[], None]:
        self._listeners.add(fn)
        return lambda: self._listeners.discard(fn)

    def _dispatch(self, notifications: list[str]) -> None:
        for fn in list(self._listeners):
            fn(notifications)

    def start(self) -> None:
        self._stopped = False
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stopped = True
        if self._task:
            self._task.cancel()
        if self._ws is not None:
            await self._ws.close()

    async def _reconnect(self) -> None:
        if self._ws is not None:
            await self._ws.close()
        url = await get_ws_url()
        log.info("[owntone-ws] connecting to %s", url)
        self._ws = await self._connect_fn(url)
        log.info("[owntone-ws] connected")

    async def _run(self) -> None:
        delay = self._backoff_base
        while not self._stopped:
            try:
                await self._reconnect()
                delay = self._backoff_base
                async for raw in self._ws:
                    try:
                        data = json.loads(raw)
                        if "notify" in data:
                            self._dispatch(data["notify"])
                    except (json.JSONDecodeError, KeyError):
                        continue
            except asyncio.CancelledError:
                return
            except Exception as e:
                log.info("[owntone-ws] closed, reconnecting in %.1fs: %s", delay, e)
            if self._stopped:
                return
            await asyncio.sleep(delay)
            delay = min(delay * 2, self._backoff_cap)


owntone_ws = OwnToneWS()
