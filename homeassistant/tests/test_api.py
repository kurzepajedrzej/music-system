"""Tests for the music-system REST API client."""
from __future__ import annotations

import aiohttp
import pytest
import yarl
from aioresponses import aioresponses

from custom_components.music_system.api import MusicSystemApiClient, MusicSystemApiError


@pytest.fixture
def mock_aioresponse():
    # aioresponses 0.7.6-0.7.9 (latest on PyPI as of 2026-08) don't pass
    # `stream_writer` to ClientResponse.__init__, which aiohttp 3.14+
    # requires as a keyword-only argument. Patch it for the duration of
    # this fixture only — scoped and torn down, not global — so it can't
    # mask bugs in unrelated tests. Safe to remove once aioresponses ships
    # a fix for aiohttp>=3.14 (upstream issue, not our bug).
    import aiohttp.client_reqrep
    from unittest.mock import Mock

    original_init = aiohttp.client_reqrep.ClientResponse.__init__

    def patched_init(self, method, url, *, stream_writer=None, **kwargs):
        original_init(self, method, url, stream_writer=stream_writer or Mock(), **kwargs)

    aiohttp.client_reqrep.ClientResponse.__init__ = patched_init
    try:
        with aioresponses() as m:
            yield m
    finally:
        aiohttp.client_reqrep.ClientResponse.__init__ = original_init


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
        await client.async_player_set_volume(42)
        request = mock_aioresponse.requests[("PUT", yarl.URL("http://192.168.1.199:3000/api/player/volume"))][0]
        assert request.kwargs["json"] == {"volume": 42}


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


async def test_async_set_output_sends_only_the_fields_given(mock_aioresponse):
    url = "http://192.168.1.199:3000/api/outputs/132116595682064"
    mock_aioresponse.put(url, payload={"ok": True}, repeat=True)
    async with aiohttp.ClientSession() as session:
        client = MusicSystemApiClient(session, "192.168.1.199", 3000)
        await client.async_set_output("132116595682064", selected=True)
        await client.async_set_output("132116595682064", selected=False)
        await client.async_set_output("132116595682064", volume=42)
        calls = mock_aioresponse.requests[("PUT", yarl.URL(url))]
        # selected=False must be sent, not dropped as falsy -- it's how a speaker is deselected.
        assert [c.kwargs["json"] for c in calls] == [{"selected": True}, {"selected": False}, {"volume": 42}]
