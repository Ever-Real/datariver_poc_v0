# Knowledge Studio Phase 5 릴리즈 리포트

- 기준일: 2026-07-28
- 대상 branch: `dev`
- DB revision: `0061`
- 상태: **Local-source release candidate; target 운영 게이트 open**
- 결정 기록: [ADR-0062](adr/0062-knowledge-studio-governed-schema-publication.md)

## 1. 전사 아키텍처/UX 검토 결론

Phase 1~5 구현은 Knowledge를 Catalog/Upload/DataHub/Neo4j와 분리된 bounded context로 유지한다.
PostgreSQL만 schema/mapping의 정본이며, DataHub는 권한 처리된 metadata/source pin,
physical adapter는 bounded sample, Neo4j는 재구축 가능한 instance projection 역할만 한다.

| 사용자 요구 | 현재 결과 | 판정 |
|---|---|---|
| 지식 레지스트리/지식 챗 두 메뉴 | Knowledge local menu에서 데이터 적재 entry를 제거하고 Studio를 별도 full-screen page로 분리 | 구현 |
| Asset wide drawer와 bounded Registry | 기존 Registry UI는 유지되지만 server-paged TanStack read model과 전체 wide drawer tab cutover는 미완성 | Open |
| Step 1 기본정보/alias/domain/security | persistent Draft, domain picker, 1.5초 autosave, IndexedDB recovery, ETag 412 dialog | 구현 |
| Step 2 layered T-Box builder | Regex 없는 lexer/parser/AST/formatter와 stable ID foundation은 구현; block operation writer, bidirectional canvas, proposal overlay/Accept는 미완성 | Open |
| Step 3 A-Box mapping | accepted typed elements, authorized Dataset picker, field mapping, `Mapped · DRAFT`, partial PATCH | 구현 |
| Preview/Pre-flight | 5~10 row typed dry-run port, no Neo4j write, exact validation receipt와 evidence | 구현 |
| Governed Publish | maker-checker, WebAuthn, exact PASS receipt, immutable T-Box/A-Box Studio Release, prior archive | 구현 |
| 실제 A-Box ingestion | 실행하지 않으며 UI/API에 `NOT_RUN`; durable job/attempt/fence는 별도 단계 | Open |
| 두 default graph daily sync | 정책만 승인; managed policy/scheduler/receipt pipeline은 미완성 | Open |

따라서 이 변경은 “Schema/Mapping 정본 발행”까지의 local-source release candidate다. 아직
완성되지 않은 Registry/T-Box/instance ingestion/default-graph 기능을 UI 성공 상태나 플랫폼
릴리즈 완료로 표시하지 않는다.

## 2. Governed Publish 흐름

~~~text
Author DRAFT
  └─ typed T-Box + A-Box Mapping Draft
       └─ submit-review (If-Match + Idempotency-Key)
            └─ REVIEW / editing locked
                 └─ independent reviewer pre-flight
                      ├─ exact Draft version
                      ├─ canonical contract hash
                      ├─ source metadata/access evidence
                      └─ append-only PASS receipt
                           └─ Publish (kg.review + kg.publish + Hardware WebAuthn)
                                ├─ prior Studio Release -> ARCHIVED
                                ├─ Ontology Version + Element index
                                ├─ immutable Binding/Rule versions
                                ├─ new Studio Release -> ACTIVE
                                ├─ Draft -> PUBLISHED
                                ├─ graph.active_studio_release_id
                                └─ outbox + idempotency receipt
~~~

모든 materialization과 canonical hash read-back은 한 PostgreSQL transaction이다. 실패하면
Graph/Ontology/Mapping/Release/Pointer/Outbox가 함께 rollback된다. 발행은 다음 항목을
의도적으로 변경하지 않는다.

- `knowledge.releases`와 `graphs.active_release_id`
- 실제 Dataset row와 ingestion 상태
- Neo4j projection
- DataHub metadata

## 3. 정본 DB/JSON 구조

`studio_releases`는 아래 canonical contract의 해시만 manifest에 저장하고, 정규화된 실제
내용은 ontology/binding/rule version table에 보존한다.

~~~json
{
  "contract_version": "KNOWLEDGE_STUDIO_RELEASE_V1",
  "draft": {
    "draft_id": "<uuid>",
    "kind": "CREATE",
    "name": "Employee Knowledge",
    "endpoint_alias": "employee_knowledge",
    "domain_id": "<uuid>",
    "domain_source_version": "<exact-version>",
    "classification": 1,
    "base_graph_id": null,
    "base_ontology_version_id": null,
    "base_release_id": null
  },
  "tbox_hash": "<sha256>",
  "abox_hash": "<sha256>"
}
~~~

| 정본 | 역할 |
|---|---|
| `studio_preflight_checks` | Draft version/contract hash/checker/evidence가 고정된 append-only receipt |
| `ontology_versions`, `ontology_elements` | immutable T-Box document와 typed stable-element index |
| `abox_binding_versions`, `abox_mapping_rule_versions` | immutable source pin과 field-to-property whitelist |
| `studio_releases` | exact Draft/version/hash/reviewer/receipt composite FK, contract/T-Box/A-Box hash, maker/checker/reason과 ACTIVE/ARCHIVED 이력 |
| `studio_drafts` | PUBLISHED lifecycle 및 receipt/graph/ontology/Studio Release read-back references |
| `graphs.active_studio_release_id` | 현재 schema/mapping contract pointer; instance release와 분리 |

동일 graph에는 partial unique index로 ACTIVE Studio Release를 하나만 허용한다. EDIT Publish는
기존 graph, ontology, active Studio Release와 instance-release base가 모두 동일할 때만
진행한다.

## 4. Physical Connection Adapter

`KnowledgeStudioPhysicalSourceAdapter`는 trusted bootstrap이 등록한 다음 exact contract만
수신한다.

- Workspace와 local Catalog Asset UUID
- provider schema version과 authorization-pruned projection version
- 허용 field path 집합과 minimum clearance
- server-owned adapter ID

브라우저는 SQL, file path, URI, endpoint, credential을 전달할 수 없다. registry-backed
reader는 5~10 row, 최대 200개 explicit field, JSON scalar, finite number, timezone-aware
receipt만 허용한다. CSV/SQLite shell은 승인된 operator manifest가 없으면 항상 fail closed
한다. 현재 기본 runtime은 adapter를 주입하지 않으므로
`SOURCE_ROW_READER_UNAVAILABLE`이 정상 상태다.

## 5. Cleanup/Teardown

`scripts/cleanup_knowledge_studio_test_artifacts.py`는 기본 dry-run이다. Apply는 exact manifest
SHA-256을 한 번 더 요구하며 다음 두 동작만 수행한다.

1. exact Draft UUID/version을 ordinary `discard` API로 전환한다.
2. explicit test root 아래 Git-untracked regular non-symlink file을 현재 SHA-256 재검증 후
   `unlink`한다.

직접 SQL, recursive delete, symlink follow, tracked-file deletion, redirect follow, token
argument 노출은 없다. 이 작업 트리에서 삭제 대상으로 식별된 고정 dummy Draft/file은 없어
임의 cleanup을 실행하지 않았다.

## 6. 검증 결과

| Gate | 결과 |
|---|---|
| Knowledge Studio focused backend | `39 passed` |
| Whole backend | `1,694 passed / 97 environment-gated skipped` |
| Python quality | Ruff lint PASS, strict mypy `421` files PASS |
| Static architecture/security/docs | PASS |
| Frontend | TypeScript PASS, ESLint PASS, `54 files / 300 tests`, production build PASS |
| Focused Studio frontend | `2 files / 8 tests` |
| Migration | sole head `0061`; `0060 -> 0061` chain confirmed |
| Canonical initial migration | repeated SHA-256 `185641e239e82d7f6948e761fd929a618fdacaebc766cbb45f031a713728eba1` |
| Changed-file format | PASS |

Repository-wide Ruff format은 이번 범위와 무관한 기존 DataHub 파일 2개만 계속 보고한다.
Target PostgreSQL app-role RLS/concurrency, 실제 OIDC two-human WebAuthn, browser accessibility,
승인된 physical source와 WSL `linux/amd64`는 local unit/source 결과와 별도인 운영 게이트다.

## 7. 다음 승인 게이트

1. Step 2 typed block/operation writer와 AST↔canvas round trip을 완성한다.
2. server-paged Registry summary/wide drawer를 기본 UI로 cutover한다.
3. isolated PostgreSQL에서 `0060 -> 0061`, app-role RLS, concurrent Publish/archive와 rollback
   fault injection을 실행한다.
4. operator-owned Connection manifest/credential boundary와 real CSV/SQLite 또는 approved DB
   adapter를 승인한다.
5. published Studio Release를 pin하는 durable ingestion job/attempt/fence와 instance Release
   publication을 별도 ADR로 구현한다.
6. managed default graph policy/scheduler/no-op/failure/publication receipts를 구현한다.
