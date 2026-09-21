#!/bin/bash
# Builds a Docker image tagged <version>-<shortsha>[-dirty], derived from a
# service's VERSION file and its own git state, then records the tag in
# versions.env for compose to pick up via --env-file. Generic: works for any
# image name + build context, not just music-backend/music-frontend.
set -euo pipefail

if [ $# -ne 2 ]; then
    echo "Usage: $0 <image-name> <build-context-dir>" >&2
    exit 1
fi

IMAGE_NAME="$1"
CONTEXT_DIR="$2"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/../versions.env"

if ! [[ "$IMAGE_NAME" =~ ^[a-z0-9]([a-z0-9_.-]*[a-z0-9])?$ ]]; then
    echo "Error: invalid image name '${IMAGE_NAME}' (expected lowercase alphanumeric, optionally with -, _, . in the middle)" >&2
    exit 1
fi

if [ ! -f "$CONTEXT_DIR/VERSION" ]; then
    echo "Error: no VERSION file found at ${CONTEXT_DIR}/VERSION" >&2
    exit 1
fi

VERSION=$(tr -d '[:space:]' < "$CONTEXT_DIR/VERSION")

if ! [[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "Error: VERSION file at ${CONTEXT_DIR}/VERSION does not contain a bare semver string (got '${VERSION}')" >&2
    exit 1
fi

SHA=$(git -C "$CONTEXT_DIR" rev-parse --short HEAD)
if [ -n "$(git -C "$CONTEXT_DIR" status --porcelain -- .)" ]; then
    SHA="${SHA}-dirty"
fi

TAG="${VERSION}-${SHA}"

echo "Building ${IMAGE_NAME}:${TAG} from ${CONTEXT_DIR}..."
docker build -t "${IMAGE_NAME}:${TAG}" "${CONTEXT_DIR}"

VAR_NAME="$(echo "${IMAGE_NAME}" | tr '[:lower:]-' '[:upper:]_')_TAG"

if [ -f "$ENV_FILE" ] && grep -q "^${VAR_NAME}=" "$ENV_FILE"; then
    sed -i.bak "s|^${VAR_NAME}=.*|${VAR_NAME}=${TAG}|" "$ENV_FILE"
    rm -f "${ENV_FILE}.bak"
else
    if [ -f "$ENV_FILE" ] && [ -s "$ENV_FILE" ] && [ -n "$(tail -c1 "$ENV_FILE")" ]; then
        echo >> "$ENV_FILE"
    fi
    echo "${VAR_NAME}=${TAG}" >> "$ENV_FILE"
fi

echo "${VAR_NAME}=${TAG}"
