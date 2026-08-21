"""Shared constants for the Music System integration."""
from __future__ import annotations

DOMAIN = "music_system"
DEFAULT_PORT = 3000
MANUFACTURER = "music-system"

PLATFORMS: list[str] = ["media_player", "switch", "button", "number"]

# Seconds between WebSocket reconnect attempts — matches
# music-system/frontend/src/lib/liveState.tsx's own reconnect delay.
RECONNECT_DELAY = 3.0

# Seconds without a live WebSocket connection before entities go unavailable.
UNAVAILABLE_AFTER = 15.0
