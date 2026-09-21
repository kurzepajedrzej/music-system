#!/bin/bash
# Music-system startup script -- warns if expected music hardware is
# missing, then starts the music stack. A missing device doesn't change
# which containers start; it only produces a warning here plus a visibly
# failing audio-capture/music-backend container (see music-system/CLAUDE.md
# "Deploying changes" for exactly how each one fails).
set -euo pipefail

COMPOSE_FILE="/root/Projects/music-system/docker-compose.yml"
ENV_FILE="/root/Projects/music-system/versions.env"

echo "=== Music-system startup ==="

# Behringer UCA202 never reports "UCA202" in its own USB/ALSA identification
# -- it enumerates generically via its Burr-Brown/TI codec chip, as ALSA
# card "CODEC" / "USB Audio CODEC" (confirmed against the real device:
# `arecord -l` -> "card 2: CODEC [USB Audio CODEC] ...").
if arecord -l 2>/dev/null | grep -qi "USB Audio CODEC"; then
    echo "[+] Behringer UCA202 detected"
else
    echo "[!] WARNING: Behringer UCA202 not detected — audio-capture will fail to start"
fi

if [ -e /dev/ttyUSB0 ]; then
    echo "[+] USB serial adapter at /dev/ttyUSB0 detected"
else
    echo "[!] WARNING: /dev/ttyUSB0 not found — music-backend's CD control will fail to start"
fi

docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" up -d --remove-orphans
