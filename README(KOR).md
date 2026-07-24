# DataRiver Next

DataRiver Next는 외부 DataHub를 중심으로 카탈로그 검색, 등록, 변경관리, 지식 그래프,
모니터링을 제공하는 거버넌스 플랫폼입니다. 이 문서는 새 환경을 초기화하고 서비스 연결,
DB 마이그레이션, 선택적 시드 및 정상 상태를 확인하는 표준 순서입니다.

영문 상세 문서는 [README.md](README.md), 설계·보안·운영 규격은 [docs/README.md](docs/README.md)를
참조하세요.

## 구성과 책임 경계

| 구성요소 | 역할 | 정본(원본) 책임 |
|---|---|---|
| PostgreSQL | CR, 승인, 감사, ABAC, 작업, 지식 릴리스 | DataRiver 업무 상태 |
| DataHub | 적용된 카탈로그 메타데이터와 계보 | 외부 카탈로그 메타데이터 |
| S3 호환 스토리지 | 업로드 객체 | 객체 바이트 |
| 외부 Redis | 캐시와 이벤트 전달 | 정본이 아닌 단기 상태 |
| 외부 OIDC/선택적 Keycloak 프로필 | 사용자 인증 | 사용자 자격 증명 |
| APISIX | API Gateway | 라우팅과 프록시 |

DataRiver는 DataHub, Redis, MinIO/S3, 그래프 엔진, Airflow와 LLM을 생성·업그레이드·삭제하지
않습니다. 이들은 별도로 운영하고 접속 정보만 DataRiver에 연결하는 실패 가능한 외부
의존성이므로 업무 정본으로 사용하지 않습니다.

부팅에 필요한 인프라 능력은 PostgreSQL과 OIDC입니다. 기본 Compose가 소유하는 상태 저장
서비스는 PostgreSQL뿐이며, 로컬 OIDC가 필요할 때만 `compose.identity.yaml`의 Keycloak
프로필을 선택합니다. Redis 캐시/전달, S3/MinIO, DataHub, Airflow, Neo4j, LLM과 관측 도구는
기능별 외부 커넥터입니다. API readiness는 PostgreSQL과 migration만 검사하므로 선택 기능의
장애가 전체 플랫폼의 부팅 성공으로 오인되거나 반대로 전체 부팅을 막지 않습니다.

## 사전 준비

- Git, Docker Engine/Desktop와 Compose v2
- Python 3.12, `uv`, Node.js 22, npm 10 (소스 실행/검증 시)
- 접근 가능한 OIDC, 두 개의 분리된 Redis URL, S3 호환 스토리지와 필요한 기능의 외부 서비스
- DataHub 기능을 사용할 경우 DataHub URL과 범위가 제한된 서비스 토큰
- 코어 스택 약 8 GiB, Airflow 포함 시 약 12 GiB 이상의 여유 메모리

실제 `.env`, `secrets/`, `runtime/`, Docker volume, 업로드 데이터는 Git에 포함하지 않습니다.

## 초기화 순서

1. 먼저 [아키텍처](docs/03_ARCHITECTURE.md), [배포](docs/08_DEPLOYMENT.md),
   [보안](docs/07_SECURITY_ABAC.md)을 읽고 위 책임 경계를 확인합니다.
2. bootstrap 스크립트로 `.env`와 로컬 비밀 파일을 생성합니다. 다른 환경의 `.env`, volume,
   secret 파일을 복사하지 않습니다.
3. 사용할 Compose overlay의 정합성을 검사합니다.
4. 인프라를 기동하고 migration 서비스로 DB를 현재 Alembic 헤드까지 올립니다.
5. API/worker/UI를 시작한 뒤 health, gateway, OIDC, DataHub capability를 확인합니다.
6. 필요할 때만 합성 반도체 시드를 적용하고 검증합니다.

Linux/macOS/WSL 예시:

```bash
./scripts/bootstrap.sh --datahub-token-file /approved-secure-transfer/datahub_token
# .env의 OIDC, REDIS_*, S3_* 및 사용할 외부 서비스 URL을 환경에 맞게 확인합니다.
scripts/compose.sh --env-file .env -f compose.yaml -f compose.identity.yaml config --quiet
scripts/compose.sh --env-file .env -f compose.yaml -f compose.identity.yaml \
  up -d --build --wait
scripts/compose.sh --env-file .env --profile tools \
  -f compose.yaml -f compose.identity.yaml \
  run --rm local-bootstrap
```

PowerShell 예시:

```powershell
./scripts/bootstrap.ps1 -DataHubTokenFile 'C:\approved-secure-transfer\datahub_token'
./scripts/compose.ps1 -EnvFile .env -f compose.yaml -f compose.identity.yaml config --quiet
./scripts/compose.ps1 -EnvFile .env -f compose.yaml -f compose.identity.yaml `
  up -d --build --wait
./scripts/compose.ps1 -EnvFile .env --profile tools `
  -f compose.yaml -f compose.identity.yaml `
  run --rm local-bootstrap
```

## 소스 기반 개발 실행

호스트 개발 모드는 PostgreSQL과 선택적 Keycloak/APISIX만 DataRiver Compose에서 실행하고,
Redis와 S3/MinIO는 별도 환경에서 운영합니다. API·relay·worker·Vite는 체크아웃 소스에서
실행합니다.

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
scripts/compose.sh --env-file .env \
  -f compose.yaml -f compose.identity.yaml -f compose.host-dev.yaml \
  run --rm migrate
./scripts/configure_keycloak_host_dev.sh
```

Windows PowerShell에서 소스 프로세스를 시작하는 예시입니다.

```powershell
uv venv --python 3.12 .venv
$env:VIRTUAL_ENV = (Resolve-Path .venv).ProviderPath
uv sync --active --frozen --all-extras
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/dev.ps1 `
  start -DataHubBaseUrl http://127.0.0.1:8080
```

상태와 종료:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/dev.ps1 status
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/dev.ps1 stop
```

이 host-development 경로가 게시하는 기본값은 PostgreSQL `5432`, API `38101`,
APISIX `9080`, Keycloak `18081`, Vite `38102`입니다. 외부 Redis와 S3/MinIO 포트는 해당
배포가 결정합니다.

## 연결 정보와 환경 변수

`scripts/bootstrap.*`가 `.env`의 기본 구조와 무시되는 secret 파일을 준비합니다. 환경에 맞게
다음 값을 점검하세요.

- `DATAHUB_BASE_URL`, `DATAHUB_EXPECTED_VERSION`, DataHub 서비스 토큰 파일
- `APP_PUBLIC_ORIGIN`, `APP_CORS_ORIGINS`, `OIDC_*`
- `DATABASE_*`, `REDIS_CACHE_*`, `REDIS_DELIVERY_*`, `S3_*`와 파일 기반 secret reference
- 선택적 UI 링크: `UI_DATAHUB_URL`, `UI_AIRFLOW_URL`, `UI_GRAFANA_URL`,
  `UI_PROMETHEUS_URL`, `UI_GRAPH_URL`

개발 환경에서는 외부 DataHub `v1.6.0rc1` capability를 정상으로 허용합니다. 운영 환경은
`DATAHUB_EXPECTED_VERSION` 및 명시적 allowlist 계약을 계속 강제합니다.

## 관리자 시스템 설정

관리자 인벤토리는 PostgreSQL/OIDC를 `BOOTSTRAP_REQUIRED`, Redis cache/delivery와 S3/DataHub를
`CORE_CONNECTOR`, 나머지를 `FEATURE_CONNECTOR`로 구분하고 필요한 필드와 비밀 여부를
제공합니다. 개발 환경의 적격 관리자는 **프로필 → 시스템 설정**에서 Redis, DataHub,
Airflow, S3, LLM, Neo4j, Prometheus, Grafana의 연결 정보를 버전 관리할 수 있습니다.

- YAML은 PostgreSQL에 워크스페이스·버전 단위로 증분 저장됩니다.
- `password`, `secret`, `token`, `api_key`, `private_key` 이름의 값은 조회 시
  `********`로 마스킹됩니다. 다른 항목만 수정할 때는 이 값을 유지하세요.
- Redis는 `redis://` 또는 `rediss://`, 다른 연결은 허용된 HTTP(S) URL을 사용합니다.
- PostgreSQL과 OIDC는 프로세스가 DB 설정을 읽기 전에 필요한 부팅 의존성이므로 시스템
  설정에서 교체하지 않고 배포 설정으로 관리합니다.
- SAVE → TEST → ACTIVATE 쓰기 흐름은 현재 개발 환경에만 열려 있습니다. 운영 반영은
  승인된 secret backend, 재시작/롤백 절차와 감사 게이트가 마련될 때까지 배포 관리입니다.
- Grafana URL을 저장하면 모니터링 메뉴가 서버 응답을 통해 sandboxed iframe으로 표시합니다.
- 운영 환경에서는 이 DB 쓰기 API가 노출되지 않으며 배포 설정과 승인된 provider profile을
  사용합니다.

사용자 목록은 OIDC 토큰에서 확인한 이메일, 부서/권한/역할, 소유 테이블 수, CR 이력 수와 최근
접속 정보를 표시합니다. 사용자 생성과 비밀번호는 DataRiver가 아닌 조직 OIDC/IdP에서 관리합니다.

Policy Book 작업은 1) RBAC DB/백엔드, 2) 수명관리 실행기, 3) Admin UI의 승인 게이트로
분리됩니다. 현재 1단계는 Role 버전별 No/Partial/Full 규칙과 정규화된 할당 증적을 추가하지만
2단계 실행기나 3단계 UI를 활성화하지 않습니다. `datariver-role-*` 마커는 전용 Role 할당
경로만 변경할 수 있고, 낙관적 잠금의 예상 버전만 달라진 같은 Role/버전/정규 접근문서의
재할당도 거부됩니다. 3단계 승인 전에는 Role이 할당된 사용자의 일반 접근문서 편집이 안전하게
거부되므로 전용 경로에서 Role을 먼저
해제해야 합니다. 상세 범위와 준비PC의 미검증 항목은
[실행 체크리스트](docs/28_POLICY_BOOK_EXECUTION_CHECKLIST.md)를 따릅니다.

## DB migration 및 시드

Compose의 `migrate` 서비스가 표준 경로입니다. 소스 실행 환경에서 명시적으로 수행하려면
migration 소유 자격 증명으로 실행합니다.

```bash
uv run alembic -c backend/alembic.ini upgrade head
```

선택적 합성 반도체 시드:

```bash
scripts/compose.sh --env-file .env --profile semiconductor-seed \
  -f compose.yaml -f compose.identity.yaml \
  -f compose.host-dev.yaml run --rm semiconductor-seed
scripts/compose.sh --env-file .env --profile semiconductor-seed \
  -f compose.yaml -f compose.identity.yaml \
  -f compose.host-dev.yaml run --rm semiconductor-seed \
  /app/.venv/bin/python -m datariver.seed verify
```

시드 적용·삭제는 합성 데이터에만 사용하며 운영 데이터에는 적용하지 않습니다.

## 정상 상태 확인

```bash
curl -fsS http://127.0.0.1:38101/api/v1/health/live
curl -fsS http://127.0.0.1:38101/api/v1/health/ready
curl -fsS http://127.0.0.1:8080/
```

- `/health/live`는 프로세스 실행 여부만 확인합니다.
- `/health/ready`는 DB 연결과 현재 Alembic 헤드 `0054`를 확인합니다.
- 브라우저에서는 `http://localhost:38102`(호스트 개발) 또는 container profile의
  `http://localhost:8080`을 열고,
  로그인 후 workspace를 선택합니다.
- Catalog에서 Tag/Term `+`를 열어 DataHub vocabulary가 표시되는지, 변경관리에서 일반 OIDC
  계정으로 CR 생성·검토 상태 흐름이 진행되는지 확인합니다.
- 모니터링에서 capability와 저장된 Grafana URL이 표시되는지 확인합니다.

## 검증 명령

```bash
uv run ruff format --check backend/src backend/tests infra/airflow/dags
uv run ruff check backend/src backend/tests infra/airflow/dags scripts
uv run mypy --strict backend/src
uv run pytest backend/tests -q
uv run python scripts/generate_initial_migration.py
uv run python scripts/verify_static.py
```

```powershell
Set-Location frontend
npm run test
npm run build
```

검증 결과는 현재 소스 상태의 증거이며, 운영 배포·복구·부하·외부 DataHub 계약 검증을 대신하지
않습니다.
