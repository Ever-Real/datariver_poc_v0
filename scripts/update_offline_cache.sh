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
  # Mac 호환성 (shasum 사용)
  LOCK_SHA=$(shasum -a 256 "$root/uv.lock" | awk '{print $1}' | cut -c1-12)
else
  LOCK_SHA=$(sha256sum "$root/uv.lock" | awk '{print $1}' | cut -c1-12)
fi

CACHE_FILENAME="datariver-uv-cache-linux-x86_64-${LOCK_SHA}.tar.gz"

echo "Checking for cache: $CACHE_FILENAME"
if [ -f "$distribution_repo_path/$CACHE_FILENAME" ]; then
  echo "Cache already exists in the distribution repository. It is up to date!"
  exit 0
fi

# 2. 캐시 폴더 생성 및 Docker를 이용한 linux/amd64 포맷 패키지 다운로드
mkdir -p "$root/offline_python"
echo "Building new offline uv cache for lock $LOCK_SHA (This may take a few minutes)..."

docker run --rm \
  -v "$root:/src:ro" \
  -v "$root/offline_python:/cache" \
  --platform linux/amd64 \
  python:3.12.12-slim-bookworm \
  /bin/sh -c "
    echo 'Installing uv...'
    pip install uv==0.9.17
    echo 'Syncing project dependencies to offline cache...'
    uv sync --project /src --frozen --no-dev --no-editable --cache-dir /tmp/uv-cache 2>&1 || true
    echo 'Compressing cache...'
    tar -czf /cache/$CACHE_FILENAME -C /tmp uv-cache
  "

# 3. 생성된 캐시를 Distribution Repo로 복사
echo "Copying $CACHE_FILENAME to distribution repository..."
cp "$root/offline_python/$CACHE_FILENAME" "$distribution_repo_path/"

# 4. Git Commit & Push 자동화
echo "Committing and pushing to distribution repository..."
cd "$distribution_repo_path"

# 이전 버전의 캐시 파일들은 용량 관리를 위해 삭제(옵션, 여기서는 유지하되 추가만 함)
git add "$CACHE_FILENAME"
git commit -m "Update offline uv cache for datariver_v1 lock $LOCK_SHA"
git push

echo "========================================================="
echo "✅ Successfully updated and pushed offline cache to GitHub!"
echo "========================================================="
