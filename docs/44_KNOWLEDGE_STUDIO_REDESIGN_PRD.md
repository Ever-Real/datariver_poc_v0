# 지식관리 레지스트리 및 Knowledge Studio 전면 개편 PRD

- 상태: **승인됨 — Phase 1 구현 기준**
- 작성일: 2026-07-28
- 범위: Knowledge Registry/Studio UX, T-Box 스키마 초안, A-Box 바인딩 초안과 그 읽기·영속 모델
- 비범위: DataHub 내부 저장소 변경, Neo4j 직접 조작, 임의 Cypher/SPARQL 실행, 일반 Chat 변경, 다른 메뉴 정보 구조 변경

이 문서는 [온톨로지 참조 노트](reference/00_ONTOLOGY.md), [아키텍처](03_ARCHITECTURE.md),
[데이터 모델](06_DATA_MODEL.md), [기존 Knowledge UI PRD](20_ENTERPRISE_UI_COMPLETION_PRD.md),
ADR-0001, ADR-0002, ADR-0004, ADR-0011, ADR-0029, ADR-0039, ADR-0043,
ADR-0044를 따른다. 기존 UI-KG 요구사항은 현재 구현 기록이며, 이 문서의 변경은
ADR/DB/API 게이트 승인과 구현 완료 후에만 이를 대체한다.

## 1. 목표와 핵심 결정

### 1.1 목표

1. 지식관리 좌측 작업 메뉴를 **지식 레지스트리**와 **지식 챗** 두 항목으로 단순화한다.
2. Asset 상세를 넓은 우측 드로어로 제공하되, 목록 조회에 snapshot/lineage 전체 조회를 섞지 않는다.
3. 신규/기존 Asset의 스키마·바인딩 작업을 전체 화면 Studio로 분리한다.
4. T-Box의 직접 편집, 파일/카탈로그/다른 Asset/LLM 기반 결과를 모두 검토 가능한 초안으로 취급한다.
5. A-Box는 무제한 데이터 적재가 아니라 허용된 원천·필드·변환을 T-Box 요소에 연결하는 버전 있는 Mapping whitelist다.

### 1.2 결정

| 항목 | 결정 |
|---|---|
| 신규 Asset 생성 | 모달을 사용하지 않는다. 생성 클릭 즉시 draft 없는 전체 화면 Step 1로 이동하고, Step 1 저장이 author-scoped Studio Draft를 만든다. Graph aggregate는 T-Box 검증 및 Studio 완료 명령에서만 원자적으로 만든다. |
| 데이터 적재 메뉴 | GNB에서 제거한다. 현재 Ingestion Studio의 기능은 Step 2/3으로 흡수하며 API 없는 기능은 unavailable로 표시한다. |
| Step 1 필드 | 사용자 입력은 이름, `endpoint_alias`, 통제된 업무 도메인, 보안등급 네 개다. alias는 소문자 영문으로 시작하는 영문/숫자/underscore 3~100자이며 materialize 때 기존 `graph.slug`가 된다. |
| 업무 도메인 | 기존 `graph_type`과 혼동하지 않는다. 도메인은 Workspace의 active `catalog.vocabulary_entries(kind=DOMAIN)` UUID/source version을 pin하고 Knowledge ABAC의 `domain_id`로 사용한다. |
| Cypher 편집기 | 화면의 양방향 편집 보조 형식이다. 안전 schema subset을 typed T-Box operation으로 변환할 뿐, 원문을 서버/Neo4j에 보내거나 실행하지 않는다. |
| LLM/파일 제안 | 항상 proposal이다. 점선/강조 preview 후 사용자가 Accept할 때만 Draft operation이 된다. 모델은 publish, activate, Cypher 실행, source 범위 확대 권한이 없다. |
| A-Box 완료 표시 | mapping readiness와 ingestion publication을 서로 다른 상태축으로 표시한다. 노드 활성 표시는 유효한 binding 존재일 뿐, Neo4j 적재나 release 발행을 뜻하지 않는다. |
| Asset lifecycle | schema Asset은 `DRAFT → REVIEW → PUBLISHED`를 따른다. Studio Draft는 version-fenced auto-save되며 명시적 Discard 전까지 만료 없이 보존한다. Discard는 audit 가능한 terminal state다. |
| block merge | 같은 canonical Class/Relation 충돌은 weight가 높은 block, 동률이면 ordinal이 큰 최신 block(LIFO)이 property/rule key를 override한다. classification, provenance, source pin과 validation 결과는 override 대상이 아니다. |
| 기본 그래프 | 전체 메타데이터 lineage와 데이터 용어사전 T-Box는 System Admin만 수정한다. 승인된 PUBLISHED T-Box와 managed mapping policy에 대한 일일 A-Box sync/auto-publication은 Phase 6 전용 ADR/보안 게이트를 통과해야 한다. |

### 1.3 바꾸지 않는 경계

- PostgreSQL의 독립 검토된 changeset/release가 지식 정본이다. Neo4j는 재구축 가능한 shadow projection이다.
- DataHub는 카탈로그·용어집·태그·소유권·계보의 외부 metadata 시스템이다. DataHub GMS/Neo4j에 domain node/edge를 추가하지 않는다.
- 모든 read/write는 Workspace, ABAC, classification envelope, source version, release lineage, optimistic version을 확인한다.
- 브라우저에는 DataHub/Neo4j/LLM/object-storage credential, 내부 endpoint, 원시 provider 오류를 주지 않는다.
- 기존 Knowledge Chat은 별도 route 및 citation-bounded GraphRAG 계약을 유지한다.
- Knowledge domain은 Catalog/Upload의 테이블을 수정하지 않는다. 허용된 source를 조회·pin할 때
  application port를 사용하고, 정규화된 immutable reference만 Knowledge가 소유한다.

## 2. 현재 상태와 호환성

현재 화면은 Registry, 데이터 적재, 지식 챗의 세 로컬 메뉴와 생성 Dialog, 고정 폭 inspector를
사용한다. Registry는 graph 목록 뒤 선택 graph의 releases/snapshot을 조회한다. 기존
ingestion은 Mode A/Mode B와 PDF 전용 durable source-analysis를 포함한다.

현행 소스에서 확인된 변경 지점은 다음과 같다.

| 현재 파일/계약 | 확인된 상태 | 개편 시 원칙 |
|---|---|---|
| `frontend/src/app/navigation.ts` | query parameter 기반 `Page`; `knowledge-studio` 없음 | Router 라이브러리를 새로 도입하지 않고 Page와 feature-owned query parser만 확장 |
| `KnowledgeWorkspaceLayout.tsx` | `REGISTRY/INGESTION/CHAT` 세 메뉴 | 최종 cutover에서 `REGISTRY/CHAT`만 남김 |
| `KnowledgeRegistry.tsx` | 전체 graph list, 선택 즉시 전체 release list와 snapshot 조회, 생성 Dialog | server-paged summary, tab-lazy drawer, Studio route로 교체 |
| `KnowledgeIngestionStudio.tsx` | Mode A/B와 기존 PDF-to-DRAFT 기능 | T-Box/A-Box step으로 이동하되 기존 durable PDF job의 보안·복구 계약 유지 |
| `knowledgeCypherDraft.ts` | 로컬 CREATE subset이 parse 때마다 UUID를 새로 생성 | stable symbol table을 가진 versioned schema codec으로 교체; 기존 parser를 그대로 확장하지 않음 |
| `GET /knowledge/graphs` | 배열 응답이며 repository가 전체 허용 graph를 읽음 | 호환 응답은 유지하고 별도 Registry page endpoint 추가 |
| `knowledge.graphs` | graph type/classification/version은 있으나 업무 domain/creator/editor가 없음 | nullable legacy-safe provenance 열을 추가하고 신규 materialize에는 필수 |
| `knowledge.ontology_versions` | `entity_types/edge_types` 집합 문서 중심 | canonical schema document는 유지하고 typed element index를 원자적으로 파생 |
| source-analysis | PDF, PUBLIC/INTERNAL, pinned/fenced durable job만 구현 | 다른 파일/DB inference를 구현된 것처럼 표시하지 않음 |

| 현재 계약 | 개편 후 처리 |
|---|---|
| page=knowledge | Registry를 연다. 현재 bookmark를 깨지 않는다. |
| page=knowledge-chat | 그대로 유지한다. 일반 Chat과 합치지 않는다. |
| graph/release/changeset API | 검토, 발행, projection, GraphRAG 계약을 바꾸지 않는다. Studio는 새 typed command로만 여기에 합류한다. |
| PDF source-analysis | Step 3 source kind로 재사용 가능하지만 PDF, PUBLIC/INTERNAL, worker capability 제한을 우회하지 않는다. Excel/CSV/TXT/DOCX 분석은 새 parser 계약 승인 전 unavailable이다. |
| DataHub DB 선택 | 브라우저가 DataHub GraphQL을 호출하지 않는다. 권한 처리된 local catalog projection에서만 후보를 찾는다. |
| 데이터 적재 메뉴 | 메뉴/직접 진입만 없앤다. AppShell, Catalog, Upload, 다른 menu route와 Chat 상태는 변경하지 않는다. |

### 2.1 기존 UI-KG 요구사항 승계

| 기존 요구사항 | 처리 |
|---|---|
| UI-KG-001 | Registry와 별도 Knowledge Chat은 유지한다. Data Ingestion 메뉴만 Studio cutover 완료 후 제거한다. |
| UI-KG-002 | 실제 graph/release 사용은 유지한다. 고정 inspector는 wide drawer로, create Dialog는 full-screen Studio로 대체한다. |
| UI-KG-003 | Mode A/B의 의미를 Step 2 T-Box/Step 3 A-Box로 승계한다. |
| UI-KG-004, UI-KG-006 | 기존 PDF durable job의 owner scope, PUBLIC/INTERNAL 제한, bounded polling/cancel/stale 상태를 Step 3에서 그대로 승계한다. DB/기타 파일은 승인 전 unavailable이다. |
| UI-KG-005 | 로컬 safe subset과 typed operation 원칙을 유지하고 stable identity, proposal overlay, 양방향 codec을 추가한다. |
| UI-KG-007, UI-KG-008 | Knowledge Chat과 일반 Chat 계약은 변경하지 않는다. |

기존 Data Ingestion 진입점을 먼저 제거해 기능을 잃게 만들지 않는다. 새 Registry/Studio가
서버 capability로 준비되었고 기존 PDF 흐름까지 Step 3에서 통과한 뒤 한 번의 cutover로
메뉴와 Dialog를 제거한다.

## 3. 사용자 경험

### 3.1 지식 레지스트리와 넓은 드로어

Registry는 TanStack Table 기반 Asset 목록이다. 이름, graph type과 별도인 업무 도메인,
보안등급, 상태, 현재 schema/release version, node/edge 수, 바인딩된 원천 수,
작성자/마지막 편집자, 생성일, 최근 변경일을 표시한다. 숫자는 권한이 적용된 server
aggregate이며 브라우저가 전체 snapshot을 읽어 계산하지 않는다. migration 이전 Asset의
작성자·편집자·업무 도메인을 추측해 채우지 않고 `기록 없음 (legacy)`로 표시한다.

행 선택 시 작업 메뉴 오른쪽 끝까지 확장 가능한 drawer를 열며, URL에는 asset ID와
선택 tab만 둔다. drawer는 Knowledge page의 두 번째 CSS grid column 안에서 overlay되어
최대 폭이 local 작업 메뉴 오른쪽 경계에 맞는다. 다른 AppShell/menu 위로 확장하지 않는다.
권한은 매 요청에서 다시 확인한다.

| Drawer tab | 내용 | 데이터 규칙 |
|---|---|---|
| 개요 | 기본정보, status, active release, node/edge/binding 집계 | summary 한 번만 조회; 전체 snapshot 금지 |
| 버전 | schema/release/changeset 이력과 작성·검토·발행 증거 | keyset cursor와 제한된 행 수 |
| 바인딩 및 Ingestion | class/relation별 binding 상태, source kind, 최근 run, 연결 Table/File | source locator, bucket, provider 오류는 노출하지 않음 |
| 그래프 미리보기 | active release의 축소 node/edge preview | server bounded view만 React Flow에 전달 |
| API | 현 사용자에게 허용된 typed DataRiver public relative endpoint와 capability | Bolt, DataHub GraphQL, SPARQL, credential, 내부 endpoint 금지 |

생성 버튼은 Studio route로 이동한다. 편집 버튼은 exact graph/ontology/release base를 pin한
새 Studio Draft를 만든다. 불변 release 삭제는 범위 밖이다.

### 3.2 전체 화면 Studio

Studio는 상위 AppShell의 다른 메뉴를 바꾸지 않는 별도 page다. 상단에는 단계, 현재
Draft, 저장 상태, 이름, classification, 나가기와 검토 요청을 표시한다.

~~~text
Step 1 기본정보 → Step 2 Graph Builder (T-Box) → Step 3 Data Enricher (A-Box)
~~~

| 단계 | 입력 | 영속 결과 | 다음 조건 |
|---|---|---|---|
| 1 기본정보 | 이름, endpoint alias, active DOMAIN vocabulary, PUBLIC/INTERNAL/CONFIDENTIAL/RESTRICTED | Studio Draft만 생성/갱신. Registry Asset/release 아님 | alias uniqueness, 형식, Workspace/domain 권한과 source version 검증 |
| 2 T-Box | block, 클래스/속성/관계/제약, source reference, proposal 결정 | typed T-Box draft operation과 layout | schema와 source pin 검증 |
| 3 A-Box | T-Box 요소별 source binding/mapping rule | versioned A-Box binding draft와 whitelist rule | mapping 검증 또는 명시적 unbound reason |
| 완료 | Studio Draft materialize | Graph, immutable candidate ontology, mapping spec의 원자적 생성 | 명령 read-back 성공 |

Step 1에서 빈 graph를 만들지 않는 이유는 불완전 ontology를 Registry, GraphRAG, projection,
release consumer에 보이지 않게 하기 위함이다. Studio Draft는 author만 보며 명시적
Discard 전까지 만료 없이 auto-save된다. Discard도 audit를 위해 terminal row로 남으며
Knowledge release truth는 아니다.

Step 3에서 외부 source를 읽고 graph fact를 같은 HTTP/DB transaction 안에 적재하지 않는다.
Step 3은 mapping을 검증하고, 완료 명령이 graph/ontology/binding spec을 원자적으로
materialize한 뒤 사용자가 선택한 경우 별도 durable A-Box run을 enqueue한다. 따라서
materialize 실패에는 job이 없고, job/provider 실패는 이미 만든 immutable schema나
binding spec을 부분 변경하지 않는다.

`endpoint_alias`는 사용자가 입력하며 immutable published API identity다. CREATE draft가
REVIEW로 전환되기 전에는 수정할 수 있지만 이후에는 고정한다. materialize command는 이를
기존 `knowledge.graphs.slug`에 저장하고 Workspace 내 draft/graph 충돌을 원자적으로 거부한다.
일반 Studio create의 graph type은 `CURATED_KNOWLEDGE`, 두 managed 기본 Asset은
`CATALOG_MIRROR`다. `ANALYTIC_PRODUCT`는 별도 create intent 없이는 선택할 수 없으며
이름에서 alias/type을 추측하지 않는다.

### 3.3 Step 2 Graph Builder

Graph Builder는 순서가 있는 아코디언 block stack이다. Header는 제목, kind, 가중치,
source 상태, proposal 수, validation 상태를 보인다. 가중치는 필수 정수 percentage
`0..100`이며 클라이언트 기본값을 만들지 않는다. merge는 canonical element별 block을
`(weight, ordinal)` 오름차순 fold하고 뒤의 property/rule key가 앞의 값을 덮어쓴다.
값 제거는 빈 값이 아니라 명시적 typed tombstone만 허용한다. 동률 LIFO도 classification,
provenance, source pin, ontology validation을 우회하지 않는다.

| Block kind | UI 용어 | 허용 입력 | 결과 |
|---|---|---|---|
| DIRECT | 직접 정의 | 안전 schema DSL/Cypher subset, React Flow 편집 | typed class/property/relation/rule draft operation |
| FILE_SCHEMA_INFERENCE | 파일 기반 스키마(Entity/Relation) 추론 | 검증된 file snapshot + 사용자 의도 | 구조 후보 proposal이며 **데이터 적재가 아님** |
| CATALOG_METADATA | DB 활용 | local catalog asset과 선택한 metadata aspect/field | schema 후보 또는 명시적 source reference |
| ASSET_RELEASE | 다른 Asset 붙이기 | 검색으로 찾은 다른 Asset의 정확한 release | release-pinned schema reference |

block N을 펼치면 이전 enabled block의 ACCEPTED operation을 순서대로 fold한 base graph가
editor/canvas에 나타난다. 현재 block의 변경은 별도 operation layer로 저장하므로 이전 block
row를 복사·수정하지 않는다. block 순서/활성 변경은 deterministic weighted re-fold와
validation을 거친다. 같은 canonical element의 property/rule conflict만 승인된
weight/LIFO 규칙으로 해결하며 element kind, endpoint 또는 classification 충돌은 validation
error로 남긴다.

`DB 활용` picker는 권한 처리된 table Asset을 복수 선택하고 identity/read-only URN,
table name, domain, description/term/tag, field path, field description/term/tag aspect를
checkbox로 선택한다. 요청 body는 임의 URN이나 DataHub query가 아니라 local Asset UUID,
exact source version과 server-returned aspect/field token만 보낸다. `다른 Asset 붙이기`도
검색 결과의 정확한 release ID/content hash만 pin한다.

#### 직접 정의

- 좌측 editor의 라벨은 `Schema Cypher (안전 subset · 실행되지 않음)`이며 CREATE-only
  schema subset만 다룬다. MATCH, MERGE, DELETE, CALL, LOAD CSV,
  procedure, parameter, URL, escape된 임의 label은 parse 오류다.
- canonical draft element는 `CLASS`, `PROPERTY`, `RELATION`, `CONSTRAINT`다. Class는 이름,
  의미/정의, 동의어, category/subcategory와 hierarchy를, Property는 owner class,
  datatype/unit/cardinality를, Relation은 source/target/domain/range/direction/cardinality를
  typed field로 가진다. Constraint는 승인된 enum/parameter만 허용하고 실행식을 받지 않는다.
- 우측 canvas에서 수정하면 canonical typed operation을 바탕으로 editor text를 재생성한다.
- editor text 변경 시 versioned parser와 기존 alias-to-stable-ID symbol table이 만든 typed
  operation만 canvas를 갱신한다. parse할 때마다 UUID를 재생성하지 않는다. 오류 시 마지막
  valid canvas를 유지하고 오류 위치를 보인다.
- 저장은 text가 아니라 typed operation, local parser version, editor checksum, draft
  optimistic version을 저장한다. Neo4j/Cypher endpoint는 없다.

#### LLM/파일 기반 제안

Schema Assistant와 파일 기반 추론은 TBoxProposal을 만든다. 제안 node/edge는 점선,
별도 색상, proposal badge로 보이며 accepted 요소와 구분된다.

- `현재 그래프에 적용`은 `MERGE_INTO_CURRENT` proposal 생성 mode다. 이름과 달리 수락 전
  existing operation을 바꾸지 않는다.
- `추가 그래프 생성`은 `APPEND_LAYER` proposal 생성 mode다. layout 영역은 분리하지만 semantic element
  ID가 겹치면 수락 전 사용자가 해결한다.
- proposal에는 source snapshot/version, parser/model binding hash, prompt policy/version,
  confidence, evidence locator, normalized output hash가 붙는다.
- 민감 source가 provider inference 부적합이면 provider 접근 전에 unavailable/denied로 끝난다.
  모델 오류를 재주입하는 무한 self-healing loop는 허용하지 않는다.
- provider/file 분석은 HTTP 요청 안에서 장시간 수행하지 않는다. 별도 fenced proposal job이
  `202`로 생성되고, 결과 typed proposal만 preview된다. 채팅 원문 보존은 별도 retention
  계약이 없으므로 기본 영속 대상이 아니며, proposal intent/output hash와 typed 결과만 남긴다.

### 3.4 Step 3 Data Enricher

상단에는 accepted T-Box만 보인다. class/relation 선택 시 하단 binding inspector가 열린다.

Mapping readiness와 instance ingestion을 한 badge로 섞지 않는다.

| Mapping badge | 정확한 의미 |
|---|---|
| 미바인딩 | 허용 mapping spec가 없음 |
| 초안 | source/rule 작성 중이며 검증·materialize 전 |
| 검증됨 | source version, field allowlist, type/unit/cardinality/policy가 유효 |
| 오래됨 | source schema/version 또는 T-Box 변경으로 재검증 필요 |

| Ingestion badge | 정확한 의미 |
|---|---|
| 실행 전 | 유효 mapping은 있으나 instance job을 실행하지 않음 |
| 대기/실행 중 | exact binding/source/T-Box pin으로 durable run 진행 중 |
| 실패 | 최근 run 실패; bounded 오류 코드만 인가된 사용자에게 표시 |
| Changeset 초안 | run이 typed instance DRAFT를 만들었으나 아직 발행되지 않음 |
| 발행됨 | 해당 run changeset이 독립 검토·발행 release에 포함됨 |

A-Box는 class와 relation 모두에 가능하다. Mapping table은 SUBJECT_ID, PROPERTY,
EDGE_LINK, EDGE_PROPERTY만 허용한다. 각 row는 source table/file field, target schema
element, transform/version, source/canonical unit, source version, classification/provenance
policy를 보인다. raw SQL join, Cypher, DataHub URN 문자 입력, provider endpoint 입력은 없다.

파일은 immutable upload manifest/snapshot, DB는 local catalog의 table Asset UUID와
server-returned field path, exact catalog projection version, exact detailed provider-schema
version을 pin하고, 다른 Asset은 release ID/hash를 pin한다. 실제 instance extraction은 별도 durable
mapping job가 만드는 typed changeset이며 Studio 저장이 Neo4j/release를 바꾸지 않는다.

현재 catalog projection은 table Asset UUID/source version은 제공하지만 field UUID와 모든
field description/tag/term을 정규화해 소유하지 않는다. 따라서 구현은 존재하지 않는 field
UUID를 만들지 않는다. Knowledge application port가 허용된 bounded catalog detail을
해석해 `asset UUID + exact source version + server-returned field path + selected aspect`의
immutable typed source reference를 만든다. 여기서 exact source는 권한 처리된 catalog
projection과 상세 DataHub schema의 두 version fence를 뜻한다. 향후 canonical field UUID가 승인되면 새 source
contract version으로만 전환한다.

그래프에서 `검증됨` 또는 `발행됨` mapping을 가진 target은 활성 스타일로 보이지만, legend와
accessible label에 mapping/ingestion 두 상태를 모두 표시한다. 색상만으로 상태를 구분하지
않는다.

### 3.5 system-managed 기본 Asset

| Asset | graph type | 기준 source | 매일 결과 |
|---|---|---|---|
| 전체 metadata lineage | CATALOG_MIRROR | 권한 처리된 catalog/lineage projection | 승인된 immutable T-Box/mapping policy가 일치하면 새 A-Box PUBLISHED receipt, 아니면 Draft/failed/no-op receipt |
| 데이터 용어사전 | CURATED_KNOWLEDGE | 승인된 DataHub vocabulary local projection | 승인된 immutable T-Box/mapping policy가 일치하면 새 A-Box PUBLISHED receipt, 아니면 Draft/failed/no-op receipt |

Airflow는 trigger일 뿐 정본이 아니다. refresh 상태와 source/mapping/version/run evidence는
PostgreSQL에 남긴다. 자동 발행은 System Admin이 별도로 승인한 managed policy가 exact graph,
PUBLISHED T-Box checksum, source/mapping contract, service principal, schedule,
classification ceiling을 모두 고정한 경우에만 허용한다. drift나 불완전 입력에서 active
release를 덮어쓰지 않으며 각 실행은 atomic publication receipt를 남긴다.

## 4. Frontend route와 component 계획

현재 앱은 query parameter 기반 Page union을 사용하므로 새 React Router를 도입하지 않는다.

| Route | 목적 | 허용 상태 |
|---|---|---|
| `page=knowledge` | Registry | `asset=<UUID>`, `drawerTab=overview|versions|bindings|preview|api` |
| `page=knowledge-studio` | 전체 Studio | 신규 Step 1은 draft 없음; 저장 후 `draft=<UUID>`, `step=basic|tbox|abox` |
| page=knowledge-chat | 기존 Knowledge Chat | 현재 계약 유지 |
| 잘못된 Studio query | Registry fallback | malformed UUID/step enum은 API 호출 없이 안내; 형식이 맞는 not-found/denied는 동일한 server response |

`workspace`는 기존 방식대로 보존한다. Knowledge route를 벗어날 때 `asset`, `drawerTab`,
`draft`, `step`만 제거하고 다른 feature query를 해석하지 않는다. syntactically valid하지만
존재하지 않거나 권한 없는 draft/asset은 동일한 not-found 응답을 사용한다. Full-screen은
브라우저 전체 화면 API가 아니라 AppShell content 전체를 쓰고 local Knowledge menu를 숨기는
Studio shell을 뜻한다.

~~~text
App
├─ KnowledgeRegistryPage
│  ├─ KnowledgeWorkspaceNav (Registry, Knowledge Chat만)
│  ├─ RegistryToolbar / KnowledgeAssetTable (manual server pagination/sorting)
│  └─ KnowledgeAssetDrawer
│     ├─ AssetOverviewTab / AssetVersionHistoryTab
│     ├─ AssetBindingsAndRunsTab / AssetGraphPreviewTab / AssetTypedApiTab
├─ KnowledgeStudioPage
│  ├─ StudioHeader / StudioStepProgress / BasicInformationStep
│  ├─ TBoxBuilderStep
│  │  ├─ TBoxBlockStack / TBoxBlockAccordion / BlockKindChooser
│  │  ├─ SchemaCypherEditor / TBoxGraphCanvas / TBoxProposalOverlay
│  │  ├─ SchemaAssistant / ProposalDecisionBar
│  │  └─ CatalogTablePicker / MetadataAspectSelector / AssetReleasePicker
│  └─ ABoxEnricherStep
│     ├─ TBoxBindingMap / BindingTargetInspector
│     └─ BindingSourcePicker / MappingWhitelistEditor / BindingValidationAndRunPanel
└─ KnowledgeChatPage (unchanged)
~~~

KnowledgeWorkspaceNav는 Knowledge 내부 전용이다. AppShell primary navigation과 다른
menu component/API type을 건드리지 않는다. 현재 shared `FlowCanvas`는 proposal edge style,
node/edge edit, stable layout event를 충분히 표현하지 못하므로 이를 변경해 다른 화면에
회귀를 만들지 않는다. `TBoxGraphCanvas`가 `@xyflow/react`를 직접 조합하고, shared
`FlowCanvas`는 release preview 전용으로 유지한다. 같은 이유로 Registry는 현재
client-side sort 전용 `DenseDataTable`을 확장하지 않고 `KnowledgeAssetTable`에서 TanStack의
manual pagination/sorting을 사용한다.

권장 파일 경계는 다음과 같다.

~~~text
frontend/src/features/knowledge/
├─ routes/knowledgeLocation.ts
├─ api/knowledgeRegistryApi.ts
├─ api/knowledgeStudioApi.ts
├─ api/knowledgeQueryKeys.ts
├─ registry/KnowledgeRegistryPage.tsx
├─ registry/KnowledgeAssetTable.tsx
├─ registry/KnowledgeAssetDrawer.tsx
├─ registry/tabs/*
├─ studio/KnowledgeStudioPage.tsx
├─ studio/StudioShell.tsx
├─ studio/basic/BasicInformationStep.tsx
├─ studio/tbox/*
├─ studio/abox/*
├─ model/tboxCodec.ts
├─ model/tboxReducer.ts
└─ KnowledgeChatPage.tsx              # behavior unchanged
~~~

`App.tsx` 변경은 lazy import와 `page === 'knowledge-studio'` 분기 추가로 제한한다.
Knowledge feature 내부 API/DTO는 `frontend/src/api/types.ts`의 거대한 공용 표면에 계속
추가하지 않고 feature module로 이동한다. 공통 `ApiClient`와 인증 경계만 재사용한다.

### 4.1 상태 소유권

- server state: Registry page, drawer tab, persisted Studio Draft, accepted operations,
  proposals, binding specs와 runs는 TanStack Query가 소유한다.
- semantic editor state: accepted typed T-Box operation reducer가 유일한 source of truth다.
  Cypher text와 React Flow node/edge는 codec으로부터 파생한다.
- transient state: 현재 invalid text buffer, selection, viewport와 form은 component state다.
  Step 1의 미전송 typed form만 ADR-0059의 same-origin IndexedDB recovery queue에 복제할 수
  있다. 이 복구 레코드는 token/권한/원시 Workspace·Subject를 포함하지 않으며 server
  Draft나 accepted canvas를 덮어쓰지 않는다.
- proposal state: accepted graph와 별도 collection/overlay다. Accept 성공 응답을 받은 뒤에만
  accepted reducer/query cache에 합친다.
- route state: asset/drawer tab 또는 draft/step만 URL에 두고 graph payload, 권한, completion
  상태를 URL/localStorage에 넣지 않는다.

### 4.2 상태·성능 규칙

- Server query key는 workspace, graph/draft, release/ontology version, authorization revision을 포함한다.
- Registry는 summary endpoint 한 개로 렌더하고 drawer tab은 열릴 때만 AbortSignal을 가진
  bounded request를 실행한다.
- table, version history, binding run history는 keyset cursor이며 브라우저가 전체 release/node/edge를
  수집해 통계를 계산하지 않는다.
- React Flow는 server 축소 preview와 현재 studio draft만 렌더한다. hidden/unmounted 화면의
  polling·animation을 중단한다.
- Canvas 위치/접힘 상태는 presentation metadata다. semantic T-Box는 typed operation store가
  유일한 source of truth다.
- 모든 write는 Idempotency-Key와 ETag/If-Match를 사용한다. 충돌 시 재조회/rebase UI를
  제공하며 자동 덮어쓰지 않는다.
- Step 1 입력은 각 변경 직후 복구 queue에 먼저 기록하고 서버 호출은 1.5초 debounce한다.
  `412`에서는 로컬 입력을 보존한 채 최신 버전 불러오기와 최신 ETag 기반 명시적 덮어쓰기
  중 하나를 선택한다. 브라우저 저장소 삭제·eviction·기기 손실까지 100% 보존한다고
  주장하지 않는다.
- Registry page는 allowlisted server sort와 opaque keyset cursor만 사용한다. target dataset의
  `EXPLAIN (ANALYZE, BUFFERS)` 전에는 응답시간이나 수용량을 주장하지 않는다.

## 5. Backend domain 및 DB 모델

### 5.1 유지할 정본

| Existing table | 유지 역할과 필요한 additive 변경 |
|---|---|
| knowledge.graphs | 소비 가능한 지식 Asset aggregate와 active release pointer. `domain_ref_id/kind/source_version`, `created_by`, `updated_by`를 legacy-nullable로 추가하고 신규 materialize에서는 필수로 검증한다. `graph_type`은 업무 domain으로 재사용하지 않는다. |
| knowledge.ontology_versions | immutable canonical T-Box schema document/checksum. schema contract version과 creator/base provenance를 추가하고 element index의 재구축 원천으로 유지한다. |
| knowledge.changesets, change_operations, validation_results | instance/A-Box typed edit와 독립 검토 |
| knowledge.releases, release_nodes, release_edges | immutable assertion/relationship snapshot |
| knowledge.projection_deployments | PostgreSQL/Neo4j projection receipt |
| knowledge.source_*와 extraction_runs | 현재 PDF source-analysis의 pinned/fenced evidence |

Studio proposal/binding은 이를 우회하거나 mutable release content를 바꾸지 않는다.
기존 graph의 누락 creator/editor/domain은 idempotency나 현재 사용자로 추정 backfill하지 않는다.
새 domain reference는 `(workspace_id, id, kind=DOMAIN)` typed local vocabulary identity와 exact
source version을 pin한다. Knowledge authorization은 이를 `ResourceAttributes.domain_id`로
전달하며 repository query도 허용 domain predicate를 적용한다.

### 5.2 새 entity 제안

| Entity/table | 핵심 속성 | 목적 및 제약 |
|---|---|---|
| knowledge.studio_drafts | workspace, author, kind CREATE/EDIT, name, endpoint alias, domain ref/version, classification, base graph/ontology/release nullable refs, state, step, version, last autosave/discard times | Step 1~3 author-scoped aggregate. 명시적 Discard 전 만료 없이 보존하고 신규 CREATE draft의 graph type은 server intent로 결정한다. materialize 전 Registry/GraphRAG에서 보이지 않음 |
| knowledge.source_references | workspace, kind UPLOAD_MANIFEST/CATALOG_ASSET/GRAPH_RELEASE, exactly-one local ref, exact version/hash/classification, bounded typed selection document/hash | T-Box input과 A-Box binding이 공유하는 immutable source pin. URL/URN/object coordinate 대신 local UUID와 opaque evidence만 외부 노출 |
| knowledge.tbox_draft_blocks | draft, ordinal, kind, title, weight, merge mode, state, version | 아코디언/layer 설계 provenance. draft+ordinal unique, weight는 `0..100` 정수이며 property/rule 충돌의 merge precedence임 |
| knowledge.tbox_block_inputs | block, source reference, purpose, ordinal | immutable source와 block 연결. 같은 input의 중복 연결을 금지 |
| knowledge.tbox_draft_operations | draft, block, proposal nullable, sequence, element kind, stable element ID, typed document, provenance, state | CLASS/PROPERTY/RELATION/CONSTRAINT UPSERT/DELETE. PROPOSED는 preview 전용, ACCEPTED만 materialize 대상 |
| knowledge.tbox_proposals | draft/block, proposal kind, source/model/parser binding hash, input/output hash, state, confidence summary, expiry | LLM/file/catalog/asset 제안 envelope. provider response/secret 저장 금지 |
| knowledge.tbox_proposal_jobs/attempts/events | draft/block, request/source/base/auth/model pins, state/stage, lease epoch/token hash, attempts와 append-only transition evidence | fallible provider/file inference를 API process 밖에서 실행. result는 TBoxProposal뿐이며 accepted graph를 직접 수정하지 않음 |
| knowledge.tbox_draft_layouts | draft, bounded layout document/checksum, version, updater | React Flow position/layer/collapse. schema validity에 사용하지 않음 |
| knowledge.ontology_elements | ontology version, schema checksum, stable element ID, kind, canonical/display name, definition/aliases/category, datatype/unit, classification, immutable document | materialize된 T-Box의 재구축 가능한 searchable index. canonical truth는 ontology version document/checksum이며 rows는 같은 transaction에서 파생 |
| knowledge.ontology_relation_endpoints | ontology version, relation element, source/target class, direction, cardinality | relation domain/range 및 mapping validation index |
| knowledge.abox_binding_drafts / abox_mapping_rule_drafts | studio draft, target stable element, source reference, readiness state/version; method/source field/target/transform/unit typed rule | Step 3 편집용 mutable aggregate. 네 mapping method 외 거부하고 materialize 전 ontology FK를 가장하지 않음 |
| knowledge.abox_binding_versions | graph/ontology version, target ontology element, source reference, version/supersedes, mapping hash, creator/times | materialize된 immutable mapping spec header. spec row는 수정하지 않음 |
| knowledge.abox_mapping_rules | binding version, ordinal, method, server-returned source field path, target property/relation ref, transform ID/version, source/canonical unit, typed condition | immutable whitelist 한 행. raw SQL/join/expression/URN 입력 금지 |
| knowledge.abox_binding_validation_results | binding version, checked source/mapping/T-Box/auth hash, outcome VALIDATED/STALE, bounded codes, validator/version/time | append-only readiness evidence. latest valid evidence로 mapping badge를 계산 |
| knowledge.abox_ingestion_runs | binding version, pinned source/mapping/T-Box/auth hashes, run state/stage/counters, proposed changeset, bounded error code, version/times | 실제 instance extraction 정본. 성공도 typed DRAFT changeset만 만들며 release 직접 변경 금지 |
| knowledge.abox_ingestion_attempts/events | run/lease epoch/token hash/worker fingerprint와 append-only evidence | 외부 실행 시 ADR-0044 수준의 fencing/retry/cancel/RLS 계약 |
| knowledge.managed_graph_policies/refresh_runs | graph, managed kind, source/mapping contract, schedule ref, latest draft/run receipt | 두 기본 Asset의 일일 refresh intent/evidence. scheduler 상태가 정본이 아님 |

모든 새 table은 workspace_id, FORCE RLS, composite workspace foreign key, least-privilege
grant, optimistic version, audit/outbox boundary를 가진다. internal UUID, opaque locator hash,
exact version/hash만 저장한다. bucket/object key, endpoint, credential, raw prompt/response,
arbitrary SQL/Cypher는 저장하지 않는다.

관계의 핵심은 다음과 같다.

~~~text
StudioDraft
├─ TBoxDraftBlock ── TBoxBlockInput ── SourceReference
│  ├─ TBoxDraftOperation
│  └─ TBoxProposal ← TBoxProposalJob/Attempt/Event
└─ ABoxBindingDraft ── ABoxMappingRuleDraft ── SourceReference

materialize
├─ Graph ── OntologyVersion ── OntologyElement/RelationEndpoint
└─ ABoxBindingVersion ── ABoxMappingRule / ABoxBindingValidationResult
                         └─ ABoxIngestionRun/Attempt/Event ── GraphChangeSet
                                                                  └─ Release
~~~

### 5.3 domain/application/infrastructure 경계

권장 backend 파일 경계는 다음과 같다.

| Layer | 제안 모듈과 책임 |
|---|---|
| domain | `domain/knowledge_studio.py`: draft/block/proposal/binding state machine, typed schema/mapping validation. SQLAlchemy/FastAPI/provider import 금지 |
| application | `services/knowledge_registry.py`, `services/knowledge_studio.py`: authorization, idempotency, materialize orchestration |
| ports | `KnowledgeRegistryReader`, `KnowledgeStudioRepository`, `CatalogMetadataSelectionPort`, `UploadManifestReader`, `TBoxProposalRunner`, `ABoxMappingRunner` |
| infrastructure | `db/models/knowledge_studio.py`, `db/knowledge_studio.py`, catalog/upload read adapters, provider worker adapter |
| HTTP | 별도 `knowledge_registry.py`, `knowledge_studio.py` router/schema. 기존 `knowledge.py` graph/release API는 호환 유지 |

Knowledge domain은 Catalog DB model을 직접 import하거나 Catalog row를 수정하지 않는다.
Catalog adapter는 현재 subject의 ABAC가 적용된 table/detail만 반환하고 Knowledge service가
그 결과를 bounded `SourceReference`로 pin한다. LLM/file worker도 accepted proposal이나
changeset을 직접 publish할 port를 갖지 않는다.

### 5.4 lifecycle 및 아키텍처 결정 게이트

~~~text
StudioDraft
  → accepted T-Box operation + source pin
  → schema validation
  → atomic materialize
       → Graph(DRAFT) + immutable OntologyVersion + OntologyElement index
       → versioned A-Box binding/rule
  → durable mapping run (optional)
       → GraphChangeSet(DRAFT)
       → independent review/publish
       → immutable Release
       → optional verified Neo4j shadow
~~~

기존 Asset 수정은 base graph, release, ontology checksum, source version을 처음에 pin하고
materialize/execute 때 다시 확인한다. 달라지면 STALE로 끝내며 최신 상태에 자동 rebinding하지 않는다.

현재 changeset은 instance operation 중심이다. T-Box schema version을 active로 승격하는
정확한 review shape는 구현 전 ADR 게이트다.

1. schema-only/composite changeset을 existing governed publication command에 추가하거나,
2. 동등한 maker/checker, receipt-backed activation, provenance, replay guarantee를 가진
   별도 schema changeset을 도입한다.

어느 쪽도 published release가 가리키는 ontology를 수정하지 않는다.

### 5.5 제약·인덱스

- draft operation은 draft+sequence unique이고 proposal accept는 one-time, version-fenced transition이다.
- ontology element는 ontology version+stable element unique/canonical name index, relation endpoint는
  source/target class index를 갖는다.
- source reference는 source kind별 exactly-one FK와 version/hash shape CHECK를 가진다.
- mapping rule은 binding version+ordinal unique다. 동일 ontology target/source의 current
  validated binding materialize는 graph lock과 partial unique policy로 직렬화한다.
- mapping run은 mapping/T-Box/source/request hash를 pin한다. attempt/event는 append-only이며
  raw lease token 대신 hash만 저장한다.
- Registry summary는 release의 저장된 node/edge count와 pre-aggregated binding/run subquery를
  한 bounded SQL query로 결합한다. graph마다 release_nodes/release_edges/source job을 순회하는
  N+1 조회를 금지한다. target EXPLAIN이 query budget을 넘을 때만 별도 transactional
  registry read-model table을 ADR과 reconciliation 계약으로 도입한다.

## 6. 제안 API boundary

현재 `GET /api/v1/knowledge/graphs`는 배열 응답이므로 같은 path를 page envelope로 바꾸지
않는다. 기존 create/changeset/release/snapshot/source-analysis/GraphRAG route도 유지한다.
새 read model과 Studio는 별도 router를 사용한다.

| Route | 용도 | 제한 |
|---|---|---|
| `GET /knowledge/registry/assets?cursor=&limit=&sort=` | Registry summary page | opaque keyset cursor, allowlisted sort, permission/domain-filtered aggregate만 |
| `GET /knowledge/registry/assets/{id}/summary` | drawer overview | bounded count, latest version, permitted API capability |
| `GET /knowledge/registry/assets/{id}/versions?cursor=&limit=` | drawer history | bounded rows, snapshot body 없음 |
| `GET /knowledge/registry/assets/{id}/bindings?cursor=&limit=` | drawer bindings/runs | source locator/provider secret 제거 |
| `GET /knowledge/registry/assets/{id}/preview?...` | graph preview | active governed release, server node/edge cap와 truncation evidence |
| `POST /knowledge/studio-drafts` | Step 1 create/edit draft | kg.create 또는 kg.edit, Idempotency-Key, author-bound response |
| `GET/PATCH /knowledge/studio-drafts/{id}` | Studio recovery/save | owner policy와 ETag; text Cypher body 없음 |
| `GET /knowledge/studio-options/domains?...` | Step 1 DOMAIN picker | local UUID/display/source version, active/authorized entries만 |
| `GET /knowledge/studio-options/catalog-assets?...` | DB/metadata source picker | permitted bounded summary와 opaque cursor; provider query/credential 없음 |
| `GET /knowledge/studio-options/graph-releases?...` | 다른 Asset picker | governed exact release ID/hash만 |
| `GET /knowledge/studio-options/uploads?...` | file source picker | requester가 사용할 수 있는 accepted immutable manifest만 |
| block/input/operation child commands | T-Box 작성 | fixed enum/typed schema, source UUID, raw query 금지 |
| `POST .../tbox/proposal-jobs` | assistant/file proposal 시작 | `202`, exact draft/source/base/auth/model pin |
| `GET .../tbox/proposal-jobs/{job}` | proposal 진행/결과 | owner-bound bounded state; provider body 없음 |
| `POST .../tbox/proposals/{proposal}/accept|reject` | preview 결정 | current draft/base/source pin 재검증 후 one-time transition |
| `POST .../validate-tbox` | schema validation | validation evidence만 반환 |
| `POST .../materialize` | graph/ontology/binding atomic create | kg.create 또는 kg.edit, idempotent, canonical read-back |
| binding/rule/run commands | A-Box 관리 | whitelist only; worker/source contract가 없으면 unavailable |

Phase 3 Data Enricher의 첫 구현 route는 기존 `/knowledge/studio/drafts` boundary 아래에
additive하게 둔다.

| Route | 용도 | 제한 |
|---|---|---|
| `GET .../drafts/{id}/abox` | accepted T-Box와 현재 Binding Draft read model | author/ABAC, bounded elements/rules, ETag/no-store |
| `GET .../drafts/{id}/abox/sources?q=&cursor=&limit=` | Dataset 후보 검색 | local authorized DataHub projection, dataset types only, opaque cursor |
| `GET .../drafts/{id}/abox/sources/{asset_id}` | 선택 Dataset 컬럼 계약 | existing Catalog service/DataHub Gateway/cache, local UUID와 field path만 반환 |
| `PATCH .../drafts/{id}/abox/bindings/{target}` | 한 Class/Relation의 mapping rule 부분 교체 | Idempotency-Key + If-Match, four-method whitelist, T-Box/source 재검증 |

이 increment의 `Mapped`는 rule이 하나 이상 영속화되었다는 뜻이며 `VALIDATED`, ingestion,
changeset 또는 publication을 뜻하지 않는다. accepted T-Box 요소가 없는 Draft에는 임의
node/property를 만들지 않고 명시적인 empty state를 반환한다.

drawer API tab은 permission이 허용된 product-facing relative path와 capability 상태만 보인다.
API key, Bolt URI, provider URL을 제공하지 않으며, 클릭된 route도 별도 authorization을 다시 통과한다.

모든 page envelope는 `items`, `next_cursor`, bounded server limit과 truncation/partial evidence를
명시한다. creator/editor display name은 server가 같은 query/read model에서 안전하게 resolve하고,
브라우저가 subject별 API를 반복 호출하지 않는다.

## 7. 단계적 rollout과 영향 격리

| Phase | additive 결과 | 사용자 cutover |
|---|---|---|
| 0 계약 | ADR, API/DB schema, weight/endpoint alias/graph type/source/retention 결정 | 없음 |
| 1 Registry backend | 새 paged summary/drawer API와 query evidence | 기존 UI 유지 |
| 2 Studio foundation | author draft, full-screen shell, Step 1, migration/RLS | server capability가 허용한 reviewer만 접근 |
| 3 T-Box | block/editor/canvas/proposal job/Accept/materialize | 기존 Mode A는 유지 |
| 4 A-Box | binding draft/version, 기존 PDF job 연결, mapping run | 기존 Mode B parity를 검증 |
| 5 UI cutover | Registry drawer와 Studio를 기본으로 전환, Data Ingestion menu/create Dialog 제거 | 이 시점에만 최종 두 메뉴 GNB |
| 6 managed Asset | 두 default graph의 policy-pinned daily A-Box sync와 atomic PUBLISHED/no-op/failed receipt | target security/operations gate 후 |

cutover capability는 서버가 현재 Workspace에서 준비된 API/schema/worker contract를
보고하는 값이다. 브라우저 상수나 mock fallback이 아니다. Phase 5 전에는 기존 UI를
삭제하지 않고, Phase 5 후 한 release 동안 rollback 가능한 source를 보존할 수 있으나 두 UI를
동시에 쓰게 해 이중 정본을 만들지 않는다.

다른 메뉴 영향 검증은 primary navigation 목록, AppShell, Catalog, Registration,
Change Management, general Chat, Admin의 route/query/cache state를 대상으로 한다. 허용된
공용 변경은 `Page`에 `knowledge-studio`를 추가하고 Knowledge 전용 query parameter를
정리하는 것뿐이다.

## 8. 비기능 요구사항과 완료 기준

| ID | Requirement | Acceptance |
|---|---|---|
| KSR-SEC-01 | Raw execution 금지 | browser/LLM/upload text가 SQL, Cypher, GraphQL, SPARQL, provider URL pass-through가 될 수 없음 |
| KSR-SEC-02 | 제안 격리 | Accept 전 ontology/release/Neo4j/changeset operation에 영향 없음; Accept 시 source/classification/base pin 재검증 |
| KSR-SEC-03 | 정확한 scope | draft, drawer, selector, asset attach, binding run 모두 Workspace/ABAC/classification/author/release 확인 |
| KSR-SEC-04 | Domain ABAC | graph/studio/source selector query가 pinned domain UUID를 authorization resource와 SQL predicate에 반영 |
| KSR-PERF-01 | Bounded registry | pagination/aggregate read model 사용, row별 snapshot/release/job 추가 fetch 없음 |
| KSR-PERF-02 | Bounded graph UI | server cap/viewport/truncation 표시, hidden tab polling 중단 |
| KSR-DATA-01 | 정본 보존 | Studio/A-Box가 PostgreSQL release semantics 유지, Neo4j 실패가 release를 변경하지 않음 |
| KSR-DATA-02 | 재현성 | source, mapping, ontology, transform/parser/model binding hash와 provenance 보존 |
| KSR-DATA-03 | Legacy 정직성 | 과거 graph의 creator/editor/domain을 추측 backfill하지 않고 누락 evidence를 명시 |
| KSR-UX-01 | 정보 정직성 | API/worker 없는 DB/file 기능은 disabled와 사유 표시; 가짜 count/job/LLM result 없음 |
| KSR-COMPAT-01 | API 호환 | 기존 `/knowledge/graphs` 배열 및 release/changeset/Chat 계약을 변경하지 않고 새 router를 additive로 제공 |

구현 완료는 두 메뉴 GNB, full-screen Studio, wide drawer가 다른 menu route/state/API에
회귀 없이 동작하고, Draft/proposal/binding/migration/RLS/negative test/target gate의 증거가
각각 기록되었을 때에만 주장할 수 있다. Local source pass를 production acceptance로 표현하지 않는다.
