import re
import time
from urllib.parse import urlparse

import httpx

from app import config

_client = httpx.AsyncClient(timeout=8.0)


class OwnToneError(Exception):
    def __init__(self, method: str, path: str, status_code: int):
        super().__init__(f"OwnTone {method} {path} -> {status_code}")
        self.status_code = status_code


async def close() -> None:
    await _client.aclose()


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
    await put("/api/player", {"volume": volume})


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
    return await get(f"/api/search?type={type_}&query={query}")


# ── Outputs ─────────────────────────────────────────────────────────────────

async def get_outputs() -> dict:
    return await get("/api/outputs")


async def set_output(output_id: str, body: dict) -> None:
    await put(f"/api/outputs/{output_id}", body)


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


async def _album_artwork_paths() -> dict[str, str]:
    global _album_artwork_cache
    if _album_artwork_cache and time.monotonic() - _album_artwork_cache["at"] < _ALBUM_ARTWORK_TTL_S:
        return _album_artwork_cache["paths"]
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
