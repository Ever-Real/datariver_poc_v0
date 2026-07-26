# Portable configuration and Chat parity execution checklist

- Status: Active
- Scope: operator profiles, deployment-owned configuration, generic UX copy, local model binding,
  and governed Chat parity
- Rule: a checked item requires source evidence, an executed gate, and the named independent review

## Phase 1 — Portable profile and explicit environment selection

- [x] P1-01 The fresh-install workflow offers a portable development profile in addition to
  platform-specific Mac and WSL profiles.
- [x] P1-02 No workflow silently selects Mac; every managed fresh/update workflow requires an
  explicit profile and records the exact ignored environment file in applied state.
- [x] P1-03 Portable development accepts both `linux/arm64` and `linux/amd64` Docker engines and
  does not enable a local LLM, graph, DataHub quickstart, or other host-specific connector.
- [x] P1-04 Compose interpolation and container `env_file` use the same explicitly selected file.
- [x] P1-05 Profile validation, state round-trip, bootstrap and negative profile cases have tests.
- [x] P1-06 The deployment guide explains clone-time profile selection and the resulting
  `.env.<profile>` ownership.
- [x] P1-REVIEW A Data Architect independently confirms profile boundaries and ADR consistency.

Evidence: `scripts/platform_workflow.py`, `workflow_fresh_setup.py`,
`workflow_update_restart.py`, `backend/tests/unit/test_platform_workflow.py`,
ADR-0048 and `docs/41_DEPLOYMENT_ENVIRONMENT_CONFIGURATION.md`. The independent Data Architect
review reported no P0/P1/P2 profile-boundary finding after the portable-profile corrections.

## Phase 2 — Deployment environment as the only live system configuration

- [x] P2-01 `.env`/orchestrator values and mounted secret references are the only live connector
  configuration source.
- [x] P2-02 Database-backed System Settings SAVE/ACTIVATE paths are removed or made unreachable;
  Admin is read-only and executes only fixed server-owned probes.
- [x] P2-03 Admin never writes a host `.env`, and deployment values are returned only as bounded,
  redacted effective configuration.
- [x] P2-04 Copy/paste option templates cover Chat, Embedding, Reranker and all supported
  connector switches without real endpoints, credentials, or environment-specific model IDs.
- [x] P2-05 A dedicated configuration reference documents every option, profile, secret boundary,
  application/restart procedure and negative constraint.
- [x] P2-06 An environment-only change is detected and causes the exact affected processes to be
  recreated; unchanged environments do not cause a restart.
- [x] P2-REVIEW Security Manager and IT Engineer independently confirm no browser-to-env writeback,
  SSRF/secret regressions, or ambiguous source of truth.

Evidence: `Settings`, `_system_configuration_entries`, the only browser calls
`GET /admin/system-configuration` and `POST .../test-deployment`,
`test_http_factory.py`, `test_system_configuration_probe.py` and
`test_platform_workflow.py`. ADR-0048 is the authority; the Security/IT reviews confirmed that
Admin has no environment writeback path and that fixed probes retain host/secret boundaries.

## Phase 3 — Domain-neutral data-catalog language

- [x] P3-01 All input placeholders, empty states, examples, prompts and demo questions are
  inventoried across the browser and runtime-published UI configuration.
- [x] P3-02 Semiconductor-specific product, lot, wafer, process and yield wording is replaced with
  generic catalog discovery, impact, ownership, quality and lineage questions.
- [x] P3-03 Optional semiconductor seed documentation and explicit seed fixtures remain clearly
  optional and are not rewritten as product defaults.
- [x] P3-04 Frontend tests assert representative generic copy and reject known domain-specific
  defaults.
- [x] P3-REVIEW An Alpha User confirms the default UI reads as a general-purpose data catalog.

Evidence: `docs/42_DOMAIN_NEUTRAL_UI_COPY_INVENTORY.md`,
`frontend/src/features/DomainNeutralCopy.test.tsx` and the affected Admin/Chat/Knowledge components.
The independent Alpha User review found no remaining P0/P1/P2 domain-specific default-copy issue.

## Phase 4 — Existing local models only

- [x] P4-01 The development PC selects model identities only in its ignored environment file; no
  committed bootstrap, consumer, UI placeholder, or fallback chooses a model name.
- [x] P4-02 The Chat model is selected from the operator-provided installed inventory for a
  32-GiB Mac Mini and is probed through the actual bounded Chat contract.
- [x] P4-03 `bge-m3:latest` is probed through the actual Embedding contract and its dimension is
  recorded from the response rather than hardcoded.
- [x] P4-04 `qllama/bge-reranker-v2-m3:q4_k_m` is served from its existing Ollama-owned blob through
  the bounded loopback reranker bridge and actually probed.
- [ ] P4-05 No new Ollama model is created; `datariver-gemma4-dev:0.1` and its obsolete creation
  helper/Modelfile are removed from the development PC and repository.
- [x] P4-06 Chat, Embedding and Reranker readiness is visible through deployment-owned Admin probes
  without claiming that a non-consumed capability is active.
- [x] P4-REVIEW Data Engineer and IT Engineer independently verify installed-model identity,
  capability responses, memory fit and process ownership.

Executed local evidence on 2026-07-26:

- `PYTHONPATH=backend/src .venv/bin/python scripts/probe_local_chat_stack.py
  --env-file .env.mac-development --source-host --confirm-actual-provider-call` completed against
  the selected installed inventory.
- The grounded Chat contract returned one valid supplied citation.
- The Embedding response reported 1,024 dimensions; the source does not contain that value as an
  expected model constant.
- The reranker returned two finite ordered results with the relevant catalog evidence first.
- Admin now treats `LLM_RERANKER` as an API runtime consumer and exposes its fixed server-owned
  `/v1/rerank` deployment probe.
- Source evidence is `infrastructure/llm/ollama.py`, `infrastructure/llm/reranker.py`,
  `scripts/local_reranker_service.py`, `scripts/probe_local_chat_stack.py`,
  `test_local_ollama_chat_composer.py` and `test_local_reranker_service.py`. The final Data
  Engineer/IT review initially found unsafe disabled/unsupported lifecycle and incomplete
  process-identity checks. Fresh/update now reconcile `start` or the same safe `stop`, and `stop`
  verifies the exact executable, existing Ollama SHA-256 blob, alias, pooling, loopback endpoint,
  reranking and no-WebUI flags before signaling. The independent re-review passed with no
  P0/P1/P2 finding after 79 focused tests and an actual managed status/probe. P4-05 remains open
  because deleting the host model is destructive.

## Phase 5 — Governed Chat feature parity

- [x] P5-01 Existing `datariver_v1` code, documentation and Git history are mapped to a
  requirement-to-source parity matrix before implementation.
- [x] P5-02 Chat sessions and messages work with Enter-to-send and an accessible multiline escape
  path.
- [x] P5-03 Favorite questions/sessions persist in the governed server boundary.
- [x] P5-04 User questions and assistant answers can be copied with explicit success/failure
  feedback.
- [x] P5-05 Assistant Markdown, including bounded tables, is rendered safely with raw HTML,
  executable links and untrusted components disabled.
- [x] P5-06 Routing distinguishes general, vector/embedding and knowledge-graph strategies through
  a typed application port and exposes the chosen route as evidence.
- [x] P5-07 Knowledge-graph routing is adapter-ready but does not claim an asset graph exists or
  bypass the next task's governed asset projection.
- [x] P5-08 Ranked evidence cards identify every table used in the answer; selecting a card opens a
  modal containing authorized table detail and lineage.
- [x] P5-09 A workflow visualization above Evidence reports bounded server states without
  fabricating provider progress.
- [x] P5-10 Authorization, classification, retention, citation integrity, rate/budget and
  provider-failure negative cases remain fail-closed.
- [ ] P5-11 Unit, contract, strict type, production build and browser acceptance gates cover the
  complete parity matrix.
- [ ] P5-REVIEW Data Architect, Alpha User and Project Manager independently confirm architecture,
  usability and checklist closure.

Current source/evidence map:

| Item | Authoritative source | Executed evidence / state |
|---|---|---|
| P5-01 | `docs/43_GOVERNED_CHAT_PARITY_MATRIX.md`, ADR-0049 | historical/current capability matrix reviewed by Data Architect and Project Manager |
| P5-02/P5-03 | `ChatPage.tsx`, `chat_history.py`, `db/chat.py`, migration `0056` | focused Chat/history/favorite backend and frontend tests pass |
| P5-04/P5-05 | `ChatPage.tsx`, `SafeMarkdown.tsx` | copy/unsafe-Markdown/table component tests pass |
| P5-06/P5-07 | `chat_routing.py`, typed graph evidence port | explicit AUTO/GENERAL/VECTOR/GRAPH and unavailable-without-fallback tests pass |
| P5-08/P5-09 | `ChatPage.tsx`, server workflow/evidence DTOs | ranked evidence/detail-lineage and server-state UI tests pass |
| P5-10 | `services/chat.py`, `classification_access.py`, `runtime_binding.py`, Redis budget guard, migrations `0056`/`0057` | focused owner, classification, exact staged provider identity, budget, drift, citation and provider-failure negatives pass; Security and Data Architect final reviews report no P0/P1/P2 |
| P5-11 | backend/frontend gate commands in `README.md` and `docs/09_TEST_STRATEGY.md` | focused gates, strict type/lint/static checks and production build pass; managed runtime, migrations, RLS and all three provider calls pass; integrated suites still expose the paused Registration/Catalog work and authenticated target-browser evidence remains open |

The paused concurrent Registration/architecture work currently leaves the repository-wide backend
and frontend suites with failures outside this objective. On 2026-07-26 the backend suite reported
1,456 passed, 89 Registration/catalog-metadata failures and 97 isolated-environment skips; the
frontend suite reported 254 passed and the same 30 Catalog/Registration failures. Those failures
are not converted into a pass for P5-11: the paused work must be reconciled and the complete README
gates plus target-browser acceptance rerun before release closure.

## Executed evidence and independent review ledger

| Phase | 2026-07-26 executed evidence | Independent review result |
|---|---|---|
| P1 | `test_platform_workflow.py`; explicit portable/Mac/WSL profile and environment round-trip negatives included in the 206-test focused backend set | Data Architect: no P0/P1/P2 profile-boundary finding |
| P2 | HTTP/OpenAPI, fixed-probe and workflow restart tests in the same focused set; repository scan confirms Admin exposes read-only inventory and fixed `test-deployment` only | Security/IT review: no browser writeback, arbitrary URL or secret-boundary finding |
| P3 | `DomainNeutralCopy.test.tsx` in the final six-file/40-test frontend set | Alpha User: no domain-specific default-copy finding |
| P4 | `probe_local_chat_stack.py --env-file .env.mac-development --source-host --confirm-actual-provider-call` exercised the selected installed Chat, Embedding and Reranker contracts before and after the managed restart; model identity remains environment-owned | Data Engineer/IT final process-ownership review: P0/P1/P2 PASS after lifecycle and exact-command hardening; derivative host-model deletion remains open |
| P5 | focused backend 206 passed; focused frontend 6 files/40 passed; Ruff format/lint, strict mypy over 388 files, static verification, TypeScript, ESLint and production build passed; the managed `mac-development` runtime returned API/Web HTTP 200 and the actual Chat/Embedding/Reranker probe passed | Security and Data Architect final reviews: P0/P1/P2 PASS; PM/Alpha source review findings on env-only docs, one-character Enter, localized status and dialog focus containment were resolved; authenticated browser acceptance remains open |
| Migration | regenerated `0001` twice with SHA-256 `2a0840c809ba440ac379c200c26e13612b21e99de2f32cfa99da7f0a6276723a`; isolated PostgreSQL passed canonical `0001→0057`, empty-data `0057→0056`, legacy `0056→0057`, and refused an intentionally partial schema; the current runtime reports `0057`, canonical staged-profile columns/FKs/CHECK and the activation trigger | Data Architect and Security final reviews: source migration contract PASS; live four-table owner RLS has `FORCE ROW LEVEL SECURITY`, restrictive owner policies and a rollback-only cross-owner test returned own read/update `1/1`, cross-owner read/update `0/0`, persisted test rows `0` |

## Final completion gate

- [ ] FINAL-01 Every item above links to authoritative source and executed evidence.
- [ ] FINAL-02 All independent review findings are resolved or recorded as explicit external gates.
- [x] FINAL-03 The current development runtime is restarted through the selected profile workflow
  and its API/Web/provider health is verified.
- [x] FINAL-04 Git status separates user-owned work, and the delivered commit contains only this
  objective's reviewed scope.

FINAL-03 evidence: `workflow_update_restart.py --profile mac-development` completed all 18 steps
at source commit `538dc25`; API live/ready and Web health returned HTTP 200, DataHub GMS returned
HTTP 200 with version `v1.6.0`, and the catalog projection upserted 2,000 rows. The post-restart
actual-provider probe reported Chat model `gemma4:e2b-it-qat`, one grounded citation, Embedding model
`bge-m3:latest` with 1,024 observed dimensions, and Reranker model
`qllama/bge-reranker-v2-m3:q4_k_m` with relevant evidence ranked first.

FINAL-04 evidence: objective commits are `4deeb7c` and the restart correction `538dc25`. The
separate in-progress Registration/architecture work was restored after restart and remains
uncommitted only in its original five paths:
`catalog_metadata_upload_parser.py`, `integration.py`, `DenseDataTable.tsx`, `docs/README.md`, and
untracked `docs/39_ONTOLOGY_KNOWLEDGE_GRAPH_REFERENCE.md`.
