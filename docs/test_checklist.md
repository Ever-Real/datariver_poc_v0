# DataRiver Step 2/3 implementation and E2E checklist

- 실행일: 2026-07-21 (Asia/Seoul)
- 브랜치: `agent/admin-ui-stabilization`
- 환경: Mac single-node development, DataHub `v1.6.0`, native Ollama, Docker Neo4j
- 판정 원칙: 코드/unit 성공과 실제 external E2E를 분리한다. 식별자와 해시는 테스트 데이터
  evidence이며 credential/token/object key는 기록하지 않는다.

상태는 `PASS`, `FAIL`, `OPEN`, `BLOCKED`만 사용한다. `BLOCKED`는 보안 gate를 우회하지 않았다는
뜻이며 성공으로 합산하지 않는다.

## 1. Infrastructure and schema

| 상태 | 항목 | 증거 |
|---|---|---|
| PASS | DataHub 정규 버전 | 별도 Compose의 GMS/Frontend/Actions/Kafka/MySQL/Elasticsearch healthy, Frontend `http://localhost:8080`; expected version `v1.6.0` |
| PASS | DataRiver 기반 서비스 | API `:18000`, Web `:18080`, Keycloak `:18081`, Airflow `:8082`, Neo4j Browser `:17474` / Bolt `:17687`, native Ollama `:11434` 확인 |
| PASS | Alembic `0034 -> 0038` | 실행 DB upgrade 성공, `0038 (head)` 재조회, API/worker 재기동 후 health 확인 |
| PASS | metadata drift | 실행 DB `alembic check` 결과 `No new upgrade operations detected`; optional `semiconductor_seed` schema는 canonical migration scope 밖으로 명시 |
| PASS | PDF source bytes | PwC PDF 9,945,560 bytes, SHA-256 `6d406f252e7ea42b3ad9a0218b4ff7f87fac762a4395dfc3a19ad3e702c58dea`, 105 pages |

## 2. Search

| 상태 | 항목 | 실제 관측 |
|---|---|---|
| PASS | Terms/Tags DataHub→API→DOM | VIEW `vw_supplier_qualification_analog_mixed_signal`에 Terms `semiconductor_scenario`, `supplier_qualification` 및 provider Tags 8개 표시 |
| PASS | 즉시 3단계 정렬 | 동일 header를 세 번 클릭해 `ascending=1`, `descending=1`, `none=1`; dropdown 없이 `ASC -> DESC -> NONE` |
| PASS | toolbar/layout | 검색창 오른쪽 Filter/CSV/Excel controls와 table horizontal overflow, page sizes `50/100/200/500/1000/전체` 확인 |
| PASS | 권한 없는 export | 현재 E2E Operator는 server export capability가 없어 CSV/Excel controls가 비활성; client-side 우회 없음 |

## 3. MANUAL registration

| 상태 | 항목 | 실제 관측 |
|---|---|---|
| PASS | OIDC UI 제출 | immutable submission serial `7` |
| PASS | Airflow apply | `datariver_manual_metadata_apply` unpaused, service OIDC 경로로 성공 |
| PASS | DataHub apply/read-back | asset `019f7e6d-2b3d-7f2f-928c-4cf44b7a4153`, URN `urn:li:dataset:(urn:li:dataPlatform:postgres,semiconductor_seed.vw_supplier_qualification_analog_mixed_signal,DEV)`, state `APPLIED` |
| PASS | provider projection evidence | projection version `ea723a59d8227793bd368119fcc77d55a5ac193617fc3930d0caa7b62b390119` |

## 4. BULK registration

### 4.1 XLSX

| 상태 | 항목 | 실제 관측 |
|---|---|---|
| PASS | immutable upload | upload `019f815e-4edc-744d-902f-bd8e6bf7be05`, SHA-256 `0df88719dafb5b1a50348847394019e3233931911ed00155688c3bfa5f0dc88b` |
| PASS | typed Airflow preparation | preparation `019f815e-8a04-79b7-b6b8-d4f0be710f64`, `READY`, rows `1/1`, attempt `1`; run `manual__2026-07-20T21:11:36.411278+00:00` success |
| PASS | candidate/receipt | proposed description `DataRiver Bulk XLSX E2E verified on 2026-07-21.`; receipt SHA `6c8ea7befbb30dc07afcebe51969a5f124aa28b598f998d10686538705275ee2`; root `bd2e872e79d316960d0fc1995dcf743dff9bd129b915d12cfbad1dd8d80cae27` |

### 4.2 CSV

| 상태 | 항목 | 실제 관측 |
|---|---|---|
| PASS | immutable upload | upload `019f816d-ad6e-7027-ac26-811442f5ad18`, 261 bytes, SHA-256 `ac84935a614d422071cfc0d12e4ac43f0171bec36fac74b9fb70ad6897006325` |
| PASS | typed Airflow preparation | preparation `019f816d-df24-73dd-809b-4c3f5916863a`, `READY`, rows `1/1`, attempt `1`; run `manual__2026-07-20T21:28:21.809799+00:00` success |
| PASS | candidate/receipt | proposed description `DataRiver Bulk CSV E2E verified on 2026-07-21.`; receipt SHA `e15f6e7751dc7f6d3f8cbc077b30f37621c9389240d04ccd3136f9aa5ec5cba0`; root `438448994d9d9592d0da07c9596a52e1a610f9c516122236fc43d5fbbd9dc39a` |

### 4.3 Registration failure evidence

| 상태 | 항목 | 증거 |
|---|---|---|
| PASS | Airflow false-success 차단 | canonical execution이 `FAILED`면 DAG run도 실패하도록 MANUAL/BULK DAG 검사 추가 |
| PASS | actual SHA/version fence | accepted manifest에 observed SHA를 저장하고 XLSX validator profile version을 `integrity-xlsx-v1`으로 일치 |
| PASS | atomic candidate publication | receipt flush 후 composite FK candidate insert, profile별 candidate hash 재검증, stale selected upload UI refresh 수정 |

## 5. CR management

| 상태 | 항목 | 증거 |
|---|---|---|
| PASS | source/unit contract | revision round, TEST attachment/content hash binding, multi-System Developer/Data Steward/global Admin authority snapshot, typed FINAL rejection 및 completion actor negative tests |
| PASS | actual workflow through `FINAL_REVIEW` | 실제 DataHub VIEW를 대상으로 CR `CR-SEMICON-E2E-260720-1EF2`를 `REGISTERED(v1) -> IN_REVIEW -> TESTING -> FINAL_REVIEW(v7)`로 진행. REVIEW/TEST approval과 transition 3건을 DB에서 재조회 |
| PASS | TEST 증거 결합 | 실제 JSON attachment SHA-256 `609672cb9f57da54dfa8866a4f94f3276857da9167c463de458d70584637122b`; attachment content hash와 `change_test_runs.result_hash` 동일, state `PASSED` |
| PASS | optimistic/typed FINAL negative | stale `If-Match`는 HTTP `409`, 일반 transition으로 `FINAL_REVIEW -> REJECTED` 시도는 HTTP `422`; aggregate는 `FINAL_REVIEW/v7` 유지 |
| PASS | FINAL WebAuthn security defense | Password/direct-grant Developer, Data Steward, global Admin 모두 HTTP `403`, remediation `FIDO2_REQUIRED`, audit reason `PHISHING_RESISTANT_AUTH_REQUIRED`; FINAL approval 0건 |
| PASS | Service Token security defense | 기존 최소권한 `datariver-airflow` service token의 FINAL approval은 HTTP `403`; `ACTION_NOT_GRANTED`, scope mismatch와 phishing-resistant assurance 부족을 policy decision에 기록 |
| PASS | success/exception teardown | 종료 후 CR `1`, DB subject `4`, Keycloak user `4`, 임시 client `1`, S3 TEST object `1` 삭제; 임시 client-secret 파일 제거. `authz.policy_decisions`는 immutable 보안 감사 증거이므로 보존 |
| PASS | E2E에서 발견한 저장/RLS 결함 수정 | 신규 CR parent를 child보다 먼저 flush하도록 수정하고, shared UoW commit 후 route-level attachment/list read 전에 RLS request context를 재설정. 관련 Ruff/mypy와 36개 focused test 통과 후 실제 attachment E2E로 재검증 |
| BLOCKED | 실제 FINAL 3인 승인 / `COMPLETED` | 이번 승인 범위의 성공 조건은 비정상 접근 차단이다. 실제 완료에는 Developer, Data Steward, global Admin 각기 다른 사람의 최근 hardware WebAuthn이 필요하며 우회하지 않음 |

## 6. Knowledge PDF, Neo4j and GraphRAG

| 상태 | 항목 | 증거 |
|---|---|---|
| PASS | PDF governed upload | upload `019f8177-3df8-7867-b4b1-61582577986c`, `ACCEPTED`, actual/declared size and SHA 일치, `application/pdf`, `FULL_SIGNATURE`, validator `integrity-format-v1` |
| PASS | local provider compatibility | native Ollama `0.32.1`; embedding `bge-m3:latest` actual 1024 dimensions; `datariver-gemma4-dev:0.1` OpenAI-compatible strict JSON completion success |
| PASS | grounding hardening | 모델은 server-owned `evidence_id`만 선택하며 원문/페이지/해시는 서버가 결합; unknown ID, fabricated endpoint, excerpt/hash와 projection read-back mismatch를 차단 |
| PASS | actual PDF analysis | 전체 105-page parse 후 page 58 actual extraction: input/output `2093/359` tokens, nodes `3`, edges `2`, 모든 page-bound evidence 검증 |
| BLOCKED | independent review/publish/project | 작성자와 다른 `kg.review` actor 및 `kg.publish` hardware WebAuthn 필요; 우회하지 않음 |
| PASS | isolated Neo4j shadow/read-back | actual PDF snapshot `3 nodes / 2 edges`, release hash `34953f1a214225e76d26640c712906ceb857cd9cf2a791f60f4c2d23ba1a681e`, `SHADOW_VERIFIED`; cleanup entity/projection `0/0` |
| PASS | actual cited GraphRAG adapter | Neo4j bounded retrieval→Gemma answer, citation `3`, answer SHA-256 `04c4a3f807598ae87f3d7bf63d2a20c789c13887c41e8ea2c611321e3c92624c`, audit record 생성; raw answer 미기록 |
| PASS | final Neo4j residue check | E2E 종료 후 읽기 전용 Cypher 재조회: `KnowledgeProjection=0`, `KnowledgeEntity=0`, `KNOWLEDGE_RELATION=0` |
| BLOCKED | product release-pinned GraphRAG route | 위 isolated adapter E2E와 별개로 canonical release의 independent review/publish는 실제 다른 사용자와 hardware WebAuthn이 필요 |

## 7. System Configuration

| 상태 | 항목 | 증거 |
|---|---|---|
| PASS | secret boundary | Admin DB/YAML에는 `file:/run/secrets/<name>` 참조만 허용; literal secret/token/password 거부 |
| PASS | actual TEST implementation | Chat strict JSON completion, embedding vector validation, Neo4j Docker-secret authentication + fixed `RETURN 1`로 강화 |
| OPEN | Admin SAVE→TEST→ACTIVATE→restart | DB profile은 아직 0건; activation은 hardware WebAuthn gate. 현재 Knowledge runtime은 deployment `.env` source임을 binding audit에 구분 기록 |

## 8. Resource observation

| 항목 | 실제 값 |
|---|---|
| Host RAM | 34,359,738,368 bytes (32 GiB) |
| Docker VM RSS | 약 8.7 GiB (측정 시점) |
| Docker configured ceiling observed | 약 19.5 GiB |
| Native `ollama serve` | E2E 종료 후 `ollama ps` loaded model 없음; 실행 중 관측치는 Gemma 약 3.6 GiB GPU + bge-m3 약 664 MiB GPU |
| 주요 container RSS | DataHub GMS 1.82 GiB, Neo4j 0.90 GiB, Elasticsearch 0.87 GiB, DataHub Frontend 0.75 GiB, broker 0.69 GiB |

32 GiB unified-memory Mac에서는 Ollama가 Docker 밖에서 Gemma 계열 weights/KV cache를 함께
사용하므로 Docker 24 GiB는 권장하지 않는다. 기본 권고는 **16 GiB**, 동시 대형 import가 필요할
때만 **18 GiB 상한**이다. 현재 약 19.5 GiB ceiling도 동작하지만 model load 중 memory pressure를
관찰해야 한다. `qwen-27b`, `qwen-35b`, `glm-4.7-flash`를 이 전체 stack과 동시에 상주시켜서는 안
된다.

## 9. Final verification gates

| 상태 | Gate |
|---|---|
| PASS | backend Ruff format/check 265 files, strict mypy 256 files, full pytest `707 passed in 11.44s` |
| PASS | frontend typecheck, lint, Vitest `37 files / 155 tests`, production build |
| PASS | `scripts/verify_static.py` |
| PASS | deterministic `0001` 2회 SHA-256 `3a95be49ae372038826f4f8b4a28cd77b666bd8fee12ea4aa71a21d8283a4d1d`; live `0038` + no metadata drift |
| PASS | `git diff --check`; 기존 사용자 변경을 보존한 채 이번 구현 범위의 source/docs/runtime evidence를 검토 |

## 10. 2026-07-21 intranet LLM / remote DataHub follow-up

| 상태 | 항목 | 증거 |
|---|---|---|
| PASS | private OpenAI-compatible adapter contract | development only, operator exact-host allowlist, HTTPS `/v1`, private non-loopback DNS resolution, fixed Chat/Embedding requests, no redirect/proxy environment, separate mounted Chat/Embedding API-key references를 unit contract로 검증 |
| PASS | unsafe configuration rejection | public/HTTP/non-`/v1` intranet profile, URL credential/query/fragment, missing API-key reference 및 production activation을 fail-closed로 검증 |
| PASS | source-host secret portability | portable `file:/run/secrets/<name>` reference가 source-host의 ignored `secrets/` directory에 단일 파일명으로만 매핑되고 path traversal을 거부함을 검증 |
| PASS | focused code verification | Ruff, strict mypy (`160` source files), related pytest `83 passed`, `scripts/verify_static.py`, source-host/graph Compose `config --quiet`, frontend lint/typecheck/System Configuration test (`3 passed`)/production build 통과 |
| OPEN | authenticated intranet model live TEST | 실제 private hostname, approved CA와 Chat·Embedding API key가 제공되지 않아 실행하지 않음. Admin System settings에서 SAVE → TEST → ACTIVATE 후 API 재시작으로 별도 검증 필요 |
| OPEN | remote DataHub token-auth live enablement | 원격 DataHub Compose owner의 maintenance window와 signing key/salt 보관이 필요하므로 이 checkout에서 변경하지 않음. README 절차 후 service-account token으로 DataHub TEST 필요 |
