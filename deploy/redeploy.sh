#!/usr/bin/env bash
#
# Rebuild and restart the running stack, then prove the new code is actually
# being served. Run it from the repository root:
#
#     bash deploy/redeploy.sh
#
# Every step that can silently do nothing is checked. The three failure modes
# this exists to tell apart:
#
#   * the image was rebuilt but the container was not replaced (compose does not
#     always recreate when the image tag is unchanged — force-recreate below);
#   * the container serves the new build but the public URL does not, which means
#     a cache or CDN in front of the origin is holding the old page;
#   * the source on this machine never changed, i.e. the pull did not land.
#
set -uo pipefail

COMPOSE="docker compose -f docker-compose.prod.yml"
RECLAIM=0
FORCE=0
SERVICES=""
while [ $# -gt 0 ]; do
  case "$1" in
    --reclaim) RECLAIM=1 ;;
    --force)   FORCE=1 ;;                 # build anyway, whatever the free space
    api|web)   SERVICES="$SERVICES $1" ;; # build just this one — far less headroom
    *) echo "usage: bash deploy/redeploy.sh [--reclaim] [--force] [api] [web]"; exit 2 ;;
  esac
  shift
done
SERVICES="${SERVICES:-api web}"
SERVICES="${SERVICES# }"

# Building both images at once needs room for two new images beside the two old
# ones. One at a time needs far less, which matters on a small root disk.
case "$SERVICES" in
  "api web"|"web api") MIN_FREE_MB=6000 ;;
  *)                   MIN_FREE_MB=2500 ;;
esac
MARKER="Needs a decision or is overdue"   # only in the rebuilt dashboard
say() { printf '\n\033[1m== %s\033[0m\n' "$1"; }

say "1/6  Pulling"
git pull origin main || { echo "git pull failed — resolve that first."; exit 1; }
echo "HEAD is now: $(git log --oneline -1)"

say "2/6  Checking the source on disk"
if ! grep -q "$MARKER" "frontend/app/(app)/dashboard/page.tsx"; then
  echo "FAIL: the new dashboard is not in the working tree."
  echo "      This checkout is not on the code you think it is. Run:"
  echo "        git status && git log --oneline -3"
  exit 1
fi
echo "OK: the new dashboard source is present."

say "3/6  Checking disk space"
# A full disk makes `build` fail deep inside the daemon with "no space left on
# device", which reads like a build error and is not one. Catch it up front.
if [ "$RECLAIM" = "1" ]; then
  echo "Reclaiming space. This removes images, build cache and abandoned build"
  echo "contexts. It does NOT touch volumes, so the database is untouched."
  before=$(df -Pm . | awk 'NR==2 {print $4}')
  sudo rm -rf /var/tmp/libpod_builder* 2>/dev/null || true
  # Podman needs to write metadata to delete an image, so on a truly full disk
  # the prune deadlocks and reports one error per image. Removing the abandoned
  # contexts first usually gives it the room it needs; run it twice, because the
  # first pass frees the space the second one needs to finish.
  for pass in 1 2; do
    echo "-- prune pass $pass"
    docker image prune -af 2>&1 | tail -3
    docker builder prune -af 2>&1 | tail -3
  done
  after=$(df -Pm . | awk 'NR==2 {print $4}')
  echo "Reclaimed $((after - before)) MB."
fi

avail_mb=$(df -Pm . | awk 'NR==2 {print $4}')
echo "Free space here: ${avail_mb} MB ($(df -Ph . | awk 'NR==2 {print $5}') used)"
if [ "$FORCE" = "1" ]; then
  echo "--force given: building regardless of free space."
elif [ "${avail_mb:-0}" -lt "$MIN_FREE_MB" ]; then
  echo
  echo "FAIL: ${avail_mb} MB free, and building '$SERVICES' wants ${MIN_FREE_MB} MB."
  echo "      A short build fails halfway with 'no space left on device'."
  echo
  echo "      Building one service at a time needs much less:"
  echo "        bash deploy/redeploy.sh --reclaim web"
  echo
  echo "      Reclaim space — none of this touches your database:"
  echo "        docker image prune -af        # images no container is using"
  echo "        docker builder prune -af      # build cache"
  echo "        sudo rm -rf /var/tmp/libpod_builder*   # abandoned build contexts"
  echo "        sudo journalctl --vacuum-size=200M     # old system logs"
  echo
  echo "      NEVER add --volumes to a prune. That deletes the postgres volume."
  echo
  echo
  echo "      Or override the check entirely:  bash deploy/redeploy.sh --force web"
  exit 1
fi

say "4/7  Building images (no cache)"
$COMPOSE build --no-cache $SERVICES || { echo "build failed — read the error above."; exit 1; }

say "5/7  Replacing containers"
$COMPOSE up -d --force-recreate $SERVICES || { echo "up failed — read the error above."; exit 1; }

say "6/7  Waiting for the API to become healthy"
for i in $(seq 1 40); do
  state=$($COMPOSE ps api 2>/dev/null | tail -n +2)
  case "$state" in
    *healthy*) echo "API is healthy."; break ;;
  esac
  [ "$i" = 40 ] && { echo "API never became healthy. Logs:"; $COMPOSE logs --tail=60 api; exit 1; }
  sleep 5
done
$COMPOSE restart nginx

say "7/7  Verifying what is actually served"
in_container=$($COMPOSE exec -T web sh -c "wget -qO- http://127.0.0.1:3000/dashboard 2>/dev/null" | grep -c "$MARKER")
echo "new dashboard inside the web container : $in_container"

public_url="${PUBLIC_URL:-}"
if [ -z "$public_url" ] && [ -f .env ]; then
  public_url=$(grep -E '^NEXT_PUBLIC_API_BASE_URL=' .env | cut -d= -f2- | tr -d '"' )
fi
if [ -n "$public_url" ]; then
  public=$(curl -sk "${public_url%/}/dashboard" | grep -c "$MARKER")
  echo "new dashboard at ${public_url%/}            : $public"
else
  public="skipped"
  echo "public URL unknown — set PUBLIC_URL=https://your.host to check it too."
fi

say "Verdict"
if [ "$in_container" -eq 0 ]; then
  echo "The container is STILL serving the old build after a no-cache rebuild."
  echo "Something is pinning the image. Check whether WEB_IMAGE in .env points at"
  echo "a prebuilt or registry image:   grep WEB_IMAGE .env"
elif [ "$public" = "skipped" ]; then
  echo "The container serves the new build. Check the site in a private window."
elif [ "$public" -eq 0 ]; then
  echo "The container serves the NEW build but the public URL serves the OLD one."
  echo "A cache in front of the origin is stale — purge the CDN (Cloudflare:"
  echo "Caching > Configuration > Purge Everything), then reload."
else
  echo "Deployed and verified: the new dashboard is live."
fi
