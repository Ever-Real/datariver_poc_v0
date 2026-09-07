# DataRiver — 개발 통합과 PREP 배포

## 1. 브랜치 역할 및 베이스라인
* **`dev` 브랜치**: 이력 관리, 통합 도구, 검증 증적(Evidence) 보존용 브랜치입니다 (추가 코드 머지 없음).
* **`dev_deploy` 브랜치**: 향후 사내 개발, 단일 소스 관리, 빌드 및 배포 표준 브랜치입니다.
* **성공 베이스라인 커밋**: `2bd5494d6f100abc8e50a844e0d01c30b93cc698`
* **검증 증적 커밋**: `4473135c3c9aa1cb44f317f1e3ae1a63de1eeacf`
* **핸드오프 커밋**: `5ae0e49b7943fb80e727d31cb3b1c90152fdf8ad`
* **현재 상태**: 운영자 리포트 6/6 완료, 후보 환경 Actual PREP `NOT_RUN` (사용자 승인 대기), 기능 회귀 121개·canonical smoke 회귀 59개·focused/retry 9개 통과, 최종 후보 `823359c090a9f794e4ee0c0416dae5245cc7707b`; fresh-clone no-cache linux/amd64 build PASS. DEV 준비 완료 `READY_FOR_PREP_OPERATOR`, 실제 PREP acceptance는 미완료입니다.

---

## 2. dev_deploy의 구조 및 런타임 계약

아래 경로는 `dev_deploy` 기준입니다. 이 문서 변경으로 dev application 코드를 병합하지 않았습니다.
* **단일 프로세스 웹 서버**: Node 백엔드가 React 정적 에셋 서빙 및 API 처리를 단일 프로세스로 수행 (FastAPI/별도 워커 미배포, 레거시 FastAPI/OIDC 문서는 참고용).
* **백엔드 구조**:
  * `backend/src/bootstrap.mjs`: 설정, 싱글톤, 스케줄러 라이프사이클 관리
  * `backend/src/server.mjs`: HTTP 인증 및 라우팅 경계 정의
  * `backend/src/interfaces/http`: 라우터, 정적 파일 서빙, 요청 처리
  * **기능 모듈**: `catalog`, `chat`, `registration`, `governance`, `quality`(도메인), `knowledge`, `k9`, `mcl`, `admin`, `auth`, `monitoring`
  * **인프라**: `provider`, `Airflow`, `MinIO`, `Neo4j`, `state-store`
  * **의존성 주입**: 지연 주입(Lazy injected) 방식으로 싱글톤 상태를 유지하며, `catalog`/`chat`/`knowledge` 및 프론트엔드 `app/api.ts` 간 결합도가 남아있음.
* **프론트엔드 구조**:
  * `frontend/src/app`: 로컬 세션 진입점
  * `frontend/src/{features,components,api,styles}`
  * `frontend/vite.config.ts`: 통합 프로덕션 설정
* **컨테이너 배포 범위 (4종)**: `web` + `pgvector` + `neo4j` + `redis`(임시 캐시)
  * **외부 연동**: DataHub, Kafka, Schema Registry, LLM/Embedding/Reranker, Airflow, MinIO
  * **데이터베이스 초기화**: `deploy/postgres-init` 내 기존 10개 SQL 파일 사용
  * **Great Expectations (GX)**: `READY` 상태는 Assertion 읽기 및 Airflow DAG 디스패치 사전 점검을 의미하며, E2E 품질 실행을 의미하지 않음 (UI 품질 컨트롤 플레인 미제공 유지).
* **호환성 유지**: `/poc-api` 경로, SQL 영구 식별자, Kafka 토픽/프로젝트/볼륨 호환성 보존.

---

## 3. 소스 빌드 및 환경 설정 규칙
* **빌드 격리 및 소스 고정**:
  * 현재 `HEAD`에서 `git archive` 기반 빌드 (`--no-cache`, `linux/amd64`, 이미지 태그: `datariver-dev-deploy-source:sha`).
  * 외부 아티팩트 다운로드, 구 소스 또는 application image 재사용 금지.
  * 승인 런타임/캐시: `Node 22.19`, `npm lock`, `pgvector:0.8.2-pg17`, `neo4j:2026.06`, `redis:8.2.6` 필수 (완전 폐쇄망/오프라인 환경 검증은 미수행 상태).
* **자격 증명 및 포트 보호**:
  * 배포 포트 `39080` 및 기존 데이터베이스 상태 보존.
  * `.env.prep.runtime`의 자동 생성 비밀번호 재사용, 기존 관리자 계정 초기화 금지, 소스 환경 파일 불변 유지 및 Git 커밋 금지 (`0600` 권한 유지).
  * 매니페스트 및 원본 상세 출처(Provenance)는 `dev:deploy/dev_deploy`로 이동 관리.

---

## 4. 표준 배포 명령어
```bash
# 1. dev_deploy 브랜치 단일 클론
git clone --single-branch --branch dev_deploy https://github.com/Ever-Real/datariver_poc_v0.git datariver-prep
cd datariver-prep

# 2. 런타임 환경 설정 복사 (권한 0600 유지)
# .env.prep 및 필요한 .runtime/.optional 사이드카 파일을 deploy/ 아래로 복사 (또는 --env-file 지정)

# 3. 사전 검증(Preflight)
./scripts/dev_deploy preflight

# 4. 이미지 빌드
./scripts/dev_deploy build

# 5. 배포 적용 (Actual PREP은 사용자 명시적 승인 필요)
./scripts/dev_deploy deploy --apply
```

---

## 5. 스모크 테스트 (Smoke Verification - 6개 목적)
1. **Health**: 웹 서버 헬스체크 및 프로세스 생존 여부
2. **Admin**: 관리자 계정 권한 및 기존 설정 접근
3. **DataHub + Glossary**: 데이터 카탈로그 및 비즈니스 용어집 연동
4. **K9**: 그래프 시맨틱 쿼리 및 연계 동작
5. **MCL**: 최신/이력 변경 로그 추적
6. **AUTO General**: 내부 검색을 사용하지 않는 일반 답변과 GENERAL route 검증
   * Readiness 통과 후 동일 실행 내의 증적을 재사용하여 추가 검증 (AUTO Search, Direct VECTOR, AUTO GRAPH, Direct GRAPH, Preview).
   * 동적 테이블/리니지 대상 범위 한정 증적 수집 (비어있거나 무관한 증적 PASS 처리 금지).
   * 설정/인증 실패 등 치명적 오류 발생 시 20분 대기 없이 즉각 중단.
   * `RETENTION_EXPIRED` 완화 상태는 명확한 이력 사유가 확인된 경우에만 수용.

## 검증 기록과 기능 연결

[PREP 계약·변경·검증 기록](deploy/dev_deploy/refactor-acceptance.md)을 먼저 확인하십시오.
원본 추출 목록은 [include](deploy/dev_deploy/source-include.manifest), [exclude](deploy/dev_deploy/source-exclude.manifest), [provenance](deploy/dev_deploy/source-provenance.json)에 보존합니다.
현재 launcher는 이 목록이나 dev checkout을 읽지 않습니다. 현재 source commit → git archive build input → image → ignored deployment receipt로 연결됩니다.

과거 FastAPI/OIDC와 `poc` 개발용 배포 지침은 **legacy**입니다. 현재 PREP 명령으로 사용하지 마십시오.
기존 `POC_*` 입력 키, `/poc-api` 및 runtime-config URL, DB `poc_*` 식별자, migration 파일명,
cookie/storage/cache/scope와 외부 오류·Kafka/Compose 식별자는 운영 호환성 때문에 남겨 두었습니다.

로컬 개발 점검: `npm ci --ignore-scripts`, `npm run build`, `npm run typecheck`, `npm run lint`.
원본 `.env.prep`의 내용을 편집하지 않습니다. 기존 `.env.prep.runtime`와 필요한 `.env.prep.optional`,
CA 파일은 운영 입력이므로 소스와 함께 삭제하지 않습니다. 기존 DB의 비밀번호를 새로 만들지 않습니다.

기존 관리자 암호는 초기화하지 않습니다. 대화형 deploy는 기존 암호를 숨김 입력받으며, 비대화형 실행에서는 `--admin-password-file`로 기존 보안 파일을 지정하십시오. provider `.env.prep`의 값을 다시 작성할 필요는 없습니다.
