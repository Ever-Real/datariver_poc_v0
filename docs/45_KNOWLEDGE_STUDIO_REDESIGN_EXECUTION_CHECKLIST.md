# 지식관리 레지스트리 및 Knowledge Studio 개편 실행 체크리스트

- 상태: **진행 중 — Phase 4 Dry-run Preview/Pre-flight increment 구현**
- 상위 문서: [Knowledge Studio 전면 개편 PRD](44_KNOWLEDGE_STUDIO_REDESIGN_PRD.md)

이 체크리스트는 한 번에 화면을 교체하지 않는다. 각 phase는 앞 단계의 API/tests를 고정하고,
다른 메뉴에 회귀가 없다는 증거를 만든 뒤 다음 단계로 진행한다.

## Phase 0 — 결정과 계약 고정

- [x] 기존 UI-KG-001~008과 새 PRD의 supersession/traceability matrix를 PRD 2.1에 작성한다.
- [x] T-Box schema lifecycle을 `DRAFT -> REVIEW -> PUBLISHED`로 고정하고 Studio Draft와
  immutable ontology/release의 경계를 ADR로 승인한다.
- [x] Studio Draft의 author-only baseline과 명시적 Discard 전 영구 보존 정책을 승인한다.
- [x] Step 1의 필수 `endpoint_alias`와 materialize 시 `graph.slug` 매핑을 승인한다.
- [x] `graph_type`과 별도인 DOMAIN vocabulary UUID/source version, legacy-null 처리,
  `ResourceAttributes.domain_id`/SQL predicate 계약을 승인한다.
- [x] block 가중치를 `0..100` 정수로 고정하고 높은 weight 우선, 동률 최신 ordinal(LIFO)
  우선의 property/rule override로 승인한다.
- [x] Step 2 source는 schema inference만, Step 3 source는 실제 row mapping/ingestion만
  수행한다는 경계를 승인한다.
- [ ] file schema inference media type, parser/model, classification/provider routing,
  source-size/page/cost profile을 Phase 3 source contract로 승인한다.
- [ ] Catalog metadata allowlist, asset release attach, mapping unit/transform registry owner를 승인한다.
- [ ] 현행 catalog table UUID + server-returned field path를 v1 source reference로 쓸지,
  별도 normalized field identity가 필요한지 결정한다. 존재하지 않는 field UUID를 만들지 않는다.
- [x] 두 system-managed graph의 T-Box 수정자는 System Admin으로 제한하고, 승인된
  managed policy에 따른 daily A-Box sync/auto-publication 정책을 결정한다.
- [ ] Data architecture, security/ABAC, application, SRE reviewer가 canonical ownership,
  RLS, API boundary, query budget을 검토한다.

**Exit:** 핵심 lifecycle/merge/alias/source-boundary/default-graph 정책은 승인됐다. 세부 source
profile과 mapping registry 항목은 해당 Phase 시작 전에 추가 승인하며 Phase 1 foundation을
막지 않는다.

## Phase 1 — additive Registry backend/read model

- [ ] 기존 `GET /knowledge/graphs` 배열과 create/changeset/release/source-analysis/GraphRAG
  응답을 변경하지 않는 contract test를 먼저 고정한다.
- [ ] `/knowledge/registry/assets` page와 drawer summary/version/binding/preview read API를 추가한다.
- [ ] allowlisted sort, opaque keyset cursor, malformed cursor/limit negative를 구현한다.
- [ ] graph domain/classification/action predicate를 SQL에 적용하고 cross-workspace,
  over-clearance, disallowed-domain existence를 노출하지 않는 test를 만든다.
- [ ] graph마다 release/snapshot/source job을 추가 조회하지 않는 one-query/grouped query를
  구현하고 query-count test를 만든다.
- [ ] 대표 dataset manifest와 target `EXPLAIN (ANALYZE, BUFFERS)` 계획을 작성한다.
  target evidence 전에는 latency/capacity를 주장하지 않는다.
- [ ] creator/editor/domain legacy-null을 추측하지 않고 server가 bounded display identity를
  함께 반환함을 검증한다.

**Exit:** 기존 UI는 그대로 동작하고 새 Registry read API가 additive, bounded, ABAC-safe다.

## Phase 2 — Studio Draft와 전체 화면 foundation

- [x] Page query router에 `knowledge-studio`를 추가하고 malformed draft/step와 draft 없는
  후속 step을 API 호출 없이 Registry fallback으로 처리한다. 형식상 유효한 not-found/denied
  draft의 동일 응답 처리는 Draft read API와 함께 완료한다.
- [x] `asset/drawerTab/draft/step` parse/serialize/cleanup이 workspace 및 다른 menu query를
  침범하지 않는 navigation test를 만든다.
- [x] author-scoped StudioDraft domain aggregate, port, service, HTTP schema, RLS repository contract를 설계한다.
- [x] `knowledge.graphs` domain/creator/editor와 `ontology_versions` contract provenance를
  additive legacy-safe migration으로 추가한다.
- [x] Step 1 name/`endpoint_alias`/domain/classification validation, domain source-version pin,
  idempotency, ETag/conflict recovery UI를 구현한다. graph type은 create intent로 server가 결정한다.
- [ ] draft base pin, explicit Discard terminal transition, no-expiry persistence,
  cross-workspace/cross-author negative tests를 구현한다.
- [x] Full-screen shell, progress, save status, leave warning, refresh/recovery UI component test를 만든다.
- [ ] materialize 전 Draft가 Registry, projection, GraphRAG, Sharing, Chat evidence에서 보이지 않는 integration test를 만든다.
- [x] SQLAlchemy metadata, additive `0059`, deterministic canonical `0001`, data model,
  author-restrictive FORCE RLS와 column grant source checks를 함께 갱신한다.

**Exit:** Step 1 draft는 recoverable하지만 소비 가능한 graph가 아니며, PostgreSQL fault injection에서 partial state가 없다.

## Phase 3 — T-Box Graph Builder

- [ ] block, input, typed T-Box operation, proposal, layout model을 approved lifecycle에 맞게 추가한다.
- [ ] immutable typed `source_references`를 upload/catalog Asset/graph release XOR constraint,
  exact source version/hash/classification과 함께 추가한다.
- [x] DIRECT safe lexer/parser/AST/formatter를 pure module로 만들고 unsupported clause,
  property/query,
  invalid property/unit, parser-canvas round trip negative tests를 만든다.
- [x] 기존 alias가 text edit/format round trip에서 같은 stable element UUID를 보존하고
  node label/relation rename에서 identity를 보존함을 test한다. alias rename/delete의 server
  typed-operation 충돌 처리는 operation API와 함께 완료한다.
- [ ] Cypher source가 server/Neo4j로 전달·실행되지 않음을 HTTP/adapter test로 증명한다.
- [ ] editor/canvas 양방향 동기화, parse-error last-valid graph, stable element ID, layout-only update를 test한다.
- [ ] block 순서/enable 변경이 이전 block을 수정하지 않고 `(weight, ordinal)` deterministic
  fold를 수행하며 동률은 최신 block(LIFO)이 우선함을 test한다.
- [ ] LLM/file/catalog/asset-release proposal의 dotted overlay와 Accept/Reject/Expired/Conflict UI를 구현한다.
- [ ] provider/file inference는 별도 durable proposal job/attempt/event와 `202` API로 실행하고
  API process가 provider latency를 기다리지 않음을 test한다.
- [ ] proposal Accept가 one-time/version-fenced이고 source/classification/base pin을 재검증함을 integration test한다.
- [ ] unavailable file inference/catalog picker가 provider 호출 없이 사유를 표시함을 test한다.
- [ ] catalog picker가 local Asset UUID/source version과 server-returned aspect/field token만
  받고 arbitrary URN/field path/provider query를 거부함을 test한다.
- [ ] asset attach가 permitted exact release/version/hash만 pin하고 hidden/over-clearance/retired asset을 찾지 못함을 test한다.
- [ ] hierarchy cycle, alias collision, domain/range/cardinality, unit/transform, classification/source drift negative cases를 만든다.
- [ ] canonical ontology schema document/checksum에서 immutable element index가 같은 transaction에
  파생되고 deterministic rebuild/hash/read-back 되는 migration test를 만든다.

**Exit:** 제안은 수락 전 accepted schema가 아니며 raw Cypher/LLM mutation path가 없다.

## Phase 4 — A-Box Data Enricher와 Mapping whitelist

- [x] T-Box map에서 accepted Class/Relation만 selectable하도록 구현한다.
- [x] author-scoped A-Box read, bounded Dataset search/detail, target-scoped idempotent PATCH와
  ETag 412 contract를 구현한다.
- [x] Class node 선택, Data Binding Panel, SUBJECT_ID/PROPERTY column mapping과 persisted
  `Mapped · DRAFT` accessible badge를 구현한다.
- [x] v1 `CATALOG_DATASET`은 local Asset UUID, provider-schema/projection 두 version,
  Draft classification ceiling, server-returned field allowlist, accepted Class/owned Property와
  `IDENTITY@1`만 수락하도록 구현하고 negative test를 만든다.
- [x] 현재 Mapping `DRAFT`와 instance ingestion `NOT_RUN`을 분리 표시하고 mapped 색상만으로
  ingestion 또는 publication 성공을 주장하지 않는다.
- [x] DataHub metadata와 physical row reader를 분리하고 local Asset UUID, exact version,
  persisted field allowlist, 5~10 row bound만 받는 typed sample port를 승인한다.
- [x] persisted Class Binding을 provider-neutral JSON graph로 변환하는 dry-run engine과
  React Flow overlay/property inspector를 구현한다. raw Cypher/SQL과 Neo4j write는 없다.
- [x] accepted Class/SUBJECT_ID/non-nullable Property/T-Box version/source authorization 및
  physical access capability를 검사하는 ETag-fenced Pre-flight evidence를 구현한다.
- [x] 승인된 physical row reader가 없는 runtime은 sample을 만들지 않고
  `SOURCE_ROW_READER_UNAVAILABLE`로 실패하며 Run Ingestion을 disabled로 유지한다.
- [ ] mutable binding/rule draft, immutable binding version/rule, append-only validation
  evidence를 분리하고 네 mapping method 외 값을 거부한다.
- [ ] source/target, unit, transform, cardinality, source version, classification/provenance validation을 구현한다.
- [ ] source picker가 local authorized catalog projection, immutable upload, exact Asset release 외 값을 수락하지 않음을 test한다.
- [ ] mapping readiness `UNBOUND/DRAFT/VALIDATED/STALE`와 ingestion
  `NOT_RUN/QUEUED/RUNNING/FAILED/DRAFT_CHANGESET/PUBLISHED`를 별도 표시함을 UI test한다.
- [ ] source schema/file hash/ontology/transform/permission/classification drift가 STALE/denied가 되는 negative tests를 만든다.
- [ ] drawer binding source list/count가 grouped bounded query이고 secret/object coordinate가 없음을 test한다.
- [ ] mapping 설정 저장이 release, Neo4j, DataHub metadata, raw source를 직접 바꾸지 않음을 integration test한다.
- [ ] Studio 완료 transaction이 graph/ontology/binding read-back 전에 실패하면 A-Box job이
  없고, 성공 후 enqueue 실패가 materialized schema/spec을 변조하지 않음을 test한다.
- [ ] 기존 PDF-to-DRAFT owner scope, PUBLIC/INTERNAL, bounded polling/cancel/stale 흐름을
  Step 3에서 재사용하고 기존 entry point와 결과가 동등함을 test한다.
- [ ] 실제 일반 mapping run은 ADR-0044 수준의 separate durable job, attempt/event,
  fencing/retry/cancel/outbox/RLS/worker role/crash matrix가 승인된 source kind에만 구현한다.

**Exit:** A-Box는 reproducible whitelist binding이며 independent review 없는 release가 되지 않는다.

## Phase 5 — Registry/Studio UI cutover

- [ ] server capability가 Registry/Studio schema/API와 기존 PDF parity를 모두 ready로 보고하는지 확인한다.
- [ ] KnowledgeRegistryPage의 TanStack manual page/sort와 wide drawer route state를 기본 화면으로 전환한다.
- [ ] drawer close/back, loading/error/denied/empty/unavailable, focus restore, keyboard accessibility를 test한다.
- [ ] overview/version/binding/preview/API tab을 lazy-load하고 close/tab-change에서 request를 abort한다.
- [x] create Dialog를 제거하고 create click이 draft 없는 full-screen Step 1로만 이동함을 test한다.
- [x] KnowledgeWorkspaceLayout에서 데이터 적재 메뉴를 제거하고 Registry/Knowledge Chat만 남긴다.
- [ ] old Mode A/B가 더 이상 독립 정본으로 쓰이지 않고 rollback source로만 남는지 확인한다.
- [ ] Catalog, Registration, Change Management, general Chat, Admin, AppShell의 focused regression을 실행한다.

**Exit:** 두 메뉴 GNB, full-screen Studio, bounded wide drawer가 기본이며 기존 Knowledge Chat과
다른 menu route/state/API에 회귀가 없다.

## Phase 6 — system-managed default graph

- [ ] metadata lineage와 glossary Asset seed/create command, source contract, mapping version, owner record를 만든다.
- [ ] scheduler trigger와 PostgreSQL canonical run/receipt state를 분리한다.
- [ ] immutable PUBLISHED T-Box checksum, exact source/mapping contract, System principal,
  classification ceiling을 pin한 managed policy가 없거나 drift하면 auto-publication을
  거부하고 reviewer-visible Draft/failed receipt로 끝남을 test한다.
- [ ] 승인된 managed policy에서는 empty/no-op, failure, replay, concurrent trigger,
  permission revocation을 안전하게 처리하고 성공한 daily A-Box sync만 atomic receipt와
  함께 PUBLISHED가 됨을 test한다.
- [ ] target DataHub/Airflow/provider/Neo4j에서 source read-back, scheduler recovery,
  projection rebuild, restore evidence를 수집한다.

## Cross-cutting verification

- [ ] backend 변경마다 README-equivalent Ruff, strict mypy, relevant pytest, verify_static을 실행하고 결과를 기록한다.
- [ ] schema 변경마다 SQLAlchemy metadata, Alembic migration, deterministic initial migration diff,
  data model, RLS/grant/role tests를 함께 검증한다.
- [ ] frontend 변경마다 TypeScript, ESLint, production build, Registry/Studio/Chat과 unaffected-menu regression을 실행한다.
- [ ] contract tests에 malformed enum/UUID/cursor, idempotency, stale If-Match, cross-workspace,
  author/reviewer separation, source/release/classification drift를 포함한다.
- [ ] load/soak plan에 Asset/version/binding/canvas/mapping workload, DB query plan, RSS,
  external dependency failure를 명시한다. 승인 workload 전에는 capacity claim을 하지 않는다.
- [ ] browser, distinct human author/reviewer, WSL/private provider, DataHub, Neo4j rebuild,
  Airflow restart/recovery는 local source gate와 별도로 기록한다.

## 금지 사항

- [ ] Studio 편의를 위해 existing graph/release를 직접 update하거나 Neo4j/DataHub 내부 모델을 수정하지 않는다.
- [ ] browser/LLM/upload text를 Cypher, SQL, SPARQL, GraphQL, URL, provider credential pass-through로 만들지 않는다.
- [ ] proposal, placeholder count, artificial ingestion success, LLM confidence를 fact/release/approval으로 표시하지 않는다.
- [ ] default graph daily job을 maker/checker, classification, provenance, release receipt의 예외로 만들지 않는다.
