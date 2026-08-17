# DataRiver 06111 Hybrid POC

## 화면과 인증 경계

POC는 별도 축약 화면을 만들지 않습니다. 원본 `App`과 기존 Dashboard, 검색, 등록관리,
변경관리, 품질관리, 지식관리, 모니터링, 거버넌스, Chat 컴포넌트를 그대로 렌더링합니다.
메뉴, 화면 배치, 탭, 필터, 상세 패널과 UI interaction은 원본과 같습니다.

Keycloak/OIDC, WebAuthn, step-up 및 외부 Workspace 인증은 현재 Node POC의 startup dependency가
아닙니다. 대신 POC는 local human credential, opaque server-side session과 HttpOnly cookie를 사용하고,
매 요청의 `subject_id`를 기존 User/System access document에 다시 결합합니다. `[poc]` 배지는 이
축약된 local-auth 제품 경계를 표시하며 무인증 실행을 의미하지 않습니다.

기본 DEV 구성은 Web과 선택적 Airflow UI를 `127.0.0.1`에만 공개합니다. 다른 사내 PC에서
접근시킬 때는 `POC_BIND_HOST` 또는 `AIRFLOW_BIND_HOST`를 검토된 사내 interface로 명시적으로
바꿔야 합니다. 이 opt-in은 네트워크 도달성만 넓히고 현재 loopback HTTP origin 계약을 충족하지
않으므로, 별도의 HTTPS ingress/origin/security acceptance 없이 사용하면 안 됩니다. 인터넷 공개용
구성이 아닙니다.

## 실제 provider와 POC 상태 저장소의 역할

브라우저는 provider URL이나 credential을 받지 않고 같은 origin의 `/poc-api`만 호출합니다.
POC Web 프로세스가 고정된 allowlist route로 provider를 호출합니다. 임의 URL, GraphQL,
Cypher, DAG ID 또는 S3 bucket을 browser가 전달할 수 없습니다.

| 화면 기능 | provider | 동작 |
|---|---|---|
| Catalog 검색·상세·lineage | DataHub GMS | 설정 시 live 조회, 미설정 시 빈 상태 |
| Bulk/Knowledge 파일 전송 | MinIO | POC Web proxy를 통해 고정 bucket/prefix에 저장 |
| Bulk 등록 준비 | Airflow | 검토된 `datariver_bulk_registration_prepare` DAG만 trigger |
| Chat | DataHub + Neo4j + Embedding + Reranker + Chat | live 근거를 고정 pipeline으로 전달 |
| Knowledge graph snapshot | 함께 실행되는 Neo4j | live 조회만 수행하며 sample graph를 seed하지 않음 |
| 사용자·System·변경관리 POC 상태 | POC PostgreSQL | 사용자가 만든 항목만 versioned JSONB로 보관 |
| DataHub 변경 이력 | Kafka MCL + Schema Registry → POC PostgreSQL | bounded normalized ledger/checkpoint와 CR link history를 append-oriented 보관 |
| 거버넌스 문서·Knowledge Studio 상태 | POC PostgreSQL | 사용자가 만든 Draft·검토·발행 기록만 보관; seed 없음 |
| DataHub 반복 inventory/detail | PostgreSQL current projection + POC Redis | Redis는 optional hot cache이며 장애 시 PostgreSQL last-good projection으로 fallback |
| 품질 control-plane 상태 | 별도 정본 서비스 필요 | fixture 대신 live DataHub 현황과 unavailable 축을 구분 |

Compose의 pgvector PostgreSQL은 POC 범위의 access/core/current state와 append-oriented Change History
원장을 durable volume에 저장합니다. 이는 운영 DataRiver schema, HA 또는 production archive 주장이
아닙니다. Redis는 정확성 정본이 아니고 반복 DataHub 로딩 속도만 개선합니다.
Airflow DAG가 기존 DataRiver API를 요구한다면 downstream 단계는 별도 시스템 설정에 따라
실패할 수 있습니다.

## 최소 `.env`

`deploy/poc/.env.example`을 `deploy/poc/.env`로 복사하고 연결할 provider만 채웁니다.
`.env`는 Git에 포함하지 말고 prep/운영 PC에서 파일 권한을 제한합니다. 값은 Web container의
서버 측 환경에만 전달되고 Vite bundle이나 runtime JavaScript에는 포함되지 않습니다.
현재 Node POC Change Management Compose는 Change History credential용 secret-file/Docker secret reader를
직접 지원하지 않습니다. Root platform 문서의 다른 service용 `secrets/` 계약을 이 POC의
지원으로 해석하지 않습니다. 현재는 ignored `.env`/deployment environment가 credential까지
소유하며, non-secret `.env` + secret injection/files 분리는 backlog입니다.

- DataHub: `DATAHUB_GMS_URL`, `DATAHUB_GMS_TOKEN`; 사용자용 링크가 필요할 때만
  `DATAHUB_UI_URL`
- Airflow: `AIRFLOW_URL`, `AIRFLOW_USERNAME`, `AIRFLOW_PASSWORD`. URL에는 `/api/v1` 또는
  `/api/v2`를 붙이지 않고 Webserver origin(예: `http://17.x.x.x:8888`)만 입력합니다. POC는
  Airflow 3 API v2에서는 `/auth/token` JWT를 발급받고, Airflow 2.x에서는 Basic auth 기반
  v1 API로 fallback합니다.
- MinIO: `MINIO_URL`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY` 및 기존 다섯 `S3_BUCKET_*`
  이름. region은 기본 `us-east-1`이며 비표준 설정에서만 `MINIO_REGION`을 추가합니다.
- LLM: Chat/Embedding/Reranker별 `URL`, `MODEL`, `TOKEN`. URL은 `/v1`까지의 base 또는
  `/v1/chat/completions`, `/v1/embeddings`, `/v1/rerank` 같은 단계별 전체 endpoint를 모두
  지원합니다.
- Neo4j: `NEO4J_USERNAME`, `NEO4J_PASSWORD`; image/port는 기본값이 있어 보통 변경 불필요
- POC 지원 컨테이너: `POC_POSTGRES_PASSWORD`를 반드시 변경합니다. 폐쇄망에서는 로컬에
  적재된 tag를 `POC_PGVECTOR_IMAGE`, `POC_REDIS_IMAGE`, `NEO4J_IMAGE`에 정확히 지정합니다.
- Change History/MCL: source, checkpoint, Registry hash와 scheduler의 전체 계약은
  [MCL 운영 Runbook](MCL_CHANGE_HISTORY_RUNBOOK.md)을 사용합니다. Scheduler는 direct capture가
  성공할 때까지 disabled 상태로 유지합니다.

Bulk XLSX/CSV는 `S3_BUCKET_FILEFOLDER`의
`bulk-registration/<upload-id>/catalog-metadata-source.xlsx` 또는 `.csv`에만 저장됩니다.
브라우저가 bucket이나 object key를 정할 수 없고, 저장 완료 후 같은 Object를 다시 읽어
SHA-256을 검증한 경우에만 후보를 생성하고 Airflow DAG를 시작합니다.

Grafana iframe은 다음 네 값을 함께 설정합니다. `UI_GRAFANA_URL`은 실제 dashboard 전체
링크이고 `GRAFANA_EMBED_BASE_URL`은 같은 dashboard의 scheme/host/port까지만 입력합니다.

```dotenv
UI_GRAFANA_URL=http://grafana.internal:3000/d/datariver/platform
GRAFANA_EMBED_BASE_URL=http://grafana.internal:3000
GRAFANA_EMBED_ENABLED=true
GRAFANA_EMBED_EVIDENCE_REFERENCE=prep-grafana-reviewed-v1
MONITORING_DASHBOARDS_JSON=[{"id":"platform","label":"Platform","url":"http://grafana.internal:3000/d/platform/main","height_px":900},{"id":"airflow","label":"Airflow","url":"http://grafana.internal:3000/d/airflow/main","height_px":900}]
```

`MONITORING_DASHBOARDS_JSON`은 최대 8개 탭을 받습니다. iframe으로 표시할 모든 URL은
`GRAFANA_EMBED_BASE_URL`과 exact origin이 같아야 하며 Grafana의 `allow_embedding` 및
사내 인증 정책도 별도로 준비해야 합니다. 조건이 맞지 않는 URL은 링크 탭으로만 표시합니다.

같은 host의 DataHub network를 재사용할 때는
`docker-compose.datahub-provider.yaml` overlay와 `DATAHUB_EXTERNAL_NETWORK`를 사용합니다. 다른
host의 DataHub·Airflow·MinIO·LLM은 사내 routable IP/DNS URL을 사용합니다. 반복적인 수동
`docker network connect`를 canonical 절차로 사용하지 않습니다.

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
`http://127.0.0.1:39080/`이며 `POC_PUBLIC_ORIGIN`도 이 exact origin과 일치해야 합니다.
현재 local-auth DEV 계약은 loopback HTTP만 허용합니다. 비-loopback 접근은 이 값을 임의로
완화하지 않고 별도 HTTPS ingress/origin acceptance에서 다룹니다. 동등한 helper는
`./scripts/run_poc.sh npm`입니다. npm 단독
모드는 Redis·pgvector·Neo4j 컨테이너를 시작하지 않습니다. 단, `.env`의
`POC_POSTGRES_*`, `POC_REDIS_URL`, `NEO4J_HTTP_URL`이 이미 실행 중인 지원 서비스의 host
주소를 가리키면 npm 실행도 PostgreSQL 상태 저장, Redis cache, Neo4j graph를 그대로
사용합니다. 이 값들이 없을 때만 상태가 Node 프로세스 수명으로 제한됩니다. 지원 컨테이너를
포함한 전체 묶음은 아래 Compose 명령을 사용합니다.

## Docker로 실행

repository root에서:

```bash
cp deploy/poc/.env.example deploy/poc/.env
# deploy/poc/.env 편집
docker compose --env-file deploy/poc/.env -f deploy/poc/docker-compose.poc.yaml up -d --build
```

또는 `./scripts/run_poc.sh docker`를 사용할 수 있습니다. 기본 Docker target은
`linux/amd64`이고 Web/gateway, Redis, pgvector PostgreSQL, Neo4j를 함께 실행합니다.
DataHub·Airflow·MinIO·LLM은 이 Compose가 생성하거나 변경하지 않습니다. PostgreSQL,
Redis, Neo4j 진단 port와 Web publish는 기본적으로 `127.0.0.1`에만 bind됩니다. Web container의
Node listener만 peer-container 통신을 위해 container 내부 `0.0.0.0:8080`을 유지합니다.

```bash
./scripts/run_poc.sh status
./scripts/run_poc.sh logs
./scripts/run_poc.sh stop
```

`stop`은 컨테이너와 network만 중지하며 Neo4j·pgvector named volume은 삭제하지 않습니다.

#### Web-only 재빌드 (애플리케이션 코드 변경 시)

Postgres·Neo4j·Redis·Airflow를 재시작하지 않고 `web` 컨테이너만 다시 빌드하고 교체합니다.

```bash
./scripts/run_poc.sh web-restart
```

이 작업은 지원 서비스 데이터를 보존하며, 코드 변경만 빠르게 반영할 때 사용합니다.
`start` 또는 `docker`가 처음 전체 스택을 시작한 후에만 유효합니다.

#### 로컬 reranker 재시작 (Mac DEV 전용)

`.env` 파일에서 `LOCAL_LLAMA_CPP_RERANKER_MODEL`과 `LLAMA_ARG_UBATCH`를 읽어 llama-server를 재시작합니다. 셸 환경의 동일 키는 무시하고 `.env` 파일 값만 사용합니다.

```bash
./scripts/run_poc.sh reranker-restart
```

`LLAMA_ARG_UBATCH=1024`는 현재 DEV의 대표 metadata reranking 요청에서 확인된 값이며, 관리자는 공식 `--ubatch-size` 옵션으로 전달합니다. `reranker-restart`는 이 값을 `.env`에 명시하도록 요구하며 빈 값이나 누락을 허용하지 않습니다.

#### DataHub 토큰 없는 DEV GMS 연결 (DEV 전용)

인증이 비활성화된 로컬 GMS 인스턴스를 사용할 때만 `.env`에 다음을 추가합니다.

```dotenv
POC_DATAHUB_ALLOW_NO_TOKEN=true
DATAHUB_GMS_URL=http://host.docker.internal:8080
DATAHUB_GMS_TOKEN=
```

`POC_DATAHUB_ALLOW_NO_TOKEN=true`는 PREP이나 OPS에서 절대 설정하지 않습니다. PREP·OPS 배포는 항상 `DATAHUB_GMS_TOKEN`을 설정하며, 이 플래그는 무관합니다. 기본값은 `false`(fail-closed)이며 Compose가 `.env` 파일에서 이 값을 컨테이너에 주입합니다.

### 별도 Airflow POC 실행

Airflow를 함께 준비해야 할 때도 Web Compose와 분리해 실행합니다. 이 구성은 repository의
기존 `bulk_registration_prepare.py`, `datariver_bulk_registration.py`,
`datariver_auth.py` 세 파일만 read-only로 mount하고 예제 DAG는 적재하지 않습니다. Web Compose가
만든 `datariver-poc-services` external network에 연결해 기본적으로 `http://web:8080`을 호출하며,
별도 host의 Web을 호출해야 할 때만 `AIRFLOW_DATARIVER_URL`을 override합니다.

```bash
docker compose --env-file deploy/poc/.env \
  -f deploy/poc/docker-compose.airflow.yaml config --quiet
docker compose --env-file deploy/poc/.env \
  -f deploy/poc/docker-compose.airflow.yaml up -d
```

`.env`에는 기본 host-local UI를 가리키는 `AIRFLOW_URL=http://127.0.0.1:18888`,
`AIRFLOW_USERNAME`, `AIRFLOW_PASSWORD`, Web과 Airflow에만 주입하는 동일한 random
`POC_AIRFLOW_SERVICE_TOKEN`,
`AIRFLOW_DAG_ID=datariver_bulk_registration_prepare`만 연결값으로 지정합니다. DAG는 안전을
위해 이 검토된 파일 하나만 mount하며 새 POC Airflow 상태에서는 active로 생성됩니다. Web은
Bulk 파일 검증을 끝낸 경우에만 REST API로 명시 실행합니다. 기존 Airflow state volume에서
DAG가 이미 pause되어 있다면 UI에서 한 번 unpause해야 합니다.

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
- POC PostgreSQL을 production canonical state, HA archive 또는 무검증 backup/rollback으로 보는 주장
- 외부 provider의 운영 SLA·권한 적정성·데이터 정합성
- Airflow DAG downstream DataRiver API 성공
- production TLS, 인터넷 공개, availability, performance, recovery 또는 security acceptance
