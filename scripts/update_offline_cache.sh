#!/usr/bin/env bash
# ==============================================================================
# UV Offline Cache Update & Publish Script
# ==============================================================================
# Python 라이브러리(uv.lock)가 변경되었을 때, 폐쇄망 배포용 오프라인 캐시를 
# 생성하고 Distribution Repository에 자동으로 Push하는 스크립트입니다.
#
# 사용법:
#   scripts/update_offline_cache.sh --distribution-repo <배포_저장소_경로>
# ==============================================================================
set -euo pipefail

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
distribution_repo_path=""

usage() {
  echo "Usage: scripts/update_offline_cache.sh --distribution-repo <path>"
  echo "Example: scripts/update_offline_cache.sh --distribution-repo ../datariver-platform-amd64-distribution"
  exit 1
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --distribution-repo)
      shift
      distribution_repo_path="$1"
      ;;
    --help|-h)
      usage
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      ;;
  esac
  shift
done

if [ -z "$distribution_repo_path" ]; then
  echo "Error: --distribution-repo argument is required." >&2
  usage
fi

if [ ! -d "$distribution_repo_path/.git" ]; then
  echo "Error: Directory '$distribution_repo_path' is not a valid git repository." >&2
  exit 2
fi

# 1. uv.lock 파일의 해시값(앞 12자리)을 구하여 캐시 파일명 결정
if ! command -v sha256sum >/dev/null 2>&1; then
  LOCK_SHA=$(shasum -a 256 "$root/uv.lock" | awk '{print $1}' | cut -c1-12)
  NPM_SHA=$(shasum -a 256 "$root/frontend/package-lock.json" | awk '{print $1}' | cut -c1-12)
else
  LOCK_SHA=$(sha256sum "$root/uv.lock" | awk '{print $1}' | cut -c1-12)
  NPM_SHA=$(sha256sum "$root/frontend/package-lock.json" | awk '{print $1}' | cut -c1-12)
fi

CACHE_FILENAME="datariver-uv-cache-linux-x86_64-${LOCK_SHA}.tar.gz"
NPM_CACHE_FILENAME="datariver-npm-modules-linux-x86_64-${NPM_SHA}.tar.gz"

echo "Checking for Python cache: $CACHE_FILENAME"
if [ ! -f "$distribution_repo_path/$CACHE_FILENAME" ]; then
  mkdir -p "$root/offline_python"
  echo "Building new offline uv cache for lock $LOCK_SHA (This may take a few minutes)..."
  docker run --rm \
    -v "$root:/src:ro" \
    -v "$root/offline_python:/cache" \
    -e UV_PROJECT_ENVIRONMENT=/tmp/.venv \
    --platform linux/amd64 \
    python:3.12.12-slim-bookworm \
    /bin/sh -c "
      echo 'Installing uv...'
      pip install uv==0.9.17
      echo 'Syncing project dependencies to offline cache...'
      uv sync --project /src --frozen --no-dev --no-editable --cache-dir /tmp/uv-cache
      echo 'Compressing cache...'
      tar -czf /cache/$CACHE_FILENAME -C /tmp uv-cache
    "
  cp "$root/offline_python/$CACHE_FILENAME" "$distribution_repo_path/"
else
  echo "Python cache already up to date!"
fi

echo "Checking for NPM cache: $NPM_CACHE_FILENAME"
if [ ! -f "$distribution_repo_path/$NPM_CACHE_FILENAME" ]; then
  mkdir -p "$root/offline_npm"
  echo "Building new offline npm cache for lock $NPM_SHA (This may take a few minutes)..."
  docker run --rm \
    -v "$root/frontend:/src:ro" \
    -v "$root/offline_npm:/cache" \
    --platform linux/amd64 \
    node:22.19.0-bookworm-slim \
    /bin/sh -c "
      echo 'Copying package files...'
      cp /src/package.json /src/package-lock.json /tmp/
      cd /tmp
      echo 'Running npm ci...'
      npm ci --ignore-scripts --no-audit --no-fund
      echo 'Compressing node_modules...'
      tar -czf /cache/$NPM_CACHE_FILENAME node_modules
    "
  cp "$root/offline_npm/$NPM_CACHE_FILENAME" "$distribution_repo_path/"
else
  echo "NPM cache already up to date!"
fi

# 4. Git Commit & Push 자동화
echo "Committing and pushing to distribution repository..."
cd "$distribution_repo_path"

git add "$CACHE_FILENAME" "$NPM_CACHE_FILENAME"
git commit -m "Update offline caches (uv: $LOCK_SHA, npm: $NPM_SHA)"
git push

echo "========================================================="
echo "✅ Successfully updated and pushed offline cache to GitHub!"
echo "========================================================="
