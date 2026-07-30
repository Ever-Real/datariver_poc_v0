# GX 기반 품질관리 고도화 PRD 및 실행 체크리스트

- 상태: **Phase 1 도메인·권한·PostgreSQL 구현 완료 — 외부 artifact gate는 비활성 보류**
- 결정 문서: [ADR-0077](adr/0077-governed-gx-quality-control-plane.md)
- 적용 범위: Task 1 품질관리 대시보드, DataHub Profile, typed Rule, GX 실행 및 결과 시각화
- 비적용 범위: Task 2 거버넌스 문서, GX Data Docs, MinIO 결과 저장, Oracle 실행,
  DataHub 품질 Aspect write-back

이 문서는 Task 1의 승인된 설계를 실행 가능한 요구사항과 phase gate로 고정한다. Phase 0은
문서·계약 단계였고, Phase 1은 Quality 도메인/권한/데이터베이스 control plane을 구현했다.
GX worker, DataHub Profile projection, API, DAG와 React 대시보드는 이후 Phase 소유이며 아직
구현된 것으로 간주하지 않는다.

## 1. 현재 상태와 확인된 공백

- `frontend/src/features/quality/QualityPage.tsx`는 계약 부재를 명시하는 unavailable 화면이다.
- `backend/src/datariver/infrastructure/datahub/http.py`의 asset detail은 최신 profile에서
  `rowCount`, `columnCount`, `sizeInBytes`, `timestampMillis`만 읽는다.
- 현재 query는 `FULL_TABLE_SNAPSHOT`과 `SAMPLE`을 함께 필터링하면서 `partitionSpec`을 반환하지
  않아 limit-one 결과의 full/sample provenance를 증명하지 못한다.
- `infra/datahub/recipes/semiconductor_postgres.yml`은 `profile_table_level_only: true`와
  `include_field_null_count: true`를 함께 설정한다. 고정된 DataHub v1.6 설정 validator는 이
  조합을 거부하므로 현 recipe는 field-profile 실행 증거가 아니다.
- Quality 도메인, `quality` schema, 전용 Action, source manifest/resolver, GX dependency,
  quality worker, Airflow quality DAG와 품질 API가 없다.
- 현재 외부 서비스 DB profile은 runtime 설정원이 아니라 audit-only다. GX source registry로
  재사용하지 않는다.

## 2. 기능·보안·UI 요구사항

### 기능 요구사항

- `FR-DQ-001 — Authorized quality snapshot`: 현재 Workspace와 권한 범위에 한정된 품질
  현황, 상태 분포, score, pass rate와 coverage를 조회하고 `as_of`, 정책/source version,
  freshness와 partial 상태를 함께 제공한다.
- `FR-DQ-002 — Typed versioned rules`: 사용자는 서버가 허용한 RuleKind와 typed parameter로
  Rule Set을 제안·버전업·독립검토·활성화·폐기한다. 기존 버전은 수정하거나 삭제하지 않는다.
- `FR-DQ-003 — Durable quality execution`: 수동/예약 실행은 PostgreSQL canonical Run과
  outbox로 접수하고 별도 quality worker가 실행한다. Airflow/GX/provider 응답만으로 완료나
  통과를 선언하지 않는다.
- `FR-DQ-004 — Bounded result drill-down`: Rule, Run, expectation 결과와 이슈를 권한
  선필터 후 cursor page로 조회한다. 원시 source/provider 위치나 실패행은 반환하지 않는다.
- `FR-DQ-005 — Profile provenance`: profile과 품질 판정은 local asset/field, rule version,
  target/schema/source binding, DataHub profile/source watermark, compiler/GX version 및
  score-policy hash에 결합한다.

### 보안 요구사항

- `SEC-DQ-001`: 전용 Quality Action, default deny, deny precedence, ABAC, maker-checker,
  hardware WebAuthn과 forced workspace RLS를 적용한다.
- `SEC-DQ-002`: list, card, score, count, facet, trend와 cursor도 detail과 같은 permitted
  asset base relation을 사용하여 숨겨진 자산/분류/분모를 노출하지 않는다.
- `SEC-DQ-003`: arbitrary GX JSON/YAML, expectation/kwargs, SQL, Python, GraphQL, URL,
  datasource, BatchRequest, row condition과 plugin/module path를 API 계약에서 제외한다.
- `SEC-DQ-004`: sample/top/distinct values, unexpected row/value/index, generated SQL,
  provider exception과 connection 정보는 수집·저장·응답·queue/cache/log/trace에 남기지 않는다.
- `SEC-DQ-005`: Airflow scheduler와 GX executor는 별도 service identity/Action/DB role을
  사용하고 API/Airflow에는 source-database credential을 주지 않는다. DataHub read token은
  기존 fixed adapter 또는 별도 Catalog Profile collector만 보유하며 browser/Airflow/quality
  worker와 공유하지 않는다.

### 비기능 요구사항

- `NFR-DQ-REL-001`: execution state와 quality outcome을 분리하고 lease/retry/cancel/crash
  중 canonical result가 하나만 남도록 fence한다.
- `NFR-DQ-PERF-001`: list page는 기본 25/최대 100, trend는 최대 90 points, overview JSON은
  1 MiB 이하이며 raw 결과를 브라우저에서 집계하지 않는다.
- `NFR-DQ-ACC-001`: Quality UI는 WCAG 2.2 AA, keyboard-only, 색상 비의존 상태, chart와
  동등한 표, 명시적 loading/empty/error/forbidden/partial/stale/unknown 상태를 제공한다.
- `NFR-DQ-PORT-001`: GX와 PostgreSQL driver의 exact frozen artifact가 Mac arm64와
  Linux/WSL amd64에서 같은 lock/hash/SBOM으로 검증되지 않으면 worker capability를 켜지 않는다.

### UI 요구사항

- `UI-DQ-001`: `현황 / 룰 관리 / 실행 이력 / 품질 이슈`를 stable URL state로 제공한다.
- `UI-DQ-002`: score, pass rate, status와 threshold는 서버 계산값만 표시한다.
- `UI-DQ-003`: availability, freshness, execution state, quality outcome을 서로 다른 축으로
  표시하고 `SUCCEEDED`를 `PASS`로 해석하지 않는다.
- `UI-DQ-004`: 목록은 server cursor page, 상세은 선택 후 lazy fetch를 사용한다.
- `UI-DQ-005`: Rule editor는 대상 → typed rule → severity/실행 정보 → 검토 순서, dirty-close,
  ETag 충돌과 maker-checker 상태를 제공한다.
- `UI-DQ-006`: 선택한 active Run만 bounded polling하고 전체 Dashboard를 초 단위로
  무기한 polling하지 않는다.
- `UI-DQ-007`: contract/profile/source/권한이 준비되지 않으면 예시 점수나 fake 결과를
  만들지 않고 `UNAVAILABLE`을 표시한다.
- `UI-DQ-008`: tablist/tabpanel, focus trap/restore, 오류 연결, chart 대체 표와 수동
  screen-reader/browser acceptance를 제공한다.

## 3. v1 Rule 계약

### Rule Set과 Version

- Rule Set은 하나의 current local DATASET을 대상으로 하는 stable aggregate다.
- 편집은 새 immutable Rule Set Version과 Rule Definitions를 만든다.
- 활성화 원자성은 개별 Rule이 아니라 Rule Set Version 전체에 둔다.
- Version lifecycle은 `PROPOSED -> APPROVED -> ACTIVE -> SUPERSEDED`,
  `PROPOSED -> REJECTED`, `ACTIVE -> REVOKED`다.
- Rule Set archive는 논리 상태 전이이며 버전·검토·실행·결과를 삭제하지 않는다.
- archive는 전용 Action/If-Match/idempotency를 요구하고 ACTIVE Version revoke 후에만
  가능하다. evidence를 삭제하지 않는 reversible visibility 전이라 v1 추가 WebAuthn 대상은
  아니다.
- 한 Rule Set에는 ACTIVE version 하나만 존재한다.
- 활성화 가능한 Version은 적어도 하나의 Rule Definition을 포함한다.
- author와 reviewer/activator는 서로 다른 활성 인간이다.
- activate/revoke는 `If-Match`, `Idempotency-Key`와 최근 hardware WebAuthn을 요구한다.
- Version은 `MANUAL_ONLY` 또는 서버가 제공한 deployment-approved schedule
  profile ID/version/hash만 선택한다. 브라우저 cron 입력은 없다.
- schedule profile은 closed `FIXED_INTERVAL_V1`(bounded integer seconds, UTC anchor) 또는
  `DAILY_LOCAL_TIME_V1`(typed wall-clock time, IANA timezone, DST ambiguous
  `EARLIER_OFFSET/LATER_OFFSET`, nonexistent `SKIP/SHIFT_FORWARD`)로 정규화한다. late grace,
  missed-window policy, bounded catch-up cap, evaluator contract와 tzdb artifact version/hash를
  함께 PostgreSQL schedule history에 pin한다. Airflow는 이를 계산하거나 소유하지 않는다.
- cadence/timezone/catch-up/workload profile 변경은 scheduler row 편집이 아니라 새 Rule Set
  Version과 독립 활성화를 요구한다.
- activation은 기존 ACTIVE version/schedule supersede, 새 version/schedule activation,
  audit/outbox를 한 transaction으로 수행한다. revoke/archive는 schedule을 `INACTIVE`로
  만들며 v1에는 개별 schedule pause/resume 명령이 없다.
- Schedule row는 Rule Set Version별 immutable payload/history이며 Rule Set별 ACTIVE partial
  UQ를 가진다. mutable state/due cursor는 fixed function만 바꾸고 scheduled Run은
  workspace/schedule Version/canonical UTC window key로 unique하다.
- missed-window enum은 `SKIP_MISSED_V1`, `LATEST_ONLY_V1`,
  `CATCH_UP_OLDEST_FIRST_V1`로 닫는다. dispatch DB-time cutoff가 `due_at + late_grace`를
  지났을 때 SKIP은 해당 window를 evidence로 기록하고 advance한다. LATEST_ONLY는 cutoff
  이하 newest 하나만 만들고 older window를 skipped로 기록한다. CATCH_UP은
  `(due_at, schedule_id, window_key)` oldest-first로 per-schedule/global cap까지 만들고 나머지는
  다음 dispatch에 due 상태로 남긴다. receipt는 cutoff와 skipped count/range hash를 pin한다.
  late-grace는 non-negative bounded duration이며 UTC window key를 바꾸지 않는다.

### RuleKind

| RuleKind | v1 의미 | Null 처리 | capability |
|---|---|---|---|
| `NOT_NULL` | 평가 대상 행의 값이 모두 non-null | null 한 건이라도 실패; `mostly` 없음 | PostgreSQL-first |
| `RANGE` | 숫자/date/timestamp column의 non-null 값이 typed min/max 안에 존재 | null은 RANGE 분모에서 제외; null 금지는 별도 `NOT_NULL` | PostgreSQL-first |
| `REGEX` | textual column의 non-null 값에 대한 명시적 full-match | null은 제외; null 금지는 별도 `NOT_NULL` | 안전한 bounded engine 증명 전 disabled |

`RANGE`는 같은 논리 타입의 `min_value`, `max_value`와 명시적 `inclusive_min`,
`inclusive_max`를 요구하며 `min <= max`여야 한다. 문자열 숫자/날짜의 암묵 변환은 금지한다.

`REGEX`는 linear-time-compatible grammar와 connector/compiler 전체 경계가 검증되어야 한다.
backreference, lookaround, inline engine flag 또는 backtracking execution을 허용하지 않는다.
안전성을 증명하지 못한 배포는 Rule definition capability에서 이를 제공하지 않는다.

Severity는 `BLOCKING` 또는 `ADVISORY`다. Rule parameter와 severity는 사용자가 typed 계약으로
정하며 portable source에 업무값을 기본 설정하지 않는다.

### 금지 입력

브라우저와 public API는 다음을 제출할 수 없다.

- DataHub URN, schema/table/provider identifier;
- GX expectation class/name, raw kwargs, suite/checkpoint JSON/YAML;
- datasource/connection URL, secret reference, BatchRequest;
- SQL, GraphQL, Python, callable/import/plugin path, row condition;
- sample/full 결과를 바꾸는 임의 GX runtime option.

## 4. Score, 상태와 집계 universe

### 결과 단위

Rule 결과는 `PASS`, `ADVISORY_FAIL`, `BLOCKING_FAIL` 중 하나다. `SUCCEEDED` completion은
활성 Version의 모든 Rule Definition에 대해 정확히 하나의 sanitized 결과가 있고
`evaluated_rule_count == rule_definition_count > 0`일 때만 가능하며 Run outcome은
`PASS/WARN/FAIL` 중 하나다. 실행 불가, 취소, stale binding, sanitizer 실패와 infrastructure
failure는 Rule 품질 실패로 위조하지 않고 non-success Run의 `quality_outcome=UNKNOWN`으로
남긴다.

### v1 score policy

고정 formula ID는 `UNWEIGHTED_RULE_PASS_RATE_V1`이다.

```text
evaluated = passed + advisory_failed + blocking_failed
score = pass_rate = 100 * passed / evaluated
```

- Dashboard aggregate에서 기여한 successful Rule 결과가 0이면 score/pass rate는 `null`,
  outcome은 `UNKNOWN`이다. 빈 Version이나 result가 누락된 Run을 `SUCCEEDED`로 만들 수 없다.
- `blocking_failed > 0`이면 `FAIL`이다.
- blocking failure 없이 `advisory_failed > 0`이면 `WARN`이다.
- 하나 이상 평가되고 모두 통과하면 `PASS`다.
- 응답은 numerator/denominator/unknown count, formula/score-policy ID·version·hash,
  aggregation grain과 `as_of`를 포함한다.
- weight 또는 업무 threshold가 필요하면 새 score-policy version과 별도 승인을 요구한다.

### Dashboard universe

- Current snapshot은 `as_of` 시점의 권한 범위 내 ACTIVE Rule Set마다 current ACTIVE
  `rule_set_version_id`와 일치하는 최신 terminal Run 하나를 고른다. 새 Version은
  SUPERSEDED Version의 결과를 상속하지 않는다. 선택 Run이 `SUCCEEDED`일 때만 해당
  Version의 Rule Definition count를 score에 반영한다.
- 최신 terminal Run이 `FAILED/STALE/CANCELLED`이거나 terminal Run이 없으면 해당 Rule Set은
  UNKNOWN이다. 과거 `SUCCEEDED`가 더 최신의 실패/취소/stale 상태를 숨길 수 없다.
- `unknown_rule_set_count`와 coverage는 Rule Set 단위다. passed/advisory-failed/
  blocking-failed/evaluated count는 선택된 `SUCCEEDED` Run의 Rule Definition 단위다.
- coverage 분모는 보이는 ACTIVE Rule Set 수이고 분자는 최신 `SUCCEEDED` 평가가 있는 Rule
  Set 수다.
- Trend는 선택 기간의 `completed_at` bucket이며 current snapshot과 섞지 않는다.
- 취소/인프라 실패/stale/미실행은 pass-rate 분모에서 제외하되 unknown/unavailable count로
  별도 표시한다.
- 카드와 표에는 `권한 범위 기준`을 표시한다.

### 상태 축

- Run: `QUEUED`, `RUNNING`, `RETRY_WAIT`, `CANCEL_REQUESTED`, `SUCCEEDED`, `FAILED`,
  `STALE`, `CANCELLED`
- Quality outcome: `PASS`, `WARN`, `FAIL`, `UNKNOWN`
- Section availability: `AVAILABLE`, `EMPTY`, `UNAVAILABLE`
- Freshness: `FRESH`, `STALE`
- Overview: `COMPLETE`, `PARTIAL`, `UNAVAILABLE`

`EMPTY`는 권한 범위 내 eligible data가 0건인 성공 응답이다. `UNAVAILABLE`은 계약/권한/
dependency 문제로 계산하지 못한 상태다. `PARTIAL`은 성공 section을 유지한 채 일부 section만
unavailable인 응답이다. stale profile은 읽기 전용 context이며 새 활성화나 실행 근거가 아니다.

## 5. Canonical data와 runtime 계약

### 목표 Quality schema

| Table | 계약 |
|---|---|
| `quality.rule_sets` | stable local asset/typed hold root, `QUALITY_RULE` policy/deadline/hold pin, logical archive |
| `quality.rule_set_versions` | immutable target/source-connection/workload/compiler/GX/score-policy/schedule와 `QUALITY_RULE` retention/hold binding |
| `quality.rule_definitions` | version/ordinal unique typed RuleKind, target field, severity, canonical hash |
| `quality.rule_reviews` | distinct-human `APPROVE/REJECT` decision and assurance evidence; activation/revocation은 fixed command evidence |
| `quality.rule_command_events` | fixed transition function이 기록하는 activation/revoke/archive/supersede assurance evidence |
| `quality.rule_schedules` | Rule Set Version별 immutable normalized schedule/evaluator/tzdb payload, ACTIVE partial UQ, next due/window/catch-up cursor |
| `quality.validation_runs` | exact rule/source/workload/security/DataHub-context/score/retention pins, retry parent, current claim/lease/source-start/access-deadline fence, separate execution/outcome |
| `quality.validation_attempts` | attempt/lease epoch/token hash/worker/source-start/terminal evidence |
| `quality.expectation_results` | run/rule unique normalized counts/ratios/hash; no raw values |
| `quality.run_events` | append-only sequence/state/reason/evidence hash |
| `quality.dispatch_call_receipts` | run-independent Airflow replay, bounded schedule/dispatch contract와 workspace-scoped `QUALITY_AUDIT` retention/hold pin |
| `quality.dispatch_run_links` | dispatch receipt와 생성된 Run의 immutable ordinal mapping |
| `quality.execution_call_receipts` | exact Run claim에 결합한 worker call replay |

### Catalog profile projection

| Table | 계약 |
|---|---|
| `catalog.asset_profile_snapshots` | local asset, deterministic identity, normalized profile kind, profiled/first/last-observed times, allowlisted metrics, provider/source/payload hash, optional keyed partition fingerprint, `QUALITY_PROFILE` retention/hold binding |
| `catalog.column_profile_metrics` | snapshot/field unique null/unique counts and proportions plus metric availability |

모든 protected row는 `workspace_id`, composite tenant FK, forced RLS를 가진다. immutable
version/review/result/event/call receipt에는 ordinary app UPDATE/DELETE 권한이 없다. 외부 provider
identifier는 local primary key가 되지 않는다. Version payload는 immutable이고 lifecycle
column은 fixed `SECURITY DEFINER` transition function만 바꾼다. ordinary role에는 direct
Version UPDATE 권한이 없다.

Profile snapshot identity는 workspace/local asset, profiled time, normalized kind,
provider/query/config/source-watermark hash, normalized allowlisted payload hash와 필요한 keyed
partition fingerprint의 canonical hash다. 같은 identity 재관측은 fixed collector function이
`last_observed_at`만 전진시키고 metric 변화 또는 HMAC key rotation은 새 snapshot을 만든다.

### DataHub Profile allowlist

v1은 table의 row/column/byte count와 profiled time, field의 path/null count/null proportion/
unique count/unique proportion만 정규화한다. non-null count는 동일한 proven full snapshot의
row/null count가 있을 때만 파생한다.

다음 값은 v1 GraphQL 요청·projection·API에서 금지한다.

- `sampleValues`, `distinctValueFrequencies`, top values와 example rows;
- min/max/mean/median/stdev, quantiles, histogram;
- 원시 partition name/spec 또는 provider response.

별도 fixed DataHub v1.6 `DatasetProfile` query는 존재하지 않는 `profileType`을 요청하지 않고
`partitionSpec { type partition }`을 요청하며 기존 version enforcement, bulkhead/circuit
breaker와 8 MiB response cap을 유지한다. fixed parser는 `FULL_TABLE`과 canonical marker를
FULL, `QUERY`와 v1.6 exact SAMPLE marker/그 sample-row suffix를 SAMPLE, valid bounded
`PARTITION`을 PARTITION, 그 밖의 valid `QUERY`를 QUERY, 누락·미지원·모호한 입력을 UNKNOWN으로
정규화한다. bounded raw `partition`은 parser 안에서만 일시적으로 읽는다. PARTITION/QUERY에
한해 deployment-owned `file:` HMAC key로 SHA-256 fingerprint/key ID를 만들 수 있다. DTO를
만들기 전에 raw 문자열을 폐기하며 unkeyed digest는 금지한다. projection에는 keyed
fingerprint/key ID만 허용되고 API/cache/log/trace/error에는 raw partition name/spec이 없다.
oversize, contract drift, ambiguous provenance는 `PARTIAL/UNAVAILABLE`이다.

### GX dependency와 execution

- 승인 compiler/runtime target: `great-expectations==1.19.1`
- 지원 Python: DataRiver baseline 3.12
- v1 datasource: PostgreSQL full-table validation only
- 미지원: Oracle, sampling, GX Cloud, GX Data Docs, custom Expectations/Actions/plugins,
  DataHub result write-back
- GX는 quality-worker dependency profile에만 추가한다.
- API/Airflow image와 dependency graph에는 GX를 넣지 않는다.
- Phase 1 dependency 변경 전 exact lock, Apache-2.0 및 모든 transitive license, SBOM,
  vulnerability, PostgreSQL driver, arm64/amd64 offline artifact를 검증한다.

### Source manifest와 worker

deployment-owned source manifest는 local asset/System/platform을 opaque connection-profile
ID/version/config hash와 매핑한다. worker manifest만 allowlisted endpoint와 `file:` secret을
해석한다. API/DB response/outbox/log에는 endpoint, secret/ref 또는 connection string을 넣지 않는다.
별도 approved workload-profile ID/version/hash가 전체 source-access hard timeout,
per-statement timeout, cancel/close margin, pool/concurrency와 scan budget을 pin한다. 변경은 새
Rule Set Version/독립 activation을 요구한다.

DataHub Profile collector는 별도 OIDC Subject, `catalog.profile.collect`, NOBYPASSRLS role과
fixed Catalog projection function만 사용한다. DataHub read token은 source DB secret과 다른
credential이며 collector/API fixed adapter 밖으로 전달되지 않는다. PARTITION/QUERY
fingerprint가 필요하면 collector만 deployment-owned HMAC key ID와 mounted `file:` key를
해석하며 raw key/partition은 DB/API/log에 없다.

실행 전 다음 운영 입력이 모두 있어야 한다.

- exact source connection mapping과 read-only principal/secret owner;
- source owner가 승인한 full-scan 시간대와 workload-profile ID/version/hash로 pin된 전체
  source-access/per-statement timeout, cancel/close margin, concurrency, connection-pool과
  cost/row/byte budget;
- egress host/port/scheme와 DNS/IP 정책;
- schedule cadence/timezone/DST policy, evaluator/tzdb artifact;
- schedule별 catch-up cap과 dispatch별 `max_due_schedules/max_created_runs`;
- profile freshness SLA;
- `QUALITY_RULE/QUALITY_RESULT/QUALITY_AUDIT` 및 Phase 2 `QUALITY_PROFILE` policy
  ID/version/hash/deadline, typed Legal Hold target와 hold generation/hash binding.

portable source는 이 값을 추측하거나 기능을 자동 활성화하지 않는다.

Run은 current attempt ID, lease epoch/token hash/owner, `lease_until`, `heartbeat_at`,
`next_attempt_at`, `source_started_at`을 가진다. source statement 직전 DB time으로 lease를
갱신하고 source-start fence와 `source_access_deadline`을 고정한다. 첫 GX statement부터
source transaction/connection close까지 전체 window의 승인된 hard timeout과
cancel/reconciliation/completion margin의 합은 frozen remaining lease보다 작아야 한다.
그 window에서는 lease renewal을 금지한다. 모든 source statement 직전에 current
epoch/token/expiry를 다시 확인하고 source-server `statement_timeout`도 남은 deadline/lease
안에 둔다. reclaim은 DB time이 `lease_until`을 지난 뒤 expired attempt를 `SUPERSEDED`로
원자 전이한 후에만 새 epoch를 만들 수 있다. hard/per-statement timeout과 connection-close
증명이 없으면 새 source query를 시작하지 않는다.

Attempt state는 `RUNNING/SUCCEEDED/RETRYABLE_FAILED/FAILED/STALE/CANCELLED/SUPERSEDED`로
닫는다. `QUEUED` Run은 current attempt가 없고, `RUNNING` 및 in-flight
`CANCEL_REQUESTED`는 `RUNNING`, `RETRY_WAIT`는 `RETRYABLE_FAILED`,
`SUCCEEDED/FAILED/STALE` Run은 같은 이름의 current attempt를 가리킨다. `CANCELLED`는
first claim 전이면 attempt가 없고, in-flight 취소면 `CANCELLED`, retry-wait 취소면
`RETRYABLE_FAILED`를 가리킨다. reclaim 후 `SUPERSEDED`는 current가 아니며 canonical
results는 `SUCCEEDED` current attempt에만 존재한다.

Airflow dispatch receipt는 Run FK 없이 workspace/service Subject/call-ID hash에 결합하여
no-work와 multi-run replay를 표현한다. dispatch는 deterministic keyset에서 배포 승인
`max_due_schedules_per_dispatch` 이하를 잠그고
`max_created_runs_per_dispatch` 이하의 scheduled-window unique Run/outbox만 만든 뒤,
처리한 `next_due_at` advance와 bounded result hash/receipt를 한 transaction으로 commit한다.
두 값은 source safe hard maximum 이하의 필수 runtime 입력이며 portable capacity default가
없다. worker execution receipt는 별도로 exact Run/attempt/lease에 결합한다.

## 6. API 계약 초안

모든 경로는 `/api/v1` 아래에 있으며 sensitive read는 `private, no-store`다.

- `GET /quality/capability`
- `GET /quality/rule-definitions`
- `GET /quality/overview`
- `GET /quality/assets`
- `GET /quality/assets/{asset_id}`
- `GET|POST /quality/rule-sets`
- `GET /quality/rule-sets/{rule_set_id}`
- `POST /quality/rule-sets/{rule_set_id}/versions`
- `POST /quality/rule-sets/{rule_set_id}/versions/{version_id}/reviews`
- `POST /quality/rule-sets/{rule_set_id}/versions/{version_id}/activations`
- `POST /quality/rule-sets/{rule_set_id}/revocations`
- `POST /quality/rule-sets/{rule_set_id}/archive`
- `GET|POST /quality/runs`
- `GET /quality/runs/{run_id}`
- `GET /quality/runs/{run_id}/results`
- `POST /quality/runs/{run_id}/cancellations`
- `POST /quality/runs/{run_id}/retries`
- `GET /quality/operations/runs`
- `GET /quality/audit/events`
- service-only `POST /quality/internal/dispatch`

### Route와 Action

| Route group | Required Action |
|---|---|
| capability | authenticated active membership; 응답에서 permitted Action을 별도 산출 |
| rule definitions, overview, assets, Rule Sets, Runs, results read | `quality.read` |
| profile field/readiness read | `quality.read` + `quality.profile.read` |
| Rule Set/version create | `quality.rule.propose` |
| review decision | `quality.rule.review` |
| activation / revocation | `quality.rule.activate` / `quality.rule.revoke` |
| logical archive | `quality.rule.archive`; owner/author 또는 governance admin이며 ACTIVE version은 먼저 revoke |
| manual run request / cancellation / retry | `quality.run.request` / `quality.run.cancel` / `quality.run.retry` |
| operations / audit read | `quality.operations.read` / `quality.audit.read` |
| internal dispatch | service-only `quality.dispatch` |

manual requester는 자신의 non-terminal manual Run만 cancel할 수 있고 operations 권한자는
scheduled/other Run을 cancel할 수 있다. Retry는 기존 terminal Run을 다시 열지 않는다.
`FAILED/STALE/CANCELLED` predecessor에 대해서만 동일 immutable Rule Set Version을 pin한 새
Run과 `retry_of_run_id`를 만들며 current authorization/target/source/schedule/workload/
retention을 모두 재검증한다. `SUCCEEDED`는 retry할 수 없다.

### Mutation status와 concurrency

| Mutation | Success | Required fence |
|---|---|---|
| create Rule Set | `201 + Location + ETag` | `Idempotency-Key` |
| create Version | `201 + Location + ETag` | parent `If-Match` + `Idempotency-Key` |
| review | `201 + Location + ETag` | version `If-Match` + `Idempotency-Key` |
| activate/revoke/archive | `200 + ETag` | aggregate `If-Match` + `Idempotency-Key`; activate/revoke는 WebAuthn |
| request Run | `202 + Location` | `Idempotency-Key` |
| cancel/retry Run | `202 + Location` | Run `If-Match` + `Idempotency-Key` |
| dispatch | `200` exact replay | authenticated service call ID + canonical request hash |

필수 precondition 누락은 `428`, stale ETag는 `412`, lifecycle/idempotency 의미 충돌은 `409`다.
성공 응답은 Airflow DAG/URL, DataHub cursor/URN, source coordinate와 provider exception을
노출하지 않는다.

List는 기본 25/최대 100 keyset page다. Opaque cursor는 Workspace, permission fingerprint,
policy/generation, profile/source/rule watermark, normalized filter/sort/limit와 contract version에
결합한다. malformed/cross-scope/stale cursor는 fail closed한다.

`GET /quality/assets`는 빈 `q`를 허용하고 non-empty `q`는 NFC/trim/case normalization 후
2~100자만 허용한다. filter는 approved System/Domain/lifecycle/profile-readiness만, sort는
allowlist만 사용하며 최대 100건이다. 응답은 local UUID, bounded display name,
platform/database/schema, classification, lifecycle와 profile-readiness만 포함하고 URN/source
coordinate는 제외한다. `GET /quality/assets/{asset_id}`는 server-owned field ID, bounded
display path/type, schema/source version을 제공한다. stale/deleted historical target은 권한이
있으면 과거 evidence read에만 사용할 수 있고 새 Rule/activation target이 될 수 없다.

Capability는 `read_access`, `profile_readiness`, `rule_authoring`, `activation`,
`manual_execution`, `scheduling`, `operations`를 독립 축으로 반환한다. `read_access=DENIED`
일 때만 모든 Quality resource fetch를 막고 캐시를 제거한다. DataHub profile 장애는 profile
section/new activation만 unavailable로 만들고 과거 Run/Rule read를 지우지 않는다.
worker/source 장애는 새 실행을 막되 과거 read를 유지하며 scheduling 장애는 schedule
activation만 막는다. 응답은 supported Rule contract version, opaque `cache_scope`,
`observed_at`, `valid_until`과 sanitized reason code를 포함한다. `valid_until`은 server
database time 기준 최대 30초다.

### Overview response

Overview는 `overall_state`, `as_of`, `authorization_valid_until`, 현재 Rule Set 단위
`active_rule_set_count/evaluated_rule_set_count/unknown_rule_set_count`, Rule Definition 단위
`passed/advisory_failed/blocking_failed/evaluated_rule_count`, `score_basis_points`와 coverage를
반환한다. `score_basis_points`는 `0..10000 | null` 정수이며
`10000 * passed / evaluated`를 `ROUND_HALF_UP`으로 반올림한다. v1 Score와 pass rate는 같은
하나의 KPI이며 별도 중복 카드로 표현하지 않는다.

각 section은 독립 `availability`, `freshness`, `observed_at`, `stale_at`,
`failure_code`를 가진다. 일부 dependency 실패는 성공 section을 유지하는 HTTP `200`
`PARTIAL`이며 전체 권한 거부와 동일하게 취급하지 않는다. trend는 최대 90 points다.
small-cell 정책이 승인되지 않은 v1은 classification/System/Domain별 bucket, cohort 또는
distribution output을 반환하지 않는다. 이 값들은 승인된 asset-base 필터 입력일 수만 있다.

## 7. React dashboard 계약

### 정보 구조

1. `현황`: 단일 Score/pass-rate KPI, coverage, PASS/WARN/FAIL/UNKNOWN, trend, 최근 실패
2. `룰 관리`: Rule Set/version/lifecycle/reviewer와 typed wizard
3. `실행 이력`: Run state와 quality outcome을 분리한 cursor grid
4. `품질 이슈`: asset/field/Rule별 normalized 실패 집계

Overview는 server aggregate 한 번으로 받고 raw expectation collection을 브라우저에서
재집계하지 않는다. 1차 시각화는 accessible CSS/inline SVG와 같은 수치의 표를 사용하고 신규
chart library는 실제 요구와 bundle 측정 후 별도 승인한다.

### Polling과 cache

- 명시적으로 선택하거나 방금 접수한 non-terminal Run만 `1 -> 2 -> 5 -> 10초` backoff로
  최대 20회/visible-active 120초 polling한다. 최초 immediate read는 20회 중 첫 read다.
- hidden tab에서는 timer/read와 120초 elapsed 계산을 모두 정지한다. visible 복귀 시 남은
  budget 안에서 한 번 즉시 refresh한 뒤 backoff를 계속한다. bounded `Retry-After`는 다음
  interval을 늦출 수 있지만 20회/visible-active 120초 cap을 늘리지 않는다.
- terminal, unmount, Workspace/subject/security epoch/authorization revision/cache-scope/Run
  변경, `403/404/409/429`에서 중지하고 late response를 폐기한다.
- polling 종료는 Run 종료가 아니며 수동 refresh 상태를 표시한다.
- terminal 후 Run detail/list/result와 Overview만 invalidate한다.
- Dashboard 전체 polling과 SSE는 v1 범위가 아니다.
- React Query key는 Workspace, subject, security epoch, authorization revision,
  capability cache scope, resource, normalized filter, allowlisted sort, cursor와 limit를 포함한다.
- capability `valid_until` 만료 시 모든 Quality 화면을 먼저 숨기고 in-memory Quality cache를
  purge한 뒤 capability를 재검증한다. resource `staleTime`은 authorization lease를 넘지
  못한다. focus/manual refresh와 subject/workspace/epoch/revision 변경,
  `401/403/404/stale-cursor`도 동일하게 abort/purge한다. 지속 visible client의 권한 취소
  표시 상한은 30초다.
- URL state allowlist는 `qualityTab`, 승인된 filter, `ruleSetId`, `runId`뿐이다. source
  coordinate, permission fingerprint, cursor, secret, raw failure 또는 Rule draft는 URL에
  넣지 않으며 route/Workspace 변경 시 허용되지 않은 state를 제거한다.
- Quality result/rule draft/permission을 browser storage에 영구 저장하지 않는다.

### 접근성

- 네 탭은 `tablist/tab/tabpanel`, roving tabindex와 방향키/Home/End를 제공한다.
- 상태는 색상 외 텍스트/아이콘/수치를 제공하고 chart는 caption과 동등한 표를 제공한다.
- chart/table은 동일 caption, 명시적 table header와 horizontally scrollable region을
  제공하며 table row action은 keyboard focus와 Enter/Space를 지원한다.
- Rule dialog는 focus trap/Escape/focus restore/dirty-close를 제공한다.
- 최초 loading과 background refresh를 구분하고 `aria-busy`, 중요한 오류는 `role=alert`,
  field 오류는 `aria-invalid`와 설명을 연결한다.
- polling progress는 중요한 상태 전이만 live region에 알리고 매 poll마다 반복 발화하지
  않는다. `prefers-reduced-motion`에서는 chart/상태 animation을 제거한다.
- 실제 percentage가 없으면 progressbar를 만들지 않는다.
- 200% 확대와 320 CSS px에서 wide table을 제외한 page-level 양방향 scroll이 없어야 한다.
- 자동 semantic test는 keyboard/screen-reader/target browser 수동 검증을 대체하지 않는다.

## 8. Phase 실행 체크리스트

### Phase 0 — 계약·ADR·운영 결정

- [x] 현행 Quality/DataHub/Airflow/source 설정 공백을 source 기준으로 확인한다.
- [x] ADR-0077로 canonical ownership, worker/Airflow/credential, Rule, profile, result,
  score, retention과 MinIO 비사용 경계를 승인한다.
- [x] GX target을 exact `1.19.1`, PostgreSQL/full-table first로 고정하고 Oracle/sampling/
  Data Docs/custom plugin을 disabled로 둔다.
- [x] Rule lifecycle, suite-version activation 원자성, maker-checker/WebAuthn과 전용 Action을
  고정한다.
- [x] `NOT_NULL`, typed `RANGE`, safety-gated `REGEX` semantics를 고정한다.
- [x] score formula, current snapshot/trend universe와 execution/outcome/freshness 상태를 고정한다.
- [x] DataHub Profile allowlist와 sample/distribution 금지를 고정한다.
- [x] 목표 데이터 모델, API/UI/polling/accessibility 계약을 작성한다.
- [x] retention/Legal Hold pins, exact lease/source-timeout fence, schedule calculation inputs,
  no-work/multi-run dispatch receipt와 새-Run retry semantics를 고정한다.
- [x] source workload/egress/secret/profile freshness/retention을 deployment operating input으로
  분리하고 누락 시 fail closed하도록 고정한다.
- [x] 기존 PRD/Architecture/Data Model/Security/Test Strategy와 controlled index를 갱신한다.
- [x] Data Engineer, Backend/DBA, Frontend, Security/Governance 읽기 교차검토를 반영한다.

**Exit:** 문서/결정은 승인되었고 사용자의 연속 실행 지시에 따라 Phase 1에 진입했다.

### Phase 1 — 도메인·권한·PostgreSQL

- [ ] exact dependency lock/SBOM/license/driver/arm64+amd64 artifact gate를 먼저 통과한다.
  Mac arm64에서 GX `1.19.1` lock, SBOM, import, dependency consistency와 알려진 취약점 검사는
  통과했다. 새 transitive `tqdm`의 `MPL-2.0 AND MIT` 배포 결정과 Linux/WSL amd64 고정
  artifact 검증은 담당자/대상 호스트 증거가 필요하므로 capability는 기본 비활성 상태다.
- [x] Quality domain aggregate, pure state machine, ports/DTO와 typed compiler contract를 구현한다.
- [x] 전용 Action/ABAC/strong-auth와 service identity/group 계약을 구현한다.
- [x] 목표 `quality` schema, `QUALITY_RULE/QUALITY_RESULT/QUALITY_AUDIT` retention kind와
  RuleSet/Run Legal Hold target, fixed transition functions, RLS, grants, 핵심 indices를 한
  incremental migration으로 구현한다.
- [x] SQLAlchemy metadata, incremental migration, regenerated `0001`과 Data Model을 동기화한다.
- [ ] rule/version/review/activation/revoke/archive, route-Action matrix와 capability/read
  contract를 구현한다. 도메인 lifecycle, 고정 DB 전이 함수, Action 및 service identity
  계약은 완료했고 HTTP route/capability/read-model 연결은 Phase 4 소유로 남는다.
- [x] ACTIVE-version/due-schedule/runnable-claim/terminal-dashboard index `EXPLAIN`과
  blank/current-head/canonical re-entry/drift/RLS actual PostgreSQL 17 gate를 통과한다.
- [x] immutable evidence가 있으면 destructive downgrade를 거부하고 empty development
  schema만 안전하게 downgrade함을 검증한다.

### Phase 2 — DataHub Profile

- [x] conflicting PostgreSQL recipe를 field-profile allowlist에 맞게 교정한다.
- [x] 별도 `catalog-profile-collector` identity/Action/NOBYPASSRLS role, fixed profile GraphQL
  adapter/DTO/parser와 projection을 구현한다.
- [x] 별도 additive migration으로 Catalog Profile tables, `QUALITY_PROFILE` retention kind와
  ProfileSnapshot Legal Hold target을 구현하고 regenerated `0001`/Data Model을 동기화한다.
- [x] profile kind/provenance/freshness/partial/oversize/contract-drift를 검증한다.
- [x] sample/top/distribution 값이 모든 ingress/storage/response/log에 없음을 검증한다.
- [ ] 실제 DataHub v1.6 service principal과 target PostgreSQL recipe run report를 확보한다.

### Phase 3 — GX worker와 Airflow

- [x] isolated quality-worker dependency/runtime, fixed compiler와 sanitizer를 구현한다.
- [x] deployment-owned source resolver, read-only transaction, egress와 workload gate를 구현한다.
- [x] outbox, run-independent dispatch receipt/mapping, exact current claim/lease/source-start
  fence, execution receipt와 expired-lease reclaim을 구현한다. Human cancel과 새-Run retry API는
  Phase 4 mutation surface에서 닫는다.
- [x] 별도 Keycloak client/Subject를 쓰는 Airflow OIDC dispatch DAG와 service-only endpoint를
  paused-by-default로 구현한다.
- [ ] 전체 source-access hard timeout + cancel/reconcile/completion margin을 frozen lease
  안에 두고 statement별 epoch 재확인/timeout, connection-close-before-reclaim, 실제 PostgreSQL
  full-table, revocation-before-query, duplicate full-scan 방지와 kill/reclaim을 검증한다.

### Phase 4 — API read model과 React UI

- [ ] authorization-pruned Overview/assets/rules/runs/results read model을 구현한다.
- [ ] 네 탭, cards/trend/grid, Rule wizard와 conflict/review/activation UI를 구현한다.
- [ ] 30초 authorization lease, capability/dependency 분리, bounded polling/cache fence와
  모든 availability/freshness 상태를 component-test한다.
- [ ] keyboard/zoom/screen-reader/target browser 접근성 gate를 통과한다.

### Phase 5 — 성능·보안·target acceptance

- [ ] representative manifest에서 profile/GX source query plan, dashboard SQL
  `EXPLAIN (ANALYZE, BUFFERS)`, concurrency/pool과 60분 soak를 측정한다.
- [ ] multi-workspace/count-leakage/SoD/WebAuthn/service-token/sanitizer/SSRF 음성 matrix를 통과한다.
- [ ] 실제 Airflow → DataRiver → quality-worker → PostgreSQL source → result commit을 검증한다.
- [ ] Mac arm64와 WSL amd64 exact artifact, offline update, restart/recovery evidence를 확보한다.

### Phase 6 — release/cutover

- [ ] feature/worker/DAG enablement을 별도 운영 승인하고 rollback 기준을 고정한다.
- [ ] exact commit/image/SBOM/dataset/identity/provider evidence를 acceptance report에 연결한다.
- [ ] `dev-publish` 후 준비 PC `prep-update`와 API/Web/OIDC/worker/source health를 검증한다.
- [ ] production gate가 열리지 않은 상태를 production-ready로 표현하지 않는다.

## 9. Phase 0에서 고정하지 않는 운영 값

다음 값은 source default가 아니라 배포별 승인 데이터다. 해당 값이 없으면 관련 capability는
`UNAVAILABLE` 또는 `DISABLED_NOT_READY`다.

- source connection/secret/egress identity와 배치 위치;
- schedule cadence/timezone/DST policy, evaluator/tzdb artifact;
- schedule별 catch-up cap과 dispatch별 `max_due_schedules/max_created_runs`;
- statement/lock/전체 source-access timeout, retry/lease, pool/concurrency와 scan/row/byte budget;
- profile freshness SLA;
- future sampling size/fraction;
- score weight/업무 threshold;
- small-cell suppression, histogram/top-K/quantile과 분류별 통계 허용;
- worker replica/capacity와 target performance SLO;
- Quality retention 기간, residency, archive와 Legal Hold 범위;
- WebAuthn freshness window와 배포 ACR/AMR 값.

소스에는 typed enum, 상태 전이, default deny, safe hard maximum, page/cursor bounds,
no-sample/no-raw-result와 disabled-by-default만 고정한다.

## 10. Phase 0 검증과 비주장

Phase 0 완료 검증은 문서 링크, ADR/requirement traceability, Markdown/static source gate와
4개 역할의 교차검토다. Python/TypeScript/runtime 동작은 바뀌지 않으므로 이를 GX 실행,
Dashboard, RLS/migration 또는 target acceptance 증거로 사용하지 않는다.

이 제한은 Phase 0에서 지켜졌으며 이후 연속 실행 승인을 받았다. Phase 1은 optional
dependency lock, SQLAlchemy/Alembic과 backend control-plane을 추가했고 Phase 2는
privacy-allowlisted DataHub Profile projection을 추가했다. Phase 3는 `0069` service-only
dispatch/claim/fence/completion functions, isolated Quality worker, source manifest, sanitized
result boundary와 paused Airflow DAG를 추가했다. Worker와 DAG schedule은 계속
disabled/paused-by-default이며 실제 target source full-scan과 kill/reclaim은 Phase 5
acceptance gate로 남는다. API/frontend human capability는 Phase 4까지 비활성이다.
