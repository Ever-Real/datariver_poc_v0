# DataRiver 06111 Hybrid POC

## 화면과 인증 경계

POC는 별도 축약 화면을 만들지 않습니다. 원본 `App`과 기존 Dashboard, 검색, 등록관리,
변경관리, 품질관리, 지식관리, 모니터링, 거버넌스, Chat 컴포넌트를 그대로 렌더링합니다.
메뉴, 화면 배치, 탭, 필터, 상세 패널과 UI interaction은 원본과 같습니다.

제거되는 것은 Keycloak/OIDC 로그인, token 갱신, 로그아웃, WebAuthn, step-up 및 비밀번호
재인증 UI/동작입니다. 원본 상단 메뉴 오른쪽의 작은 `[poc]` 배지가 이 무인증 실행 경계를
표시합니다.

이 구성은 사내망의 다른 PC에 공개하는 POC입니다. 인터넷 공개용 구성이 아닙니다.

## 실제 provider와 sample-memory의 역할

브라우저는 provider URL이나 credential을 받지 않고 같은 origin의 `/poc-api`만 호출합니다.
POC Web 프로세스가 고정된 allowlist route로 provider를 호출합니다. 임의 URL, GraphQL,
Cypher, DAG ID 또는 S3 bucket을 browser가 전달할 수 없습니다.

| 화면 기능 | provider | 동작 |
|---|---|---|
| Catalog 검색·상세·lineage | DataHub GMS | 설정 시 live 조회, 미설정 시 빈 상태 |
| Bulk/Knowledge 파일 전송 | MinIO | POC Web proxy를 통해 quarantine/accepted bucket에 저장 |
| Quality Run 실행 요청 | Airflow | 고정 `datariver_quality_dispatch` DAG만 trigger |
| Chat | DataHub + Embedding + Reranker + Chat | DataHub 근거를 고정 pipeline으로 전달 |
| Knowledge graph snapshot | 함께 실행되는 Neo4j | live 조회만 수행하며 sample graph를 seed하지 않음 |
| 변경관리 POC 상태 | browser memory | 사용자가 만든 CR 흐름만 보관하며 새로고침하면 초기화 |
| 거버넌스·품질 control-plane 상태 | 별도 정본 서비스 필요 | fixture 대신 빈 상태 또는 unavailable 표시 |

별도 PostgreSQL/Valkey/DataRiver API가 없으므로 변경관리 승인, 거버넌스 정본, 품질 결과
보존은 실제 운영 처리로 주장하지 않습니다. Airflow DAG가 기존 DataRiver API를 요구한다면
그 downstream 단계는 별도 시스템의 설정에 따라 실패할 수 있습니다.

## 최소 `.env`

`deploy/poc/.env.example`을 `deploy/poc/.env`로 복사하고 연결할 provider만 채웁니다.
`.env`는 Git에 포함하지 말고 prep/운영 PC에서 파일 권한을 제한합니다. 값은 Web container의
서버 측 환경에만 전달되고 Vite bundle이나 runtime JavaScript에는 포함되지 않습니다.

- DataHub: `DATAHUB_GMS_URL`, `DATAHUB_GMS_TOKEN`; 사용자용 링크가 필요할 때만
  `DATAHUB_UI_URL`
- Airflow: `AIRFLOW_URL`, `AIRFLOW_USERNAME`, `AIRFLOW_PASSWORD`
- MinIO: `MINIO_URL`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY` 및 기존 다섯 `S3_BUCKET_*`
  이름. region은 기본 `us-east-1`이며 비표준 설정에서만 `MINIO_REGION`을 추가합니다.
- LLM: Chat/Embedding/Reranker별 `URL`, `MODEL`, `TOKEN`
- Neo4j: `NEO4J_USERNAME`, `NEO4J_PASSWORD`; image/port는 기본값이 있어 보통 변경 불필요

DataHub·Airflow·MinIO·LLM 컨테이너가 별도 Compose project에서 실행 중이면 그 project도
`POC_SHARED_NETWORK`와 같은 external network에 연결하고 `.env` URL에 container DNS 이름을
사용합니다. 다른 host에 있다면 사내 IP/DNS URL을 사용합니다.

## Prep에서 npm으로 실행

Node.js 22.19 이상이 준비된 host에서:

```bash
cp deploy/poc/.env.example deploy/poc/.env
# deploy/poc/.env 편집
cd frontend
npm ci
npm run poc
```

`npm run poc`는 POC build 후 정적 화면과 gateway를 한 프로세스로 실행합니다. 기본 URL은
`http://<prep-ip>:39080/`입니다. 동등한 helper는 `./scripts/run_poc.sh npm`입니다. npm 단독
모드는 Neo4j 컨테이너를 시작하지 않으므로 Neo4j live graph는 비활성화됩니다. 외부 provider
연결을 포함한 Web+Neo4j 전체 묶음은 아래 Compose 명령을 사용합니다.

## Docker로 실행

repository root에서:

```bash
cp deploy/poc/.env.example deploy/poc/.env
# deploy/poc/.env 편집
docker compose --env-file deploy/poc/.env -f deploy/poc/docker-compose.poc.yaml up -d --build
```

또는 `./scripts/run_poc.sh docker`를 사용할 수 있습니다. 기본 Docker target은
`linux/amd64`이고 Web/gateway와 Neo4j만 함께 실행합니다. DataHub·Airflow·MinIO·LLM은
이 Compose가 생성하거나 변경하지 않습니다.

```bash
./scripts/run_poc.sh status
./scripts/run_poc.sh logs
./scripts/run_poc.sh stop
```

`stop`은 컨테이너와 network만 중지하며 Neo4j named volume은 삭제하지 않습니다.

### Git pull만 가능한 Prep PC의 프록시 Dockerfile

Git이 추적하는 표준 빌드 파일은 `deploy/poc/Dockerfile.example`입니다. Prep PC 전용 프록시
설정은 이 파일을 직접 수정하지 말고, Git에서 제외되는 `Dockerfile.local`에 둡니다.

이미 기존의 추적 대상 `deploy/poc/Dockerfile`을 수정해 `git pull`이 중단되는 Prep PC에서는
다음 절차를 최초 한 번만 실행합니다. 백업은 pull 대상 저장소 밖에 생성합니다.

```bash
cd /path/to/datariver_poc_v0
git status --short
cp deploy/poc/Dockerfile ../datariver-poc-prep-Dockerfile.backup
git restore --source=HEAD -- deploy/poc/Dockerfile
git pull --ff-only origin dev

cp ../datariver-poc-prep-Dockerfile.backup deploy/poc/Dockerfile.local
# deploy/poc/.env에서 다음 값 지정
# POC_DOCKERFILE=deploy/poc/Dockerfile.local

git status --short
docker compose --env-file deploy/poc/.env \
  -f deploy/poc/docker-compose.poc.yaml config --quiet
docker compose --env-file deploy/poc/.env \
  -f deploy/poc/docker-compose.poc.yaml up -d --build
```

`Dockerfile.local`과 `deploy/poc/.env`는 Git에 포함되지 않으므로 이후 `git pull --ff-only
origin dev`가 두 파일을 덮어쓰지 않습니다. 표준 `Dockerfile.example`이 변경된 커밋을 받은
경우에는 다음 명령으로 차이를 확인하고, 최신 example을 다시 복사한 뒤 필요한 프록시 설정만
재적용합니다.

```bash
diff -u deploy/poc/Dockerfile.example deploy/poc/Dockerfile.local || true
```

프록시가 필요하지 않은 host는 `.env`의 기본값
`POC_DOCKERFILE=deploy/poc/Dockerfile.example`을 그대로 사용합니다.

## 주장하지 않는 것

- 실제 사용자 인증, Workspace ABAC/RLS 또는 다중 사용자 격리
- PostgreSQL canonical state, durable audit, migration, backup 또는 rollback 증거
- 외부 provider의 운영 SLA·권한 적정성·데이터 정합성
- Airflow DAG downstream DataRiver API 성공
- production TLS, 인터넷 공개, availability, performance, recovery 또는 security acceptance
