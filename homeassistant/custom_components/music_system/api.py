"""REST client for the music-system backend."""
from __future__ import annotations

from typing import Any

from aiohttp import ClientError, ClientSession


class MusicSystemApiError(Exception):
    """Raised when a call to the music-system backend fails."""


class MusicSystemApiClient:
    """Thin REST wrapper over music-system/backend's HTTP API."""

    def __init__(self, session: ClientSession, host: str, port: int) -> None:
        self._session = session
        self._base_url = f"http://{host}:{port}"

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def ws_url(self) -> str:
        return f"ws://{self._base_url.split('://', 1)[1]}/api/ws"

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            async with self._session.request(method, f"{self._base_url}{path}", **kwargs) as resp:
                if resp.status >= 400:
                    raise MusicSystemApiError(f"{method} {path} failed: HTTP {resp.status}")
                return await resp.json()
        except ClientError as err:
            raise MusicSystemApiError(f"{method} {path} failed: {err}") from err

    async def async_get_health(self) -> dict[str, Any]:
        return await self._request("GET", "/api/health")

    async def async_get_state(self) -> dict[str, Any]:
        return await self._request("GET", "/api/state")

    async def async_cd_command(self, cmd: str) -> dict[str, Any]:
        return await self._request("POST", f"/api/cd/{cmd}")

    async def async_cd_select_disc(self, disc: int) -> dict[str, Any]:
        return await self._request("POST", f"/api/cd/disc/{disc}")

    async def async_cd_select_track(self, track: int) -> dict[str, Any]:
        return await self._request("POST", f"/api/cd/track/{track}")

    async def async_player_command(self, cmd: str) -> dict[str, Any]:
        return await self._request("PUT", f"/api/player/{cmd}")

    async def async_player_set_volume(self, volume: int) -> None:
        await self._request("PUT", "/api/player/volume", json={"volume": volume})

    async def async_source_cd(self) -> dict[str, Any]:
        return await self._request("POST", "/api/source/cd")

    async def async_source_library(self) -> dict[str, Any]:
        return await self._request("POST", "/api/source/library")
