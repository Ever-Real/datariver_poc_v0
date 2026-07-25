# DataRiver Next

DataRiver Next is a secure catalog and knowledge-governance control plane around an externally operated DataHub. It preserves catalog search, registration, change management, monitoring and evidence-based Chat, and adds reviewed knowledge-graph changesets/releases, release-pinned API products and grants, external Redis-backed cache/delivery and optional Airflow scheduling.

The runtime is a boundary-enforced modular monolith with independent relay and worker processes. PostgreSQL remains the business source of truth, while modules can later be extracted without sharing domain models or bypassing ports.

## Current project snapshot

This README describes the source after Phase 6E. It is a Single-node Pilot baseline, not an HA or
production-acceptance claim. Mac development runs native `linux/arm64`; the preparation PC must use
separately built/imported native `linux/amd64` artifacts from the same clean commit. Do not force one
Compose-wide platform or copy Docker volumes between architectures.

The smallest DataRiver-owned set is migrate/API/web plus PostgreSQL and an approved OIDC capability;
the local Keycloak overlay is optional when an external IdP exists. DataHub, separate Redis
cache/delivery, S3/MinIO, Neo4j, Airflow, APISIX, model providers and observability are selectable
external capabilities. A feature reports unavailable or degraded when its required connector is
absent; no connector becomes canonical business truth.

For a blank environment:

1. verify the native Docker platform and check out one clean reviewed commit;
2. choose one ignored environment file, run `scripts/bootstrap.sh` or `scripts/bootstrap.ps1`, and
   provide secrets only through the generated/mounted secret files;
3. configure external endpoints and the named connector network, render Compose with
   `scripts/compose.sh ... config --quiet`, then start only the required overlays;
4. reconcile database roles, run the migration service through revision `0055`, and verify live,
   ready and capability endpoints;
5. apply optional synthetic seeds only in non-production environments and run their verification;
6. execute target-specific OIDC, provider read-back, backup/restore and migration acceptance before
   routing users.

Detailed entry points:

- [Feature specification](docs/04_FEATURE_SPEC.md)
- [API specification](docs/05_API_SPEC.md)
- [Table specification and core ERD](docs/06_DATA_MODEL.md)
- [Architecture](docs/03_ARCHITECTURE.md)
- [Deployment and migration](docs/08_DEPLOYMENT.md), [Mac-to-WSL runbook](docs/26_MAC_TO_WSL_MIGRATION_RUNBOOK.md)
- [Security/ABAC](docs/07_SECURITY_ABAC.md), [master backlog](docs/29_MASTER_EXECUTION_BACKLOG.md)

Remaining WSL/external-provider/browser/load/physical-retention checks are explicit external gates.
Runtime API/OIDC Origin validation is intentionally deferred as backlog item `R5-FE-04` at P2; the
source must not be represented as having that protection.

## 직렬 실행 워크플로

반복되는 Mac 개발 PC와 WSL 준비 PC 초기화·업데이트 절차는 다음 두 실행파일로 통합한다.
두 프로그램은 기존 bootstrap/Compose/migration/Keycloak 스크립트를 순서대로 호출하며, shell로
입력값을 재해석하지 않는다.

- `scripts/workflow_fresh_setup.py`: **빈 환경 전용**이다. Docker 아키텍처와 clean checkout을
  검사하고, URL은 형식을 검증하며, token/password/access key는 파일 또는 숨김 입력으로만
  받는다. bootstrap, 이미지 검증·load 또는 build, PostgreSQL/Keycloak, migration, 선택
  connector, storage 초기화, 기본 runtime, health/DataHub probe, 최초 catalog sync를 순차
  실행한다. 기존 DB·object를 이관하는 환경은 이 명령 대신
  [Mac-to-WSL runbook](docs/26_MAC_TO_WSL_MIGRATION_RUNBOOK.md)의 백업/복원 게이트를 사용한다.
- `scripts/workflow_update_restart.py`: 첫 프로그램이 기록한 ignored state를 기준으로
  `git pull --ff-only`를 선택 실행하고 변경 경로를 분류한다. 문서·테스트·이 운영
  워크플로만 바뀌면 컨테이너를 재시작하지 않는다. Frontend, Backend, migration,
  Keycloak, Airflow, APISIX, Neo4j 또는 local connector가 바뀌면 실행 중이던 선택
  서비스와 필수 서비스 중 영향 범위만 build/recreate한다.

Mac 신규 개발 환경의 기본 topology(DataHub/Redis/MinIO/Airflow local)는 다음 한 명령으로
시작한다. Neo4j와 APISIX는 필요할 때만 각각 `--graph-mode local`, `--with-gateway`를
추가한다. 외부 Neo4j는 `--graph-mode external --neo4j-uri
bolt+s://<actual-host>:7687 --neo4j-auth-file <username-password-file>`로 연결하며, credential
파일 내용은 `username/password` 형식이어야 한다.

```bash
./scripts/workflow_fresh_setup.py \
  --profile mac-development \
  --datahub-mode local \
  --redis-mode local \
  --storage-mode local \
  --airflow-mode local
```

준비 PC에서는 배포 repository에서 검증·해제한 **release root**와 별도 Redis archive를
지정한다. `--datahub-base-url`은 UI가 아니라 container에서 접근 가능한 GMS origin이고,
MinIO도 Console이 아닌 S3 API origin을 입력한다. 실제 외부 주소는 예제 placeholder를
복사하지 말고 대상 값으로 바꾼다.

```bash
RELEASE_DIR="$HOME/workspace/datariver_platform_amd_distribution/restore/datariver-<release-id>"
REDIS_ARCHIVE="$HOME/workspace/datariver_platform_amd_distribution/redis-8.2.6-bookworm-linux-amd64-<release>.tar.gz"

./scripts/workflow_fresh_setup.py \
  --profile wsl-preparation \
  --release-dir "$RELEASE_DIR" \
  --redis-image-archive "$REDIS_ARCHIVE" \
  --datahub-mode external \
  --datahub-base-url http://<actual-datahub-gms-host>:8080 \
  --datahub-token-file /approved-secure-transfer/datahub_token \
  --redis-mode local \
  --storage-mode external \
  --airflow-mode external \
  --airflow-ui-url http://<actual-airflow-ui-host>:8080
```

개발 변경을 commit한 Mac에서는 아래 명령으로 현재 source를 적용한다. 준비 PC에서는 먼저
새 amd64 release를 반입한 뒤 `--git-pull --release-dir "$RELEASE_DIR"`를 사용한다. Backend,
Frontend 또는 Compose가 현재 offline release보다 새로우면 서비스 중지 전에 실패하므로,
Git pull만으로 낡은 이미지를 새 코드처럼 실행하지 않는다.

```bash
# Mac: 현재 clean commit을 build하고 영향 서비스만 재생성
./scripts/workflow_update_restart.py --profile mac-development

# WSL: fast-forward pull 후 검증한 amd64 release로 영향 서비스만 재생성
./scripts/workflow_update_restart.py \
  --profile wsl-preparation \
  --git-pull \
  --release-dir "$RELEASE_DIR"
```

`.env.*`, `secrets/`, `runtime/operator-workflow/*.json`은 Git으로 이동하지 않는다. 업데이트
프로그램의 `--refresh-bootstrap`은 기존 provider/LLM/Neo4j 설정과 secret을 보존하면서 파생
파일만 재생성한다. 두 프로그램은 forward apply 도구이며 자동 rollback 도구가 아니다.
준비 PC는 이전 source commit과 이전 immutable release를 보존하고, 실패 시 사용자 트래픽을
연결하지 않은 채 runbook의 rollback 절차를 수행한다.

외부 OpenAI-compatible Chat/Embedding/Reranker는 이 OS bootstrap에서 임의 활성화하지 않는다.
플랫폼 기동 후 Admin System Settings에서 secret **reference**, private allowlist, URL, model을
TEST/SAVE/ACTIVATE하고 API/해당 worker를 업데이트 워크플로로 재시작한다. Mac profile의
기본 Ollama Chat 설정도 실제 모델 준비와 capability 확인을 대신하지 않는다.

## Canonical ownership

| State | Canonical owner |
|---|---|
| Applied catalog metadata | External DataHub |
| Change intent, approval, audit, jobs, ABAC and KG releases | DataRiver PostgreSQL |
| Credentials | External OIDC provider / mounted secret files |
| Uploaded objects | S3-compatible object storage; manifest in PostgreSQL |
| Cache and short-lived delivery | Separate external Redis endpoints; never canonical |
| Graph query projection | Rebuildable from immutable KG releases |

## Repository map

```text
backend/          FastAPI application, domain modules and workers
frontend/         React + TypeScript web application
infra/            PostgreSQL, Keycloak, Airflow, APISIX and runtime configuration
seed/             explicit deterministic semiconductor seed artifacts
docs/             PRD, architecture, security, API/data specifications and ADRs
scripts/          bootstrap, migration generation and reference-snapshot tools
.github/          portable CI and dependency-update policy
```

## Prerequisites

- Git, Docker Engine/Desktop with Compose v2, at least 8 GiB free memory for core + local identity, and about 12 GiB when Airflow is also enabled.
- Production and shared environments require an externally operated DataHub endpoint and scoped service token. The supported Mac development topology below starts an isolated local DataHub v1.6.0 instead.
- `DATAHUB_EXPECTED_VERSION` is a required deployment setting and must be an exact stable release;
  the current example is `v1.6.0`. The external deployment pins each component using its reviewed
  contract (the current example is `infra/contracts/datahub-v1.6.0-images.json`) and proves its
  rendered images with `scripts/verify_datahub_image_inventory.py`.
- For local source checks: Python 3.12, `uv 0.9.17`, Node.js 22.19 and npm 10.

No real `.env`, secret, uploaded object, database volume or generated Keycloak realm is committed.

## Git and clean-clone portability

Commit only the repository sources. A second PC clones the same tree, runs the matching bootstrap command below, sets its own DataHub URL/origins, and starts the desired overlays. Do not copy `.env`, `secrets/`, `runtime/`, volumes or uploaded objects through Git. The frozen Python and npm locks plus CI define the reproducible toolchain; production promotes digest-pinned images built from the reviewed commit.

## 폐쇄망 개발 PC 이관과 초기화

`docker_imgs/`는 Git에서 무시되는 반입 산출물 디렉터리다. 여기에는 정확한 source commit의
Git bundle, Linux OCI 이미지 tar, SHA-256 검증 파일, 이미지 ID/digest manifest와 release
index만 둔다. `.env`, `secrets/`, DB·외부 S3
볼륨, 업로드 파일, DataHub 데이터 및 Ollama 모델은 포함하지 않는다. 반입 PC의 Docker
아키텍처가 같아야 한다. 이 Mac 구성의 bundle은 기본적으로 `linux/arm64`이며,
`linux/amd64` 서버에는 별도의 amd64 bundle을 연결망 빌드 환경에서 만들어야 한다.
Apple Silicon Docker Desktop은 Buildx가 활성화되어 있으면 아래처럼 `linux/amd64`를 반출할
수 있다. 이 경우 기존 ARM64 tag는 임시 백업 후 즉시 복원하므로 실행 중인 ARM64 container의
image ID는 바뀌지 않는다. 단, cross-platform build와 tar 생성에는 Docker Desktop 데이터
디스크에 충분한 여유 공간(권장 30 GiB 이상)이 필요하다.

### 연결망 준비 PC: 이미지 반출

현재 소스 revision으로 내부 이미지를 다시 빌드한 뒤 tar를 만든다. 기본 bundle에는 즉시
실행하지 않는 API/Web container 이미지도 포함한다. 따라서 개발 중에는 호스트 소스를
실행하더라도 이후 container 실행으로 전환할 수 있다. 기존 DataHub가 있는 이관에는 첫
bundle만 필요하다.

```bash
chmod +x scripts/export_offline_images.sh scripts/dev_host.sh
./scripts/export_offline_images.sh --platform linux/aarch64 \
  --build-datariver --include-observability

# Linux x86_64/amd64 운영 PC용 (DataHub를 별도 운영하는 현재 경로)
./scripts/export_offline_images.sh --platform linux/amd64 \
  --build-datariver --include-observability
```

두 명령은 같은 clean commit에서 실행하므로 기본적으로 동일한
`docker_imgs/datariver-<12자리-commit>/arm64|amd64` 릴리스 아래에 기록된다. 기존 platform
디렉터리는 덮어쓰지 않는다. Redis/MinIO reference image까지 외장 매체로 복사하려면 해당
배포본의 라이선스·재배포 검토를 운영자가 승인한 뒤에만 두 명령에
`--include-local-connectors --accept-local-connector-license-review`를 추가한다. 승인 없이도
DataRiver source와 core image를 반출하고 대상이 별도로 운영하는 Redis/MinIO endpoint에
연결할 수 있다.

### 연결망 준비 PC: Python 의존성 캐시 반출

`uv.lock`은 정확한 버전을 고정하지만 package artifact 자체를 Git에 넣지 않는다. 따라서
새 lockfile을 반입하기 전에는 대상과 같은 OS·CPU·Python 3.12·`uv 0.9.17` 환경에서 아래
명령으로 검증 가능한 cache archive를 만든다. 이 스크립트는 별도 임시 virtual environment에
전체 dependency를 설치한 뒤, archive를 다시 풀어 `--offline` 설치까지 확인한다.

```bash
chmod +x scripts/export_offline_python_cache.sh
./scripts/export_offline_python_cache.sh
```

출력되는 `offline_python/datariver-uv-cache-*.tar.gz`, 동일 이름의 `.sha256`, `.manifest.tsv`는
Git에 commit하지 않는다. checksum과 manifest를 확인한 뒤 승인된 내부 artifact 저장소 또는
외장 매체로 대상 Mac에 전달한다. 이 cache는 생성한 OS·CPU·Python·uv 버전에만 사용한다.

관측성 profile을 사용하지 않는 대상은 `--include-observability`를 생략해도 된다. 반대로 이
Mac에서 현재처럼 Grafana/Prometheus/OTel/Tempo/Loki/Alertmanager를 함께 사용할 경우
`datariver-observability-pilot-arm64.tar`도 같은 방식으로 반입한다. 이 bundle은
Single-node Pilot 관측성용이며, 기업 운영 telemetry backend를 대체하지 않는다.

DataHub가 전혀 없는 Apple-Silicon 개발 PC까지 준비하려면, 공식 DataHub `v1.6.0` checkout과
이미지를 먼저 연결망에서 준비한 후 별도 bundle도 만든다.

```bash
./scripts/start_datahub_mac_dev.sh start
./scripts/export_offline_images.sh --include-datahub-mac-dev
```

두 번째 명령은 `datahub-v1.6.0-mac-dev-arm64.tar`와
`datahub-v1.6.0-source.bundle`을 만든다. 이 DataHub quickstart는 Mac 개발용이며 운영
DataHub 배포본이 아니다. 특히 upstream quickstart가 참조하는
`acryldata/datahub-kafka-setup:head`는 bundle manifest에 실제 관측 digest를 기록한다. 이를
일반 운영 환경의 mutable tag 허용 근거로 사용하면 안 된다. 운영 DataHub는 별도 소유자가
모든 component digest와 보안 설정을 확정해야 한다.

반입 전 `scripts/verify_offline_release.sh`로 release ID, source commit, target platform,
manifest와 모든 `*.sha256`을 확인하고, 외장 매체 또는 승인된 내부 artifact 저장소로 해당
release 디렉터리를 전달한다. 내부 Registry가 있으면 tar 대신 해당 Registry로 digest 고정
이미지를 승격하는 방식을 우선한다.

교차 빌드한 amd64 bundle은 arm64 반출 PC에서 `--artifact-only`로 checksum/source/manifest를
검증한다. 이 옵션은 target Docker를 검증하지 않으므로 WSL 반입 시에는 생략하고 `--load`와
`--env-file`을 사용해야 한다.

```bash
./scripts/verify_offline_release.sh docker_imgs/<release-id> \
  --platform linux/amd64 --source-dir . --artifact-only
```

### WSL 폐쇄망 반입 시 권한·환경·이미지 확인

릴리스를 root 또는 다른 계정으로 압축 해제하면 exporter의 제한된 staging mode 때문에
`amd64/`가 현재 운영 계정에 존재하지 않는 것처럼 보일 수 있다. 릴리스 디렉터리만 정확히
지정해 소유권과 읽기 권한을 복구하고, 애플리케이션 checkout이나 Docker volume 전체에
재귀 권한 변경을 적용하지 않는다.

```bash
RELEASE_DIR=/transfer/datariver-release/datariver-<12자리-commit>
sudo chown -R "$(id -un):$(id -gn)" "$RELEASE_DIR"
sudo find "$RELEASE_DIR" -type d -exec chmod 0755 {} +
sudo find "$RELEASE_DIR" -type f -exec chmod 0644 {} +
test -r "$RELEASE_DIR/amd64/datariver-core-amd64.tar"
```

`.env.wsl-preparation`과 secret 파일은 Git 관리 대상이 아니므로 `git pull`로 갱신되지 않는다.
기존 파일에 bootstrap을 다시 적용한 뒤, Redis 전환 환경에서는 다음 네 canonical 설정이
모두 존재하는지 확인한다. `VALKEY_*` 이름은 이전 환경을 읽기 위한 alias일 뿐 신규 설정에
추가하지 않는다.

```dotenv
REDIS_CACHE_URL=redis://redis-cache:6379/0
REDIS_DELIVERY_URL=redis://redis-delivery:6379/0
REDIS_CACHE_SECRET_REF=file:/run/secrets/redis_cache_password
REDIS_DELIVERY_SECRET_REF=file:/run/secrets/redis_delivery_password
```

Docker Desktop의 containerd image store가 기록한 OCI manifest ID와 WSL Docker가
`docker image load` 후 표시하는 config ID는 다를 수 있다. `already exists`는 동일 layer
재사용 메시지이며 실패가 아니다. Bundle checksum, `linux/amd64`, tar의 해당 tag가 가리키는
config digest와 대상의 `docker image inspect .Id`가 모두 일치해야 한다. 엔진 간 표시 ID
차이를 이유로 이미지를 반복 삭제하거나 volume을 제거하지 않는다. 실행 가능한 확인 명령은
[Mac-to-WSL runbook](docs/26_MAC_TO_WSL_MIGRATION_RUNBOOK.md)에 둔다.

Core-only release와 별도로 승인·반입한 Redis tar는 `redis:8.2.6-bookworm` tag로 load한 뒤
offline Compose에 그 tag를 명시한다. 외부 Redis를 선택한 배포는 이 서비스를 시작하지 않고
두 private `redis://` 또는 `rediss://` endpoint를 설정한다.

```bash
REDIS_IMAGE=redis:8.2.6-bookworm \
scripts/compose.sh --env-file .env.wsl-preparation \
  -f compose.local-connectors.yaml \
  up -d --wait --no-build --pull never redis-cache redis-delivery
```

### 폐쇄망 공통 사전조건

1. Git mirror 또는 승인된 source bundle에서 이 repository의 동일 commit을 checkout한다.
2. Docker Engine/Desktop와 Compose v2, Python 3.12, `uv 0.9.17`, Node.js 22.19/npm 10을
   대상 Mac에 설치한다. 호스트 소스 실행은 Git만으로 완료되지 않는다. 연결망 준비 PC에서
   `scripts/export_offline_python_cache.sh`로 만든 uv cache archive 또는 사내 PyPI mirror와
   npm cache 또는 사내 npm mirror도 함께 준비해야 한다. 폐쇄망에서는 `uv sync --offline` 및
   `npm ci --offline`이 필요한 패키지를 찾지 못하면 의도적으로 실패한다.
3. 승인된 환경 설정과 비밀정보를 별도 보안 채널로 배포한다. 개발 PC의 비밀정보를 Git이나
   이미지 tar에 넣지 않는다. 새 환경에서는 최소한 DataHub service token, DB 역할별
   password, Redis password, S3 credential, OIDC client/issuer와 TLS·CA 신뢰 구성을
   대상 환경 값으로 발급한다.
4. DataHub, Redis, S3/MinIO, Airflow, 외부 DB/Oracle 및 LLM은 DataRiver Compose가 자동
   설치하는 외부 시스템이 아니다. 기본 Compose가 소유하는 상태 저장 인프라는
   PostgreSQL뿐이고, 로컬 OIDC가 필요할 때만 Keycloak overlay를 선택한다. Airflow/APISIX와
   개발용 Neo4j도 명시적 선택 profile이다. DataHub는 외부 catalog provider이며, 실제
   Postgres/Oracle source system도 해당 시스템 또는 DataHub ingestion이 별도로 운영한다.

`System settings` 화면은 접속 주소, 모델 ID, 비밀 **참조명**과 비민감 옵션을 관리한다.
비밀번호·token을 화면에 저장하거나 browser로 보내지 않는다. 개발 PC에서 TEST/SAVE 후
명시적으로 ACTIVATE하고 API/관련 Worker를 재시작해야 적용된다. 운영에서는 이 runtime
activation을 활성화하지 않고 배포 설정과 secret mount를 사용한다.

### 원격 DataHub v1.6의 Token authentication 활성화

원격 DataHub 화면에서 `Token based authentication is currently disabled`가 보이면 DataRiver가
아닌 **원격 DataHub GMS 인증**이 비활성화된 상태다. 원격 서버의 실제 Compose checkout에서
처리한다. 이 변경 뒤에는 모든 프로그램 API 요청이 Bearer token을 요구하므로, 연결된 ingestion과
자동화에도 같은 유지보수 창과 token 배포가 필요하다.

1. 현재 DataHub Compose 파일·`.env`·metadata DB를 백업하고 `docker compose config --services`로
   실제 GMS/Frontend service 이름을 확인한다. 볼륨이나 metadata DB를 지우지 않는다.
2. Git 밖의 `0600` 파일에 signing key와 salt를 한 번 생성해 계속 보관한다. 이 두 값을 변경하면
   access token과 session이 무효화된다.

   ```bash
   umask 077
   mkdir -p secrets
   {
     printf '%s\n' 'METADATA_SERVICE_AUTH_ENABLED=true'
     printf 'DATAHUB_TOKEN_SERVICE_SIGNING_KEY='; openssl rand -hex 32
     printf 'DATAHUB_TOKEN_SERVICE_SALT='; openssl rand -hex 32
   } > secrets/datahub-token-auth.env
   chmod 600 secrets/datahub-token-auth.env
   ```

3. 현재 v1.6 Compose에 `datahub-gms`의 `METADATA_SERVICE_AUTH_ENABLED=true` 및
   `DATAHUB_TOKEN_SERVICE_SIGNING_KEY`/`DATAHUB_TOKEN_SERVICE_SALT`를 추가한다. Frontend에도
   `METADATA_SERVICE_AUTH_ENABLED=true`를 전달하고, `datahub-upgrade`에는 같은 key/salt를
   전달한다. 표준 `without-neo4j` Compose라면 아래 override를 기존 파일에 더한다. service 이름은
   실제 배포의 `config --services` 출력에 맞춘다.

   ```yaml
   services:
     datahub-gms:
       environment:
         METADATA_SERVICE_AUTH_ENABLED: "true"
         DATAHUB_TOKEN_SERVICE_SIGNING_KEY: ${DATAHUB_TOKEN_SERVICE_SIGNING_KEY}
         DATAHUB_TOKEN_SERVICE_SALT: ${DATAHUB_TOKEN_SERVICE_SALT}
     datahub-frontend-react:
       environment:
         METADATA_SERVICE_AUTH_ENABLED: "true"
     datahub-upgrade:
       environment:
         DATAHUB_TOKEN_SERVICE_SIGNING_KEY: ${DATAHUB_TOKEN_SERVICE_SIGNING_KEY}
         DATAHUB_TOKEN_SERVICE_SALT: ${DATAHUB_TOKEN_SERVICE_SALT}
   ```

4. 기존 Compose 파일 조합 그대로 검증한 뒤 GMS/Frontend만 재생성한다. quickstart, PostgreSQL,
   without-neo4j 등의 다른 topology 파일을 임의로 섞지 않는다.

   ```bash
   docker compose --env-file .env --env-file secrets/datahub-token-auth.env \
     -f <current-datahub-compose>.yaml -f compose.token-auth.override.yaml config --quiet
   docker compose --env-file .env --env-file secrets/datahub-token-auth.env \
     -f <current-datahub-compose>.yaml -f compose.token-auth.override.yaml \
     up -d --no-deps --force-recreate datahub-gms datahub-frontend-react
   ```

5. 다시 로그인해 **Settings → Users & Groups → Service Accounts**에서 DataRiver 전용 service
   account를 만들고, **Settings → Access Tokens**에서 token을 발급한다. token 원문은 한 번만
   표시되므로 대상 PC의 `secrets/datahub_token`에 보안 채널로 배치한다. 역할은 DataRiver가 실제로
   조회·변경할 Dataset/Tag/Term/Domain 범위로 최소화한다.

인증 문제가 있으면 `METADATA_SERVICE_AUTH_ENABLED=false`로 되돌리고 **같은** signing key/salt를
유지한 채 GMS/Frontend를 재생성한다. 이 rollback은 metadata를 삭제하지 않는다. 변수와 token
전제조건은 [동봉된 DataHub v1.6 authentication 문서](runtime/datahub-v1.6.0/docs/authentication/README.md)와
[personal access token 문서](runtime/datahub-v1.6.0/docs/authentication/personal-access-tokens.md)를 따른다.

### Case 1 — 기존 DataHub가 이미 운영 중인 경우 (현재 권장 경로)

아래는 기존 DataHub GMS가 같은 Mac의 `8080` 또는 승인된 원격 URL에서 정상 운영 중이고,
DataRiver의 변경 중인 API·Worker·UI는 container가 아닌 checkout source에서 실행하는 절차다.
DataHub가 같은 Mac Docker Desktop에 있다면 Docker process에는
`host.docker.internal:8080`, host source process에는 `127.0.0.1:8080`을 사용한다.

```bash
# 1. 반입한 immutable release의 source/checksum/platform을 검증하고 모든 bundle을 적재한다.
# <release-id>는 예: datariver-0123456789ab
./scripts/verify_offline_release.sh docker_imgs/<release-id> \
  --platform linux/aarch64 --source-dir . --load --env-file .env.mac-development

# 2. 원격 DataHub service-account token은 보안 반입 위치에서 secret file로 배치한다.
#    토큰 원문을 명령 인자, shell history, Git에 넣지 않는다.
install -d -m 700 secrets
install -m 600 /approved-secure-transfer/datahub_token secrets/datahub_token
```

별도 보안 반입 파일이 없고 DataHub 화면에서 token 원문만 복사한 경우에는, 위의 두 `install`
명령 대신 같은 위치에서 아래를 한 줄씩 실행한다. 세 번째 명령을 실행한 뒤 token을 붙여넣고
Enter를 한 번 더 누른다. 입력 내용은 터미널에 표시되지 않는다. `echo <token>` 또는
`bootstrap.sh`의 positional argument처럼 token을 명령행에 넣지 않는다.

```bash
install -d -m 700 secrets
printf 'Paste DataHub token, then press Enter: '
read -r -s datariver_datahub_token
printf '\n'
printf '%s' "$datariver_datahub_token" > secrets/datahub_token
unset datariver_datahub_token
chmod 600 secrets/datahub_token
```

bootstrap은 이미 존재하는 `secrets/datahub_token`을 보존하므로, 다음 명령에는 token 인자를
넣지 않는다.

```bash

# 3. DataRiver 환경 초기화. 원격 DataHub URL은 container/host 모두 같은 HTTPS origin을 쓴다.
./scripts/bootstrap.sh --host-development \
  --datahub-base-url https://datahub.example.internal

# 4. 상태 저장소와 로컬 identity만 container로 시작한다.
scripts/compose.sh --env-file .env \
  -f compose.yaml -f compose.identity.yaml -f compose.source-host.yaml \
  config --quiet
scripts/compose.sh --env-file .env \
  -f compose.yaml -f compose.identity.yaml -f compose.source-host.yaml \
  up -d --pull never --no-build --wait \
  postgres keycloak
./scripts/configure_keycloak_host_dev.sh
scripts/compose.sh --env-file .env \
  -f compose.yaml -f compose.identity.yaml -f compose.source-host.yaml \
  run --rm migrate
scripts/compose.sh --env-file .env --profile object-storage-tools \
  -f compose.yaml -f compose.identity.yaml -f compose.source-host.yaml \
  run --rm storage-init
scripts/compose.sh --env-file .env --profile tools \
  -f compose.yaml -f compose.identity.yaml \
  -f compose.source-host.yaml run --rm local-bootstrap
```

`compose.source-host.yaml`은 PostgreSQL만 내부 `data` network와 전용 `source-access`
bridge에 함께 연결한다. 후자는 host source process가 사용하는 명시적
`127.0.0.1` binding만 게시하며 다른 application service를 수용하지 않는다. `docker ps`의
PostgreSQL ports가 `5432/tcp`로만 보이고 `127.0.0.1:5432->5432/tcp`가 없다면 오래된 overlay로
생성된 container이므로, 최신 overlay를 받은 뒤 같은 세 Compose 파일로 다시 생성한다.

`manifest.tsv.sha256`은 manifest 파일의 무결성을 확인한다. manifest 내용의 image ID와
repository digest를 승인 목록과 비교한다. `docker load`가 외부 registry 접속을 유발해서는
안 되며, 이후 Compose에도 `--pull never --no-build`를 유지한다.

호스트 소스 의존성은 반입한 cache/mirror로 설치한다. 이미 준비된 `.venv`와 npm cache가
없다면 이 단계에서 멈추고 package artifact를 먼저 반입한다.

```bash
# 연결망 준비 PC에서 만든 cache archive의 checksum을 먼저 확인한 뒤 실행한다.
(cd <artifact-directory> && shasum -a 256 -c datariver-uv-cache-<os>-<arch>-<lock-hash>.tar.gz.sha256)
mkdir -p "$HOME/.cache"
tar -xzf datariver-uv-cache-<os>-<arch>-<lock-hash>.tar.gz -C "$HOME/.cache"

uv sync --frozen --all-extras --offline
(cd frontend && npm ci --offline --no-audit --no-fund)

# API, relay, upload worker, validation worker, governance worker, Vite를 source에서 실행한다.
# bootstrap이 .env에 기록한 DATAHUB_BASE_URL을 자동으로 사용한다.
./scripts/dev_host.sh start
./scripts/dev_host.sh status
curl --fail --silent --show-error http://127.0.0.1:38101/api/v1/health/ready
```

`--host-development` bootstrap은 source API `38101`, Vite `38102`와 승인된 GMS
`DATAHUB_BASE_URL`을 `.env`에 기록하며 `dev_host.sh`와 Keycloak redirect configurator는 같은
값을 읽는다. `dev_host.sh start`의 `--datahub-base-url`은 일회성 override가 필요할 때만 사용한다.

Vite는 npm wrapper가 아니라 checkout의 Vite Node entrypoint를 직접 실행해 기록된 PID와 실제
listener가 일치한다. `stop`과 다음 `start`는 이전 launcher가 남긴 Vite도 현재 사용자, 현재
checkout의 `frontend/node_modules/vite`, 현재 `.env`의 `WEB_PORT`가 모두 일치할 때만 정리한다.
다른 checkout, Docker, Windows `iphlpsvc` 또는 제3자 process는 종료하지 않으며 포트 검사와 함께
실패한다.

기존 source-host를 이 포트 계약으로 전환할 때는 volume이나 infra container를 지우지 않는다.
먼저 `./scripts/dev_host.sh stop`을 실행한다. 최신 launcher가 시작했거나 같은 checkout의 이전
launcher가 남긴 Vite listener는 자동 종료된다. 그래도 포트가 남으면
`sudo ss -ltnp "sport = :38101"` 및 `sudo ss -ltnp "sport = :38102"`로 listener의 PID를 확인한다.
PID가 DataRiver의 이전 Uvicorn process임을 `ps -fp <PID>`로 확인한 경우에만
`kill -TERM <PID>`로 종료한다.
Docker가 점유한 경우에는 `docker ps --filter publish=38101 --filter publish=38102`로 정확한
container를 찾고, 이전 DataRiver API/web container임을 확인한 뒤 해당 compose project에서만
중지한다. WSL의 `ss`에 PID가 보이지 않으면 Windows 측도
`powershell.exe -NoProfile -Command "Get-NetTCPConnection -State Listen -LocalPort 38101,38102"`로
확인한다. 그 밖의 process이면 임의 종료하지 않고 운영자가 충돌을 해소한다. 이후 token 인자 없이 같은
`bootstrap.sh --host-development --datahub-base-url ...`을 다시 실행하고
`configure_keycloak_host_dev.sh`로 단일 허용 redirect origin을 `38102`에 맞춘 뒤 source-host를
재시작한다.

이 개발 PC는 이후 Git으로 소스를 갱신할 수 있다. 다만 source checkout과 offline bundle의
backend image는 서로 다른 버전일 수 있으므로, 새 Alembic revision이 포함된 pull 뒤에는
bundle의 오래된 `migrate` container를 실행하지 말고 아래처럼 source 기준으로 적용한다.
Dockerfile·Compose·기반 image가 바뀐 commit은 Git만으로 반영되지 않으므로, 연결된 build PC에서
새 bundle을 만들어 반입·검증·`docker load`해야 한다.

```bash
git pull --ff-only
uv sync --frozen --all-extras --offline
(cd frontend && npm ci --offline --no-audit --no-fund)

# 새 migration이 있는 경우에만 실행한다. API/worker는 먼저 중지한다.
./scripts/dev_host.sh stop
./scripts/dev_host.sh migrate
./scripts/dev_host.sh start
./scripts/dev_host.sh status
```

`secrets/`·`.env`의 변경도 Git pull 대상이 아니다. 승인된 별도 보안 채널로 배포한 뒤,
관련 source process만 재시작한다. 새 release가 `secrets/`의 파일명, Keycloak realm template 또는
Compose secret mount를 추가한 경우에는 source process를 시작하기 전에 아래 bootstrap을 다시
실행한다. 기존의 non-empty `secrets/datahub_token`은 보존되며, token을 명령행에 다시 넣지 않는다.
`keycloak_identity_admin_client_secret` 같은 새 파일만 생성되고, 이어지는 Keycloak configurator가
이미 존재하는 realm의 dedicated client secret을 안전하게 일치시킨다.

```bash
./scripts/bootstrap.sh --host-development \
  --datahub-base-url https://datahub.example.internal
scripts/compose.sh --env-file .env \
  -f compose.yaml -f compose.identity.yaml -f compose.source-host.yaml \
  up -d --pull never --no-build --wait keycloak
./scripts/configure_keycloak_host_dev.sh
```

외부 DataHub가 원격 HTTPS 주소라면 bootstrap이 `.env`에 기록한 `DATAHUB_BASE_URL`이 정확한
GMS HTTPS origin인지 확인한다. 이후 `dev_host.sh start`는 이 값을 자동으로 사용한다. CLI의
`--datahub-base-url`은 `.env`를 변경하지 않는 일회성 override다. API가 아닌 browser에는 DataHub
service token을 주지 않는다.
사설 CA를 쓰는 경우 macOS의 시스템 신뢰 저장소와 host Python이 그 CA를 신뢰하게 사전 배포하며,
TLS 검증을 끄지 않는다. Airflow까지 테스트할 때는 `bootstrap.sh`가 기록한
`DATARIVER_API_BASE_URL`만 사용한다. macOS Docker Desktop은 native loopback gateway의
`host.docker.internal:38101`을, Linux/WSL은 loopback API를 외부에 노출하지 않는 private Docker
bridge의 `host.docker.internal:38103`을 사용한다.

```bash
scripts/compose.sh --env-file .env \
  -f compose.yaml -f compose.identity.yaml -f compose.source-host.yaml \
  -f compose.airflow.yaml up -d --pull never --no-build --wait \
  airflow-api-server airflow-scheduler airflow-dag-processor airflow-triggerer
```

Linux/WSL에서 **source API도 WSL에서 실행할 때만**, bootstrap에
`--source-host-airflow-bridge`를 추가한다. `dev_host.sh`가 Docker bridge의 RFC1918 address에만
`airflow-api-bridge`를 만들고 `127.0.0.1:38101` API로만 forward한다. `0.0.0.0` bind, Windows/LAN
port-forward 또는 API token을 Airflow에 주는 방식으로 우회하지 않는다.

```bash
./scripts/bootstrap.sh --host-development --source-host-airflow-bridge \
  --datahub-base-url https://datahub.example.internal
./scripts/dev_host.sh start
./scripts/dev_host.sh status
# airflow-api-bridge가 running이어야 한다.
```

bridge가 시작되지 않으면 컨테이너·volume을 삭제하지 말고 Docker bridge의 IPAM 구성부터 확인한다.
IPv4/IPv6 gateway가 함께 반환되는 Docker Engine도 지원한다.

```bash
docker network inspect bridge
cat runtime/source-host/airflow-api-bridge.err.log
```

`DATAHUB_BASE_URL`은 DataHub **GMS**의 origin(예: `https://datahub-gms.example.internal`)이며
`/api` path나 DataHub Frontend URL이 아니다. 이 설정은 API가 scoped service token으로 provider에
연결할 수 있게 할 뿐, 외부 catalog를 브라우저나 API 시작 시점에 자동 복사하지 않는다. 첫 projection은
Airflow의 최소권한 service account만 실행할 수 있다. Airflow가 healthy가 된 뒤 아래를 한 번 실행해
즉시 동기화하고, 계속 6시간 주기 동기화를 원하면 DAG를 unpaused 상태로 둔다.

동기화는 DataHub의 고정 `scrollAcrossEntities` 계약을 사용한다. 추가/갱신은 언제나 가능하지만,
누락 asset의 tombstone은 기본적으로 억제된다. 외부 DataHub 운영자가 해당 배포의 point-in-time
scroll을 실제 동시 변경/만료/재시도 조건에서 검증하고 승인 근거를 남긴 경우에만
`DATAHUB_VERSION_ENFORCEMENT=enforce`,
`DATAHUB_CATALOG_PIT_VERIFIED=true`,
`DATAHUB_CATALOG_PIT_EVIDENCE_REFERENCE=<accepted-reference>`를 함께 설정한다. 버전 일치만으로는
충분하지 않으며, 기본 `false`에서 정상 완료한 run은
`SUPPRESSED_UNVERIFIED_SNAPSHOT`을 보고하고 삭제하지 않는다. 페이지 안전 한도는
`DATARIVER_CATALOG_SYNC_MAX_PAGES`(기본 10,002, 범위 1..100,002)로 설정한다. 각 Airflow
재시도는 서버의 public page ordinal에서 바로 재개하며 provider cursor를 노출하거나 앞 페이지를
다시 순회하지 않는다. API는 DataHub 호출 전에 workspace별 실행권을 예약해 snapshot의 역순 적용을
막고, 8 MiB 응답 상한을 넘으면 동일 cursor의 page size를 1까지 단계적으로 줄인다.

```bash
# local-bootstrap이 먼저 완료되어 Airflow service account의 catalog.sync 권한이 있어야 한다.
scripts/compose.sh --env-file .env \
  -f compose.yaml -f compose.identity.yaml -f compose.source-host.yaml \
  -f compose.airflow.yaml exec airflow-api-server \
  /bin/bash /opt/datariver/airflow-entrypoint.sh \
  dags unpause datariver_catalog_sync
scripts/compose.sh --env-file .env \
  -f compose.yaml -f compose.identity.yaml -f compose.source-host.yaml \
  -f compose.airflow.yaml exec airflow-api-server \
  /bin/bash /opt/datariver/airflow-entrypoint.sh \
  dags trigger datariver_catalog_sync
```

Sync run이 `SUCCESS`가 되면 Search는 DataHub의 Dataset projection을 표시한다. 실패하면 Airflow
task log의 DataHub provider code를 확인한다: `UNAUTHORIZED`는 `secrets/datahub_token`의 service
account 범위가 Dataset/Tag/Glossary Term read에 부족한 경우이고, `VERSION_MISMATCH`는 GMS가
`DATAHUB_EXPECTED_VERSION`과 다를 때다. `NETWORK`/TLS 실패는 source API가 원격 GMS의 사설 CA를
신뢰하지 못한 경우이므로 TLS 검증을 끄지 말고 해당 CA를 host trust store에 설치한다.

source-host에서 Airflow를 처음 시작할 때 API origin을 지정하지 않으면 container topology의 기본값
`http://api:8000`을 사용한다. 이 topology에는 API container가 없으므로 task가 DNS 오류로 실패한다.
현재 `bootstrap.sh --host-development`은 macOS 및 Windows-host source에는
`DATARIVER_API_BASE_URL=http://host.docker.internal:38101`을, Linux/WSL에는 private bridge의
`DATARIVER_API_BASE_URL=http://host.docker.internal:38103`을 기록한다. 후자는
`--source-host-airflow-bridge`를 명시한 경우에만 선택된다. 이전 bootstrap으로 만든 환경은 token
인자 없이 한 번 다시 실행하고 source-host와 Airflow 네 서비스를 반드시 재생성한다.

```bash
./scripts/bootstrap.sh --host-development --source-host-airflow-bridge \
  --datahub-base-url https://datahub.example.internal
./scripts/dev_host.sh stop
./scripts/dev_host.sh start
scripts/compose.sh --env-file .env \
  -f compose.yaml -f compose.identity.yaml -f compose.source-host.yaml \
  -f compose.airflow.yaml up -d --pull never --no-build --force-recreate --wait \
  airflow-api-server airflow-scheduler airflow-dag-processor airflow-triggerer
```

`datariver_bulk_registration_prepare`와 `datariver_manual_metadata_apply`는 각각 5분 주기의
bounded receipt worker이며, 등록할 receipt가 없을 때도 DataRiver API에 안전하게 조회한다.
`datariver_catalog_sync`는 6시간 주기의 DataHub-to-projection reconciliation이다. 세 DAG가
동시에 `temporary failure in name resolution`으로 실패하면 DataHub token 문제가 아니라 이 API
origin 또는 내부 proxy/DNS 구성을 먼저 확인한다.

포함된 Airflow UI 인증은 loopback 개발용이다. 공유/운영 Airflow는 조직의 SSO 구성을 별도로
적용해야 한다.

GraphRAG 개발 검증에는 Neo4j projection과 native Ollama model artifact도 별도 반입한다.
Ollama는 Docker image가 아니라 호스트 프로세스이므로 engine과
`gemma4:e2b-it-qat`, `bge-m3:latest` model blobs를 연결망에서 미리 준비한다.

```bash
ollama show gemma4:e2b-it-qat
ollama show bge-m3:latest
./scripts/prepare_ollama_mac_dev.sh
scripts/compose.sh --env-file .env -f compose.yaml -f compose.graph.yaml \
  up -d --pull never --no-build --wait neo4j
./scripts/dev_host.sh preflight \
  --enable-local-ollama --enable-neo4j
./scripts/dev_host.sh stop
./scripts/dev_host.sh start \
  --enable-local-ollama --enable-neo4j
```

`preflight`는 프로세스를 시작하지 않고 선택한 Neo4j/Chat/Embedding의 최종 Settings 계약을
검증해 안전한 JSON 결과를 출력한다. 실제 endpoint 연결 여부는 각 System Settings의 고정 TEST로
별도 확인한다. `--enable-local-ollama`과 `--enable-neo4j`는 서로 독립적인
Mac 개발 capability이며, 둘을 함께 켜야만 각 기능이 활성화되는 전역 전제는 아니다. 각 Asset/LLM
system setting은 실제 비밀정보가 아닌 이미 mount된 참조명을 사용한다. 위 startup-resolver의
두 값을 명시적으로 opt-in한 환경에서만 TEST/SAVE/ACTIVATE한 뒤 source-host 프로세스를
재시작한다.

사내 OpenAI-compatible LLM을 사용할 때는 위 두 flag를 함께 쓰지 않는다. 먼저 Neo4j container를
기동하고 Chat·Embedding·Neo4j System Settings revision을 각각 TEST/SAVE/ACTIVATE한다. 이후에는
System Settings startup resolver가 세 profile을 함께 읽으므로 flag 없이 source-host process만
재시작한다.

```bash
scripts/compose.sh --env-file .env -f compose.yaml -f compose.graph.yaml \
  up -d --pull never --no-build --wait neo4j
./scripts/dev_host.sh stop
./scripts/dev_host.sh start
```

### Case 2 — DataHub도 아직 없는 경우

이 경우는 **Mac 개발 PC**에 한해 제공되는 local DataHub `v1.6.0` quickstart 절차다. 실제
운영 DataHub를 대신하지 않는다. 먼저 Case 1의 platform bundle에 더해
`datahub-v1.6.0-mac-dev-arm64.tar`와 source bundle을 적재한다.

```bash
cd docker_imgs
shasum -a 256 -c datahub-v1.6.0-mac-dev-arm64.tar.sha256
shasum -a 256 -c datahub-v1.6.0-source.bundle.sha256
docker load -i datahub-v1.6.0-mac-dev-arm64.tar
cd ..

mkdir -p runtime
git clone docker_imgs/datahub-v1.6.0-source.bundle runtime/datahub-v1.6.0
git -C runtime/datahub-v1.6.0 checkout 059a36c0b035a6057de00114ccac0ea9003d6bc2

# Local DataHub quickstart has no external service token. Use the explicit
# development-only Mac placeholder generated by this profile.
./scripts/bootstrap.sh --mac-development \
  --datahub-base-url http://host.docker.internal:8080
./scripts/start_datahub_mac_dev.sh start-offline
```

이후 Case 1의 3단계부터 이어서 DataRiver infra container와 source-host process를 시작한다.
DataHub를 실제 운영에 새로 설치해야 한다면 이 quickstart가 아니라 별도 DataHub 운영
repository, 고정 component digest, 인증·백업·Kafka/DB/검색 cluster 설계와
`verify_datahub_image_inventory.py`/`verify_datahub_contract.py` 검증을 사용한다.

## Validated Mac development PC

This is a single-developer topology, not a production deployment. On a 32 GiB Mac, set Docker Desktop to **16 GiB memory and 6 CPUs** by default, or at most **18 GiB** for a bounded large import; Ollama runs natively on macOS outside that limit. The selected `datariver-gemma4-dev:0.1` model reuses Gemma4 E2B QAT weights with an 8,192-token context ceiling. Do not run a second Ollama container.

The first bootstrap generates a private local DataHub placeholder token, all DataRiver/Neo4j secrets and the Keycloak realm. It does not copy another machine's `.env`, volumes or credentials. The separate DataHub wrapper obtains the official `v1.6.0` source checkout under ignored `runtime/` and starts its official Apple-Silicon `without-neo4j` topology. `without-neo4j` is intentional: DataHub lineage remains in DataHub; the separate Neo4j service below is a rebuildable **DataRiver knowledge-graph projection sandbox**, never a DataHub database.

```bash
# Native macOS Ollama must already be running. This reuses the Gemma4 E2B QAT
# weights and creates a local 8,192-token development derivative.
./scripts/prepare_ollama_mac_dev.sh

./scripts/bootstrap.sh --mac-development
./scripts/start_datahub_mac_dev.sh start

scripts/compose.sh --env-file .env --profile observability \
  -f compose.yaml -f compose.identity.yaml -f compose.airflow.yaml \
  -f compose.gateway.yaml -f aux-compose.yml -f compose.graph.yaml config --quiet
scripts/compose.sh --env-file .env --profile observability \
  -f compose.yaml -f compose.identity.yaml -f compose.airflow.yaml \
  -f compose.gateway.yaml -f aux-compose.yml -f compose.graph.yaml \
  up -d --build --wait
scripts/compose.sh --env-file .env --profile tools \
  -f compose.yaml -f compose.identity.yaml \
  -f compose.airflow.yaml -f compose.gateway.yaml -f aux-compose.yml \
  -f compose.graph.yaml run --rm local-bootstrap

# Optional but recommended: deterministic catalog/KG test data.
scripts/compose.sh --env-file .env --profile semiconductor-seed \
  -f compose.yaml -f compose.identity.yaml \
  -f compose.airflow.yaml -f compose.gateway.yaml -f aux-compose.yml \
  -f compose.graph.yaml run --rm semiconductor-seed
scripts/compose.sh --env-file .env --profile semiconductor-seed \
  -f compose.yaml -f compose.identity.yaml \
  -f compose.airflow.yaml -f compose.gateway.yaml -f aux-compose.yml \
  -f compose.graph.yaml run --rm semiconductor-seed \
  /app/.venv/bin/python -m datariver.seed verify
```

Use DataRiver at `http://localhost:38102`, its API at `http://localhost:38101`, its gateway at `http://localhost:19080`, local DataHub GMS at `http://localhost:8080`, DataHub UI at `http://localhost:19002`, Neo4j Browser at `http://localhost:17474`, and Neo4j Bolt at `bolt://localhost:17687`. The local model is reached only by backend containers through `host.docker.internal:11434`; it receives fixed, non-executable typed extraction/citation contracts and cannot execute SQL, Cypher, HTTP requests, files, or DataRiver mutations. The Neo4j volume may be deleted and rebuilt, but PostgreSQL knowledge releases remain canonical. See [ADR-0023](docs/adr/0023-mac-development-local-inference-and-graph-projection.md) for the canonical ownership and development-only security boundary.

On the 32 GiB Mac development host, keep Docker Desktop at `16 GiB` by default and use `18 GiB` only
for bounded large imports rather than raising it to `24 GiB`: the full DataRiver + DataHub stack
uses substantial memory, while the host Ollama
`gemma4` derivative needs separate unified-memory headroom when loaded. Recheck `docker stats` and
`ollama ps` during GraphRAG tests; sustained swap or memory pressure means stop optional services,
not enlarge both Docker and model budgets past physical memory.

## Initialization and verification checklist

Use this sequence for a new environment or a restored database. It is safe to repeat the
non-destructive bootstrap, migration, seed verification and health checks; do not reuse another
environment's secrets or volumes.

1. Read [architecture](docs/03_ARCHITECTURE.md), [deployment](docs/08_DEPLOYMENT.md) and the
   canonical ownership table above. PostgreSQL owns DataRiver workflow state; DataHub is the
   external owner of applied catalog metadata; S3-compatible storage owns object bytes; Redis is
   disposable cache/delivery state.
2. Bootstrap `.env` and ignored secret files with `scripts/bootstrap.sh` or
   `scripts/bootstrap.ps1`. Set the external DataHub base URL, service token, OIDC origins and any
   optional UI links before starting services. `DATAHUB_EXPECTED_VERSION` remains a stable release
   contract. The bundled Mac launcher checks out the exact stable `v1.6.0` commit and uses the
   digest-pinned `v1.6.0` component images; do not add an RC compatibility exception for this local
   topology.
3. Validate the selected Compose overlay with `docker compose ... config --quiet`, then bring up
   the external Redis and S3 connectors, then PostgreSQL and the selected local Keycloak/APISIX
   overlays. For an existing PostgreSQL volume, run `scripts/reconcile-postgres-roles.sh` (or the
   PowerShell equivalent) before and after applying `alembic upgrade head` through the migration
   service; the second idempotent pass repairs Phase 2 grants when roles were created after an older
   migration. Readiness requires revision `0055`.
4. Start the API, relay, workers and web service using either the container profile or the
   host-development commands below. Check `/api/v1/health/live`, `/api/v1/health/ready`,
   `/api/v1/capabilities` and the APISIX/Vite proxy before using application workflows.
5. Apply the optional deterministic seed only when synthetic reference data is wanted, then run its
   `verify` command. Never seed production data.
6. Sign in, choose a workspace and complete a catalog, registration and change-request state flow.
   Development can validate normal CR state transitions with the local ordinary OIDC account;
   hardware-key enforcement remains a production-sensitive-operation gate.

### Administrator system configuration

Policy Book/RBAC, retention execution and Admin UI completion use three explicit approval gates.
Phase 1 adds Role-version No/Partial/Full data rules plus normalized assignment evidence. Phase 2
adds a disabled-first archive-only execution control plane with separate scheduler/archive DB roles,
fenced leases, current-policy/Role/target/Hold revalidation and immutable full read-back evidence.
Its exact capability attestation is committed before a conditional, non-auto-retried object create;
every expired write lease is reconciled read-only and with a bounded persistent recovery budget. It
interprets provider `LastModified` as `[t, t+1s)` and accepts a receipt only when the policy
lifecycle/effective window, execution authorisation and exact capability cover that entire interval.
The configured archive-principal fingerprint still requires
operator evidence binding it to the provider access-key identity before target activation. It
contains no deletion or partition-drop path and does not silently enable unfinished Admin controls.
See the
[Policy Book PRD](docs/27_POLICY_BOOK_ADMIN_GOVERNANCE_PRD.md),
[execution checklist](docs/28_POLICY_BOOK_EXECUTION_CHECKLIST.md) and
[ADR-0036](docs/adr/0036-policy-book-rbac-and-admin-approval-gates.md) plus
[ADR-0037](docs/adr/0037-retention-execution-control-plane.md). On a new or upgraded database,
run `alembic upgrade head` and verify `/api/v1/health/ready` reports required/current revision
`0055`. Legacy Role markers remain usable by the existing ABAC document but are not normalized audit
evidence until an Admin explicitly reassigns the Role. Manual/fallback edits cannot submit a
`datariver-role-*` marker; the dedicated assignment path matches it to the locked Role row and
rejects exact same Role/version/canonical-access no-ops even when only the optimistic expected version
changes. The Phase 3 editor and both generic/fallback backend paths now reject a Role-bound or
unverifiable marker state; remove the Role through that dedicated path before making a generic
access-document edit. Migration `0041`
also fails closed when a same-name CHECK/FK/index or forced-RLS policy has a non-canonical
definition; the executed evidence and the remaining Windows/WSL gate are recorded in the checklist.
The archive profile additionally requires both `RETENTION_ARCHIVE_EXECUTION_ENABLED=true` and the
mounted `runtime/retention-execution.enabled` file to contain exactly `ENABLED`. Bootstrap creates
that file as `DISABLED`; activate or disable it only with an atomic temporary-file replacement after
the WORM conformance, restore and accountable-owner gates are accepted.

The profile menu presents grouped, server-authorized administration entries. **Accounts & access**
contains Users, Systems, server-managed Role definitions/assignment and the applicable
security/exception workflows;
**Retention & erasure governance** contains policy, Legal Hold and erasure review. Provider
eligibility remains a nested policy approval because it is distinct from connection configuration.

The inventory always shows deployment-managed PostgreSQL/OIDC bootstrap requirements, separate
Redis cache/delivery and S3/DataHub core connectors, and optional feature connectors with their
required fields and secret flags. In development, an eligible administrator can open
**Profile → System settings** and select a badge for Redis, DataHub, Airflow, S3, the grouped
Chat/Embedding/Reranker LLM models, Neo4j, Prometheus or Grafana. Unconfigured entries start from a
server-owned sample YAML containing no credential values. Each SAVE creates a versioned YAML
revision in PostgreSQL. The browser may save addresses, model identifiers, non-sensitive options
and strict `file:/run/secrets/<name>` references; a literal `password`, `secret`, `token`, `api_key`
or `private_key` value is rejected. Actual values remain in ignored local secret files/Docker
secrets, and `.env` contains only deployment switches or reference paths. Use
`url`, `endpoint` or `base_url` for an HTTP(S)
endpoint; Redis uses `redis://` or `rediss://`. The bounded versions API exposes newest-first
hash/TEST/activation history without YAML or credentials. A saved Grafana URL is supplied by the
server to the Monitoring page and rendered in its
sandboxed iframe. Production keeps configuration in deployment/approved-provider controls and does
not expose this write API.

**SAVE** validates and versions the YAML. **TEST** runs one fixed server-side probe against that
exact saved revision and never accepts a request URL. **ACTIVATE** is available only for a current
AVAILABLE revision, an implemented runtime consumer and a recent hardware-WebAuthn administrator.
It selects the version for the next process startup; it never hot-reloads or restarts a client.
Redis cache requires API restart, Redis delivery requires relay/worker restart, and DataHub GMS and
S3 changes require API plus relevant worker restart. Local Ollama or the development
intranet OpenAI-compatible Chat/Embedding adapters together with Neo4j require an API restart;
the Reranker remains storable/testable inventory and has no runtime activation. Its TEST contract is
a private, fixed and bounded `POST /v1/rerank` inference request under
`INTRANET_RERANK_V1`; it is not OpenAI-compatible. A local Ollama `404` for that route is an honest
unavailable capability, not a reason to claim readiness or block unrelated authoring. The API can
report only the version it loaded itself and does not infer worker success.

Mac bootstrap deliberately leaves the startup resolver disabled. To opt into development-only
ACTIVATE, set both values in the selected ignored deployment env file before saving/activating a
revision:

```dotenv
SYSTEM_CONFIGURATION_RUNTIME_ACTIVATION_ENABLED=true
SYSTEM_CONFIGURATION_RUNTIME_WORKSPACE_ID=00000000-0000-4000-8000-000000000100
```

Compose consumers keep `SYSTEM_CONFIGURATION_SECRET_ROOT=/run/secrets`; `scripts/dev_host.sh`
maps the same canonical references to this checkout's ignored `secrets/` directory. Do not put
credential values in the env file. After ACTIVATE, recreate the API and relevant workers:

```bash
scripts/compose.sh --env-file .env \
  -f compose.yaml -f compose.identity.yaml -f compose.airflow.yaml \
  -f compose.gateway.yaml -f aux-compose.yml -f compose.graph.yaml \
  up -d --force-recreate api governance-apply-worker upload-worker upload-validation-worker
```

APISIX uses DNS discovery through Docker's embedded resolver, so replacing the API container does
not require restarting the gateway or leave it pinned to the old container address.

### 사내 OpenAI-compatible LLM (개발 전용)

상용·공용 LLM API는 계속 차단된다. 반면 사내에서 직접 운영하는 OpenAI-compatible model gateway는
development 환경에서만 `INTRANET_OPENAI_COMPATIBLE` connection mode로 연결할 수 있다. 이 mode는
`https://<private-host>/v1`만 허용하고, host는 deployment의
`INTRANET_OPENAI_COMPATIBLE_ALLOWED_HOSTS`에 정확히 등록되며 private non-loopback 주소로만
해결되어야 한다. URL에 credential·query·fragment를 넣거나 HTTP/TLS 우회를 사용하면 거부된다.

먼저 해당 source-host/Compose 환경에서 operator allowlist와 실제 API key를 별도 보안 채널로
준비한다. Chat과 Embedding key는 분리되어 있으며, bootstrap이 만든 random placeholder는 model API
key가 아니다.

```bash
# .env — operator-managed allowlist. 실제 사내 host는 Git에 넣지 않는다.
INTRANET_OPENAI_COMPATIBLE_ALLOWED_HOSTS=llm-gateway.corp.example

# secure transfer로 실제 key를 배치한다. browser나 YAML에는 key 원문을 넣지 않는다.
chmod 600 secrets/intranet_llm_chat_api_key secrets/intranet_llm_embedding_api_key
```

Admin → System settings → LLM Models에서 Chat Model과 Embedding을 각각 저장한다.
`gemma4` chat endpoint만으로는 GraphRAG pipeline을 완성할 수 없으므로, `/v1/embeddings`를 구현한
사내 embedding model(예: 승인된 BGE deployment)도 별도 설정한다.

```yaml
# Chat Model
connection_mode: INTRANET_OPENAI_COMPATIBLE
base_url: https://llm-gateway.corp.example/v1
model: gemma4:latest
secret_references:
  api_key: file:/run/secrets/intranet_llm_chat_api_key
options:
  api_style: openai_compatible
  context_tokens: 8192
  timeout_seconds: 60
```

```yaml
# Embedding
connection_mode: INTRANET_OPENAI_COMPATIBLE
base_url: https://llm-gateway.corp.example/v1
model: bge-m3:latest
secret_references:
  api_key: file:/run/secrets/intranet_llm_embedding_api_key
options:
  api_style: openai_compatible
  timeout_seconds: 60
```

Reranker가 필요한 배포만 별도 private endpoint를 설정한다. 이 revision은 SAVE/TEST까지만
지원하고 ACTIVATE는 의도적으로 제공하지 않는다.

```yaml
# Reranker — OpenAI-compatible API가 아님
connection_mode: INTRANET_RERANK_V1
base_url: https://reranker.corp.example/v1
model: bge-reranker-v2-m3
secret_references:
  api_key: file:/run/secrets/intranet_llm_reranker_api_key
options:
  api_style: rerank_v1
  timeout_seconds: 60
  top_n: 10
```

Chat/Embedding revision은 **SAVE → TEST → ACTIVATE** 순서로 처리한 뒤 API를 재시작한다.
source-host launcher는
portable `/run/secrets` reference를 ignored `secrets/` directory로만 매핑하며, Compose는 API
container에만 세 모델 key를 mount한다. 사내 endpoint는 fixed strict-JSON Chat probe와 one-vector
Embedding probe를 통과해야 한다. key를 보낸 뒤 `401`/`403`을 받으면 `UNAVAILABLE`이며 성공이 아니다.

위 ACTIVATE 절차는 Chat/Embedding에만 적용된다. Reranker TEST는 정렬된 유한 점수와 유효한
문서 index를 검증하지만 런타임 소비자 활성화를 만들지 않는다.

The exact state and security boundary are controlled by [ADR-0028](docs/adr/0028-development-system-configuration-startup-activation.md).

### Membership renewal and CR responsibility routing

Human Workspace memberships expire after six calendar months; service accounts remain
operator-managed. A user can request the next six-month term during the final 30 days. Every
eligible global Admin sees the same pending queue, but the requester cannot approve their own
extension and approval requires the existing recent WebAuthn assurance. Existing overdue users get
a 30-day migration transition window. Operate at least two eligible global Admin accounts before a
renewal window opens; browser time is never used as access authority.

Every new CR target now binds to a canonical System. REVIEW and TEST each require Developer
approval evidence for every target System before the next stage. FINAL requires Developer and Data
Steward approval for every target System plus one role-separated global Admin approval. A person
assigned the same responsibility to several Systems may cover those Systems, but one actor cannot
satisfy two FINAL role classes. See [ADR-0026](docs/adr/0026-expiring-human-membership-renewal.md)
and [ADR-0027](docs/adr/0027-change-request-system-role-authority.md).

#### CR workflow and FINAL security boundary

The canonical CR path is `REGISTERED -> IN_REVIEW -> TESTING -> FINAL_REVIEW`. A multi-target,
non-executable `CHANGE_INTAKE` completes after FINAL approval; a single governed DataHub aspect
moves through `APPLY_QUEUED -> APPLYING -> APPLIED|APPLY_FAILED`. A resubmission creates a new
current revision, so an approval or test result from an older revision can never satisfy the new
round. Every state command is version-fenced and idempotent. TEST evidence is a typed run bound to
private attachment bytes and their content hash; the platform does not accept browser-supplied raw
SQL as proof.

Both FINAL approval and FINAL rejection use the typed FINAL decision API. An ordinary transition
cannot bypass that boundary. FINAL approval requires all target Systems' Developer and Data
Steward lanes plus one global Admin lane, with a different actor for each responsibility class.
These sensitive writes additionally require a recent hardware-WebAuthn/LoA-2 session whose
`acr`, `amr` and `auth_time` satisfy the server policy. Password/direct-grant tokens and service
tokens fail closed with `401` or `403`; there is no password downgrade. Immutable policy-decision
evidence remains in `authz.policy_decisions`.

The workflow, negative cases and executed local evidence are recorded in
[the use-case catalogue](docs/usecases.md), [the test checklist](docs/test_checklist.md) and
[ADR-0027](docs/adr/0027-change-request-system-role-authority.md). A successful password-token
denial proves the security gate, not a successful human FINAL approval; production promotion still
requires a real browser and approved hardware authenticator journey.

The administrator navigation contains one **Audit/Log 조회** entry with Metadata Change Log and
System Security Log tabs. Their read/export controls remain unavailable until a workspace-scoped,
masked audit API exists; the UI does not manufacture log rows. Retention policy, Legal Hold and
erasure review are three stages in one lifecycle: default duration, exceptional hold precedence,
and independent deletion-intent review. Approval still does not execute deletion, and the workflow
is provider-neutral even though PostgreSQL stores its canonical policy/evidence.

WebAuthn enrollment is labelled without a USB assumption. It is the accepted recent-hardware gate
for high-risk direct mutations, not a removable cosmetic menu item. An intranet operator may set
`OIDC_HARDWARE_WEBAUTHN_ENABLED=false`; DataRiver then hides enrollment/step-up and refuses hardware
assurance, so protected mutations stay unavailable rather than falling back to an ordinary password.
Replacing that lost functionality still requires a reviewed assurance alternative that preserves
self-change denial and the two-human administrator invariant.

### Enterprise UI completion scope

The Change Management, Knowledge Management, My Profile and administrator surfaces are controlled
by [the enterprise UI PRD](docs/20_ENTERPRISE_UI_COMPLETION_PRD.md) and its
[completion checklist](docs/21_ENTERPRISE_UI_COMPLETION_CHECKLIST.md). The implementation uses the
current React application, TanStack tables, Tailwind CSS and React Flow; `datariver_v0` is a
read-only interaction reference and is never imported into the v1 runtime.

- Change requests use the existing typed intake, private attachment, approval and transition APIs.
  Their detail dialog has a four-stage Stepper and loads only authorized catalog lineage. Existing
  request-item edits and generated SQL result presentation remain disabled until version-fenced
  server contracts exist. System selection and Developer/Data Steward/global Admin approval lanes
  come from canonical server routing and immutable authority snapshots, never UI fixtures.
  Attachment POSTs return `202 STARTED`: a separate upload worker claims one intent through a
  bounded database function, verifies S3/MinIO HEAD metadata and the complete byte SHA-256, and
  records STORED before the current human can finalize it. The browser sends an exact upload UUID,
  so a network/408/5xx-lost POST or finalize response is recovered without matching by filename or
  content alone. Polling stops after 20 reads or 120 seconds, pauses while a tab is hidden and
  aborts on context cancellation. The detail screen can recheck at most ten current-round STORED
  intents selected by the server before its SQL limit, refresh successes and retain a partial
  failure warning. One selection is capped at 10 files, 10 MiB each and 32 MiB total.
- Knowledge Registry and releases use the canonical graph APIs. The visual ontology editor and its
  local `CREATE (alias:Label)`/relationship subset produce typed provenance-bearing changeset
  operations; arbitrary Cypher is rejected and no Cypher string is sent to the server. Integrity-
  verified PDF uploads can enter the governed typed extraction flow; model-selected evidence IDs
  resolve to server-owned page excerpts before a DRAFT changeset is created. DB-schema source
  extraction remains unavailable until its governed proposal/job contract exists.
- Knowledge Chat is a distinct route from general Chat and calls only release-pinned, bounded
  Neo4j evidence retrieval and the graph-specific OpenAI-compatible synthesis contract. An answer
  is accepted only when every cited ID belongs to the authorized evidence bundle and the exact
  model/configuration/prompt/tool versions are audited.
- Profile administrator entries are rendered only from the `/admin/me` operation context. Missing
  audit/security-log exports, IdP user creation, system CRUD and dictionary mutation are shown as
  unavailable instead of using browser mocks or direct provider writes.

This is a development UI, but the same authorization and canonical-ownership boundaries apply.
An empty graph canvas contains a labelled placeholder node so the layout never collapses; it is not
mock domain evidence.

## Local quick start with bundled Keycloak

Linux/macOS/WSL:

```bash
./scripts/bootstrap.sh --datahub-token-file /approved-secure-transfer/datahub_token
# Set DATAHUB_BASE_URL in .env to the existing DataHub REST base URL.
# With the host-development Compose profile, backend containers instead use
# DATAHUB_CONTAINER_BASE_URL (default: http://datahub-gms:8080) through the
# external DATAHUB_DOCKER_NETWORK (default: datahub_network).
scripts/compose.sh --env-file .env -f compose.yaml -f compose.identity.yaml config --quiet
scripts/compose.sh --env-file .env -f compose.yaml -f compose.identity.yaml \
  up -d --build --wait
scripts/compose.sh --env-file .env --profile tools \
  -f compose.yaml -f compose.identity.yaml \
  run --rm local-bootstrap
```

Bootstrap is safe to rerun: it preserves every existing infrastructure credential, migrates legacy
Valkey secret filenames to their Redis aliases when needed, updates a token only from an explicitly
supplied file path,
and regenerates derived Keycloak configuration. Credential rotation is a separate deliberate
operation followed by restart and dependency-specific verification.

PowerShell:

```powershell
./scripts/bootstrap.ps1 -DataHubTokenFile 'C:\approved-secure-transfer\datahub_token'
# Set DATAHUB_BASE_URL in .env.
./scripts/compose.ps1 -EnvFile .env -f compose.yaml -f compose.identity.yaml config --quiet
./scripts/compose.ps1 -EnvFile .env -f compose.yaml -f compose.identity.yaml `
  up -d --build --wait
./scripts/compose.ps1 -EnvFile .env --profile tools `
  -f compose.yaml -f compose.identity.yaml `
  run --rm local-bootstrap
```

The catalog renders the bounded, authorization-pruned lineage graph itself. Selecting a graph node
opens the authorized local catalog detail. The external DataHub Lineage iframe is intentionally not
invoked by the UI, so DataRiver never depends on a browser DataHub session or forwards a provider
credential. The export worker is an opt-in Compose profile with its own database and S3 credentials.

```powershell
./scripts/bootstrap.ps1 -DataHubTokenFile 'C:\approved-secure-transfer\datahub_token' `
  -DataHubEmbedOrigin 'http://127.0.0.1:9002' -EnableCatalogExportWorker
./scripts/compose.ps1 -EnvFile .env --profile catalog-export `
  -f compose.yaml -f compose.identity.yaml `
  up -d --build catalog-export-worker
```

Open `http://localhost:8080`, sign in as `datariver-admin`, and read the generated temporary password from `secrets/keycloak_demo_password`. The first sign-in requires a new password but does not request a mobile OTP. The local realm keeps ordinary login at LoA 1 and reserves its user-verifying cross-platform WebAuthn key for an explicitly requested LoA 2 step-up. High-risk operations remain fail-closed until the user enrolls a key, completes step-up, and the resulting token satisfies the configured ACR, AMR and `auth_time` contract. Bootstrap assigns this active default Workspace, so a verified user does not need to type it after login:

```text
00000000-0000-4000-8000-000000000100
```

After the first-login change, use **내 프로필 → 비밀번호 변경**. DataRiver starts the branded
authentication system's password-change action and returns to the same profile; the ordinary UI
does not expose the provider product name or administration URL. Editing
`secrets/keycloak_demo_password` does not change an existing account because that file is only the
bootstrap-time temporary credential source. DataRiver does not receive or store the replacement.

For the bundled local identity profile, **Admin → 계정/권한 → User → 신규 사용자 등록** creates
the authentication identity and current Workspace membership together. It requires recent WebAuthn
assurance, an optional existing 간편 Role, and a temporary password of at least 12 characters. The
authentication system forces the new user to replace that password at first login. The temporary
value is excluded from DataRiver DB, idempotency, outbox/audit payloads and responses. Deliver it
only through an approved secure channel. Enterprise/non-Keycloak OIDC leaves this control disabled
and continues to use the organization's identity onboarding process.

Workspace is not an Admin-only screen option: it is the tenant/security scope for every user,
membership, RLS, ABAC and cache entry. With `WORKSPACE_SELECTION_ENABLED=true`, the selector is a
validated URL convenience, not browser-stored authority, and every API request rechecks membership.
Set it to `false` for a single-Workspace UI; the selector disappears and DataRiver always uses the
server-verified default while preserving the same internal security boundary. A missing default
fails closed. OIDC user/profile/role state remains in React memory only: startup uses
the Keycloak SSO session for a silent authorization-code + PKCE round-trip, then hydrates the
verified profile from `GET /auth/me`. The local administrator is a `security-administrators` member
and can read its server-derived administrator menu without reauthentication. Password reauth or
hardware WebAuthn is requested only by the corresponding sensitive mutation; no operation is
automatically replayed after that redirect.

Use **WebAuthn 보안키 등록** in the signed-in profile area to enroll an authenticator allowed by the
organization IdP policy. The UI does not require one specific USB form factor. A denied
high-risk action shows **보안키로 인증** and returns to the same `?page=...` view after Keycloak
step-up. DataRiver never replays the approval or publish request automatically; review it and click
the operation again. The local identity profile has no mobile-OTP setup step.

The two presentation/security switches are deployment settings, meaning values loaded by the API
process from this machine's ignored `.env` (or a production orchestrator/secret policy), not fields
that a signed-in browser administrator can lower during the protected action:

```dotenv
# Single-Workspace presentation; Workspace ABAC/RLS remains active.
WORKSPACE_SELECTION_ENABLED=false
# Optional. Disables DataRiver WebAuthn use and leaves WebAuthn-gated writes denied.
OIDC_HARDWARE_WEBAUTHN_ENABLED=false
```

After changing either value, recreate the API process so it reloads configuration:

```bash
scripts/compose.sh --env-file .env -f compose.yaml up -d --force-recreate api
```

Silent access-token renewal keeps one API client and swaps only its request-time token. It no
longer recreates every feature client or causes a periodic screen-wide data reload; a failed
renewal still returns to explicit Sign In.

The `local-identity` bootstrap is rejected when `APP_ENV=production`. With an enterprise IdP, provision `(issuer, sub)` and a workspace membership through the controlled environment onboarding process; do not reuse local identities.

## Host-development quick start

Use this topology while API, workers and UI are changing frequently. PostgreSQL and optional
Keycloak/APISIX stay in DataRiver containers; Redis and S3/MinIO are independently operated.
Uvicorn, the long-running backend relay/workers and Vite run directly from the checked-out source.
The production-oriented base Compose remains private by default; `compose.host-dev.yaml` publishes
only the required development ports on loopback.

Every repository Compose/host-development combination is a **Single-node Pilot**, even if multiple
processes run on that host. HA requires independent nodes, off-host distributed storage and accepted
failover/restore evidence; replica settings alone are not an HA claim (ADR-0013).

The v1 repository still does not own DataHub. The example below reuses a DataHub GMS already exposed on host port `8080`; replace both URLs and the scoped token when the external service is elsewhere.

Browser-visible auxiliary links are optional and independent of backend provider endpoints. Configure only the links that the deployment wants to expose with `UI_DATAHUB_URL`, `UI_AIRFLOW_URL`, `UI_GRAFANA_URL`, `UI_PROMETHEUS_URL`, and `UI_GRAPH_URL`. The API validates and publishes them through the authenticated capabilities response; it does not invent localhost defaults or return credentials. Production accepts HTTPS links only. Grafana remains a new-window link unless the deployment separately supplies matching exact-origin `GRAFANA_EMBED_BASE_URL`, explicitly enables `GRAFANA_EMBED_ENABLED`, records `GRAFANA_EMBED_EVIDENCE_REFERENCE`, and passes the same origin into the web CSP; the browser cannot enable embedding or provide a frame URL.

For a native Windows checkout, bootstrap from PowerShell. First use supplies an approved token file
path with `-DataHubTokenFile`; later runs preserve the installed token when omitted. A token value
must never be placed in process arguments.
The script disables inherited ACLs on the ignored secrets and Keycloak-runtime directories and
grants full control only to the current Windows identity and `SYSTEM`; do not move generated files
to a location that replaces those ACLs.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/bootstrap.ps1 `
  -DataHubTokenFile 'C:\approved-secure-transfer\datahub_token' `
  -HostDevelopment -DataHubBaseUrl http://host.docker.internal:8080
```

For a checkout stored inside WSL, bootstrap and run Docker commands in that WSL distribution so Linux file permissions are preserved:

```bash
./scripts/bootstrap.sh --datahub-token-file /approved-secure-transfer/datahub_token \
  --host-development \
  --datahub-base-url http://host.docker.internal:8080
scripts/compose.sh --env-file .env \
  -f compose.yaml -f compose.identity.yaml -f compose.host-dev.yaml \
  config --quiet
scripts/compose.sh --env-file .env \
  -f compose.yaml -f compose.identity.yaml -f compose.host-dev.yaml \
  up -d --build --wait postgres keycloak
./scripts/configure_keycloak_host_dev.sh
scripts/compose.sh --env-file .env \
  -f compose.yaml -f compose.identity.yaml -f compose.host-dev.yaml \
  run --rm migrate
scripts/compose.sh --env-file .env --profile object-storage-tools \
  -f compose.yaml -f compose.identity.yaml -f compose.host-dev.yaml \
  run --rm storage-init
scripts/compose.sh --env-file .env --profile tools \
  -f compose.yaml -f compose.identity.yaml \
  -f compose.host-dev.yaml run --rm local-bootstrap
```

Run the changing source processes from Windows PowerShell so the supported Windows uv/Node toolchains are used:

```powershell
# Create this once with the supported native Windows uv/Python toolchain.
uv venv --python 3.12 .venv
$env:VIRTUAL_ENV = (Resolve-Path .venv).ProviderPath
uv sync --active --frozen --all-extras

powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/dev.ps1 `
  start -DataHubBaseUrl http://127.0.0.1:8080
```

When the same checkout is also tested from WSL, keep its interpreter separate so it cannot replace
the native Windows host runtime: `UV_PROJECT_ENVIRONMENT=.venv-wsl uv sync --frozen --all-extras`.

The launcher also supports this command when the checkout is reached through a WSL UNC path: it
maps only the Vite `npm.cmd` child to a temporary drive, because `cmd.exe` cannot use a UNC working
directory. Backend source processes keep their original checked-out path.

Start the gateway from WSL only after the Windows host API is live. The script discovers the current WSL-to-Windows gateway address:

```bash
./scripts/start_gateway_host_dev.sh
```

If the optional Airflow stack is running with host source processes, recreate its four long-running
services with the dedicated overlay after the gateway is ready. This keeps ordinary host-dev Compose
validation independent of Airflow while routing DAG calls through APISIX:

```bash
scripts/compose.sh --env-file .env \
  -f compose.yaml -f compose.identity.yaml -f compose.airflow.yaml \
  -f compose.host-dev.yaml -f compose.airflow.host-dev.yaml \
  up -d --force-recreate airflow-api-server airflow-scheduler \
  airflow-dag-processor airflow-triggerer
```

Open Vite at `http://localhost:38102`, API docs at `http://localhost:38101/api/docs`, Keycloak at `http://localhost:18081`, and APISIX at `http://localhost:9080`. Vite proxies `/api` through APISIX. Inspect or stop host processes with `./scripts/dev.ps1 status` and `./scripts/dev.ps1 stop`. Runtime PIDs and logs are written only below the ignored `runtime/host-dev/` directory.

The host process manager starts Uvicorn first and requires `/api/v1/health/ready` before starting
workers or Vite. It forces the Uvicorn file watcher to poll so a Windows host process reliably
reloads backend sources stored in the WSL filesystem before APISIX serves them. `/health/live` proves
only that the process is running; readiness also leases an API database connection and requires the packaged sole Alembic head. If readiness reports
`SCHEMA_REVISION_MISMATCH`, run the documented migration command before restarting host processes.

The DataRiver host-development port map is PostgreSQL `5432`, Uvicorn `38101`, APISIX `9080`,
Keycloak `18081` and Vite `38102`. External Redis and S3/MinIO ports belong to their deployments.
Do not run a bare `docker compose up` for this topology because that would also start the
containerized API, workers and web service.

Database connection ceilings are explicit settings. Budget the server for
`API replicas × (DATABASE_POOL_SIZE + DATABASE_POOL_MAX_OVERFLOW) + long-running workers ×
(WORKER_DATABASE_POOL_SIZE + WORKER_DATABASE_POOL_MAX_OVERFLOW) + migration/seed/IdP/Airflow/admin
reserve`. The current one-API/four-worker defaults can lease at most 60 DataRiver runtime
connections before that reserve; this is a ceiling calculation, not a recommended production
`max_connections` value.

The repository includes a fail-closed PgBouncer/RLS probe contract and source tests, but the
development or production database path does not deploy PgBouncer. A target transaction-mode
pooler must pass the live two-workspace connection-reuse probe before adoption.

Apply and verify the optional synthetic semiconductor reference data after migration and local identity bootstrap:

```bash
scripts/compose.sh --env-file .env --profile semiconductor-seed \
  -f compose.yaml -f compose.identity.yaml \
  -f compose.host-dev.yaml run --rm semiconductor-seed
scripts/compose.sh --env-file .env --profile semiconductor-seed \
  -f compose.yaml -f compose.identity.yaml \
  -f compose.host-dev.yaml run --rm semiconductor-seed \
  /app/.venv/bin/python -m datariver.seed verify
```

## Deployment profiles

```bash
# Core with external OIDC/DataHub
scripts/compose.sh --env-file .env up -d --build --wait

# Local identity
scripts/compose.sh --env-file .env -f compose.yaml -f compose.identity.yaml \
  up -d --build --wait

# Scheduled DataHub projection sync and probes (DAGs paused initially)
scripts/compose.sh --env-file .env -f compose.yaml -f compose.airflow.yaml \
  up -d --build --wait

# Local API gateway on http://localhost:9080
scripts/compose.sh --env-file .env -f compose.yaml -f compose.gateway.yaml \
  up -d --build --wait

# Optional local-only observability UI and OTLP backend on Grafana :3300,
# Prometheus :9090 and Alertmanager :9093. This is still Single-node Pilot.
scripts/compose.sh --env-file .env -f compose.yaml -f aux-compose.yml \
  --profile observability up -d --wait

# Archive-only Retention workers. Keep disabled until dedicated DB/S3 secrets, workspace allowlist,
# Object Lock negative conformance and restore evidence have been accepted.
scripts/compose.sh --env-file .env --profile retention-archive config --quiet
scripts/compose.sh --env-file .env --profile retention-archive up -d --build \
  retention-scheduler retention-archive-worker
# After acceptance only: atomically replace runtime/retention-execution.enabled with exact ENABLED.

# Entire local integration stack; all overlays compose together
scripts/compose.sh --env-file .env -f compose.yaml -f compose.identity.yaml \
  -f compose.airflow.yaml -f compose.gateway.yaml up -d --build --wait
```

### Optional durable Knowledge PDF analysis

The core platform does not require this capability. With
`KNOWLEDGE_SOURCE_WORKER_ENABLED=false`, catalog, governance and existing Knowledge reads remain
available, while a new PDF-analysis enqueue fails closed and no job is left permanently queued.
Neo4j is not a prerequisite: the worker needs one complete Chat + Embedding provider pair, its own
PostgreSQL login and a read-only object-store identity for the accepted-source bucket.

Bootstrap must first create the ignored environment and secret files. Configure and probe the
provider pair in that environment, then opt in on a second bootstrap pass:

```bash
# Mac arm64: first establish the Mac profile, then enable/probe the local Embedding contract.
./scripts/bootstrap.sh --env-file .env.mac-development --mac-development
# Edit .env.mac-development: set the reviewed LOCAL_OLLAMA_EMBEDDING_* values and
# LOCAL_OLLAMA_EMBEDDING_ENABLED=true, then rerun:
./scripts/bootstrap.sh --env-file .env.mac-development --mac-development \
  --enable-knowledge-source-worker

# Linux/WSL amd64: first create the preparation profile, then configure one private
# INTRANET_OPENAI_COMPATIBLE_CHAT_* + EMBEDDING_* pair and its mounted key files.
./scripts/bootstrap.sh --env-file .env.wsl-preparation --wsl-preparation \
  --datahub-token-file /approved-secure-transfer/datahub_token
./scripts/bootstrap.sh --env-file .env.wsl-preparation --wsl-preparation \
  --enable-knowledge-source-worker

# Native Windows PowerShell uses .env and does not provide the WSL preparation preset.
./scripts/bootstrap.ps1 -DataHubTokenFile 'C:\approved-secure-transfer\datahub_token'
# Configure/probe Chat + Embedding in .env, then:
./scripts/bootstrap.ps1 -EnableKnowledgeSourceWorker
```

The opt-in refuses an incomplete inference pair. It writes the dedicated
`datariver_knowledge` DSN/secret reference, the separate `s3_knowledge_*` files and
`KNOWLEDGE_SOURCE_WORKER_ENABLED=true`; it does not activate Neo4j or manufacture provider
acceptance. For an existing PostgreSQL volume, reconcile the new NOBYPASSRLS role before and after
Alembic. The role must also be an unprivileged LOGIN with no membership that permits `SET ROLE`;
revision `0054` removes prior direct schema/table/function privileges and reapplies only its exact
allowlist. With a custom environment file, the checked-in helper reads `DATARIVER_ENV_FILE`:

```bash
# Choose exactly one for this shell:
DATARIVER_ENV_FILE=.env.mac-development  # Mac
# DATARIVER_ENV_FILE=.env.wsl-preparation  # Linux/WSL
export DATARIVER_ENV_FILE
scripts/compose.sh --env-file "$DATARIVER_ENV_FILE" -f compose.yaml up -d --wait postgres
./scripts/reconcile-postgres-roles.sh
scripts/compose.sh --env-file "$DATARIVER_ENV_FILE" -f compose.yaml run --rm migrate
./scripts/reconcile-postgres-roles.sh
scripts/compose.sh --env-file "$DATARIVER_ENV_FILE" -f compose.yaml \
  --profile knowledge-source up -d --wait api knowledge-source-worker
scripts/compose.sh --env-file "$DATARIVER_ENV_FILE" -f compose.yaml run --rm migrate \
  /app/.venv/bin/alembic -c backend/alembic.ini current
# Required output: 0055 (head)
```

### WSL 준비 PC에서 Migration 이후

Migration이 `0055 (head)`에 도달해도 API/Worker를 바로 시작하지 않는다. 역할을 한 번 더
reconcile하고, 대상 issuer에 맞는 local identity를 bootstrap한 후 선택한 외부 connector를
초기화한다. 아래 `RELEASE_DIR`은 checksum과 source commit을 확인한 실제 절대 경로다.

```bash
RELEASE_DIR=/transfer/datariver-release/datariver-<12자리-commit>
OFFLINE_COMPOSE="$RELEASE_DIR/amd64/offline-core.compose.yaml"

# 현재 release의 helper가 password를 전달하지 못하는 경우에도 동작하는 명시적 role reconcile.
scripts/compose.sh --env-file .env.wsl-preparation -f compose.yaml \
  exec -T postgres sh -ec \
  'export PGPASSWORD="$(tr -d "\r\n" </run/secrets/postgres_password)"; exec sh /docker-entrypoint-initdb.d/010_roles.sh'

scripts/compose.sh --env-file .env.wsl-preparation \
  -f compose.yaml -f compose.identity.yaml -f "$OFFLINE_COMPOSE" \
  run --rm --pull never migrate \
  /app/.venv/bin/alembic -c backend/alembic.ini current

scripts/compose.sh --env-file .env.wsl-preparation --profile tools \
  -f compose.yaml -f compose.identity.yaml -f "$OFFLINE_COMPOSE" \
  run --rm --pull never local-bootstrap
```

외부 MinIO/S3를 선택했다면 실제 private endpoint와 별도 secret을 먼저 설정하고
`storage-init`을 한 번 실행한다. 외부 소유자가 bucket/IAM을 이미 관리하는 환경에서도
DataRiver가 사용하는 bucket 계약과 최소 권한 probe는 통과해야 한다. S3 기능을 아직
승인하지 않았다면 init을 억지로 통과시키지 말고 해당 기능을 비활성 상태로 둔다.
`S3_ENDPOINT_URL`과 `S3_PUBLIC_ENDPOINT_URL`에는 MinIO Console/UI 포트가 아니라 S3 API
origin을 넣는다. Kubernetes NodePort는 service의 `targetPort`가 MinIO API `9000`을 가리킬
때만 사용할 수 있다. 외부 MinIO가 per-bucket `PutBucketCors`를 지원하지 않으면 운영자가
exact-origin CORS를 별도로 구성하고 `S3_CORS_MANAGEMENT_MODE=external`을 선택한다.

```bash
scripts/compose.sh --env-file .env.wsl-preparation \
  --profile object-storage-tools \
  -f compose.yaml -f compose.identity.yaml -f "$OFFLINE_COMPOSE" \
  run --rm --pull never storage-init

scripts/compose.sh --env-file .env.wsl-preparation \
  -f compose.yaml -f compose.identity.yaml -f "$OFFLINE_COMPOSE" \
  up -d --wait --no-build --pull never keycloak

# Keycloak health는 외부 8081이 아니라 컨테이너 내부 management port 9000에 있다.
docker inspect --format '{{.State.Health.Status}}' datariver-next-keycloak-1
curl -fsS \
  http://127.0.0.1:8081/realms/datariver/.well-known/openid-configuration \
  >/dev/null

scripts/compose.sh --env-file .env.wsl-preparation \
  -f compose.yaml -f compose.identity.yaml -f "$OFFLINE_COMPOSE" \
  up -d --wait --no-build --pull never \
  api web outbox-relay upload-worker upload-validation-worker governance-apply-worker

curl -fsS http://127.0.0.1:8000/api/v1/health/live
curl -fsS http://127.0.0.1:8000/api/v1/health/ready
curl -fsS http://127.0.0.1:8080/healthz
```

Neo4j/Knowledge worker, APISIX, Airflow와 observability는 각각의 provider·image·secret gate가
통과한 경우에만 profile/overlay로 추가한다. 기본 Catalog/Search/CR 운영을 위해 이들을
강제로 시작하지 않는다.

When the selected Mac or WSL profile intentionally uses the optional local MinIO reference, it uses
the configurable `S3_BUCKET_ACCEPTED`. Create the buckets with the general storage initializer,
then create/attach the generated worker identity and its exact `GetBucketLocation` +
accepted-bucket `GetObject` policy. Skip these commands for external S3/MinIO:

```bash
scripts/compose.sh --env-file "$DATARIVER_ENV_FILE" \
  -f compose.local-connectors.yaml --profile object-storage up -d --wait minio
scripts/compose.sh --env-file "$DATARIVER_ENV_FILE" \
  -f compose.yaml --profile object-storage-tools run --rm storage-init
scripts/compose.sh --env-file "$DATARIVER_ENV_FILE" \
  -f compose.local-connectors.yaml --profile object-storage \
  run --rm minio-knowledge-identity-init
```

For external S3/MinIO, its owner must create the accepted bucket and a non-admin principal with the
same narrow read contract, place that principal's keys in the two `S3_KNOWLEDGE_*_FILE` mounts, and
prove allowed reads plus anonymous, write, delete and other-bucket denials. This target proof is an
`EXTERNAL_GATE`; the local initializer is not production IAM evidence.

The worker streams and verifies at most 50 MiB/500 pages, retains only
`KNOWLEDGE_SOURCE_MEMORY_SPOOL_BYTES` in RAM and spills the remainder into the worker-only
`knowledge-spool` volume. Keep the directory absolute, non-root, writable only by the worker and
budget at least one maximum source per concurrent worker plus temporary/provider overhead. Do not
mount it into the API/web or use it as evidence storage.

Each parsed page and provider batch is capped at 40,000 characters. A larger single page fails
before either inference provider is called. The worker rechecks the pinned model configuration,
source manifest, graph/base/ontology and current requester authorization before source read, again
before inference, at every bounded provider checkpoint and in the final locked transaction.

Owner job history is ordered with non-terminal work first and uses an owner/workspace/graph/order
bound opaque cursor. The browser renders one page of at most 100 jobs, and the transactional enqueue
path permits at most 20 non-terminal jobs for one owner/graph. This keeps every active job
discoverable without accumulating unbounded history in browser memory. After the 120-poll visible
window, the same job can be explicitly resumed without a page reload.

Disable new work by setting `KNOWLEDGE_SOURCE_WORKER_ENABLED=false`, recreating the API, and stopping
`knowledge-source-worker`. Existing durable rows are retained. Authorized cancellation uses the
version-fenced API/UI; never edit state/lease columns. On restart the worker supersedes expired
attempts and recovers or terminally cancels them under the stored retry limit. Alembic `0054`
refuses downgrade once any durable Knowledge job evidence exists; preserve the database and use a
forward fix instead of deleting the ledger.

Overlays may be combined. Keep PostgreSQL and worker databases private, and permit Redis, S3 and
DataHub only through the explicit connector network and target firewall policy. See
[deployment operations](docs/08_DEPLOYMENT.md) before using a non-local environment.

If another local stack owns a default port, host bindings can be overridden for headless integration verification, for example:

```bash
WEB_PORT=18080 KEYCLOAK_PORT=18081 APISIX_PORT=19080 \
  scripts/compose.sh --env-file .env -f compose.yaml -f compose.identity.yaml \
  -f compose.airflow.yaml -f compose.gateway.yaml up -d --build --wait
```

An OIDC issuer is an identity, not merely a port mapping. For browser sign-in on alternate ports, also change `APP_PUBLIC_ORIGIN`, `OIDC_PUBLIC_ORIGIN`, `OIDC_PUBLIC_AUTHORITY` and `OIDC_ISSUER` consistently in `.env`, then rebuild web/API/Keycloak. Never accept tokens from two issuer strings for convenience.

## 운영 환경 업데이트 가이드

이 절차는 승인된 릴리스 커밋을 운영 PC의 기존 배포에 반영하기 위한 순서이다. 저장소의
기본 Compose는 **Single-node Pilot** 토폴로지이며 HA 운영 배포본이 아니다. 실제 운영은
[배포 운영 문서](docs/08_DEPLOYMENT.md)의 외부 OIDC, 별도 운영 DataHub, 백업·복구,
TLS, 이미지 digest 고정 및 승격 게이트를 먼저 충족해야 한다. `compose.identity.yaml`,
`compose.graph.yaml`, 관측성 Pilot 및 합성 시드는 로컬 전용이므로 운영 명령에 추가하지
않는다. 조직이 검토한 운영 overlay가 있다면 아래 모든 Compose 명령에 동일한 `-f` 목록을
일관되게 적용한다.

### 1. 변경 전 확인 및 코드 갱신

DB와 오브젝트 스토리지의 복구 지점을 생성하고 복구 가능성을 확인한 후 작업한다. `.env`,
`secrets/`, 런타임 볼륨은 배포 환경 소유이며 Git에서 복사하거나 덮어쓰지 않는다. 다음
`git status --short` 출력이 비어 있지 않으면 중단하고 운영 PC의 로컬 변경부터 보존한다.

```bash
cd /path/to/datariver_v1
git status --short
git fetch --prune origin
git switch main
git pull --ff-only origin main
git rev-parse --verify HEAD
```

승인된 릴리스 SHA와 마지막 출력이 같은지 확인한다. 운영 설정은 최소한
`APP_ENV=production`, HTTPS 외부 URL과 정확한 CORS origin,
`DATAHUB_VERSION_ENFORCEMENT=enforce`, 운영용 secret 파일 참조를 사용해야 한다.
고위험 CR/관리자 작업에는 `OIDC_HARDWARE_WEBAUTHN_ENABLED=true`를 유지하고, 별도의
Maker-Checker 승격을 완료하지 않았다면 `ADMIN_PASSWORD_FALLBACK_ENABLED=false`로 둔다.
브라우저의 시스템 설정을 런타임에 바로 반영하는
`SYSTEM_CONFIGURATION_RUNTIME_ACTIVATION_ENABLED`도 운영에서는 활성화하지 않는다.

```bash
docker compose -f compose.yaml config --quiet
```

### 2. 이미지 준비와 DB 마이그레이션

정식 운영 배포는 CI에서 검증한 digest 고정 이미지를 받아야 한다. 현재 저장소를 직접
빌드하는 Single-node 운영 PC라면 다음 명령으로 동일 소스의 이미지를 먼저 준비한다.

```bash
docker compose -f compose.yaml build --pull
```

애플리케이션을 올리기 전에 권한이 분리된 `migrate` 서비스로 Alembic을 실행한다. 이
릴리스의 필수 revision은 `0055`이다. 호스트의 임의 DB 계정으로 `alembic`을 직접 실행하지
않는다.

```bash
scripts/compose.sh --env-file .env -f compose.yaml run --rm migrate
scripts/compose.sh --env-file .env -f compose.yaml run --rm migrate \
  /app/.venv/bin/alembic -c backend/alembic.ini current
```

두 번째 명령의 현재 revision이 `0055 (head)`인지 확인한다. 마이그레이션 실패 시 서비스를
재기동하거나 downgrade를 추측 실행하지 말고, 로그와 DB 상태를 보존한 채 배포를 중단한다.

### 3. API·Worker·Web 재기동과 상태 확인

마이그레이션이 성공한 뒤 기본 서비스를 재생성한다. Compose의 의존성도 `migrate` 성공을
요구하므로 이미 최신인 DB에서는 이 단계가 안전하게 재확인된다.

```bash
scripts/compose.sh --env-file .env -f compose.yaml up -d --wait
scripts/compose.sh --env-file .env -f compose.yaml ps
scripts/compose.sh --env-file .env -f compose.yaml logs --since=10m \
  api outbox-relay upload-worker upload-validation-worker governance-apply-worker
```

운영 URL로 liveness와 readiness를 각각 확인한다. 아래 호스트명은 실제 TLS origin으로
바꾼다. liveness `200`만으로는 배포 성공이 아니며 readiness도 `200`이어야 한다.

```bash
curl --fail --silent --show-error \
  https://datariver.example.internal/api/v1/health/live
curl --fail --silent --show-error \
  https://datariver.example.internal/api/v1/health/ready
```

### 4. FIDO2/Keycloak 보증 계약 확인

대상 IdP가 운영자가 관리하는 Keycloak일 때만, 승인된 bootstrap 관리자 secret을 파일로
마운트한 관리 단말에서 다음 migration을 실행한다. 다른 IdP는 동일한 `acr`/`amr`/
`auth_time` 보증을 제공하는 공급자별 절차가 필요하다.

```bash
uv run python scripts/configure_keycloak_assurance.py \
  --base-url https://identity.example.internal \
  --admin-username '<bootstrap-admin>' \
  --admin-password-file /run/secrets/keycloak_admin_password \
  --username '<managed-security-admin>' \
  --configure-step-up \
  --revoke-user-sessions \
  --apply
```

같은 명령에서 `--apply`만 제거해 read-only drift 검사를 다시 수행한다. 그 후 서로 다른
실사용 Developer, Data Steward, 전역 Admin으로 시스템 담당자를 확인하고, 브라우저에서
승인된 하드웨어 인증기를 사용한 FINAL step-up을 검증한다. 일반 password/direct-grant 및
service token의 FINAL 호출은 `401` 또는 `403`으로 차단되어야 한다. 로컬 전용
`scripts/e2e/run_cr_workflow.py`는 운영에서 실행하지 않는다.

### 5. 실패 시 처리

무조건적인 `alembic downgrade`나 볼륨 삭제는 금지한다. readiness 또는 핵심 워크플로우가
실패하면 신규 트래픽 승격을 중단하고 위 로그, 릴리스 SHA, migration revision을 보존한다.
이전 이미지로 되돌릴 수 있는지는 새 스키마와의 호환성을 먼저 확인해야 하며, 호환되지
않으면 승인된 복구 절차로 DB·오브젝트 저장소의 일관된 복구 지점을 사용한다.

## Main functional flows

- Catalog: an authorized local projection serves cursor-bound ALL-term search, facets, autocomplete and a lazy `platform -> database -> schema -> asset` Resource Tree before selected details are enriched through a fixed DataHub adapter. Global and catalog autocomplete use the same Schema/Table/Column/Tag/Term/Description semantics and return bounded plain-text match evidence; Workspace switching remounts the global search boundary so prior-tenant queries and late responses cannot remain visible. The rebuildable projection and HTTP response both have explicit description/tag/term/column bounds; `description_truncated`, `tags_truncated` and `terms_truncated` are rendered so a clipped summary is never presented as complete. Search avoids a full exact-count scan: `total_exact=false` marks a lower bound and cursor presence controls navigation. Facets apply the same search fields through one server-ranked PostgreSQL grouping-set query. The result table shows source-backed Terms and Tags beside the asset identity, exposes a horizontal scroll region, and offers per-column ascending/descending sorting and text filtering over the currently loaded page. Page sizes are 25/50/100; one page action makes one bounded asset request and the browser never walks every cursor page. Facets refresh only when the query/filter/authorization scope changes. Collapsing a tree branch evicts its descendants, and one expanded branch retains at most 200 nodes. Database/schema hierarchy comes only from typed DataHub browse containers; the platform never invents it by splitting URNs. Tag/Term entry suggestions come only from the authorization-pruned workspace projection; global provider vocabulary is not merged because DataHub's provider search has no workspace/classification predicate. Authorized detail keeps `Table Details` and a fixed-height, authorization-pruned local `Lineage` graph. The graph fits its detail-panel viewport, wraps each stage after three nodes without omitting nodes, and supports pan, node positioning and zoom. Selecting a tree or lineage node opens its authorized detail directly instead of rescanning search pages; the external DataHub Lineage iframe is not invoked by this UI. DataHub column `label` is shown as read-only Logical Name separately from editable Description. A `sync_id`-bound full reconciliation is sequential and single-writer, stores its opaque provider cursor only on the server, proves stable total/distinct coverage, and tombstones missing DataHub-owned assets only with accepted point-in-time evidence; otherwise it completes with deletion suppressed. Governed CSV/XLSX export is a server-managed, owner-scoped job bound to the exact query/filter, permission/classification-policy snapshot and projection watermark; toolbar buttons never synthesize a browser-side file. Export excludes RESTRICTED assets unconditionally, neutralizes spreadsheet formula injection, reauthorizes every download, and issues only a 60-second URL after object metadata reconciliation.
- Registration: browser multipart upload goes directly to quarantine storage. Table/column Tag and
  Term values remain on a one-line scrollable badge control with thin previous/next buttons; the
  compact `+` opens its vocabulary/new-proposal input directly below that control. Workers complete
  the object, stream SHA-256/size/format checks with bounded memory, copy to a
  validation-attempt-scoped accepted key, fully re-read the promoted bytes and delete quarantine
  only after the version-fenced database acceptance commits. Manual editing keeps at most one
  100-column provider page plus sparse edits in the browser. SAVE reauthorizes the current asset,
  checks both projection and provider versions, rehydrates the complete non-truncated schema
  server-side, creates one immutable `UPLOAD_METADATA_MANUAL_YYMMDD_SERIAL.csv` receipt and queues
  a database-time/lease-fenced execution. The worker applies exactly five typed DataHub aspects and
  marks APPLIED only after full read-back hash equality; owner/Admin history exposes append-only
  attempt and per-aspect success/failure evidence. Typed BULK CSV/XLSX is limited to 16 MiB and
  10,000 rows, parses ZIP/XML off the API event loop and replays candidates from a bounded
  attempt-local spool, publishes candidates only after complete source/root reconciliation, and
  permits one ETag-fenced server-authored Change Request per dataset-description candidate.
  Airflow retries reuse a stable run ID/call ordinal and DataRiver replays a committed response
  without a second effect. A read-only bounded DB/S3 reconciler classifies missing, mismatched and
  unreferenced Manual receipt evidence but never deletes either side. The browser never receives
  MinIO, Airflow or DataHub credentials, automatic status polling stops after a bounded window or
  while hidden, and raw provider mutation forms remain unavailable.
- Change management: typed DataHub aspect UPSERT requests are server-bound to an authorized local dataset identity and scope, then move through legal transitions and distinct final approval. In new-CR intake, each Tag/Term `+` uses only the bounded authorization-pruned workspace projection; provider-wide `*` vocabulary is excluded because it cannot carry the same Workspace/classification predicate. Keyword input narrows that projection before a comma-aware new proposal is offered. Column input reserves the table Schema track, so column item/Type/Description/Term/Tag/requested-change/management align with Table/Owner/description/Terms/Tags/requested-change/column-addition above it. Reads use the current authorized target; approval and forward transitions reject identity, revision or authorization-scope drift. REVIEW and TEST require every routed System's Developer evidence, while FINAL requires every routed System's Developer and Data Steward plus one role-separated global Admin. Every FINAL decision also requires recent hardware-WebAuthn assurance. Generic raw Aspect creation and the legacy upload-derived raw proposal API additionally require the deny-by-default, hardware-human-only `change.raw.create` action and are not exposed in the ordinary UI. A leased worker applies each aspect idempotently and only marks `APPLIED` after re-read hash equality. Apply-time requester/policy reauthorization, DataRiver target serialization and external provider CAS remain explicit production gates.
- Classification access administration: eligible human security administrators can review and independently approve versioned four-class Search/Chat policies, review or revoke immutable inference-provider profile versions, and govern policy-bound RESTRICTED Search grants. ADR-0020 additionally permits an audited, read-only same-workspace catalog review of non-deleted quarantined DataHub projections for classification remediation, including the fixed typed DataHub metadata detail; it never enables export, Chat, arbitrary provider access or mutation. The Admin UI never accepts provider endpoints or credentials, and RESTRICTED evidence is never eligible for Chat.
- Knowledge graph: create a graph/ontology, author typed node/edge changesets, validate, independently review, publish or roll back immutable releases, export governed views and call bounded analysis. Raw SQL/Cypher is never accepted.
- API sharing: create a governed-release-pinned contract version, publish it with recent strong authentication, bind an active non-expiring service Subject plus issuer/OIDC `client_id` to explicit scopes/classification/validity and quotas, revoke it, and invoke fixed Snapshot/Neighbors/local-Chat surfaces. Ledger, canonical result and monthly quota commit atomically; exact retries replay the stored no-store response without executing or charging twice. List/detail, replay, publish, grant and invocation revalidate current authority and independently reviewed lineage; client-only legacy grants are non-invokable until explicitly upgraded.
- Chat: deterministic baseline answers only from catalog or active-release knowledge evidence that passed prefiltering and per-item authorization. Immutable chunks bind workspace, classification, typed scope, source/version/effective time and content hash; only validated cited chunk IDs are persisted, otherwise the answer is `검증 불가`. Persistence additionally requires the workspace's independently approved ACTIVE retention policy: each new session binds its exact policy ID/hash and database-time deadline, and a superseded, expired or legacy-unbound session is append-closed. There is no duration fallback. The default inference-worker contract rejects SQL, Cypher, arbitrary HTTP, tools and mutation fields. Development Knowledge processing may use either the fixed loopback Ollama adapter in [ADR-0023](docs/adr/0023-mac-development-local-inference-and-graph-projection.md) or the private-network OpenAI-compatible adapter in [ADR-0030](docs/adr/0030-development-intranet-openai-compatible-adapter.md); both retain a fixed non-executable response contract and server-side validation. Commercial/public external inference remains disabled until live revalidation, delivery/streaming, metrics and scaled red-team gates are accepted.
- Monitoring: liveness, readiness, dependency capabilities, workspace counts, outbox dead letters and ABAC-protected Prometheus HTTP metrics remain independent so one degraded optional dependency does not hide core state. Database-pool metrics expose only bounded connection states and configured limits, never workspace, subject or query labels.

The upload store is an external S3-compatible deployment and is not an accepted WORM boundary. A
MinIO target is supported through the provider-neutral port but its selected distribution, license,
provenance and S3 behavior remain deployment gates. The separate immutable-archive port is promoted
only against a maintained target that passes Object Lock negative conformance and restore gates; see
ADR-0012 and ADR-0033.

The bundled Airflow password file and `SimpleAuthManager` are strictly loopback local-development conveniences. Before any non-local Airflow exposure, use the deployment's supported enterprise/FAB SSO integration; the included DAG service account already uses short-lived Keycloak client credentials for DataRiver API calls.

OpenAPI is available at `http://localhost:38101/api/docs` in source-host development, at the deployment-selected API port in other non-production topologies, or through the web proxy at `/api/docs` when enabled. The container API continues to listen on its internal port `8000`.

## Optional semiconductor seed

The seed is deterministic synthetic reference data and never installs by default. It contains 12 catalog assets and a 257-node/279-edge semiconductor value-chain release, including 168 monthly facility-capacity and product-demand observations with assertion-level provenance. Apply records separate maker/checker and authorized-publisher evidence, 536 immutable changeset operations, a canonical PostgreSQL read-back receipt and the published lineage before setting the active release. Verify rechecks the active release, role permissions, the exact operation ledger and a canonical row reconstruction hash; seed data is not a governance bypass.

```bash
scripts/compose.sh --env-file .env --profile semiconductor-seed run --rm semiconductor-seed
scripts/compose.sh --env-file .env --profile semiconductor-seed run --rm semiconductor-seed \
  /app/.venv/bin/python -m datariver.seed verify
scripts/compose.sh --env-file .env --profile semiconductor-seed run --rm semiconductor-seed \
  /app/.venv/bin/python -m datariver.seed remove --confirm-synthetic-data
```

Apply/remove require explicit confirmation. Production mode rejects any non-`none` seed profile.

### Large external value-chain seed and DataHub lineage

For catalog-scale and lineage testing, use the separate, restartable external seed workflow in
[the semiconductor seed workflow](docs/17_SEMICONDUCTOR_SEED_WORKFLOW.md). It is deliberately
separate from the small in-application reference seed above: it writes only the dedicated
`semiconductor_seed` PostgreSQL schema, never DataRiver business tables.

The local command creates 500 PostgreSQL tables, 500 PostgreSQL views, 20 deterministic rows per
table by default, a labelled Oracle **MOCK** DDL artifact, and 2,000 DataHub dataset entities when
the `dual` scope is selected. The schema is reset only after explicit confirmation and refuses to
remove unexpected objects.

On the validated Mac Compose topology, trigger the same bounded workflow through Airflow after the
core stack is healthy. It is manual-only and has no schedule. `docker compose exec` does not invoke
the service entrypoint automatically, so retain the wrapper below: it loads the Airflow database
and API secrets from their mounted files without exposing them in the command or shell history.

```bash
scripts/compose.sh --env-file .env \
  -f compose.yaml -f compose.identity.yaml -f compose.airflow.yaml \
  -f compose.gateway.yaml -f aux-compose.yml -f compose.graph.yaml \
  exec airflow-api-server /bin/bash /opt/datariver/airflow-entrypoint.sh \
  dags unpause datariver_semiconductor_seed_ingestion
scripts/compose.sh --env-file .env \
  -f compose.yaml -f compose.identity.yaml -f compose.airflow.yaml \
  -f compose.gateway.yaml -f aux-compose.yml -f compose.graph.yaml \
  exec airflow-api-server /bin/bash /opt/datariver/airflow-entrypoint.sh \
  dags trigger datariver_semiconductor_seed_ingestion
# After the run is SUCCESS, return the manual-only DAG to its default pause state.
scripts/compose.sh --env-file .env \
  -f compose.yaml -f compose.identity.yaml -f compose.airflow.yaml \
  -f compose.gateway.yaml -f aux-compose.yml -f compose.graph.yaml \
  exec airflow-api-server /bin/bash /opt/datariver/airflow-entrypoint.sh \
  dags pause datariver_semiconductor_seed_ingestion
```

```powershell
# Run from the repository root after the host-development dependencies are healthy.
.\.venv\Scripts\python.exe .\scripts\generate_semiconductor_seed.py `
  --apply --confirm-reset --ingest-datahub --entity-scope dual
```

`--ingest-datahub`는 controlled semiconductor Glossary·Tag를 먼저 UPSERT하고 테이블 및
실제 PostgreSQL 컬럼의 Term/Tag를 함께 적용한 뒤 read-back 검증합니다. 물리 데이터 생성
없이 vocabulary만 먼저 초기화·검증하려면 다음을 실행합니다.

```powershell
.\.venv\Scripts\python.exe .\scripts\generate_semiconductor_seed.py --seed-governance
```

The command reads the local PostgreSQL owner password and DataHub token only from ignored secret
files, writes its evidence only below ignored `runtime/semiconductor-seed/`, and verifies the exact
generated DataHub entity count through the typed aspect-read endpoint. It also provisions a
controlled semiconductor glossary/tag hierarchy and applies family, scenario, provenance, stage,
execution, and platform metadata to every generated dataset plus field semantics to PostgreSQL,
view and clearly labelled Oracle MOCK fields. It never prints a secret. The vocabulary-only initialization and read-only verification
commands are in [the semiconductor governance taxonomy](docs/18_SEMICONDUCTOR_GOVERNANCE_TAXONOMY.md).
Use the paused-on-creation `datariver_semiconductor_seed_ingestion` Airflow DAG for repeatable
manual runs; see the workflow document for its bounded resource settings and trigger procedure.
`infra/datahub/recipes/semiconductor_postgres.yml` is the separate native DataHub CLI recipe for a
real PostgreSQL source inspection. Do not use its Oracle companion as an Oracle source recipe: it
is intentionally a MOCK metadata manifest.

## Source verification

```bash
uv sync --frozen --all-extras
uv run ruff format --check backend/src backend/tests infra/airflow/dags scripts/reconcile_manual_receipts.py scripts/verify_nginx_headers.py
uv run ruff check backend/src backend/tests infra/airflow/dags scripts/configure_keycloak_assurance.py scripts/generate_initial_migration.py scripts/generate_semiconductor_seed.py scripts/migrate_s3_objects.py scripts/probe_pgbouncer_rls.py scripts/probe_policy_revocation.py scripts/probe_s3_contract.py scripts/reconcile_manual_receipts.py scripts/verify_datahub_contract.py scripts/verify_datahub_image_inventory.py scripts/verify_nginx_headers.py scripts/verify_static.py
uv run mypy backend/src backend/tests scripts/migrate_s3_objects.py scripts/probe_s3_contract.py scripts/reconcile_manual_receipts.py scripts/verify_nginx_headers.py
uv run pytest backend/tests -q
uv run python scripts/verify_static.py

cd frontend
npm ci
npm run typecheck
npm run lint
npm run test -- --run
npm run build
```

The web security-header behavior gate requires Docker and an already-built native image. It never
pulls during verification, rejects a daemon/image architecture mismatch and removes only the exact
temporary containers/network it creates:

```bash
docker build --pull=false -f frontend/Dockerfile -t datariver-next-web:header-gate .
uv run python scripts/verify_nginx_headers.py --web-image datariver-next-web:header-gate
```

It verifies the pinned Nginx parser with empty and populated origins, then checks the five canonical
security fields exactly once across SPA/runtime/assets/API success and `304/404/503/502-or-504`.
The API fixture also proves exact ETag/Vary and other application-header preservation, while every
direct-inner response must omit HSTS. Run it natively on both Mac arm64 and preparation-PC WSL
amd64; the Mac result is not WSL evidence. Approved HSTS presence remains a real TLS-edge
acceptance check.

For the atomic Sharing invocation contract, run the destructive-but-isolated PostgreSQL acceptance
harness explicitly. It refuses to reuse an existing container, creates random mode-`0600` temporary
credentials, proves canonical and additive migration paths plus downgrade refusal and fail-closed
tamper probes, exercises the Phase 6C timeout/Subject/context/fault/replay/interleaving matrix, then
removes its container and credentials:

```bash
DATARIVER_SHARING_VERIFY_CONFIRM=1 ./scripts/verify_atomic_sharing_postgres.sh
```

Before production promotion, verify the external DataHub runtime independently of application
startup:

```bash
uv run python scripts/verify_datahub_contract.py --base-url https://datahub.example.internal
# `runtime/` is ignored: render this JSON from the independently operated DataHub deployment.
uv run python scripts/verify_datahub_image_inventory.py runtime/datahub-rendered.compose.json
```

An existing Keycloak realm is not updated by startup import. Apply and re-read the assurance
contract with a file-mounted admin credential. The migration removes a stale mobile-TOTP user
action, adds the AMR mapper, creates and validates the password/LoA-1 plus WebAuthn/LoA-2 flow, and
binds it only after structural verification:

```bash
uv run python scripts/configure_keycloak_assurance.py \
  --base-url https://identity.example.internal \
  --admin-username '<bootstrap-admin>' \
  --admin-password-file /run/secrets/keycloak_admin_password \
  --username '<managed-security-admin>' \
  --configure-step-up \
  --revoke-user-sessions \
  --apply
```

Rerun the same command without `--apply` to perform a read-only drift check. WebAuthn enrollment is
explicit (`webauthn-register:skip_if_exists`) rather than a realm-wide first-login action. The
portable profile accepts user-verifying cross-platform authenticators; production-approved
attestation roots and AAGUID allowlists remain deployment inputs and promotion gates.

The administrator API uses recent hardware WebAuthn for direct membership-access changes. A typed
password-reauthentication Maker-Checker path exists only for the exact
`WORKSPACE_MEMBERSHIP_ACCESS_UPDATE_V1` command and is disabled by default. Do not enable
`ADMIN_PASSWORD_FALLBACK_ENABLED` until two real eligible human security administrators have been
provisioned and the target IdP/browser `max_age=0` reauthentication plus one-time consume journey
has passed. The local bootstrap does not create a fake second administrator; with the default local
bootstrap the fallback therefore remains unavailable.

For a non-production integration check, add `--probe-browser-flow` and a valid
`--probe-redirect-uri`. The probe creates a random temporary user, proves that LoA 1 issues an
authorization code and access token with `acr=1`, `amr=pwd` and `auth_time`, while LoA 2 stops at
WebAuthn, and removes the user in a `finally` cleanup. It never prints the generated password and
does not attempt to emulate a real security key.

With the local semiconductor seed, Keycloak and host API running, measure same-token policy
revocation against the direct API (100 iterations each for inactive membership, explicit action deny
and system/domain scope removal):

```powershell
uv run python scripts/probe_policy_revocation.py
# Only if a prior process was forcibly interrupted and left its ignored recovery snapshot:
uv run python scripts/probe_policy_revocation.py --recover
```

The probe restores and verifies the original Airflow service membership on every normal/error exit.
It writes only aggregate timings to `runtime/policy-probe/last-result.json`; bearer tokens and raw
membership attributes are never written to the result.

CI repeats these checks, audits dependencies, scans source/IaC and release-equivalent backend/frontend images, emits CycloneDX SBOMs, verifies the generated Alembic migration, compiles Airflow DAGs and validates each Compose overlay. The local Compose/OIDC/RLS/gateway/recovery evidence and the remaining production gates are recorded in [the acceptance report](docs/12_ACCEPTANCE_REPORT.md).

## Security invariants

- Application ABAC and PostgreSQL RLS remain mandatory even behind APISIX.
- Search/list/count, Chat evidence, export and analysis use the same workspace/classification boundary.
- Requester final self-approval is forbidden; high-risk operations require recent strong authentication.
- Administrator self-access changes are forbidden. Password fallback is typed, five-minute,
  Maker-Checker, one-time and default-disabled; it never converts password/OTP into hardware assurance.
- API, relay, upload, governance, bootstrap and migration database identities are separate; each worker receives only its own table grants and mounted secrets.
- DataHub writes cannot bypass governance, and an external acknowledgement alone never means applied.
- Redis loss affects latency/delivery only; PostgreSQL outbox and leased job state recover correctness.
- Secrets are mounted as files. Production rejects HTTP external endpoints, wildcard CORS and seed activation.
- Web Nginx and APISIX re-resolve replaceable API containers; a rolling API replacement must not require restarting the UI.

Start with the [artifact index](docs/README.md), [PRD](docs/01_PRD.md), [architecture](docs/03_ARCHITECTURE.md), [ABAC model](docs/07_SECURITY_ABAC.md) and [API specification](docs/05_API_SPEC.md).

## License

DataRiver project code is distributed under the [Apache License 2.0](LICENSE). Dependencies and container images remain under their own licenses and must pass the inventory/review gate in [constraints](docs/02_CONSTRAINTS.md).
