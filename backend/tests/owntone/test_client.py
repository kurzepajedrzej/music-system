import asyncio

import httpx
import pytest
import respx

from app import config
from app.owntone import client as owntone


@respx.mock
async def test_get_raises_on_non_2xx():
    respx.get(f"{config.OWNTONE_URL}/api/player").mock(
        return_value=httpx.Response(500)
    )
    with pytest.raises(owntone.OwnToneError):
        await owntone.get_player()


@respx.mock
async def test_put_raises_on_non_2xx_instead_of_silently_noop():
    route = respx.put(f"{config.OWNTONE_URL}/api/player/play").mock(
        return_value=httpx.Response(400)
    )
    with pytest.raises(owntone.OwnToneError):
        await owntone.player_command("play")
    assert route.called


@respx.mock
async def test_put_succeeds_on_2xx():
    respx.put(f"{config.OWNTONE_URL}/api/player/play").mock(
        return_value=httpx.Response(204)
    )
    await owntone.player_command("play")  # must not raise


def _reset_album_artwork_cache(monkeypatch):
    # _album_artwork_cache and _last_forced_refresh_at are module-level
    # globals shared across the whole test session — reset them so each
    # test's respx mocks are actually exercised instead of being silently
    # answered from another test's stale cached data.
    monkeypatch.setattr(owntone, "_album_artwork_cache", None)
    monkeypatch.setattr(owntone, "_last_forced_refresh_at", 0.0)


@respx.mock
async def test_resolve_album_artwork_path_uses_artwork_url_field_only(monkeypatch):
    _reset_album_artwork_cache(monkeypatch)
    respx.get(f"{config.OWNTONE_URL}/api/library/albums?offset=0&limit=1000").mock(
        return_value=httpx.Response(
            200,
            json={"total": 1, "items": [{"id": "42", "artwork_url": "/artwork/group/3"}]},
        )
    )
    path = await owntone.resolve_album_artwork_path("42")
    assert path == "artwork/group/3"


@respx.mock
async def test_resolve_album_artwork_path_returns_none_for_unknown_id(monkeypatch):
    _reset_album_artwork_cache(monkeypatch)
    respx.get(f"{config.OWNTONE_URL}/api/library/albums?offset=0&limit=1000").mock(
        return_value=httpx.Response(200, json={"total": 0, "items": []})
    )
    path = await owntone.resolve_album_artwork_path("nope")
    assert path is None


@respx.mock
async def test_resolve_album_artwork_path_rejects_malformed_artwork_url(monkeypatch):
    # lstrip("./") is cosmetic, not a security boundary. If OwnTone itself
    # ever published a malformed artwork_url (misconfigured, compromised, or
    # an API shape we didn't anticipate), resolve_album_artwork_path must
    # refuse to hand back anything that isn't one of the documented safe
    # shapes ("artwork/group/<digits>" or "artwork/item/<digits>") — not
    # proxy an arbitrary internal OwnTone path to an unauthenticated caller.
    _reset_album_artwork_cache(monkeypatch)
    respx.get(f"{config.OWNTONE_URL}/api/library/albums?offset=0&limit=1000").mock(
        return_value=httpx.Response(
            200,
            json={"total": 1, "items": [{"id": "99", "artwork_url": "/../../api/config"}]},
        )
    )
    path = await owntone.resolve_album_artwork_path("99")
    assert path is None


@respx.mock
async def test_resolve_album_artwork_path_rate_limits_forced_refresh_on_repeated_miss(monkeypatch):
    # A miss forces one full paginated library refetch so a genuinely new
    # album resolves promptly. Repeated misses against the same (possibly
    # nonexistent) id — reachable via unauthenticated client input to the
    # artwork router — must not each force their own full refetch.
    _reset_album_artwork_cache(monkeypatch)
    route = respx.get(f"{config.OWNTONE_URL}/api/library/albums?offset=0&limit=1000").mock(
        return_value=httpx.Response(200, json={"total": 0, "items": []})
    )
    for _ in range(5):
        assert await owntone.resolve_album_artwork_path("nonexistent") is None
    # One request for the initial (empty) cache fill, one forced refresh
    # from the first miss — the remaining four misses land inside the
    # rate-limit window and must not trigger any more.
    assert route.call_count == 2


async def test_concurrent_cache_misses_trigger_only_one_refetch(monkeypatch):
    # The rate-limit interval above only gates the *decision* to force a
    # refresh, and only helps against effectively-sequential calls (each one
    # observes the previous one's write before deciding). Under real
    # concurrency, many requests can each see a stale/empty cache and each
    # start their own get_albums() call before any of them has finished
    # repopulating the cache — proven against a real threaded server in the
    # security review (120 refetches from 3 bursts of 40 concurrent misses).
    # _album_artwork_refill_lock makes the actual refill single-flight: this
    # test proves that regardless of how many coroutines race in at once,
    # only one of them actually calls get_albums().
    #
    # respx's mocked transport doesn't yield control to the event loop the
    # way real I/O does, which would make concurrent calls behave as if
    # sequential and mask this exact bug — so this monkeypatches
    # get_albums() directly with a coroutine that does a real asyncio.sleep,
    # guaranteeing genuine interleaving among the gathered calls.
    _reset_album_artwork_cache(monkeypatch)
    call_count = {"n": 0}

    async def slow_get_albums():
        call_count["n"] += 1
        await asyncio.sleep(0.05)
        return {"items": [{"id": "1", "artwork_url": "/artwork/group/1"}]}

    monkeypatch.setattr(owntone, "get_albums", slow_get_albums)

    results = await asyncio.gather(*[owntone._album_artwork_paths() for _ in range(20)])
    assert call_count["n"] == 1
    assert all(r == {"1": "artwork/group/1"} for r in results)


@respx.mock
async def test_get_albums_paginates_past_the_1000_item_page_size():
    page1_items = [{"id": str(i)} for i in range(1000)]
    page2_items = [{"id": "1000"}]
    respx.get(f"{config.OWNTONE_URL}/api/library/albums?offset=0&limit=1000").mock(
        return_value=httpx.Response(200, json={"total": 1001, "items": page1_items})
    )
    respx.get(f"{config.OWNTONE_URL}/api/library/albums?offset=1000&limit=1000").mock(
        return_value=httpx.Response(200, json={"total": 1001, "items": page2_items})
    )
    result = await owntone.get_albums()
    assert len(result["items"]) == 1001
    assert result["items"][-1]["id"] == "1000"


@respx.mock
async def test_get_albums_single_page_makes_one_request():
    route = respx.get(f"{config.OWNTONE_URL}/api/library/albums?offset=0&limit=1000").mock(
        return_value=httpx.Response(200, json={"total": 3, "items": [{"id": "1"}, {"id": "2"}, {"id": "3"}]})
    )
    result = await owntone.get_albums()
    assert len(result["items"]) == 3
    assert route.call_count == 1


async def test_get_ws_url_uses_explicit_env_var(monkeypatch):
    monkeypatch.setattr(config, "OWNTONE_WS_URL", "ws://explicit:1234")
    assert await owntone.get_ws_url() == "ws://explicit:1234"


@respx.mock
async def test_get_ws_url_fallback_handles_missing_port(monkeypatch):
    monkeypatch.setattr(config, "OWNTONE_WS_URL", "")
    monkeypatch.setattr(config, "OWNTONE_URL", "http://owntonehost")
    respx.get("http://owntonehost/api/config").mock(
        return_value=httpx.Response(500)
    )
    url = await owntone.get_ws_url()
    assert url == "ws://owntonehost:3688"
