#!/bin/bash
set -e

# Handle cookies.txt permissions securely
# We copy the secret to a temporary location owned by appuser
# This ensures access regardless of host file permissions
if [ -f "/app/cookies.txt" ]; then
    echo "Found cookies.txt, securing permissions..."
    # Copy to temp dir which is already owned by appuser (created in Dockerfile)
    cp /app/cookies.txt /app/temp/cookies_secure.txt
    chown appuser:appuser /app/temp/cookies_secure.txt
    chmod 644 /app/temp/cookies_secure.txt

    # Override the environment variable to point to the secure copy
    export COOKIES_FILE_PATH="/app/temp/cookies_secure.txt"
fi

# Execute the CMD passed to docker run/compose as appuser
# using gosu to drop root privileges
exec gosu appuser "$@"
