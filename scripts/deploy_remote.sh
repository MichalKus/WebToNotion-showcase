#!/bin/bash
# VPS-side deployment: pull the pinned image, recreate the container, verify it
# actually serves traffic, and roll back to the previous image on failure.
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"

ENV_FILE="$APP_DIR/.env"

# --- BEGIN HELPERS ---

# Read a single key from a .env file WITHOUT interpreting the file as shell.
# The file holds live API keys; sourcing it would execute any value containing
# command substitution. Only known-safe deployment config is read this way.
read_env_var() {
    local env_file="$1"
    local key="$2"
    local line value

    [ -f "$env_file" ] || return 0

    line="$(grep -E "^[[:space:]]*${key}=" "$env_file" | tail -n 1 || true)"
    [ -n "$line" ] || return 0

    value="${line#*=}"
    # Strip one layer of matching surrounding quotes.
    if [[ "$value" == \'*\' ]]; then
        value="${value:1:${#value}-2}"
    elif [[ "$value" == \"*\" ]]; then
        value="${value:1:${#value}-2}"
    fi
    printf '%s' "$value"
}

# Prefer a value already exported by the CI runner; fall back to the .env file.
resolve_config() {
    local key="$1"
    local current="${!key:-}"
    if [ -n "$current" ]; then
        printf '%s' "$current"
    else
        read_env_var "$ENV_FILE" "$key"
    fi
}

# --- END HELPERS ---

if [ ! -f "$ENV_FILE" ]; then
    echo "❌ Error: .env file not found in $APP_DIR"
    exit 1
fi

# The file arrives over scp with the umask of the CI runner. Lock it down
# before anything else reads it (review C4).
chmod 600 "$ENV_FILE"
echo "✅ Configuration file found and secured (600)"

# Serialize concurrent runs against the same directory (review R10).
exec 9>"$APP_DIR/.deploy.lock"
if ! flock -n 9; then
    echo "❌ Another deployment is already running in $APP_DIR"
    exit 1
fi

WEBTONOTION_IMAGE="$(resolve_config WEBTONOTION_IMAGE)"
PORT="$(resolve_config PORT)"
COMPOSE_PROJECT_NAME="$(resolve_config COMPOSE_PROJECT_NAME)"
CACHE_VOLUME_NAME="$(resolve_config CACHE_VOLUME_NAME)"
export WEBTONOTION_IMAGE PORT COMPOSE_PROJECT_NAME CACHE_VOLUME_NAME

for required in WEBTONOTION_IMAGE PORT COMPOSE_PROJECT_NAME CACHE_VOLUME_NAME; do
    if [ -z "${!required}" ]; then
        echo "::error::Required deployment variable $required is not set"
        exit 1
    fi
done

CONTAINER_NAME="$COMPOSE_PROJECT_NAME"
HEALTH_CHECK_URL="http://localhost:${PORT}/api/v1/health/"
# Named to avoid colliding with the application's own MAX_RETRIES (review R11).
HEALTH_MAX_RETRIES=30
HEALTH_RETRY_DELAY=2

IS_PROD=false
if [[ "$COMPOSE_PROJECT_NAME" == *"prod"* ]]; then
    IS_PROD=true
fi

echo "🚀 Starting deployment..."
echo "📂 Target Directory: $APP_DIR"
echo "🔧 Project Name:     $COMPOSE_PROJECT_NAME"
echo "🔌 Port:             $PORT"
echo "💾 Cache Volume:     $CACHE_VOLUME_NAME"
echo "📦 Image:            $WEBTONOTION_IMAGE"
echo "🏭 Production:       $IS_PROD"

# 1. Bootstrap external resources. The compose file declares the network and
# cache volume as external, so a clean VPS fails without these (review #8).
if ! docker network inspect app-network >/dev/null 2>&1; then
    echo "🌐 Creating missing network: app-network"
    docker network create --driver bridge app-network
fi

if ! docker volume inspect "$CACHE_VOLUME_NAME" >/dev/null 2>&1; then
    echo "💾 Creating missing volume: $CACHE_VOLUME_NAME"
    docker volume create "$CACHE_VOLUME_NAME"
fi

# Compose bind-mounts ./cookies.txt; if it is absent Docker silently creates a
# *directory* there, which entrypoint.sh's [ -f ] test then skips, costing
# yt-dlp its authentication with no error (review R3).
if [ ! -e "$APP_DIR/cookies.txt" ]; then
    echo "🍪 cookies.txt absent - creating empty placeholder file"
    touch "$APP_DIR/cookies.txt"
elif [ -d "$APP_DIR/cookies.txt" ]; then
    echo "::warning::cookies.txt exists as a directory - Docker created it from a"
    echo "::warning::missing bind mount. Remove it and supply the real file."
fi

# 2. Capture the running image ID for rollback. {{.Image}} is the immutable
# local ID; {{.Config.Image}} would be the tag, which `compose pull` overwrites
# moments later, making rollback a no-op (review #6).
ROLLBACK_IMAGE=""
if [ "$IS_PROD" = true ] && docker inspect "$CONTAINER_NAME" >/dev/null 2>&1; then
    ROLLBACK_IMAGE="$(docker inspect --format '{{.Image}}' "$CONTAINER_NAME" 2>/dev/null || true)"
    if [ -n "$ROLLBACK_IMAGE" ]; then
        echo "📸 Rollback target captured: $ROLLBACK_IMAGE"
    fi
fi

# 3. Pull and recreate.
if [ -n "${DOCKERHUB_USERNAME:-}" ] && [ -n "${DOCKERHUB_TOKEN:-}" ]; then
    echo "🔑 Logging into Docker Hub..."
    echo "$DOCKERHUB_TOKEN" | docker login -u "$DOCKERHUB_USERNAME" --password-stdin
fi

echo "⬇️  Pulling image..."
docker compose pull webtonotion

echo "♻️  Recreating container..."
if ! docker compose up -d --force-recreate --no-deps webtonotion; then
    echo "::error::docker compose up failed"
    exit 1
fi

# 4. Health check. Polls the HTTP endpoint directly rather than Docker's health
# status, which stays "starting" until the first scheduled probe (review C1).
# Runs in BOTH environments so a crash-looping dev container is not reported
# as a success (review R4).
check_health() {
    local i status
    for i in $(seq 1 "$HEALTH_MAX_RETRIES"); do
        if curl -sf --max-time 5 "$HEALTH_CHECK_URL" >/dev/null 2>&1; then
            echo "✅ Health check passed on attempt $i"
            return 0
        fi
        status="$(docker inspect --format '{{.State.Status}}' "$CONTAINER_NAME" 2>/dev/null || echo "missing")"
        if [ "$status" != "running" ]; then
            echo "❌ Container is not running (state: $status)"
            return 1
        fi
        echo "⏳ Waiting for service... ($i/$HEALTH_MAX_RETRIES)"
        sleep "$HEALTH_RETRY_DELAY"
    done
    echo "❌ Health check timed out after $((HEALTH_MAX_RETRIES * HEALTH_RETRY_DELAY))s"
    return 1
}

echo "🩺 Checking health at $HEALTH_CHECK_URL"
if check_health; then
    echo "✨ Deployment successful"
    docker image prune -f
    exit 0
fi

echo "::error::Health check failed"
docker logs --tail 50 "$CONTAINER_NAME" 2>&1 || true

# 5. Rollback (prod only). Rolls back by image ID and re-verifies, rather than
# declaring success the moment `up` returns (review R5).
if [ "$IS_PROD" != true ]; then
    echo "::error::Dev deployment failed health check"
    exit 1
fi

if [ -z "$ROLLBACK_IMAGE" ]; then
    echo "::error::No previous image captured - cannot roll back"
    exit 1
fi

echo "🔄 Rolling back to $ROLLBACK_IMAGE..."
# Rewrite the pin in place. No pull: the ID exists only in the local daemon.
if grep -qE "^[[:space:]]*WEBTONOTION_IMAGE=" "$ENV_FILE"; then
    sed -i "s|^[[:space:]]*WEBTONOTION_IMAGE=.*|WEBTONOTION_IMAGE='${ROLLBACK_IMAGE}'|" "$ENV_FILE"
else
    printf "WEBTONOTION_IMAGE='%s'\n" "$ROLLBACK_IMAGE" >> "$ENV_FILE"
fi
export WEBTONOTION_IMAGE="$ROLLBACK_IMAGE"

if ! docker compose up -d --force-recreate --no-deps webtonotion; then
    echo "::error::Rollback failed to start the previous image - service is DOWN"
    exit 1
fi

if check_health; then
    echo "::warning::Deployment failed; rolled back to $ROLLBACK_IMAGE and verified healthy"
    exit 1
fi

echo "::error::Rollback started but did not become healthy - service is DOWN"
exit 1
