# Knowledge Studio Phase 6 RC cutover preparation

- 기준일: 2026-07-28
- RC tag: `v1.1.0-RC1`
- 필수 DB revision: `0061`
- 배포 성격: **Single-node Pilot RC 검증; production acceptance 아님**
- 선행 결정: [ADR-0062](adr/0062-knowledge-studio-governed-schema-publication.md)

## 1. 범위와 비범위

이번 RC는 Phase 5의 governed schema/mapping publication과 Step 2의 시각적 상호작용
scaffold를 운영 PC에서 검토할 수 있게 한다. Step 2 scaffold는 다음 경계를 갖는다.

- 최초 캔버스는 실제로 비어 있으며 placeholder Class/Relation을 만들지 않는다.
- 사용자가 이름을 입력한 경우에만 브라우저 메모리에 로컬 테스트 노드를 만든다.
- 노드 drag, handle 연결, 명시적으로 선택한 노드 삭제를 시험할 수 있다.
- 로컬 노드/관계선은 typed operation, Draft T-Box 또는 Accepted schema가 아니다.
- 서버 저장, autosave, Publish, Neo4j write, DataHub mutation은 발생하지 않는다.
- 새로고침이나 Studio 이탈 시 로컬 요소가 사라진다.
- `REVIEW`, `PUBLISHED`, `DISCARDED` lifecycle에서는 scaffold 조작도 잠긴다.

따라서 이 화면은 Step 2 canvas cutover의 시각·입력 검증용이다. 아직 열려 있는 weighted
block fold, AST 양방향 operation writer, proposal Preview/Accept와 T-Box persistence 완료를
의미하지 않는다.

## 2. 운영 PC 사전 조건

아래 절차는 저장소 기본 `compose.yaml`을 사용하는 기존 Single-node Pilot 운영 PC용이다.
조직이 승인한 production overlay가 있다면 모든 Compose 명령에 같은 `-f` 목록을 일관되게
추가한다.

1. PostgreSQL과 object storage 복구 지점 및 복원 가능성을 먼저 확인한다.
2. `.env`, `secrets/`, runtime volume은 운영 PC에 남겨 두고 Git으로 덮어쓰지 않는다.
3. `git status --short`가 비어 있지 않으면 중단한다.
4. 실제 HA/production 승격에는 외부 OIDC, TLS, digest-pinned image, target PostgreSQL RLS,
   두 명의 실제 WebAuthn 사용자와 restore evidence가 별도로 필요하다.
5. 다른 CPU 아키텍처의 Docker image/volume을 복사하지 않는다. Source는 Git으로, 승인된
   dependency/image artifact는 별도 checksum 경로로 이관한다.

준비 PC에서 `dev`의 최신 화면만 빠르게 확인하는 일상 경로는 다음 한 명령이다.

~~~bash
cd /path/to/datariver_v1
./scripts/development_cycle.py prep-update
~~~

이 명령은 `origin/dev` fast-forward, offline dependency 조건 검사, ignored
`.env.wsl-intranet-development` 재적용, migration, source-host 시작과 API/Web/OIDC probe를
하나의 안정된 인터페이스로 수행한다. 아래의 수동 명령은 `main` RC cutover 또는 장애
진단용이며 일상 `prep-update`를 대체하지 않는다.

## 3. `main` RC checkout 검증

~~~bash
cd /path/to/datariver_v1
git status --short
git fetch --prune origin main
git fetch --tags origin
git switch main
git pull --ff-only origin main
git rev-parse HEAD
git rev-list -n 1 v1.1.0-RC1
git merge-base --is-ancestor v1.1.0-RC1 HEAD
~~~

`git status --short`는 빈 출력이어야 하고, 두 SHA 출력은 같아야 한다. 마지막 명령도
exit code `0`이어야 한다. 다르면 migration이나 Docker 재기동을 시작하지 않는다.

## 4. Compose 렌더링, image 준비와 revision `0061`

운영자가 승인한 `.env`와 secret reference가 이미 존재한다는 전제다. 호스트의 임의 DB
계정으로 Alembic을 실행하지 않고 권한이 분리된 `migrate` 서비스만 사용한다.

~~~bash
cd /path/to/datariver_v1
docker info --format '{{.OSType}}/{{.Architecture}}'
docker compose version
scripts/compose.sh --env-file .env -f compose.yaml config --quiet
scripts/compose.sh --env-file .env -f compose.yaml build --pull
scripts/compose.sh --env-file .env -f compose.yaml run --rm migrate
scripts/compose.sh --env-file .env -f compose.yaml run --rm migrate \
  /app/.venv/bin/alembic -c backend/alembic.ini current
~~~

마지막 출력은 `0061 (head)`여야 한다. 실패하거나 다른 revision이면 API/Web을 재기동하지
않고 DB 상태와 migrate log를 보존한다. Revision `0061`의 downgrade는 publication evidence를
파괴할 수 있으므로 자동 rollback 수단으로 사용하지 않는다.

정식 production은 위의 source build 대신 CI에서 검증하고 digest로 고정한 동일 RC image를
사용해야 한다. WSL `linux/amd64` 준비 PC는 Mac `linux/arm64` image를 재사용하지 않는다.

## 5. Docker 재기동과 readiness

~~~bash
cd /path/to/datariver_v1
scripts/compose.sh --env-file .env -f compose.yaml up -d --wait
scripts/compose.sh --env-file .env -f compose.yaml ps
scripts/compose.sh --env-file .env -f compose.yaml logs --since=10m \
  api outbox-relay upload-worker upload-validation-worker governance-apply-worker
~~~

운영 TLS origin으로 다음 두 요청을 수행한다.

~~~bash
curl --fail --silent --show-error \
  https://datariver.example.internal/api/v1/health/live
curl --fail --silent --show-error \
  https://datariver.example.internal/api/v1/health/ready
~~~

예시 hostname은 운영자가 승인한 실제 origin으로 바꿔야 한다. Liveness만 성공하고
readiness가 실패하면 트래픽을 연결하지 않는다.

## 6. Graph Builder 진입과 수동 UI 검증

1. 운영 TLS origin을 열고 승인된 사용자로 로그인한다.
2. `지식 레지스트리`에서 `Asset 생성`을 선택한다.
3. Step 1에서 이름, `endpoint_alias`, 업무 도메인, 보안등급을 입력하고
   `저장 후 Graph Builder`를 누른다.
4. URL이
   `?page=knowledge-studio&draft=<server-issued-uuid>&step=tbox`를 포함하는지 확인한다.
   임의 UUID를 만들어 URL에 넣지 않는다.
5. Step 2에서 `Accepted schema가 없습니다.`와 `Accepted T-Box · 0개`를 확인한다.
6. `로컬 테스트 노드 이름`에 검증용 이름을 입력해 두 개의 노드를 추가한다.
7. 노드를 드래그하고 각 노드의 handle을 연결해 로컬 관계선 수가 증가하는지 확인한다.
8. 하나의 노드를 선택하고 `선택 노드 삭제`를 눌러 연결선도 함께 제거되는지 확인한다.
9. 이 조작 후에도 `Accepted T-Box · 0개`인지 확인한다.
10. 새로고침하여 로컬 노드가 사라지고 빈 상태로 돌아오는지 확인한다.

`서버 Accepted T-Box 확인`은 로컬 노드를 저장하지 않는다. 실제 accepted typed operation이
없는 Draft에서는 서버가 A-Box 전환을 거부하는 것이 정상 동작이다.

## 7. Sign-off evidence

운영 승인자는 다음을 한 묶음으로 기록한다.

- `main` HEAD와 `v1.1.0-RC1` tag SHA
- Docker OS/architecture와 Compose version
- Alembic `0061 (head)` 출력
- API live/ready 응답
- 로그인한 사용자/Workspace 및 실제 Draft UUID
- empty/add/drag/connect/delete/refresh 각 화면의 캡처
- 브라우저 console 오류와 API 오류의 bounded log
- 미실행 상태인 Step 2 persistence, physical reader, instance ingestion/default graph gate

이 증거가 승인되기 전에는 RC tag가 production acceptance나 HA sign-off를 뜻하지 않는다.

## 8. 개발 PC 실행 증거

RC 준비 소스는 안정된 `development_cycle.py dev-publish` 경로에서 다음을 통과했다.

- Ruff repository format `427` files, lint, strict mypy `421` files
- backend `1,694 passed / 97 environment-gated skipped`
- frontend TypeScript, ESLint, `55 files / 303 tests`, production build
- focused Graph Builder/Studio `2 files / 8 tests`
- PostgreSQL 실제 additive migration `0058 -> 0059 -> 0060 -> 0061`
- API readiness, Web health, Keycloak, DataHub GMS `v1.6.0`
- authorization-pruned catalog projection 2,000 rows sync

가시 브라우저는 로컬 Keycloak 로그인 화면까지 열었다. 기존 로그인 세션이 없어
자격증명/토큰을 우회하지 않았으며, 인증 후 실제 add/drag/connect/delete/refresh 화면 캡처는
운영 승인자의 최종 sign-off gate로 남는다.
