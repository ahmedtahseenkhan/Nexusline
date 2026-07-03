#!/usr/bin/env bash
# =============================================================================
# load-offline-bundle.sh
#
# Companion to build-offline-bundle.sh. Loads the saved Docker images from the
# offline bundle into the local Docker engine on an air-gapped host.
#
# Usage (from inside the extracted bundle directory):
#   ./deploy/load-offline-bundle.sh
#
# Or point it at an explicit images.tar:
#   ./deploy/load-offline-bundle.sh /path/to/images.tar
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- locate images.tar ------------------------------------------------------
# Priority: explicit arg > bundle root (deploy/..) > current dir.
if [[ "${1:-}" != "" ]]; then
  IMAGES_TAR="$1"
elif [[ -f "${SCRIPT_DIR}/../images.tar" ]]; then
  IMAGES_TAR="${SCRIPT_DIR}/../images.tar"
elif [[ -f "${PWD}/images.tar" ]]; then
  IMAGES_TAR="${PWD}/images.tar"
else
  echo "ERROR: images.tar not found." >&2
  echo "       Run this from inside the extracted bundle, or pass the path:" >&2
  echo "       ./deploy/load-offline-bundle.sh /path/to/images.tar" >&2
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: docker is not installed / not on PATH." >&2
  exit 1
fi

echo "==> Loading images from ${IMAGES_TAR}"
docker load -i "${IMAGES_TAR}"

echo
echo "==> Loaded images:"
docker images --format '    {{.Repository}}:{{.Tag}}  ({{.Size}})' \
  | grep -E 'nexusline-(api|web)|postgres|redis|nginx' || true

cat <<'EOF'

============================================================================
  Images loaded. Next steps:

    1. cp .env.example .env && edit .env      # secrets, DB creds, hostnames
    2. Place TLS certs in deploy/tls/         # fullchain.pem, privkey.pem
    3. docker compose -f docker-compose.prod.yml up -d
    4. docker compose -f docker-compose.prod.yml exec api alembic upgrade head

  Full runbook: docs/deployment.md
============================================================================
EOF
