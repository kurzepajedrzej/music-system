import asyncio
import re
import time
from urllib.parse import quote, urlparse

import httpx

from app import config

_client = httpx.AsyncClient(timeout=8.0)


class OwnToneError(Exception):
    def __init__(self, method: str, path: str, status_code: int):
        super().__init__(f"OwnTone {method} {path} -> {status_code}")
        self.status_code = status_code


async def close() -> None:
    # _client is a process-wide singleton, not scoped to a single app
    # lifespan. In production the process exits right after this runs, so
    # it would never matter either way — but this codebase's own test
    # suite (tests/routers/test_source.py) deliberately runs the real ASGI
    # lifespan multiple times per process via `with TestClient(app) as
    # client:` (see that file's docstring for why). Leaving _client closed
    # here means every OwnTone call after the first such lifespan cycle
    # raises RuntimeError, which broadcast_state() swallows silently —
    # manifesting as a hung `ws.receive_json()` in a later, unrelated test
    # rather than a clear failure. Recreating a fresh client keeps the
    # module usable across repeated startup/shutdown cycles.
    global _client
    await _client.aclose()
    _client = httpx.AsyncClient(timeout=8.0)


async def get(path: str) -> dict:
    r = await _client.get(f"{config.OWNTONE_URL}{path}")
    if r.status_code >= 400:
        raise OwnToneError("GET", path, r.status_code)
    return r.json()


async def put(path: str, body: dict | None = None) -> None:
    r = await _client.put(f"{config.OWNTONE_URL}{path}", json=body)
    if r.status_code >= 400:
        raise OwnToneError("PUT", path, r.status_code)


async def post(path: str) -> None:
    r = await _client.post(f"{config.OWNTONE_URL}{path}")
    if r.status_code >= 400:
        raise OwnToneError("POST", path, r.status_code)


async def delete(path: str) -> None:
    r = await _client.delete(f"{config.OWNTONE_URL}{path}")
    if r.status_code >= 400:
        raise OwnToneError("DELETE", path, r.status_code)


# ── Player ──────────────────────────────────────────────────────────────────

async def get_player() -> dict:
    return await get("/api/player")


async def player_command(cmd: str) -> None:
    await put(f"/api/player/{cmd}")


async def seek_to(position_ms: int) -> None:
    await put(f"/api/player/seek?position_ms={position_ms}")


async def set_player_volume(volume: int) -> None:
    # Like seek_to, this is one of OwnTone's query-param endpoints, not a
    # JSON body -- PUT /api/player {"volume": N} 400s.
    await put(f"/api/player/volume?volume={volume}")


# ── Queue ───────────────────────────────────────────────────────────────────

async def get_queue() -> dict:
    return await get("/api/queue")


async def clear_queue() -> None:
    await put("/api/queue/clear")


async def add_to_queue(uri: str, playback: str | None = None) -> None:
    params = f"uris={uri}"
    if playback:
        params += f"&playback={playback}"
    await post(f"/api/queue/items/add?{params}")


async def remove_queue_item(item_id: int) -> None:
    await delete(f"/api/queue/items/{item_id}")


async def play_queue_item(item_id: int) -> None:
    await put(f"/api/player/play?item_id={item_id}")


# ── Library ─────────────────────────────────────────────────────────────────

async def get_albums() -> dict:
    # OwnTone paginates at 1000 items per page; the old client hardcoded a
    # single limit=1000 request and silently truncated any library bigger
    # than that. This walks pages until it has everything.
    all_items: list[dict] = []
    offset = 0
    page_size = 1000
    while True:
        page = await get(f"/api/library/albums?offset={offset}&limit={page_size}")
        items = page.get("items", [])
        all_items.extend(items)
        if len(items) < page_size or len(all_items) >= page.get("total", len(all_items)):
            break
        offset += page_size
    return {"items": all_items}


async def get_album_tracks(album_id: str) -> dict:
    return await get(f"/api/library/albums/{album_id}/tracks")


async def search(query: str, type_: str = "tracks,albums") -> dict:
    # query has no reason to contain meaningful reserved characters, but
    # type_ is meant to contain literal commas (e.g. "tracks,albums") —
    # encoding the comma would change the semantic value OwnTone expects.
    encoded_query = quote(query, safe="")
    encoded_type = quote(type_, safe=",")
    return await get(f"/api/search?type={encoded_type}&query={encoded_query}")


# ── Outputs ─────────────────────────────────────────────────────────────────

async def get_outputs() -> dict:
    return await get("/api/outputs")


async def set_output(output_id: str, body: dict) -> None:
    await put(f"/api/outputs/{output_id}", body)


async def get_output_list() -> list[dict]:
    # For combined state snapshots: an outputs error means "no outputs",
    # never a failed snapshot -- player/queue/CD are still worth delivering.
    try:
        return (await get_outputs()).get("outputs", [])
    except Exception:
        return []


# ── Artwork ─────────────────────────────────────────────────────────────────
# OwnTone serves artwork from /artwork/..., not /api/artwork/..., and keys it
# by small internal ids (group/3, item/2) rather than the persistent album id
# the rest of the API uses. The ONLY correct mapping is each item's own
# artwork_url field — never trust a client-supplied path (that was the path
# traversal bug in the old artwork.ts).

async def get_artwork(path: str) -> httpx.Response:
    return await _client.get(f"{config.OWNTONE_URL}/{path}")


def _normalize_artwork_path(artwork_url: str) -> str:
    # NOTE: this is cosmetic (strips a leading "./" or "/"), not a security
    # boundary — it must never be relied on to neutralize a malformed path.
    # The actual safety check is _SAFE_ARTWORK_PATH below, applied at
    # resolve time.
    return artwork_url.lstrip("./")


# The only path shapes OwnTone is documented to publish in an album's
# artwork_url field. If OwnTone ever returned something else (misconfigured,
# compromised, or just a future API change we haven't accounted for), we must
# refuse to forward it rather than proxy an arbitrary internal OwnTone path
# back to an unauthenticated caller.
_SAFE_ARTWORK_PATH = re.compile(r"^artwork/(group|item)/\d+$")

_album_artwork_cache: dict | None = None
_ALBUM_ARTWORK_TTL_S = 60.0

# A miss forces a full paginated library refetch (see below) so a genuinely
# new album resolves promptly. But repeated misses against the same
# nonexistent id (unauthenticated, client-triggerable) must not be able to
# force unlimited full-library refetches against OwnTone — so forced
# refreshes are rate-limited independently of the normal cache TTL.
_last_forced_refresh_at: float = 0.0
_FORCED_REFRESH_MIN_INTERVAL_S = 5.0

# The rate limit above only gates the *decision* to force a refresh, and
# only helps when calls are effectively sequential (each one observes the
# previous one's write before deciding). Under real concurrency, many
# requests can each see a stale/empty cache and each start their own
# `get_albums()` call before any of them has finished repopulating the
# cache — the rate limit does nothing to stop that on its own.
#
# A plain asyncio.Lock around the refill closes that gap for the success
# case, but creates a worse one for the failure case: a Lock only serializes
# *turns*, so when get_albums() raises (OwnTone down/restarting), every
# waiter queued behind the lock gets its own turn and makes its own failing
# attempt, one after another — N concurrent callers during an outage means
# up to N sequential httpx timeouts (8s each) queued back to back, all
# reachable via this same unauthenticated route.
#
# A shared in-flight asyncio.Task avoids both problems: every concurrent
# caller awaits the *same* task, so a failure is delivered to all of them
# the instant the one real attempt fails (asyncio re-raises the same
# exception to every awaiter of a failed task — no retry-per-waiter), and
# because a fresh task is created per refill cycle rather than one
# long-lived lock object, there's no cross-event-loop binding concern either
# (a module-level asyncio.Lock() binds to whichever event loop first awaits
# it, which would break under multiple event loops in one process — not
# currently how this app runs, but worth avoiding while touching this code).
#
# Sharing one task between callers does mean cancellation has to be handled
# deliberately: awaiting a task directly makes the awaiter's cancellation
# propagate *into* the task, which would then deliver CancelledError to every
# other concurrent caller as well — one caller's timeout killing everybody
# else's request. asyncio.shield() below is what prevents that: a cancelled
# awaiter is detached from the shared task, and the task itself keeps running
# for the remaining waiters.
_album_artwork_refill_task: asyncio.Task | None = None


async def _album_artwork_paths() -> dict[str, str]:
    global _album_artwork_cache, _album_artwork_refill_task
    if _album_artwork_cache and time.monotonic() - _album_artwork_cache["at"] < _ALBUM_ARTWORK_TTL_S:
        return _album_artwork_cache["paths"]
    if _album_artwork_refill_task is None or _album_artwork_refill_task.done():
        # A previous refill task that reached a terminal state — completed,
        # raised, or was cancelled — is replaced here with a fresh one, so a
        # caller arriving afterwards gets a real retry rather than awaiting a
        # dead task. (.done() is True for all three of those states.)
        _album_artwork_refill_task = asyncio.ensure_future(_refill_album_artwork_cache())
    # shield: if *this* caller is cancelled (e.g. wrapped in asyncio.wait_for,
    # or its request's cancellation scope tears down), only this caller's
    # await is cancelled. Without the shield the cancellation would travel
    # into the shared task and be re-delivered to every other coroutine
    # awaiting it, turning one caller's cancellation into everyone's failure.
    return await asyncio.shield(_album_artwork_refill_task)


async def _refill_album_artwork_cache() -> dict[str, str]:
    global _album_artwork_cache
    albums = await get_albums()
    paths = {
        str(album["id"]): _normalize_artwork_path(album["artwork_url"])
        for album in albums.get("items", [])
        if album.get("artwork_url")
    }
    _album_artwork_cache = {"at": time.monotonic(), "paths": paths}
    return paths


async def resolve_album_artwork_path(album_id: str) -> str | None:
    global _album_artwork_cache, _last_forced_refresh_at
    paths = await _album_artwork_paths()
    if album_id not in paths:
        now = time.monotonic()
        if now - _last_forced_refresh_at >= _FORCED_REFRESH_MIN_INTERVAL_S:
            _last_forced_refresh_at = now
            _album_artwork_cache = None  # album may post-date the cache — refresh once
            paths = await _album_artwork_paths()

    path = paths.get(album_id)
    if path and not _SAFE_ARTWORK_PATH.match(path):
        # OwnTone published something we don't recognize as a safe artwork
        # path — refuse to forward it rather than trust it blindly.
        return None
    return path


# ── WebSocket URL discovery ─────────────────────────────────────────────────
# OwnTone exposes its WS port via /api/config -> websocket_port. If that
# lookup fails and OWNTONE_URL has no explicit port (e.g. just a hostname),
# fall back to OwnTone's documented default WS port (3688) rather than
# producing ws://host:NaN.

async def get_ws_url() -> str:
    if config.OWNTONE_WS_URL:
        return config.OWNTONE_WS_URL
    parsed = urlparse(config.OWNTONE_URL)
    try:
        cfg = await get("/api/config")
        return f"ws://{parsed.hostname}:{cfg['websocket_port']}"
    except Exception:
        fallback_port = parsed.port - 1 if parsed.port else 3688
        return f"ws://{parsed.hostname}:{fallback_port}"
