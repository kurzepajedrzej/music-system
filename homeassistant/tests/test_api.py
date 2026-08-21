"""Tests for the music-system REST API client."""
from __future__ import annotations

import aiohttp
import pytest
from aioresponses import aioresponses

from custom_components.music_system.api import MusicSystemApiClient, MusicSystemApiError


@pytest.fixture
def mock_aioresponse():
    with aioresponses() as m:
        yield m


def test_ws_url_derives_from_host_and_port():
    client = MusicSystemApiClient(session=None, host="192.168.1.199", port=3000)
    assert client.ws_url == "ws://192.168.1.199:3000/api/ws"
    assert client.base_url == "http://192.168.1.199:3000"


async def test_async_get_state_returns_parsed_json(mock_aioresponse):
    async with aiohttp.ClientSession() as session:
        client = MusicSystemApiClient(session, "192.168.1.199", 3000)
        mock_aioresponse.get(
            "http://192.168.1.199:3000/api/state",
            payload={"player": None, "queue": [], "currentTrack": None, "cd": {"state": "stopped"}, "timestamp": 1},
        )
        result = await client.async_get_state()
        assert result["cd"]["state"] == "stopped"


async def test_async_get_state_raises_on_http_error(mock_aioresponse):
    async with aiohttp.ClientSession() as session:
        client = MusicSystemApiClient(session, "192.168.1.199", 3000)
        mock_aioresponse.get("http://192.168.1.199:3000/api/state", status=503)
        with pytest.raises(MusicSystemApiError):
            await client.async_get_state()


async def test_async_get_state_raises_on_connection_error(mock_aioresponse):
    async with aiohttp.ClientSession() as session:
        client = MusicSystemApiClient(session, "192.168.1.199", 3000)
        mock_aioresponse.get("http://192.168.1.199:3000/api/state", exception=aiohttp.ClientConnectionError())
        with pytest.raises(MusicSystemApiError):
            await client.async_get_state()


async def test_async_cd_command_posts_to_correct_path(mock_aioresponse):
    async with aiohttp.ClientSession() as session:
        client = MusicSystemApiClient(session, "192.168.1.199", 3000)
        mock_aioresponse.post("http://192.168.1.199:3000/api/cd/play", payload={"state": "playing"})
        result = await client.async_cd_command("play")
        assert result["state"] == "playing"


async def test_async_cd_select_disc_posts_disc_number(mock_aioresponse):
    async with aiohttp.ClientSession() as session:
        client = MusicSystemApiClient(session, "192.168.1.199", 3000)
        mock_aioresponse.post("http://192.168.1.199:3000/api/cd/disc/3", payload={"disc": 3})
        result = await client.async_cd_select_disc(3)
        assert result["disc"] == 3


async def test_async_player_command_puts_to_correct_path(mock_aioresponse):
    async with aiohttp.ClientSession() as session:
        client = MusicSystemApiClient(session, "192.168.1.199", 3000)
        mock_aioresponse.put("http://192.168.1.199:3000/api/player/pause", payload={"state": "pause"})
        result = await client.async_player_command("pause")
        assert result["state"] == "pause"


async def test_async_player_set_volume_sends_json_body(mock_aioresponse):
    async with aiohttp.ClientSession() as session:
        client = MusicSystemApiClient(session, "192.168.1.199", 3000)
        mock_aioresponse.put("http://192.168.1.199:3000/api/player/volume", payload={"ok": True})
        # Just verify the call succeeds - the mock will only match if the correct method and path are used
        await client.async_player_set_volume(42)


async def test_async_source_cd_and_library_post_to_correct_paths(mock_aioresponse):
    async with aiohttp.ClientSession() as session:
        client = MusicSystemApiClient(session, "192.168.1.199", 3000)
        mock_aioresponse.post("http://192.168.1.199:3000/api/source/cd", payload={"state": "play"})
        mock_aioresponse.post("http://192.168.1.199:3000/api/source/library", payload={"state": "stop"})
        assert (await client.async_source_cd())["state"] == "play"
        assert (await client.async_source_library())["state"] == "stop"


async def test_async_get_health_returns_parsed_json(mock_aioresponse):
    async with aiohttp.ClientSession() as session:
        client = MusicSystemApiClient(session, "192.168.1.199", 3000)
        mock_aioresponse.get(
            "http://192.168.1.199:3000/api/health", payload={"owntone": True, "cd": True, "pipe": True}
        )
        result = await client.async_get_health()
        assert result["owntone"] is True
