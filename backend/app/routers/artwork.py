from fastapi import APIRouter, HTTPException, Response

from app.owntone import client as owntone

router = APIRouter(prefix="/api/artwork", tags=["artwork"])

# OwnTone answers 204 when an item has no artwork; a Response carrying one of
# these statuses must not be given a body.
_NULL_BODY_STATUSES = {204, 205, 304}


@router.get("/album/{album_id}")
async def album_artwork(album_id: str, maxwidth: int | None = None, maxheight: int | None = None):
    # The only safe source of an artwork path is OwnTone's own artwork_url
    # field, resolved server-side — album_id never reaches the upstream URL.
    resolved = await owntone.resolve_album_artwork_path(album_id)
    if not resolved:
        raise HTTPException(404, "no artwork for this album")
    return await _stream(resolved, maxwidth, maxheight)


@router.get("/item/{item_id}")
async def item_artwork(item_id: int, maxwidth: int | None = None, maxheight: int | None = None):
    # item_id is typed as int by FastAPI's path converter, so anything
    # containing "/" or non-digit characters is a 422/404 before this runs.
    return await _stream(f"artwork/item/{item_id}", maxwidth, maxheight)


async def _stream(upstream_path: str, maxwidth: int | None, maxheight: int | None) -> Response:
    qs = ""
    if maxwidth or maxheight:
        parts = []
        if maxwidth:
            parts.append(f"maxwidth={maxwidth}")
        if maxheight:
            parts.append(f"maxheight={maxheight}")
        qs = "?" + "&".join(parts)

    try:
        upstream = await owntone.get_artwork(upstream_path + qs)
    except Exception:
        raise HTTPException(502, "artwork upstream unreachable")

    if upstream.status_code in _NULL_BODY_STATUSES:
        return Response(status_code=upstream.status_code)

    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type=upstream.headers.get("Content-Type", "image/jpeg"),
        headers={"Cache-Control": "public, max-age=86400"},
    )
