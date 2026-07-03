#!/usr/bin/env bash
# =============================================================================
# build-offline-bundle.sh
#
# Builds every image the on-prem stack needs and packages them — together with
# the production compose file, .env.example, and the deploy/ directory — into a
# single self-contained tarball. Copy that tarball to an air-gapped host, run
# deploy/load-offline-bundle.sh, then `docker compose -f docker-compose.prod.yml up -d`.
#
# Usage:
#   ./deploy/build-offline-bundle.sh [VERSION]
#   VERSION=1.2.0 ./deploy/build-offline-bundle.sh
#
# Run from a machine WITH internet + Docker (to pull base images and build).
# =============================================================================
set -euo pipefail

# --- resolve paths (script lives in deploy/, project root is one level up) ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${ROOT_DIR}"

# --- version: arg > env > default ------------------------------------------
VERSION="${1:-${VERSION:-1.0.0}}"

COMPOSE_FILE="docker-compose.prod.yml"
API_IMAGE="nexusline-api:${VERSION}"
WEB_IMAGE="nexusline-web:${VERSION}"

# Third-party images that must ride along in the bundle (kept in sync with the
# compose file). Update here if you bump a pinned base image.
BASE_IMAGES=(
  "postgres:16-alpine"
  "redis:7-alpine"
  "nginx:1.27-alpine"
)

BUNDLE_NAME="nexusline-offline-${VERSION}"
STAGE_DIR="${ROOT_DIR}/${BUNDLE_NAME}"
TARBALL="${ROOT_DIR}/${BUNDLE_NAME}.tar.gz"

echo "==> Building NexusLine offline bundle ${VERSION}"
echo "    project root : ${ROOT_DIR}"
echo "    api image    : ${API_IMAGE}"
echo "    web image    : ${WEB_IMAGE}"
echo

# --- 1. pull pinned base images (so the exact versions land in the tar) -----
echo "==> Pulling base images"
for img in "${BASE_IMAGES[@]}"; do
  echo "    - ${img}"
  docker pull "${img}"
done

# --- 2. build the application images with deterministic tags ----------------
echo
echo "==> Building application images"
API_IMAGE="${API_IMAGE}" WEB_IMAGE="${WEB_IMAGE}" \
  docker compose -f "${COMPOSE_FILE}" build

# Also tag :latest so the compose default (${API_IMAGE:-nexusline-api:latest})
# resolves on the air-gapped host without any extra env.
docker tag "${API_IMAGE}" "nexusline-api:latest"
docker tag "${WEB_IMAGE}" "nexusline-web:latest"

# --- 3. save all images into one tar ----------------------------------------
echo
echo "==> Saving images (this can take a few minutes)"
rm -rf "${STAGE_DIR}"
mkdir -p "${STAGE_DIR}"

docker save -o "${STAGE_DIR}/images.tar" \
  "${BASE_IMAGES[@]}" \
  "${API_IMAGE}" "nexusline-api:latest" \
  "${WEB_IMAGE}" "nexusline-web:latest"

# --- 4. copy the deploy artifacts alongside the images ----------------------
echo "==> Staging compose file, env template, and deploy/"
cp "${COMPOSE_FILE}"        "${STAGE_DIR}/"
cp ".env.example"           "${STAGE_DIR}/"
cp -R "deploy"              "${STAGE_DIR}/deploy"
# Do not ship any real key material or leftover archives.
rm -f "${STAGE_DIR}/deploy/license.key" "${STAGE_DIR}/deploy/license_pubkey.pem" 2>/dev/null || true
echo "${VERSION}" > "${STAGE_DIR}/VERSION"

# --- 5. compress the whole thing --------------------------------------------
echo "==> Compressing -> ${TARBALL}"
rm -f "${TARBALL}"
tar -C "${ROOT_DIR}" -czf "${TARBALL}" "${BUNDLE_NAME}"
rm -rf "${STAGE_DIR}"

BUNDLE_SIZE="$(du -h "${TARBALL}" | cut -f1)"

cat <<EOF

============================================================================
  Offline bundle ready:  ${TARBALL}  (${BUNDLE_SIZE})
============================================================================
Next steps (on the AIR-GAPPED host):

  1. Copy ${BUNDLE_NAME}.tar.gz to the target host (USB / approved transfer).
  2. tar -xzf ${BUNDLE_NAME}.tar.gz && cd ${BUNDLE_NAME}
  3. ./deploy/load-offline-bundle.sh            # docker load all images
  4. cp .env.example .env && edit .env          # secrets, DB creds, hostnames
  5. Place TLS certs in deploy/tls/ (fullchain.pem, privkey.pem)
  6. docker compose -f docker-compose.prod.yml up -d

See docs/deployment.md for the full runbook.
============================================================================
EOF
