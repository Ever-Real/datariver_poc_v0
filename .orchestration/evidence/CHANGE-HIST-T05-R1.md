# CHANGE-HIST-T05 R1 repair 증거

## 판정과 provenance

- builder 자체 검증 판정: `PASS`
- Orca run: `run_fe1ea01316d1`
- task / dispatch: `task_915bb412dec5` / `ctx_2c2e6ef9bc38`
- owner role: `40_DATA_AI_KNOWLEDGE Builder`
- exact base 및 독립 검증 evidence head: `15c981beae6006d066744d579f4e3eeee206cf34`
- source candidate under repair: `49528ca50fd0f286d998105b0dbe70c41040caa9`
- exact product repair SHA: `d84456b5b4581f368854a6710656adbaf54bfa7c`
- worktree: `/Users/everreal/orca/workspaces/datariver_poc_v0/change-hist-t05-r1`
- G1/G2/G3/G4: 모두 `NOT_APPROVED`

제품 repair와 검증은 F-01, F-02, F-03에만 한정했다. prior builder/validation evidence는
수정하지 않았고 이 R1 문서를 추가했다. 제품 repair commit에는 아래 제품/테스트 4개 경로만
포함되며 evidence/receipt는 별도 후속 commit으로 분리한다.

## Finding disposition

### F-01 — `PASS`

- DataHub 각 scroll page의 `total`이 non-negative safe integer이고 모든 page에서 동일한지 확인한다.
- terminal cursor가 끝난 시점의 unique asset cardinality가 provider total과 정확히 같을 때만
  current projection을 commit한다.
- malformed/repeated cursor, malformed/inconsistent total, invalid asset identity, duplicate-induced
  cardinality gap, premature terminal page, complete cardinality 이후 continuation cursor 및 later-page
  failure는 모두 last-good을 교체하지 않는다.
- `total=0`, empty items, terminal cursor 조합은 유효한 zero generation으로 commit한다.
- negative regression에서 `total=2`지만 terminal page에 1건만 온 경우 write count가 유지되었고,
  별도 zero regression은 빈 projection commit과 fresh-process 재사용을 확인했다.

### F-02 — `PASS`

- PostgreSQL current projection이 구성되면 이를 먼저 읽고 valid value를 authoritative current로
  선택한다.
- Redis는 PostgreSQL read 자체가 실패한 경우에만 bounded availability fallback으로 사용한다.
  PostgreSQL이 정상 응답한 split-success에서는 stale Redis를 읽지 않는다.
- negative regression에서 Redis의 `redis_old`와 PostgreSQL의 `postgres_new`가 공존할 때 fresh
  process가 `postgres_new`만 반환했고 PostgreSQL read 1회, Redis read 0회였다.

### F-03 — `PASS` (source/in-memory/SQL contract)

- 기존 `poc_state`에 binding-scoped active embedding generation pointer를 저장한다. 새 table,
  migration, service 또는 dependency를 추가하지 않았다.
- 모든 변경 vector를 먼저 memory에서 완성한 뒤, 기존 Catalog projection row를 `FOR UPDATE`로
  확인하고 embedding upsert, retained row generation 이동, deleted/stale row 제거, active pointer
  갱신을 하나의 PostgreSQL transaction에서 commit한다.
- semantic search SQL은 binding뿐 아니라 요청 generation, PostgreSQL current Catalog generation,
  active embedding generation이 모두 같은 row만 검색한다. Catalog가 교체됐지만 새 embedding이
  실패/미완성인 동안에는 old/deleted generation을 반환하지 않고 lexical provider fallback으로
  fail safe한다.
- in-memory negative regression은 2개 asset generation에서 다음 generation vector validation이
  실패해도 prior active pointer가 유지되며 새 generation 검색이 empty임을 확인했다. 성공한
  replacement 후에는 삭제된 `asset-a`가 old/new generation 모두에서 검색되지 않고 `asset-b`만
  current generation에 남았다.
- PostgreSQL adapter contract test는 projection fence, delete, active pointer write가 `BEGIN`과
  `COMMIT` 사이에 있고 search SQL이 current/active generation을 함께 조건화함을 확인했다.

### D-01 — `PASS`

- prior 문서를 rewrite하지 않았다.
- focused product repair commit은 `d84456b5b4581f368854a6710656adbaf54bfa7c`이며 base/evidence
  provenance `15c981beae6006d066744d579f4e3eeee206cf34`와 분리했다.
- 이 문서와 대응 receipt만 별도 R1 evidence commit으로 생성한다. evidence commit SHA는 commit
  생성 후 Orca `worker_done`에 exact value로 보고한다.

## Fresh validation

repository에는 dependency를 설치하거나 symlink하지 않았다. `/tmp/datariver-t05-r1.abhvXg`에
source를 새로 동기화하고, task와 DEV integration의 `frontend/package-lock.json` SHA-256이 모두
`1b9bbbf01732c7eea657020ada5bccd274dbc84e59eb5059ad55299c5ac56892`임을 확인한 뒤 기존 unchanged
dependency snapshot을 temporary copy에만 symlink했다.

| 검증 | 결과 |
|---|---|
| focused ESLint 5개 허용 frontend 파일, zero warning | `PASS` |
| `npm --prefix frontend run build:poc` | `PASS`; 기존 `>500 kB` chunk warning만 존재 |
| Node server/provider/chat/performance | `PASS` — 28 passed, 0 failed |
| Catalog workspace/API Vitest | `PASS` — 2 files, 32 passed, 0 failed |
| F-01 terminal partial / valid zero | `PASS` — last-good 1건 유지 / zero 0건 commit |
| F-02 Redis/PG split-success | `PASS` — `POSTGRES_CURRENT_PROJECTION` |
| F-03 in-memory deletion/failure + PostgreSQL SQL transaction/search fence | `PASS` |
| `git diff --check`, conflict marker, allowlist, hardcoding/credential diff scan | `PASS` |

최종 performance harness 관찰값은 cold HTTP 503 `21.854 ms`, provider 2 pages, warm HTTP 200
`4.730 ms`, provider 0 page, payload 2,861 B, parse `0.049 ms`였다. 이는 deterministic local
harness 결과이며 TARGET 성능 수치가 아니다.

## 실패 및 정정 이력

- 최초 Node 묶음 실행은 temporary copy에 `dist-poc`가 아직 없어 root static test 1건이 HTTP 404로
  실패했다. 같은 source에서 `build:poc` 후 재실행하여 27/27, 최종 chat benchmark 포함 실행에서
  28/28을 확인했다. 제품 동작 실패로 판정하지 않는다.
- 첫 Vitest 호출은 repository root 기준 잘못된 executable/cwd를 사용해 test discovery 전에 종료했다.
  `frontend` cwd에서 같은 두 파일을 다시 실행해 32/32를 확인했다.

## NOT_EXECUTED

- active DEV runtime candidate 배포, restart, cache flush, browser timing
- 실제 DataHub/Redis/PostgreSQL/Embedding provider mutation과 실제 PostgreSQL transaction 실행
- TARGET load/soak/capacity, TARGET browser, PREP, OPS
- dependency/package/lockfile, migration/schema/table, backend/T03/T04 변경
- 새 DB/cache/service/container/framework 및 container lifecycle
- UI/CR/IAM, external metadata write, merge, push, integration, publication
- G1/G2/G3/G4 승인과 독립 R1 재검증

## 결론

독립 검증의 F-01, F-02, F-03 및 D-01을 허용 경로 안에서 최소 repair했다. builder focused
검증은 모두 통과했으나 실제 provider/DB 및 TARGET 검증과 독립 R1 acceptance는 수행하지 않았으므로
그 결과를 production 또는 release 승인으로 승격하지 않는다.
