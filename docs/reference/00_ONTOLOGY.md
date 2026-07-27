# 온톨로지 참조 노트

> 상태: 비권위 연구 참고자료.
>
> 이 문서는 아이디어와 용어를 정리하며 `docs/README.md`에 등재된 요구사항, ADR,
> 보안 경계 또는 구현 계약을 대체하지 않는다. 충돌할 경우 controlled document와 ADR이
> 우선한다.

## 1. 현재 아키텍처 경계

DataRiver에서 PostgreSQL은 비즈니스 정본을 소유한다. DataHub와 Neo4j는 장애가
발생하거나 다시 구축할 수 있는 외부 projection이며, 브라우저 또는 LLM은 이들에 직접
질의하지 않는다.

```text
[Browser]
    |
    | typed HTTP API
    v
[DataRiver API: 인증 · Workspace/ABAC · 입력 제한 · 감사]
    |
    +--------> [PostgreSQL: canonical business truth]
    |
    +--------> [DataHub adapter: typed metadata operation]
    |
    +--------> [Neo4j adapter: typed and bounded graph operation]
```

다음 경계는 연구 기능에도 그대로 적용한다.

- raw SQL, Cypher, GraphQL 또는 임의 HTTP pass-through를 노출하지 않는다.
- 그래프 탐색은 서버가 소유한 고정 operation/template과 제한된 파라미터만 사용한다.
- 모든 캐시와 provider 호출은 Workspace, 주체, 권한, 정책, source version 범위를
  포함한다.
- provider 결과와 LLM 출력은 신뢰하지 않으며, canonical 데이터로 재검증한다.
- Neo4j 장애 시 catalog 정본이나 권한 판단을 Neo4j로 대체하지 않는다.

## 2. 모델링 용어

온톨로지 후보는 다음 네 요소로 설명할 수 있다.

1. `C` (Classes/Concepts): `Dataset`, `Table`, `Column`, `BusinessTerm` 같은 개념
2. `H` (Hierarchical relations): `is-a`, `subClassOf` 같은 분류 관계
3. `R` (Non-taxonomic relations): 소유, 계보, 용어 매핑 같은 연관 관계
4. `A` (Axioms/Rules): 도메인 제약과 검증 규칙

LPG와 RDF는 목적에 따라 평가한다.

| 후보 | 적합한 경우 | 도입 전 확인 |
|---|---|---|
| LPG/Neo4j | bounded lineage, 영향도 탐색, 속성 중심 projection | typed operation, 깊이·행 수 제한, rebuild/검증 계약 |
| RDF/SHACL | 표준 vocabulary, 형식 제약과 논리 검증이 핵심인 경우 | 별도 ADR, 운영 복잡도, canonical ownership |

현재 Neo4j 사용 사실이 RDF 또는 다른 표현 방식의 영구 배제를 뜻하지 않는다. 저장 기술
결정은 승인된 요구사항과 ADR로만 확정한다.

## 3. Whitelist 매핑 후보

다음은 구현 테이블명이 아닌 매핑 정의의 개념 예시다.

| 의미 | 입력 종류 | 매핑 방식 | 주체 | 대상 | 관계 또는 속성 |
|---|---|---|---|---|---|
| 테이블-컬럼 소유 | 정규화된 catalog record | `EDGE_LINK` | `Table` | `Column` | `HAS_COLUMN` |
| 컬럼 물리명 | 정규화된 catalog record | `PROPERTY` | `Column` | - | `physical_name` |
| 비즈니스 용어 매핑 | 승인된 vocabulary binding | `EDGE_LINK` | `Column` | `BusinessTerm` | `MAPPED_TO_TERM` |
| 외래키 계보 | 검증된 constraint record | `EDGE_LINK` | `Column` | `Column` | `FOREIGN_KEY_TO` |

매핑 정의에는 최소한 다음 항목이 필요하다.

- 입력 record type과 schema version
- canonical identifier 및 source locator
- 허용 node/edge type과 속성
- Workspace, classification, policy 및 source version
- projection idempotency key와 rebuild version
- 누락·충돌·삭제 처리 및 감사 증거

입력 테이블명이나 컬럼명을 그대로 실행문으로 보간하지 않는다. 원천 수집, 정규화,
projection 기록은 각 adapter의 typed contract를 통과해야 한다.

## 4. 안전한 projection 흐름

```text
[Approved source record]
          |
          v
[Typed normalization + schema validation]
          |
          v
[Workspace/ABAC + classification policy]
          |
          v
[Versioned allowlist mapping]
          |
          v
[Idempotent projection adapter]
          |
          v
[Receipt/hash/reconciliation evidence]
```

Airflow 같은 orchestrator를 사용하더라도 작업 payload는 secret-free locator와 고정
operation ID를 전달해야 한다. provider credential, 임의 실행문 또는 브라우저 입력을
작업에 그대로 전달하지 않는다.

DataHub 내부 저장 구조와 도메인 지식그래프를 임의로 결합하지 않는다. projection 간
연결이 필요하면 승인된 canonical identifier와 명시적 동기화 계약을 사용한다.

## 5. GraphRAG 연구 후보

GraphRAG가 필요할 경우 다음과 같은 제한된 흐름을 검토할 수 있다. 이는 현재 구현 완료를
의미하지 않는다.

1. 사용자 질의를 typed intent와 제한된 entity 후보로 정규화한다.
2. 서버가 허용된 graph operation ID와 파라미터 schema를 선택한다.
3. 현재 주체의 Workspace, 권한, 정책과 classification 범위를 계산한다.
4. 서버 소유 read-only template으로 깊이, 행 수, 시간, 비용을 제한해 조회한다.
5. 반환 identifier를 canonical catalog 또는 활성 release 증거로 재검증한다.
6. 허용된 evidence만 LLM에 전달하고 citation과 source version을 함께 반환한다.

LLM이 생성한 Cypher를 직접 실행하거나 provider 오류를 LLM에 재주입해 임의 쿼리를
반복하는 self-healing loop는 허용하지 않는다. 새로운 graph operation은 별도 ADR,
positive/negative 권한 테스트, 비용 제한, 감사 및 provider failure 검증을 거쳐야 한다.

## 6. 후보 유즈케이스와 수용 조건

| 유즈케이스 | 기대 결과 | 필수 수용 조건 |
|---|---|---|
| 영향도 분석 | 승인된 상·하류 자산 탐색 | denied intermediary 우회 금지, bounded depth |
| 품질 트리아지 | 품질 이슈와 승인된 계보 연결 | canonical quality evidence, stale 표시 |
| 용어 추천 | 메타데이터 초안 제안 | 사람 승인 전 mutation 금지, 근거와 model version |
| 비즈니스-IT 매핑 | 용어와 물리 자산의 추적 가능한 연결 | source locator, version, Workspace scope |

## 7. 추진 시 확인 순서

1. `docs/03_ARCHITECTURE.md`, `docs/04_FEATURE_SPEC.md`,
   `docs/07_SECURITY_ABAC.md`에서 ownership과 보안 경계를 확인한다.
2. 새로운 저장소, operation 또는 실패 의미가 생기면 ADR을 작성한다.
3. schema 변경은 SQLAlchemy metadata, Alembic migration,
   `docs/06_DATA_MODEL.md`를 함께 갱신한다.
4. unit/contract 테스트에 허용·거부·교차 Workspace·revocation·provider failure 사례를
   포함한다.
5. target 환경에서 projection rebuild, receipt reconciliation, 부하 및 복구 증거를
   남긴다.

문서 경로는 `docs/reference/00_ONTOLOGY.md`이며, 에이전트와 구현자는 이 문서를
controlled source가 아닌 설계 입력으로만 사용한다.
