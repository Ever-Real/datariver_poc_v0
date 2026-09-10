# DataRiver

DataRiver는 DataHub를 중심으로 데이터 카탈로그, 검색, 등록·변경 관리, 지식그래프, 근거 기반 대화, 품질 정보와 운영 관리를 제공하는 서비스입니다. `dev_deploy` 브랜치의 소스로 애플리케이션을 빌드·배포하고 후속 개발을 진행합니다.

## 아키텍처와 코드 위치

React·TypeScript 화면과 Node.js 서버를 분리한 모듈형 모놀리스입니다. 배포 시 하나의 Node.js 프로세스가 API와 빌드된 화면을 함께 제공합니다.

```text
브라우저 → Node.js API·React 화면 제공
              ├─ PostgreSQL: 사용자·설정·업무 상태·수집 기록
              ├─ Neo4j: 지식그래프 조회용 데이터
              ├─ Redis: 임시 캐시
              └─ 외부 서비스: DataHub, Kafka, Schema Registry,
                             대화·임베딩·재정렬 모델, Airflow, MinIO
```

직접 배포하는 컨테이너는 `web`, `pgvector`, `neo4j`, `redis`입니다. 외부 서비스와 모델은 별도로 준비해야 합니다. GX 품질 실행 준비 점검은 외부 실행 경로의 연결을 확인합니다. 품질 작업의 실제 실행 결과는 별도로 확인합니다.

| 경로 | 역할 |
|---|---|
| `backend/src/bootstrap.mjs` | 설정·공유 객체 조립과 서버·스케줄러 수명주기 |
| `backend/src/server.mjs`, `backend/src/interfaces/http/` | HTTP 요청·인증 연결·라우팅·정적 파일 제공 |
| `backend/src/modules/` | 기능별 업무 처리 |
| `backend/src/infrastructure/` | 상태 저장과 외부 서비스 접근 |
| `backend/scripts/` | 초기 구성·사용자 관리·외부 서비스 사전 점검 |
| `frontend/src/` | `app` 진입점, `features` 기능 화면, 공통 UI·API·스타일 |
| `deploy/` | Dockerfile·Compose·환경 계약·PostgreSQL 초기 스키마 |
| `scripts/` | 소스 점검·빌드·배포·운영 검증 |
| `package.json`, `package-lock.json` | 공통 실행 명령과 의존성 버전 고정 |

기능 모듈은 `catalog`, `chat`, `registration`, `governance`, `quality`, `knowledge`, `k9`, `mcl`, `admin`, `auth`, `monitoring`으로 구분합니다. K9는 메타데이터·계보·의미 검색용 데이터를 구성하고, MCL은 메타데이터 변경 로그를 수집합니다. 모듈은 공유 상태와 지연 주입 연결을 사용하므로 수정할 때 호출부와 상태 수명주기를 함께 확인합니다.

## 이관과 실행 준비

배포에는 리눅스 셸, Python 3.10 이상, Docker와 Docker Compose가 필요합니다. Git은 저장소 복제나 버전 관리에만 선택적으로 사용됩니다. 대상 이미지는 `linux/amd64`이며, 호스트에서 개발 점검을 실행하려면 Node.js 22.19 이상과 npm도 준비합니다. 실행기는 Python 표준 라이브러리를 사용하므로 uv나 가상환경은 필수가 아닙니다. 기존 `.venv/`는 빌드 대상에서 제외됩니다.

기본 컨테이너 이미지와 npm 패키지에 접근할 수 있는 승인된 저장소·미러·프록시가 필요합니다.

### 소스만 반입한 경우

숨김 파일인 `.gitignore`, `.dockerignore`도 포함해 반입합니다. Git 초기화나 커밋(`git init`/`add`/`commit`) 없이 복사된 소스 디렉터리 상태 그대로 바로 빌드·배포할 수 있습니다(Git을 사용할 경우 기존 방식으로 버전 관리 가능).

스크립트 실행 권한을 부여한 뒤 진행합니다.

```bash
chmod +x scripts/dev_deploy
```

빌드는 현재 소스 폴더를 읽어 처리하며, `runtime/`, 환경 설정 파일(`.env*`), 개인키, 생성 캐시 및 루트 `README.md`는 소스 해시 계산과 빌드 대상에서 자동으로 제외됩니다. 소스 코드를 수정한 경우에는 다시 빌드해야 하지만, 루트 `README.md`만 수정한 경우에는 재빌드가 필요하지 않습니다.

### 운영 입력

같은 PREP PC에서도 기존 소스와 다른 디렉터리에 `dev_deploy`를 받습니다. 다른 PC에서는 같은 브랜치를 새로 받습니다. 운영 입력은 새 소스 루트의 `deploy/`에 준비합니다.

| 파일 | 독립 신규 설치에서의 처리 |
|---|---|
| `deploy/.env.prep` | 기존 PREP의 파일을 내용 변경 없이 복사 |
| `deploy/.env.prep.optional` | 사용 중이면 함께 복사. 기본 파일에 없는 추가 provider 설정 |
| 환경 설정에서 지정한 CA 파일 | 설정된 절대 경로에서 읽을 수 있도록 준비 |
| 기존 `.env.prep.runtime` | 기존 39083의 복구용으로 보존. `datariver-dev` 신규 설치에서는 읽지 않음 |

기존 파일이 `deploy/prep39083/`에 있다면 원본을 남겨두고 새 소스의 `deploy/`로 **복사**합니다. 비밀 설정 파일의 권한은 `0600`으로 관리하며 Git·이미지·공유 로그에 넣지 않습니다. `.optional`과 기본 파일에 같은 키가 있으면 사전 점검이 실패합니다. 필수 설정 항목은 `deploy/env-contract.json`과 `scripts/dev_deploy.py`를 확인합니다.

기존 파일을 수정하지 않고 새 PC의 접속 주소는 `--public-origin`으로 지정합니다. 원본 파일의 포트·프로젝트·DB 접속 설정 대신 새 프로젝트에 필요한 값만 `runtime/dev_deploy/dev/derived.env`에 적용합니다. 외부 provider의 주소·인증·workspace 계약은 유지합니다. 새 PC에서도 해당 provider, 프록시, DNS, CA 및 사내망 허용 범위가 유효해야 합니다.

독립 설치는 새 PostgreSQL·Neo4j 데이터와 새 관리자 계정을 만듭니다. 기존 39083의 사용자·metadata·그래프·checkpoint는 자동 복사되지 않습니다. 새 비밀정보와 설치 ID는 `runtime/dev_deploy/dev/generated.json`, 관리자 비밀번호는 같은 디렉터리의 `admin-password`에 저장됩니다. 이후 **같은 설치를 재배포할 때** 이 파일들을 보존합니다. 두 번째 PC에 별도의 새 설치를 만들 때는 이 파일들과 기존 볼륨을 복사하지 않습니다.

Kafka client/group ID는 설치마다 별도로 생성하고 재배포 시 재사용합니다. 같은 프로젝트명을 다른 PC에서 사용해도 consumer group을 공유하지 않습니다. broker/topic/schema/auth 계약은 기존 설정을 사용하며, Kafka ACL은 새 consumer group의 사용을 허용해야 합니다.

### 필요한 이미지 확보

| 용도 | 이미지 |
|---|---|
| Web 빌드 기반 | `node:22.19.0-bookworm-slim` |
| PostgreSQL·벡터 확장 | `pgvector/pgvector:0.8.2-pg17-bookworm` |
| Neo4j | `neo4j:2026.06.0` |
| Redis | `redis:8.2.6-bookworm` |
| Web | 현재 소스에서 `build`가 생성하는 `datariver-dev-deploy-source:<소스 해시 앞 12자리>` |

모두 `linux/amd64` 기준입니다. 같은 PREP PC에 위 기반 이미지가 이미 있으면 그대로 사용합니다. 별도 PC로 반입할 기반 이미지는 다음과 같이 확보합니다. 아래 `save`는 이미지를 내려받지 않으므로 해당 플랫폼 이미지가 먼저 있어야 합니다.

```bash
mkdir -p runtime/transfer
docker image save --platform linux/amd64 \
  --output runtime/transfer/datariver-base-images-linux-amd64.tar \
  node:22.19.0-bookworm-slim \
  pgvector/pgvector:0.8.2-pg17-bookworm \
  neo4j:2026.06.0 \
  redis:8.2.6-bookworm
(cd runtime/transfer && sha256sum datariver-base-images-linux-amd64.tar > datariver-base-images-linux-amd64.tar.sha256)
```

두 파일을 새 PC의 `runtime/transfer/`로 옮긴 뒤 확인하고 불러옵니다. 기존 Docker를 사용하는 PC에서는 동일 태그가 다른 이미지를 가리키는지 먼저 확인하며, 기존 서비스용 태그를 임의로 덮어쓰지 않습니다.

```bash
(cd runtime/transfer && sha256sum -c datariver-base-images-linux-amd64.tar.sha256) && \
  docker image load --input runtime/transfer/datariver-base-images-linux-amd64.tar
```

Web은 아래 `build`에서 소스로 만듭니다. 기반 이미지 반입만으로 완전한 오프라인 소스 빌드가 되지는 않습니다. `npm ci`와 production dependency 정리를 위해 잠금 파일에 맞는 npm 패키지를 제공하는 승인된 저장소·미러·프록시가 필요합니다. 이미지는 운영 `.env`나 DB 데이터를 포함하지 않습니다.

## datariver-dev 배포

기본 프로젝트는 `datariver-dev`, Web 포트는 `39091`입니다. 같은 PREP PC와 다른 PC에서 동일한 명령을 사용하며 접속 주소만 해당 PC에 맞춥니다.

| 서비스 | 호스트 바인딩·포트 | 컨테이너 포트 |
|---|---|---|
| Web | `0.0.0.0:39091` | `8080` |
| PostgreSQL | `127.0.0.1:35432` | `5432` |
| Redis | `127.0.0.1:36379` | `6379` |
| Neo4j HTTP | `127.0.0.1:37475` | `7474` |

네트워크는 `datariver-dev-services`, 영속 볼륨은 `datariver-dev_pgvector-data`, `datariver-dev_neo4j-data`, `datariver-dev_neo4j-logs`입니다. Redis는 기존 캐시 정책에 따라 영속 볼륨을 사용하지 않습니다. 컨테이너 내부의 서비스명과 포트는 유지합니다. 새 프로젝트의 네 호스트 포트는 다른 서비스가 사용하지 않아야 합니다.

프로젝트 루트에서 `대상PC_IP`를 실제 주소로 바꾸고 순서대로 실행합니다. 실패하면 다음 단계로 진행하지 않습니다.

```bash
./scripts/dev_deploy check-source
./scripts/dev_deploy preflight --public-origin "http://대상PC_IP:39091"
./scripts/dev_deploy build
./scripts/dev_deploy deploy --public-origin "http://대상PC_IP:39091" --apply
```

`check-source`는 Git 커밋 대신 소스 내용의 SHA256 해시와 대상 파일 수를 표시합니다. 이 해시로 빌드 입력과 배포 일관성을 검증합니다.

`preflight`는 환경 입력 계약을 확인합니다. 실제 provider 연결은 배포 내부의 사전 점검에서 확인합니다.

Airflow 연결에는 `AIRFLOW_URL`, `AIRFLOW_USERNAME`, `AIRFLOW_PASSWORD`를 사용합니다. `POC_AIRFLOW_SERVICE_TOKEN`은 Airflow에서 DataRiver 등록 작업을 호출할 때 사용하는 선택 설정입니다. 해당 연동을 사용한다면 양쪽의 기존 토큰을 유지합니다. 토큰이 없으면 해당 서비스 호출은 인증 미구성으로 차단되며, 배포 smoke 통과가 이 선택 연동의 실행 성공을 뜻하지는 않습니다. `preflight`에는 값 대신 `SET`/`ABSENT`만 표시됩니다.

`build`는 실행 중인 컨테이너를 변경하지 않으며, 현재 소스 폴더를 기반으로 `datariver-dev-deploy-source:<소스 해시 앞 12자리>` 이미지를 빌드합니다.

- 동일 소스 해시, 유효한 `receipt.json`, 로컬 이미지가 존재하면 빌드·태깅 없이 기존 이미지를 재사용합니다(과거 빌드 기록은 원래 입력에 연결되어 보존).
- 일반 빌드는 Docker 캐시를 활용하며, 클린 빌드가 필요한 경우 `./scripts/dev_deploy build --no-cache`를 사용합니다. 기존 태그가 있는 상태에서 강제 재빌드하면 시간 접미사를 붙여 기존 참조를 보존합니다. 이미지는 자동으로 삭제되지 않습니다.
- 빌드 중 실시간 Docker plain 출력과 15초 간격의 heartbeat(경과 시간/무출력 알림)를 제공하며, 로그는 `runtime/dev_deploy/build/<소스해시>.log`와 `receipt.json`에 기록됩니다.
- `./scripts/dev_deploy build-log`로 최근 빌드 로그 마지막 60줄을 확인하거나 `--follow`로 실시간 추적할 수 있습니다(Git·환경 설정 없이 동작).

배포가 성공한 뒤 소스·빌드 입력이 같고 이미지와 빌드 기록이 남아 있으면 다음 재배포에 build를 반복할 필요가 없습니다. 기능 코드·의존성·Dockerfile·실행 스크립트를 변경하면 일반 build를 다시 수행합니다. 운영 환경 파일만 바꾼 경우에는 보통 이미지 재빌드가 필요하지 않지만 preflight와 배포 검증은 다시 수행합니다. 소스 해시는 GitHub 접속 없이 현재 폴더에서 계산합니다.

Dockerfile은 `deploy/Dockerfile` 하나이며, 버전별로 쌓이는 것은 빌드 이미지입니다. 배포 성공과 복구 이미지 보존을 확인한 뒤 다음 명령으로 오래된 소스 이미지를 정리할 수 있습니다.

```bash
./scripts/dev_deploy images
./scripts/dev_deploy clean-images --apply
```

`images`와 `clean-images`의 기본 동작은 삭제 없는 미리보기입니다. `clean-images --apply`만 삭제하며, 실행·중지된 모든 컨테이너의 이미지, 현재 디렉터리의 빌드·배포 성공 기록이 참조하는 이미지, 최근 소스 이미지 3개와 별도 태그가 붙은 이미지는 보존합니다. 이 도구가 확인한 `datariver-dev-deploy-source`의 오래된 이미지만 삭제하고 기반 이미지·빌드 캐시·볼륨은 건드리지 않습니다. 삭제 직전 상태가 달라지거나 Docker가 거부하면 보류합니다. 빌드·배포·이미지 태깅과 동시에 실행하지 않습니다. 결과는 `runtime/dev_deploy/image-cleanup.json`에 남습니다.

기본 빌드는 운영 환경 파일을 읽지 않습니다. 기존 환경 파일에 빌드용 `HTTP_PROXY`, `HTTPS_PROXY`, `NO_PROXY`가 있다면 다음처럼 지정합니다. 이 세 키만 Docker 빌드에 전달하며 provider 인증정보는 전달하지 않습니다. `.optional` 파일도 기존 해석 규칙으로 읽습니다. 파일 내용을 변경하지 않습니다.

```bash
./scripts/dev_deploy build --build-env-file deploy/.env.prep
./scripts/dev_deploy build-log --follow
```

npm 설치·production 의존성 정리는 각 단계에서 임시 프록시 설정을 사용하고 종료 시 제거합니다. 화면에는 Node/npm 버전, npm 단계, 프록시의 SET/ABSENT만 표시합니다. 프록시를 지정하지 않으면 셸 또는 Docker 클라이언트의 기존 빌드 프록시 설정을 사용합니다. 소스 빌드에는 npm 패키지 접근이 필요하며, 현재 잠금 파일의 공개 registry 경로를 사용할 수 없는 환경에서는 승인된 프록시·미러를 먼저 준비해야 합니다.

`deploy --apply`는 새 프로젝트의 상태를 구성하고 Web을 기동합니다. 재배포에서는 해당 프로젝트의 호환되는 상태와 비밀정보를 재사용합니다. 빌드 후 소스코드를 수정한 경우에는 다시 빌드해야 배포할 수 있습니다(루트 `README.md`만 수정한 경우에는 재빌드 불필요).

배포 터미널에는 `[1/11] 소스·이미지 확인`을 표시하고, 완료되면 같은 줄 오른쪽에 경과 시간과 `[PASS]`를 붙인 뒤 다음 단계로 넘어갑니다. 실패·중단은 `[FAIL]`·`[INTERRUPTED]`로 표시합니다. 대기 중에는 같은 줄을 갱신하며, 파일로 출력하면 제어문자 없이 완료 결과와 1분 간격의 대기 알림을 기록합니다. 단계 번호는 시간 기준 진행률이 아닙니다. `[9/11] Smoke 검증`에서는 서버·이미지 상태, 관리자 로그인, DataHub 조회·용어집, 관리형 그래프·의미 검색 인덱스, MCL 최신 수집·이력, AUTO 일반 대화·응답 경로를 `[1/6]`~`[6/6]` 이름과 결과로 표시합니다. 검색·GRAPH 대화·미리보기 검증은 다음 기능 검증 단계에서 수행하며, 전체 성공은 최종 acceptance로 확인합니다.

상세 `DEPLOY_PROGRESS` 기록은 `runtime/dev_deploy/dev/deploy-*.log`에 실행별로 남습니다(권한 `0600`). 비밀값·원시 provider 응답은 기록하지 않습니다. 별도 터미널에서 `./scripts/dev_deploy deploy-log --follow`로 최신 기록을 볼 수 있습니다. `--port 39083`을 지정하면 해당 PREP의 진행 기록을 읽습니다. 이전 실행기의 실행 중 작업에는 표시가 소급 적용되지 않습니다.

중단 후에는 배포 CLI와 해당 실행의 임시 검증 컨테이너가 끝났는지 확인한 뒤 업데이트합니다. 최초 bootstrap 도중 중단된 상태는 자동 재개를 보장하지 않습니다. 환경 파일, `runtime/`의 생성 비밀정보와 기존 볼륨을 보존하고, 현재 소스를 다시 `build`한 뒤 재배포합니다. 일반 빌드는 Docker 캐시를 사용할 수 있습니다.

PostgreSQL 메모리 제한은 4GiB입니다. 기존 `datariver-dev` 컨테이너에 더 작은 제한이 남아 있으면 deploy가 해당 컨테이너의 제한을 올립니다. 작은 제한에서 발생한 OOM 이력이 있으면 기존 Web을 먼저 멈추고 PostgreSQL을 한 번 재시작한 뒤 정상 배포 순서를 진행합니다. 컨테이너·볼륨 identity와 생성 비밀정보를 보존하며, 과거 OOM과 조치는 `runtime/dev_deploy/dev/postgres-recovery.json`에 남깁니다. 이미 4GiB 이상에서 발생한 OOM은 자동 재시작으로 우회하지 않고 원인 확인을 요구합니다. 이 기존 컨테이너 보정은 `datariver-dev`에만 적용합니다.

`PREVIOUS_DEPLOY_VERIFIER_RUNNING:<컨테이너ID>`가 나오면 이전 deploy의 임시 검증 컨테이너가 아직 실행 중입니다. 해당 ID의 용도와 이전 CLI 종료 여부를 확인한 뒤 그 검증 작업을 종료하고 다시 실행합니다. 실제 서비스나 다른 프로젝트를 일괄 중단하지 않습니다.

현재 디렉터리에 빌드 결과가 없으면 `SOURCE_BUILD_REQUIRED`, 빌드 기록이 손상됐거나 현재 소스와 맞지 않으면 `SOURCE_BUILD_RECEIPT_INVALID`로 배포 전에 종료합니다. 이 경우 현재 소스에서 `build`를 성공시킨 뒤 배포합니다. 다른 디렉터리의 `receipt.json`을 복사하거나 수동으로 만들지 않습니다.

기존 `datariver-prep39083`과 `39080`은 변경 대상이 아닙니다. 기존 PREP를 대상으로 하는 `--port 39083`은 별도의 운영 재배포용이므로 독립 설치에서는 사용하지 않습니다.

환경 파일이 다른 위치에 있으면 `preflight`와 `deploy`에 `--env-file <파일경로>`를 지정합니다. `.optional`은 지정한 환경 파일명 뒤에 같은 접미사를 붙여 같은 디렉터리에 둡니다. 관리자 계정은 `admin`이며 생성 비밀번호 파일은 로컬에서만 확인합니다. 재배포 시 필요한 기존 관리자 비밀번호를 비대화형으로 제공하려면 `--admin-password-file <보안파일경로>`를 사용합니다.

웹에서 관리자 비밀번호를 변경해도 배포 디렉터리의 `runtime/dev_deploy/dev/admin-password`는 자동으로 갱신되지 않습니다. 변경 후 첫 재배포에는 현재 비밀번호를 숨김 입력하는 옵션을 사용합니다.

```bash
./scripts/dev_deploy deploy --port 39091 --env-file deploy/.env.prep --public-origin "http://대상PC_IP:39091" --prompt-admin-password --apply
```

6/11 초기 구성 단계에서 현재 `admin` 비밀번호를 입력합니다. 입력값은 화면·명령 이력에 표시되지 않으며, 로컬 `admin-password` 사본을 권한 `0600`으로 갱신합니다. DB의 비밀번호를 재설정하는 명령이 아니므로 현재 웹 로그인에 사용하는 값을 입력해야 합니다. 이후에는 갱신된 사본을 재사용합니다. 비대화형 실행은 최신 비밀번호가 들어 있는 `--admin-password-file`을 사용하며 두 옵션을 함께 지정하지 않습니다. 인증 실패 시 비밀번호를 확인하고 반복 로그인으로 우회하지 않습니다.

배포 명령은 focused readiness, 운영 smoke 6단계, 검색·대화·그래프 미리보기 검증을 수행합니다. 성공 직후 같은 full smoke를 별도로 반복할 필요는 없습니다. 최초 수집과 임베딩은 데이터 규모에 따라 시간이 필요합니다. 외부 DataHub·GX·Airflow·MinIO·모델은 연결한 서비스를 공유하므로, 독립된 Docker 프로젝트가 외부 데이터까지 복제하거나 격리하는 것은 아닙니다.

기능 검증의 영향도 질문은 발행된 계보 그래프의 테이블·뷰·데이터셋 유형에서 후보를 고른 뒤, 현재 권한으로 조회한 Catalog 테이블과 실제 downstream 관계를 확인해 실행합니다. 후보가 없으면 최대 10페이지의 Catalog에서 분산 선택하며, lineage 조회는 전체 최대 20회입니다. `NO_TEST_DATA_GRAPH_RELATION`은 확인한 전체 Catalog 테이블에 검증 가능한 관계가 없는 경우이고, `GRAPH_TARGET_SEARCH_LIMIT`은 조회 범위 안에서 찾지 못해 존재 여부를 확정할 수 없는 경우입니다. 두 경우 모두 기능 PASS로 처리하지 않습니다. 컬럼 계보의 연결 수가 많아 테이블 후보가 가려지지 않도록 기존 유형 필터를 사용합니다. `features.json`의 `target_selection`에 그래프 노드·관계·데이터셋 후보 수, Catalog 조회 수·선택 경로·범위 제한 여부를 기록합니다.

39091에서 대상 선택이 실패하면 소스를 업데이트한 뒤 다음 명령으로 해당 구간만 확인합니다. 현재 `datariver-dev` Web의 이미지로 임시 검사 컨테이너를 실행하며, 기존 admin 비밀번호 파일로 로그인해 그래프·Catalog·lineage를 조회합니다. 빌드, Web 재시작, provider 수집, LLM 질의, full smoke는 실행하지 않습니다.

```bash
./scripts/dev_deploy check-graph-target --public-origin "http://대상PC_IP:39091"
```

결과는 `runtime/dev_deploy/dev/graph-target.json`에 저장합니다. 이 명령의 PASS는 검증 가능한 테이블과 관계를 찾았다는 뜻이며 배포 acceptance가 아닙니다. 최종 배포에는 현재 소스로 정상 build/deploy와 전체 acceptance를 수행합니다.

## 배포 확인과 장애 대응

빌드 성공만으로 배포 완료가 아닙니다. 자동 검증이 모두 통과하고 브라우저에서 관리자 로그인, 검색, 일반 대화, 실제 테이블 영향도 질문, 지식그래프 미리보기와 기존 데이터 보존을 확인해야 합니다.

MCL 최신 수집과 K9 의미 검색 준비는 정상이어야 합니다. `SOURCE_NOT_CONFIGURED`, `FAILED`, 원인 불명의 `UNKNOWN`은 완료로 처리하지 않습니다. MCL 과거 이력은 사유가 `RETENTION_EXPIRED`인 `DEGRADED_GAP`만 허용하며, 이력의 불완전성을 구분해 표시합니다.

| 위치 | 확인 내용 |
|---|---|
| `runtime/dev_deploy/build/` | 빌드 로그(`<소스해시>.log`)와 결과(`receipt.json`) |
| `runtime/dev_deploy/dev/provider-preflight.json` | 외부 연결 사전 점검의 단계·오류 코드·HTTP 상태 분류 |
| `runtime/dev_deploy/dev/readiness.json` | K9·MCL 준비 상태와 인증·연결 실패 원인 |
| 같은 디렉터리의 `smoke.json`, `smoke-failure.json` | 운영 smoke 결과 또는 실패 진단 |
| 같은 디렉터리의 `features.json`, `acceptance.json` | 기능 검증과 최종 배포 결과 |

실패하면 먼저 출력된 단계·오류 코드와 해당 결과 파일을 확인합니다. 8/11 실패는 `READINESS_FAILED`, 10/11 실패는 `FEATURES_FAILED`에 검사 단계·코드·HTTP 상태를 표시합니다. 인증 실패로 시작하지 못한 기능 검사는 `NOT_RUN`이며 K9·MCL 자체 장애나 성공을 뜻하지 않습니다. `readiness.json`·`features.json`의 `failure`에 안전한 오류 정보와 실패 시각을 남기며, `accepted_at`은 해당 검사가 성공했을 때만 기록합니다. Smoke 실패 시 현재 실행이 반환한 `SMOKE_FAILED|stage=...|code=...|http=...`를 표시합니다. 이전 단계 실패 후에도 읽기 전용 진단을 계속할 수 있으므로, 마지막 smoke 번호가 실패 원인을 뜻하지는 않습니다. `smoke-failure.json`의 `failed_at`, `stage`, `classification`, `readiness`를 이번 실행과 대조합니다. 초기 단계 실패에서는 뒤 단계의 파일이 없을 수 있으므로 이전 실행 결과를 이번 성공 증거로 사용하지 않습니다.

설정 누락·인증 오류·종료된 실패를 무조건 재시도하지 않습니다. 볼륨 삭제, DB 초기화, 관리자 재생성, 무조건적인 그래프 재구성으로 우회하지 않습니다. 자동 복구를 가정하지 말고 기존 이미지와 데이터 호환성을 확인해 승인된 절차로 복구합니다.

`PROVIDER_PREFLIGHT_FAILED`는 빌드 성공 후 외부 서비스 사전 점검에서 실패했다는 뜻입니다. `PROVIDER_PREFLIGHT|status=FAILED|stage=...|code=...|http=...`로 실패한 점검을 확인합니다. 39091 배포 시도 후에는 다음 명령으로 이 구간만 다시 확인할 수 있습니다.

```bash
./scripts/dev_deploy check-providers
```

마지막 배포 시도에서 생성한 `runtime/dev_deploy/dev/derived.env`와 그 안에 지정된 기존 로컬 이미지를 사용합니다. 생성 파일에 저장된 프로젝트·포트와 값을 그대로 읽으며, 원본 `.env.prep`의 해석 규칙은 바꾸지 않습니다. 소스 업데이트 후에도 이 진단을 위해 다시 빌드할 필요는 없습니다. 임시 컨테이너에서 외부 연결·인증·모델 응답과 MCL discovery를 점검하며 Web 교체·state 초기화·full smoke는 수행하지 않습니다. 원본 환경 파일을 수정했더라도 이 명령은 마지막 배포 시도의 입력을 검사합니다. 비밀값과 원시 응답은 출력하지 않으며, 진단 PASS를 배포 acceptance로 사용하지 않습니다.

## 개발 및 Agent 작업 원칙

먼저 이 문서와 담당 모듈, 관련 호출부, `package.json`, 배포 실행 코드를 확인합니다.

기본 개발 점검은 다음과 같습니다.

```bash
npm ci --ignore-scripts
npm run typecheck
npm run lint
npm run build
```

`npm start`는 Node 서버를 실행하므로 운영 입력과 데이터 연결을 먼저 확인합니다. `npm run dev`는 화면 개발 서버만 실행하며 기본 포트 `39080`을 사용하므로 기존 서비스와 충돌하지 않는 환경에서 사용합니다. 변경 기능에 필요한 회귀 검증은 별도로 수행합니다.

- 기능 변경은 해당 모듈에 한정하고 HTTP·업무 규칙·외부 서비스 경계를 유지합니다. 공통 상태, 트랜잭션, 연결 풀, 스케줄러를 임의로 중복 생성하지 않습니다.
- `POC_*`, `/poc-api`, DB의 `poc_*`, 세션·저장 키와 migration 파일명은 호환성 계약입니다. 단순 명칭 정리로 변경하지 않습니다.
- 비밀값·사용자 데이터는 출력하거나 테스트 자료로 반입하지 않습니다. 의존성 보안 경고는 영향과 조치 방침을 확인하고, 자동 강제 업데이트로 해결하지 않습니다.
- 병렬 작업은 수정 파일이 겹치지 않을 때만 수행합니다. 공통 설정 통합, 고비용 빌드, 실제 배포는 담당자 한 명이 관리합니다.
- 변경 범위 검증을 먼저 하고 최종 소스로 빌드·배포를 확인합니다. mock·검사 생략·권한 완화로 성공을 만들지 않으며, 실제 실행하지 않은 검증은 미실행으로 기록합니다.
- 실제 PREP 변경은 운영자 승인 후 수행합니다. 실행 명령이나 운영 계약을 바꾸면 이 README도 함께 수정하고, 결과는 변경 내용·검증·남은 문제 위주로 짧게 보고합니다.
