# Knowledge Asset 운영 모델 및 사용자 여정

## 1. 화면별 책임

| 화면 | 사용자가 하는 일 | PostgreSQL 정본 | 결과 |
|---|---|---|---|
| 조회 및 생성 | Asset 조회·생성·편집·아카이브, 버전 포커싱 | Graph, Studio Release, Instance Release | 현재 상태와 이력 |
| Studio Step 1 | 이름, alias, Domain, 보안등급 | Studio Draft | Asset 계약 초안 |
| Studio Step 2 | 직접/문서/DB/LLM T-Box 블록 순차 병합 | T-Box block/element/proposal | 검토 전 schema |
| Studio Step 3 | T-Box 대상과 DB source field Binding | A-Box Binding/Rule Draft | 재현 가능한 Mapping 계약 |
| 정보 관리 / 인스턴스·적재 | 직접 입력, 문서+LLM Changeset, Binding 조회, 검토·발행 | Changeset, immutable Release | 운영 A-Box |
| 정보 관리 / 프로파일 | Property 설명, 단위, 동의어 | Property Profile | 구조와 분리된 의미 메타 |
| 정보 관리 / API & Chat | API opt-in, Chat 조건/우선순위 | Delivery Policy | 안전한 제공 범위 |
| Chat Test | 특정 Graph/Release/Node로 GraphRAG 검증 | Release + verified Projection | 인용 포함 테스트 |

## 2. 정본과 파생물

```mermaid
flowchart LR
  D["Studio Draft"] --> SR["Approved Studio Release<br/>T-Box + Mapping contract"]
  SR --> G["Knowledge Asset / Graph"]
  G --> C["Typed A-Box Changeset"]
  C --> IR["Immutable Instance Release"]
  IR --> P["Neo4j Shadow Projection"]
  IR --> API["Typed DataRiver API"]
  DP["Delivery Policy"] --> API
  DP --> CHAT["Platform Chat graph scope"]
  P --> CHAT
```

- PostgreSQL의 Studio Release와 Instance Release가 정본이다.
- Neo4j는 Release hash/count 검증이 가능한 Projection이며 직접 수정 대상이 아니다.
- LLM 결과는 T-Box Proposal 또는 A-Box DRAFT Changeset이다. 자동 Publish 경로는 없다.
- `Mapped`, `Schema Published`, `Instance Published`, `Projection Verified`는 서로 다른 상태다.

## 3. T-Box 구성

Graph Builder는 하나의 accepted editor state에서 Tree, React Flow와 safe-Cypher 표현을
동기화한다. 직접 작성, 문서 업로드, Catalog metadata 검색, LLM Assistant 결과는 모두
Proposal을 거쳐 현재 블록에 병합하거나 새 블록으로 추가한다. 이전 블록은 읽기 전용으로
누적되고 최신 블록에서 이전 Class를 참조할 수 있다. 동일 identity/name 충돌은 기본
`KEEP_ORIGINAL`이며 사용자 승인 없이 덮어쓰지 않는다.

## 4. A-Box 구성

### 직접 입력

발행된 T-Box의 Class/Relationship을 선택해 typed Node/Edge operation을 DRAFT Changeset에
추가한다. 모든 operation은 source reference, locator, version, method와 confidence를
요구한다. 제출, 독립 승인, 발행 후에만 새 Instance Release가 된다.

### 문서 + LLM

검증 업로드된 PDF, CSV, TXT, JSON, XML, HTML과 macro-free DOCX/XLSX/PPTX는 별도 worker가
parser/embedding/extraction 단계를 수행하고 근거가 결합된 DRAFT Changeset을 만든다.
PDF는 실제 page, 나머지는 bounded evidence segment를 사용한다. 실패, stale, 취소와
retry는 durable job state로 표현한다. 모델은 Release를 직접 만들 수 없으며 legacy
DOC/XLS, XML entity, macro/external OpenXML payload는 허용하지 않는다.

### DB Binding

Studio는 Catalog의 로컬 Asset UUID, provider schema version, projection version과 명시적
field allowlist를 고정한다. 현재 승인된 physical reader는 5–10행 Preview/Preflight
계약이며 전체 DB ingestion으로 표현하지 않는다. 전체 적재는 운영자가 등록한 batch
reader, 별도 worker lease/attempt/event와 source read-back이 준비되어야 활성화한다.

## 5. 외부 API와 Chat

Asset의 endpoint alias는 식별자다. Delivery Policy에서 API가 활성화되면 인증된 호출자는
alias resolver에서 현재 active Release의 snapshot, GraphRAG와 export 상대 경로를 받을 수
있다. 모든 실제 호출은 OIDC, Workspace, Domain, Classification과 action authorization을
다시 통과한다.

Chat의 의미 라우터는 GRAPH 여부만 판단한다. 이후 Delivery Policy의 ANY/ALL/제외 조건과
우선순위가 하나의 권한 있는 Graph Release를 선택한다. 동률은 임의 선택하지 않는다.
질문이나 브라우저가 SQL, Cypher, provider URL 또는 credential을 전달할 수 없다.

## 6. 의도적으로 남은 운영 게이트

- 승인된 DB/CSV batch physical reader와 대용량 A-Box worker
- system-managed lineage/glossary 기본 Graph의 scheduler·receipt·managed publish policy
- 목표 환경의 부하/soak, Neo4j rebuild 및 복구 증거

이 항목은 UI success 상태로 가장하지 않으며, capability가 없으면 명시적으로 unavailable
또는 NOT_RUN으로 표시한다.
