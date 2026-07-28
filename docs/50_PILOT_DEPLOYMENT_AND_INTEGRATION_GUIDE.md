# Pilot 운영 환경 배포 및 시스템 연계 가이드

이 문서는 인터넷이 차단된 Linux amd64 Pilot 서버에 DataRiver를 **소스 체크아웃 없이**
배포하고, `/home/datariver/.env`와 `/home/datariver/secrets/`만으로 운영 설정을 유지하는
실무 절차다.

적용 범위:

- 준비 PC: 사내망 Linux/WSL, Docker Engine `linux/amd64`, DataRiver `dev` checkout
- Pilot 서버: 사내 폐쇄망 Linux `amd64`, Docker Engine, Docker Compose v2
- 이관 파일: `release.tar.gz`, `release.tar.gz.sha256`, `deploy_pilot.sh`
- Pilot 서버에 두지 않는 것: Git checkout, Docker build context, package index cache, 실제
  준비 PC `.env`, 준비 PC `secrets/`

중요한 운영 경계:

- Pilot 서버에는 `workflow_update_restart.py`가 없다. Pilot의 설정 반영과 Day 2 업데이트는
  항상 `deploy_pilot.sh`로 수행한다.
- Admin > 시스템 설정은 현재 적용 파일 `/home/datariver/.env`를 표시한다.
  **현재값 테스트 후 반영 명령 복사**는 현재 실행값을 테스트한 후 운영자 명령을 복사할
  뿐, 서버 명령을 브라우저에서 실행하지 않는다.
- PostgreSQL, Redis, API는 외부에 publish하지 않는다. Web `38102`와 Keycloak `18081`도
  기본적으로 서버 loopback에만 bind한다.
- 다른 PC에서 IP로 직접 사용하는 HTTP는 Secure Context가 아니므로 지원하지 않는다.
  사내 신뢰 HTTPS ingress가 없으면 소수의 Pilot 사용자는 이 문서의 SSH tunnel 절차를
  사용한다.

## 0. 최초 1회 사전 확인

### 준비 PC

DataRiver 저장소 루트에서 실행한다.

```bash
git branch --show-current
git status --short
git remote get-url origin
uname -s
uname -m
docker version --format 'client={{.Client.Os}}/{{.Client.Arch}} server={{.Server.Os}}/{{.Server.Arch}}'
docker compose version
```

필수 결과:

- branch: `dev`
- `git status --short`: 출력 없음
- origin: `Ever-Real/datariver_v1`
- Docker server: `linux/amd64`

Mac mini의 arm64 Docker daemon에서는 `export_release.sh`를 실행하지 않는다. 반드시 준비
PC의 native Linux amd64 Docker daemon을 사용한다.

### Pilot 서버

`datariver` 운영 계정으로 확인한다.

```bash
id
uname -s
uname -m
docker version --format 'server={{.Server.Os}}/{{.Server.Arch}}'
docker compose version
df -h /home /var/lib/docker
```

필수 결과:

- OS/architecture: `Linux`, `x86_64` 또는 `amd64`
- Docker server: `linux/amd64`
- `datariver` 계정이 승인된 방식으로 Docker를 실행할 수 있음
- archive, 압축 해제본, `images.tar`, 로드된 이미지와 데이터 볼륨을 함께 저장할 충분한
  공간이 있음

운영 디렉터리를 최초 1회 만든다.

```bash
sudo install -d -o datariver -g datariver -m 0750 /home/datariver
sudo install -d -o datariver -g datariver -m 0750 /home/datariver/incoming
sudo install -d -o datariver -g datariver -m 0750 /home/datariver/artifacts
sudo install -d -o datariver -g datariver -m 0700 /home/datariver/backups
```

## 1. 산출물 이관 (Artifact Transfer)

### 1.1 준비 PC에서 정확한 `dev` commit 선택

저장소 루트에서 실행한다.

```bash
git switch dev
git fetch --prune origin dev
git merge --ff-only origin/dev
git status --short
RELEASE_COMMIT=$(git rev-parse --verify HEAD)
RELEASE_SHORT=$(printf '%s' "$RELEASE_COMMIT" | cut -c1-12)
printf 'RELEASE_COMMIT=%s\nRELEASE_SHORT=%s\n' "$RELEASE_COMMIT" "$RELEASE_SHORT"
```

`git status --short`에 한 줄이라도 출력되면 export하지 않는다. 사용자 변경을 commit하거나
별도로 보존한 후 깨끗한 `dev`에서 다시 시작한다.

### 1.2 모든 amd64 이미지와 의존성을 archive로 생성

Redis의 정확한 digest 재배포 승인이 기록되어 있을 때만 아래 승인 플래그를 사용한다.

```bash
RELEASE_OUT="$PWD/docker_imgs/datariver-$RELEASE_SHORT"
./scripts/export_release.sh \
  --commit "$RELEASE_COMMIT" \
  --output "$RELEASE_OUT" \
  --accept-redis-image-redistribution
```

이 명령은 다음 이미지를 Linux amd64로 준비하고 하나의 `images.tar`에 넣는다.

- DataRiver backend: 잠긴 Python runtime/library와 Alembic 포함
- DataRiver web: 빌드된 정적 asset과 Nginx runtime 포함
- Keycloak
- PostgreSQL과 DataRiver 초기 role SQL
- digest가 고정된 Redis

생성 결과를 확인한다.

```bash
ls -lh \
  "$RELEASE_OUT/release.tar.gz" \
  "$RELEASE_OUT/release.tar.gz.sha256" \
  "$RELEASE_OUT/deploy_pilot.sh"
(
  cd "$RELEASE_OUT"
  sha256sum --check release.tar.gz.sha256
)
```

성공 결과는 `release.tar.gz: OK`다. 같은 commit/output 경로의 archive는 immutable하므로
덮어쓰지 않는다.

### 1.3 승인된 망연계 또는 USB로 복사

승인 매체가 준비 PC의 `/mnt/approved-transfer`에 mount된 예:

```bash
TRANSFER_DIR="/mnt/approved-transfer/datariver-$RELEASE_SHORT"
install -d -m 0750 "$TRANSFER_DIR"
install -m 0644 "$RELEASE_OUT/release.tar.gz" "$TRANSFER_DIR/release.tar.gz"
install -m 0644 "$RELEASE_OUT/release.tar.gz.sha256" "$TRANSFER_DIR/release.tar.gz.sha256"
install -m 0755 "$RELEASE_OUT/deploy_pilot.sh" "$TRANSFER_DIR/deploy_pilot.sh"
sync
(
  cd "$TRANSFER_DIR"
  sha256sum --check release.tar.gz.sha256
)
```

Pilot 서버에서 승인 매체가 `/mnt/approved-transfer`에 mount된 예:

```bash
TRANSFER_DIR="/mnt/approved-transfer/datariver-$RELEASE_SHORT"
install -m 0644 "$TRANSFER_DIR/release.tar.gz" /home/datariver/incoming/release.tar.gz
install -m 0644 \
  "$TRANSFER_DIR/release.tar.gz.sha256" \
  /home/datariver/incoming/release.tar.gz.sha256
install -m 0755 "$TRANSFER_DIR/deploy_pilot.sh" /home/datariver/incoming/deploy_pilot.sh
cd /home/datariver/incoming
sha256sum --check release.tar.gz.sha256
```

사내 SCP가 승인된 경우 준비 PC에서 다음처럼 전송할 수 있다.

```bash
PILOT_SERVER="<PILOT_SERVER_IP_OR_HOSTNAME>"
scp \
  "$RELEASE_OUT/release.tar.gz" \
  "$RELEASE_OUT/release.tar.gz.sha256" \
  "$RELEASE_OUT/deploy_pilot.sh" \
  "datariver@$PILOT_SERVER:/home/datariver/incoming/"
```

Pilot 서버에서 다시 검증한다.

```bash
cd /home/datariver/incoming
chmod 0755 deploy_pilot.sh
sha256sum --check release.tar.gz.sha256
```

`.env`, `secrets/`, DB dump, Docker volume 또는 준비 PC checkout은 이관 묶음에 추가하지 않는다.

## 2. 환경 변수 및 Secrets 설정 (`.env`와 `secrets/`)

### 2.1 첫 실행으로 template과 stack-owned secret 생성

Pilot 서버에서 실행한다.

```bash
cd /home/datariver/incoming
DATARIVER_PILOT_HOME=/home/datariver \
  ./deploy_pilot.sh /home/datariver/incoming/release.tar.gz
```

최초 실행의 정상 동작:

1. archive와 내부 `SHA256SUMS`를 검증한다.
2. 다섯 개 이미지를 `docker load`한다.
3. `/home/datariver/releases/datariver-<12-char-sha>/`를 만든다.
4. release의 `.env.example`을 mode `0600`으로 `/home/datariver/.env`에 설치한다.
5. stack-owned secret을 `/home/datariver/secrets/`에 생성한다.
6. operator-owned DataHub/S3 값이 없으므로 container를 시작하지 않고 exit code `3`으로
   중단한다.

즉, 수동 `cp .env.example .env` 대신 deployer가 다음 의미의 작업을 안전하게 수행한다.

```bash
install -m 0600 \
  /home/datariver/releases/datariver-<12-char-sha>/.env.example \
  /home/datariver/.env
```

기존 `/home/datariver/.env`가 있으면 deployer는 덮어쓰지 않는다.

생성 결과를 확인한다.

```bash
ls -ld /home/datariver/secrets /home/datariver/runtime
ls -l /home/datariver/.env
find /home/datariver/secrets -maxdepth 1 -type l -print
find /home/datariver/secrets -maxdepth 1 -type f -exec stat -c '%a %U:%G %n' {} \;
```

필수 결과:

- `secrets/`, `runtime/`: mode `700`
- `.env`, 각 secret: mode `600`
- symlink 검색: 출력 없음

### 2.2 `.env` 편집

먼저 백업한 후 편집한다.

```bash
cp -p /home/datariver/.env \
  "/home/datariver/backups/env-before-initial-deploy-$(date +%Y%m%dT%H%M%S)"
vi /home/datariver/.env
```

다음 두 값은 변경하지 않는다.

```dotenv
DATARIVER_ENV_FILE=/home/datariver/.env
DATARIVER_OPERATOR_PROFILE=source-free-pilot
```

2026-07-28 이전 Pilot template으로 이미 `/home/datariver/.env`를 만든 서버는 새 deployer를
처음 실행하기 전에 누락된 고정 metadata만 1회 추가한다.

```bash
grep -q '^DATARIVER_ENV_FILE=' /home/datariver/.env ||
  printf '\nDATARIVER_ENV_FILE=/home/datariver/.env\n' >> /home/datariver/.env
grep -q '^DATARIVER_OPERATOR_PROFILE=' /home/datariver/.env ||
  printf 'DATARIVER_OPERATOR_PROFILE=source-free-pilot\n' >> /home/datariver/.env
chmod 0600 /home/datariver/.env
```

인증서가 없는 소수 사용자 Pilot은 SSH tunnel을 사용하므로 다음 localhost 값을 유지한다.

```dotenv
APP_PUBLIC_ORIGIN=http://localhost:38102
APP_CORS_ORIGINS=http://localhost:38102
APP_TRUSTED_HOSTS=localhost,127.0.0.1,api
OIDC_PUBLIC_ORIGIN=http://localhost:18081
OIDC_PUBLIC_AUTHORITY=http://localhost:18081/realms/datariver
OIDC_ISSUER=http://localhost:18081/realms/datariver
PILOT_BIND_ADDRESS=127.0.0.1
PILOT_WEB_PORT=38102
PILOT_OIDC_PORT=18081
```

사내에서 이미 신뢰되는 인증서를 종료하는 별도 HTTPS ingress가 준비된 경우에만
`APP_PUBLIC_ORIGIN`, `OIDC_PUBLIC_ORIGIN`, `APP_TRUSTED_HOSTS`를 그 정확한 HTTPS origin으로
바꾼다. `PILOT_BIND_ADDRESS=127.0.0.1`은 그대로 둔다. 자체 CA/서버 개인키를 이 release에
추가하지 않는다.

placeholder가 남았는지 확인한다.

```bash
grep -nE 'example\.internal|REPLACE_|CHANGE_ME' /home/datariver/.env
```

실제 설정 전에는 검색 결과가 있을 수 있다. 최종 배포 직전에는 출력이 없어야 한다.

### 2.3 필수 operator secret 입력

shell history에 secret 값을 직접 쓰지 않고, 숨김 prompt로 입력한다.

DataHub service token:

```bash
umask 077
read -r -s -p 'DataHub service token: ' DATARIVER_SECRET
printf '\n'
install -m 0600 /dev/null /home/datariver/secrets/datahub_token
printf '%s' "$DATARIVER_SECRET" > /home/datariver/secrets/datahub_token
unset DATARIVER_SECRET
```

S3/MinIO access key:

```bash
umask 077
read -r -s -p 'S3 access key: ' DATARIVER_SECRET
printf '\n'
install -m 0600 /dev/null /home/datariver/secrets/s3_access_key
printf '%s' "$DATARIVER_SECRET" > /home/datariver/secrets/s3_access_key
unset DATARIVER_SECRET
```

S3/MinIO secret key:

```bash
umask 077
read -r -s -p 'S3 secret key: ' DATARIVER_SECRET
printf '\n'
install -m 0600 /dev/null /home/datariver/secrets/s3_secret_key
printf '%s' "$DATARIVER_SECRET" > /home/datariver/secrets/s3_secret_key
unset DATARIVER_SECRET
```

선택 worker를 활성화할 때는 해당 provider가 발급한 값을 같은 방식으로 만든다.

- `knowledge-source`: `s3_knowledge_access_key`, `s3_knowledge_secret_key`
- `catalog-export`: `s3_export_access_key`, `s3_export_secret_key`
- `retention-archive`: `s3_archive_access_key`, `s3_archive_secret_key`
- 사내 LLM: `intranet_llm_chat_api_key`, `intranet_llm_embedding_api_key`

마지막으로 전체 권한을 정규화하고 빈 필수 secret이 없는지 확인한다.

```bash
chmod 0700 /home/datariver/secrets
find /home/datariver/secrets -maxdepth 1 -type f -exec chmod 0600 {} \;
test -s /home/datariver/secrets/datahub_token
test -s /home/datariver/secrets/s3_access_key
test -s /home/datariver/secrets/s3_secret_key
find /home/datariver/secrets -maxdepth 1 -type l -print
```

마지막 명령은 아무것도 출력하지 않아야 한다.

## 3. 운영 서버 컨테이너 구동 (Deployment)

### 3.1 최종 배포

```bash
cd /home/datariver/incoming
sha256sum --check release.tar.gz.sha256
DATARIVER_PILOT_HOME=/home/datariver \
  ./deploy_pilot.sh /home/datariver/incoming/release.tar.gz
```

deployer는 다음 순서로 실행한다.

1. 외부 archive checksum과 내부 파일 checksum 검증
2. image ID, source commit, `linux/amd64` 검증
3. Compose에 `build:`가 없고 모든 image가 `pull_policy: never`인지 검증
4. PostgreSQL, 두 Redis, Keycloak 시작 및 health 대기
5. Alembic `upgrade head` one-shot 실행
6. S3 bucket 초기화 one-shot 실행
7. 비운영 local identity bootstrap one-shot 실행
8. API, Web, 기본 worker 시작 및 health 대기
9. 성공한 release만 `/home/datariver/current`로 지정

`set -e`로 실행되므로 migration, bootstrap 또는 health 하나라도 실패하면 성공 marker를
갱신하지 않는다. Alembic은 revision table을 기준으로 이미 적용된 migration을 다시
실행하지 않으며, 수동 SQL을 운영 서버에 붓지 않는다.

### 3.2 Compose 상태와 로그 확인

현재 release의 Compose 명령을 준비한다.

```bash
cd /home/datariver
export DATARIVER_RELEASE_ID=$(basename "$(readlink -f /home/datariver/current)")
export DATARIVER_PILOT_ENV_FILE=/home/datariver/.env
export DATARIVER_PILOT_SECRETS_DIR=/home/datariver/secrets
export DATARIVER_PILOT_RUNTIME_DIR=/home/datariver/runtime
PILOT_COMPOSE=(
  docker compose
  --env-file /home/datariver/.env
  -f /home/datariver/docker-compose.yaml
)
"${PILOT_COMPOSE[@]}" ps
```

기본 로그:

```bash
"${PILOT_COMPOSE[@]}" logs --tail=200 postgres keycloak api web
"${PILOT_COMPOSE[@]}" logs --tail=200 \
  redis-cache redis-delivery outbox-relay upload-worker governance-apply-worker
```

실시간 확인:

```bash
"${PILOT_COMPOSE[@]}" logs --follow --tail=100 api web keycloak
```

`Ctrl+C`는 log follow만 종료하며 container는 종료하지 않는다.

Alembic 현재 revision 확인:

```bash
"${PILOT_COMPOSE[@]}" --profile deploy-tools run --rm --no-deps \
  migrate /app/.venv/bin/alembic -c backend/alembic.ini current
```

서버-local health 확인:

```bash
curl --noproxy '*' -fsS http://127.0.0.1:38102/healthz
curl --noproxy '*' -fsS \
  http://127.0.0.1:18081/realms/datariver/.well-known/openid-configuration
```

### 3.3 인증서 없이 소수 Pilot 사용자가 접속하는 방법

각 테스트 사용자의 PC에서 SSH tunnel을 열고 그 terminal을 유지한다.

```bash
PILOT_SERVER="<PILOT_SERVER_IP_OR_HOSTNAME>"
ssh -N \
  -L 38102:127.0.0.1:38102 \
  -L 18081:127.0.0.1:18081 \
  "datariver@$PILOT_SERVER"
```

그 사용자 PC의 browser에서 다음 URL만 연다.

```text
http://localhost:38102
```

로그인은 `http://localhost:18081`로 이동한 뒤 `http://localhost:38102`로 돌아온다.
`localhost`는 browser가 잠재적으로 신뢰 가능한 origin으로 취급하므로 이 방식은 자체 CA
배포 없이 소수 사용자 Pilot에 사용할 수 있다. SSH 계정/port-forwarding은 사내 정책상
허용된 사용자에게만 제공한다.

여러 사용자가 `https://<SERVER_IP>:38102`로 직접 접속하려면 서버 IP SAN을 포함하고 각
client가 이미 신뢰하는 인증서와 별도 HTTPS ingress가 필요하다. 이 항목은
`TARGET_EXTERNAL_GATE`이며 이 repository의 Pilot bundle은 자체 CA를 생성하지 않는다.

## 4. 외부 시스템 연계 (System Integration)

### 4.1 공통 연결 규칙

Pilot container에서 `localhost`는 해당 container 자신이다.

- 같은 Linux host에서 별도 process/container port로 공개된 서비스:
  `http://host.docker.internal:<PORT>`
- 다른 사내 서버의 서비스:
  `http://<RFC1918_IP>:<PORT>` 또는 신뢰 가능한
  `https://<HOST_OR_IP>:<PORT>`
- browser가 직접 여는 URL/iframe/presigned URL: HTTPS DataRiver를 사용할 때 반드시
  HTTPS

provider hostname/IP를 Admin에서 테스트하려면
`SYSTEM_CONFIGURATION_PROBE_ALLOWED_HOSTS`에 정확히 추가한다.

```bash
vi /home/datariver/.env
```

예:

```dotenv
SYSTEM_CONFIGURATION_PROBE_ALLOWED_HOSTS=keycloak,postgres,redis-cache,redis-delivery,10.20.30.41,10.20.30.42
# HTTP/redis/bolt만 제공되는 정확한 격리망 IP만 선택적으로 중복 승인한다.
SYSTEM_CONFIGURATION_PROBE_PLAINTEXT_ALLOWED_IPS=10.20.30.41
```

wildcard, URL, CIDR 또는 port를 이 allowlist에 넣지 않는다. URL의 hostname/IP만 넣는다.
두 번째 allowlist에는 hostname도 넣지 않는다. 정확한 IP만 허용되며 첫 번째 allowlist의
부분집합이어야 한다. 동일 IP에서 Airflow와 Grafana가 서로 다른 port를 사용하면 IP는 한 번만
적는다. 이 옵션은 고정 Admin probe에만 적용되며 LLM gateway HTTPS 및 production browser URL
정책을 변경하지 않는다.

설정 변경 후 Pilot 재적용:

```bash
DATARIVER_PILOT_HOME=/home/datariver \
  /home/datariver/incoming/deploy_pilot.sh \
  /home/datariver/incoming/release.tar.gz
```

그다음 Admin > 시스템 설정을 새로고침하고 대상 시스템의 **연결 테스트**를 실행한다.
Admin에 표시되는 적용 파일은 `/home/datariver/.env`여야 한다.

### 4.2 DataHub

`/home/datariver/.env`:

```dotenv
DATAHUB_BASE_URL=http://10.20.30.41:8080
DATAHUB_SECRET_REF=file:/run/secrets/datahub_token
DATAHUB_EXPECTED_VERSION=v1.6.0
DATAHUB_VERSION_ENFORCEMENT=report
```

browser에서 DataHub 화면 링크가 필요할 때만 추가한다.

```dotenv
UI_DATAHUB_URL=https://datahub.internal.example
```

`DATAHUB_BASE_URL`은 API/worker의 server-side 연결이고, `UI_DATAHUB_URL`은 사용자 browser가
직접 접근한다. 둘은 동일할 필요가 없다. token은
`/home/datariver/secrets/datahub_token`에만 둔다.

### 4.3 MinIO 또는 S3-compatible storage

`/home/datariver/.env`:

```dotenv
S3_ENDPOINT_URL=http://10.20.30.42:9000
S3_PUBLIC_ENDPOINT_URL=https://s3.internal.example
S3_PUBLIC_ORIGIN=https://s3.internal.example
S3_REGION=us-east-1
S3_BUCKET_QUARANTINE=datariver-quarantine
S3_BUCKET_ACCEPTED=datariver-accepted
S3_BUCKET_EXPORTS=datariver-exports
S3_BUCKET_FILEFOLDER=datariver-filefolder
S3_BUCKET_INFOSCHEMA=datariver-infoschema
S3_CORS_MANAGEMENT_MODE=bucket
```

- `S3_ENDPOINT_URL`: API/worker가 접근
- `S3_PUBLIC_ENDPOINT_URL`, `S3_PUBLIC_ORIGIN`: presigned URL을 받은 browser가 접근
- HTTPS DataRiver에서 `S3_PUBLIC_ORIGIN=http://...`는 deployer가 거부한다.
- bucket CORS에는 정확한 `APP_PUBLIC_ORIGIN`만 허용해야 한다.

권한은 목적별로 분리한다. `knowledge-source`, `catalog-export`, `retention-archive` profile을
활성화하면 각각의 S3 access/secret 파일을 별도로 만든다.

### 4.4 Airflow

이 Pilot bundle은 Airflow image를 포함하지 않는다. 외부 Airflow는 DataRiver API를
호출하는 독립 시스템이다.

DataRiver 화면에서 Airflow 링크를 제공할 때:

```dotenv
UI_AIRFLOW_URL=https://airflow.internal.example
AIRFLOW_WORKSPACE_ID=<Datariver-workspace-UUID>
```

외부 Airflow 쪽에는 다음을 별도로 설정한다.

- DataRiver API URL: Airflow container/host에서 실제 도달 가능한 HTTPS URL
- OIDC token URL: Pilot Keycloak의 실제 도달 가능한 URL
- client ID: `datariver-airflow`
- client secret: Pilot 최초 realm과 일치하는 승인된 `airflow_client_secret`
- workspace ID: 위 `AIRFLOW_WORKSPACE_ID`

Airflow credential을 `UI_AIRFLOW_URL` 또는 browser 설정에 넣지 않는다.

### 4.5 사내 LLM model server

현재 Pilot runtime이 지원하는 사내 adapter는 Chat과 Embedding이다. Reranker는 이
source-free Pilot profile에서 구성하지 않는다.

`/home/datariver/.env`:

```dotenv
INTRANET_OPENAI_COMPATIBLE_ALLOWED_HOSTS=10.20.30.43
# Set only when the exact approved hostname intentionally resolves to a public
# address; it must also appear in INTRANET_OPENAI_COMPATIBLE_ALLOWED_HOSTS.
INTRANET_OPENAI_COMPATIBLE_APPROVED_PUBLIC_HOSTS=
INTRANET_OPENAI_COMPATIBLE_CHAT_ENABLED=true
INTRANET_OPENAI_COMPATIBLE_CHAT_BASE_URL=https://10.20.30.43/api/llm/openai/v1
INTRANET_OPENAI_COMPATIBLE_CHAT_MODEL=/models/llm/gemma-4-31B-it
INTRANET_OPENAI_COMPATIBLE_CHAT_API_KEY_SECRET_REF=file:/run/secrets/intranet_llm_chat_api_key
INTRANET_OPENAI_COMPATIBLE_CHAT_TIMEOUT_SECONDS=60
INTRANET_OPENAI_COMPATIBLE_CHAT_CONTEXT_TOKENS=8192
INTRANET_OPENAI_COMPATIBLE_CHAT_TEMPERATURE=0
INTRANET_OPENAI_COMPATIBLE_CHAT_TOP_P=0.9
INTRANET_OPENAI_COMPATIBLE_CHAT_REPETITION_PENALTY=1.05
INTRANET_OPENAI_COMPATIBLE_CHAT_ENABLE_THINKING=true

INTRANET_OPENAI_COMPATIBLE_EMBEDDING_ENABLED=true
INTRANET_OPENAI_COMPATIBLE_EMBEDDING_BASE_URL=https://10.20.30.43/api/llm/openai/v1
INTRANET_OPENAI_COMPATIBLE_EMBEDDING_MODEL=/models/embedding/bge-m3
INTRANET_OPENAI_COMPATIBLE_EMBEDDING_API_KEY_SECRET_REF=file:/run/secrets/intranet_llm_embedding_api_key
INTRANET_OPENAI_COMPATIBLE_EMBEDDING_TIMEOUT_SECONDS=60

INTRANET_RERANKER_ENABLED=true
INTRANET_RERANKER_BASE_URL=https://10.20.30.43/api/llm/openai
INTRANET_RERANKER_MODEL=/models/Reranker/bge-reranker-v2-m3
INTRANET_RERANKER_API_KEY_SECRET_REF=file:/run/secrets/intranet_llm_reranker_api_key
INTRANET_RERANKER_TIMEOUT_SECONDS=60
INTRANET_RERANKER_TOP_N=10
```

API key는 `.env`가 아니라 다음 파일에 입력한다.

```bash
umask 077
read -r -s -p 'Intranet LLM API key: ' DATARIVER_SECRET
printf '\n'
install -m 0600 /dev/null /home/datariver/secrets/intranet_llm_chat_api_key
printf '%s' "$DATARIVER_SECRET" > /home/datariver/secrets/intranet_llm_chat_api_key
install -m 0600 /dev/null /home/datariver/secrets/intranet_llm_embedding_api_key
printf '%s' "$DATARIVER_SECRET" > /home/datariver/secrets/intranet_llm_embedding_api_key
unset DATARIVER_SECRET
```

Chat 실제 사용에는 endpoint 연결 외에도 승인된 inference provider profile과 활성
classification-access policy binding이 필요하다. Admin 연결 테스트 성공을 인증/권한 정책
승인으로 간주하지 않는다.

### 4.6 Grafana Dashboard

링크만 제공:

```dotenv
UI_GRAFANA_URL=https://grafana.internal.example
```

iframe embed는 Grafana의 SSO, CSP/frame-ancestor, cookie, HTTPS 증거가 있을 때만 활성화한다.

```dotenv
GRAFANA_EMBED_BASE_URL=https://grafana.internal.example
GRAFANA_EMBED_ENABLED=true
GRAFANA_EMBED_EVIDENCE_REFERENCE=<APPROVED_EVIDENCE_ID>
```

Grafana username/password 또는 API token을 browser 환경 변수에 넣지 않는다. HTTPS
DataRiver 화면에 HTTP Grafana/DataHub iframe을 넣으면 mixed content로 차단되며 deployer도
HTTP embed origin을 거부한다.

## 5. 향후 시스템 업데이트 절차 (Day 2 Operations)

### 5.1 새 commit을 준비 PC에 적용하고 새 archive 생성

준비 PC 저장소 루트:

```bash
./scripts/development_cycle.py prep-update
git status --short
RELEASE_COMMIT=$(git rev-parse --verify HEAD)
RELEASE_SHORT=$(printf '%s' "$RELEASE_COMMIT" | cut -c1-12)
RELEASE_OUT="$PWD/docker_imgs/datariver-$RELEASE_SHORT"
./scripts/export_release.sh \
  --commit "$RELEASE_COMMIT" \
  --output "$RELEASE_OUT" \
  --accept-redis-image-redistribution
(
  cd "$RELEASE_OUT"
  sha256sum --check release.tar.gz.sha256
)
```

`prep-update`가 source-host를 갱신하는 과정과 Pilot image export는 별개다. Pilot 서버는
항상 새 `release.tar.gz`를 받아야 새 application code를 사용한다.

### 5.2 업데이트 전 DB 백업

Pilot 서버:

```bash
cd /home/datariver
export DATARIVER_RELEASE_ID=$(basename "$(readlink -f /home/datariver/current)")
export DATARIVER_PILOT_ENV_FILE=/home/datariver/.env
export DATARIVER_PILOT_SECRETS_DIR=/home/datariver/secrets
export DATARIVER_PILOT_RUNTIME_DIR=/home/datariver/runtime
PILOT_COMPOSE=(
  docker compose
  --env-file /home/datariver/.env
  -f /home/datariver/docker-compose.yaml
)
BACKUP_FILE="/home/datariver/backups/datariver-before-update-$(date +%Y%m%dT%H%M%S).dump"
"${PILOT_COMPOSE[@]}" exec -T postgres sh -ec \
  'export PGPASSWORD="$(cat /run/secrets/postgres_password)";
   exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' \
  > "$BACKUP_FILE"
chmod 0600 "$BACKUP_FILE"
test -s "$BACKUP_FILE"
ls -lh "$BACKUP_FILE"
```

이 DB dump와 `/home/datariver/.env`, `/home/datariver/secrets/`, 외부 S3 데이터의 backup은
승인된 backup 정책으로 함께 보존한다.

### 5.3 새 archive 이관 및 보존

1절의 USB/망연계/SCP 절차로 새 세 파일을 `/home/datariver/incoming/`에 둔다.

```bash
cd /home/datariver/incoming
chmod 0755 deploy_pilot.sh
sha256sum --check release.tar.gz.sha256
RELEASE_ID=$(tar -tzf release.tar.gz | awk -F/ 'NR == 1 {print $1}')
printf 'RELEASE_ID=%s\n' "$RELEASE_ID"
install -d -m 0750 "/home/datariver/artifacts/$RELEASE_ID"
install -m 0644 release.tar.gz "/home/datariver/artifacts/$RELEASE_ID/release.tar.gz"
install -m 0644 \
  release.tar.gz.sha256 \
  "/home/datariver/artifacts/$RELEASE_ID/release.tar.gz.sha256"
install -m 0755 deploy_pilot.sh "/home/datariver/artifacts/$RELEASE_ID/deploy_pilot.sh"
```

### 5.4 최소 다운타임 재배포

```bash
DATARIVER_PILOT_HOME=/home/datariver \
  /home/datariver/incoming/deploy_pilot.sh \
  /home/datariver/incoming/release.tar.gz
```

동작 특성:

- 기존 named volume과 데이터를 삭제하지 않는다.
- 변경되지 않은 container는 Compose가 재사용한다.
- migration은 application 최종 재생성 전에 one-shot으로 실행한다.
- API/Web는 single-node이므로 image가 바뀌는 순간 짧은 재생성 시간이 발생할 수 있다.
- schema 변경이 구버전 API와 호환되지 않으면 무중단을 주장하지 말고 점검 시간을 잡는다.

배포 후 확인:

```bash
readlink -f /home/datariver/current
cat /home/datariver/current/source-commit.txt
cd /home/datariver
export DATARIVER_RELEASE_ID=$(basename "$(readlink -f /home/datariver/current)")
export DATARIVER_PILOT_ENV_FILE=/home/datariver/.env
export DATARIVER_PILOT_SECRETS_DIR=/home/datariver/secrets
export DATARIVER_PILOT_RUNTIME_DIR=/home/datariver/runtime
docker compose \
  --env-file /home/datariver/.env \
  -f /home/datariver/docker-compose.yaml \
  ps
curl --noproxy '*' -fsS http://127.0.0.1:38102/healthz
curl --noproxy '*' -fsS \
  http://127.0.0.1:18081/realms/datariver/.well-known/openid-configuration
```

SSH tunnel 또는 승인 HTTPS client에서 로그인, Workspace 권한, 핵심 조회/등록/Knowledge
흐름을 다시 확인한다.

### 5.5 코드 변경 없이 `.env` 또는 secret만 변경

```bash
cp -p /home/datariver/.env \
  "/home/datariver/backups/env-before-change-$(date +%Y%m%dT%H%M%S)"
vi /home/datariver/.env
DATARIVER_PILOT_HOME=/home/datariver \
  /home/datariver/incoming/deploy_pilot.sh \
  /home/datariver/incoming/release.tar.gz
```

Admin > 시스템 설정에서 파일이 `/home/datariver/.env`로 표시되는지 확인하고 대상 연결을
다시 테스트한다. Admin 버튼이 복사하는 명령도 위 명령과 같다.

### 5.6 실패 시 중단과 rollback 기준

- 새 deploy가 `current` link 변경 전에 실패하면 로그를 보존하고 원인을 수정한다. DB나
  volume을 삭제하지 않는다.
- migration이 실행되지 않았다면 이전
  `/home/datariver/artifacts/<PREVIOUS_RELEASE_ID>/release.tar.gz`를 같은 deployer로 다시
  배포할 수 있다.
- migration이 새 revision으로 진행됐다면 이전 image만 재배포하지 않는다. 호환성 검토
  또는 위에서 만든 DB backup 복원이 먼저다.
- rollback을 위해 `docker compose down -v`, `docker volume rm`, PostgreSQL data directory
  삭제를 사용하지 않는다.

이전 archive 재배포 형식:

```bash
PREVIOUS_RELEASE_ID="<datariver-12-char-sha>"
DATARIVER_PILOT_HOME=/home/datariver \
  "/home/datariver/artifacts/$PREVIOUS_RELEASE_ID/deploy_pilot.sh" \
  "/home/datariver/artifacts/$PREVIOUS_RELEASE_ID/release.tar.gz"
```

DB restore는 기존 DB를 덮어쓰는 파괴적 작업이므로 장애 승인, 점검 시간, 현재 장애 DB의
별도 보존을 먼저 완료한 후 `docs/13_OPERATIONS_RUNBOOK.md`의 복구 절차를 따른다.

## TARGET_EXTERNAL_GATE

다음 항목은 source test나 archive 생성 성공으로 대체할 수 없다.

- 실제 준비 PC에서 exact commit의 amd64 archive 생성
- 실제 Pilot 서버에서 checksum/image platform 검증과 empty/existing volume 배포
- 운영 DB backup/restore와 rollback rehearsal
- DataHub/S3/Airflow/LLM/Grafana의 실제 route, firewall, credential, timeout 검증
- browser-facing S3/Grafana/DataHub의 HTTPS, CORS, CSP/frame, mixed-content 검증
- 승인 HTTPS ingress/certificate 또는 사용자별 SSH tunnel 승인
- 실제 client browser 로그인, PKCE, redirect, logout, Workspace ABAC/RLS 검증
- exact Redis image digest의 재배포 승인

이 항목을 수행하지 않았다면 운영 배포 성공으로 보고하지 않는다.
