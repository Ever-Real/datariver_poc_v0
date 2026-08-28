# PREP Wafer hardcoding and fixture-leakage audit

Date: 2026-08-28 KST  
Audit base / Handoff: `5664dd00659d41c5987ed1c2cb30577dfa4f84ea`  
Product under audit: `80618b6039bf994585a2a3ff623b44c1e16efeb5`  
Starting `origin/main`: `892239850fbdc447ad1b45df664ad7382b285385`  
Starting `origin/dev`: `5664dd00659d41c5987ed1c2cb30577dfa4f84ea`

## Verdict

`Wafer` is not a PREP deployment dependency in the audited Product. The case-insensitive
inventory contains 795 `wafer` matches on 745 lines in 70 files, but there are zero occurrences
in the PREP smoke, deploy entry point, deploy controller, or modules copied into the final POC
runtime image. The exact literal `urn:li:glossaryTerm:wafer` occurs 16 times in nine files, all of
which are tests or test fixtures.

The historical `PREP_RUNTIME_SMOKE_FAILED` value did not identify an entity failure. Commit
`fab42bd03eb8cbe9b3bcbff6c4cfdb2cf5e5fc6c` introduced it as the fallback for any non-login
failure from the authenticated smoke. Commit
`46500c130de9c8bebedd143eca946b5d9166e63b` removed it in favor of the sanitized typed smoke
failure record. Neither version of `scripts/smoke_prep39083.mjs` contained `Wafer`, a fixed
Dataset URN, a fixed GlossaryTerm URN, `entityExists`, or an entity mutation.

Accordingly, the operator-supplied observation that a separate lookup returned
`entityExists=false` / `glossaryTerm.exists=false` for
`urn:li:glossaryTerm:wafer` does not explain the failed smoke. That URN was not used by the
audited smoke request path. The missing Term is normal target metadata absence, not evidence of an
authorization failure. The exact historical failure substage remains unknown because the legacy
wrapper discarded it.

No Product correction is justified by this audit. Replacing the current bounded read smoke with a
synthetic mutation fixture would add state and cleanup risk without fixing the observed failure.

## Search accounting

The authoritative inventory command was run against audit base `5664dd00...`, before this report
was added:

```text
rg -n --hidden -i 'wafer|urn:li:glossaryTerm:wafer|Wafer ID' .
```

The report file itself is therefore not included in the totals below. The alternatives overlap;
the leftmost `wafer` alternative accounts for the 795 match tokens.
Separate exact accounting found:

| Measure | Count |
|---|---:|
| Files with a case-insensitive `wafer` match | 70 |
| Matching lines | 745 |
| Match tokens | 795 |
| Exact literal `urn:li:glossaryTerm:wafer` | 16 in 9 files |
| `Wafer ID` phrase | 31 in 8 files |
| PREP-runtime-reachable `Wafer` occurrences | 0 |
| PREP smoke / deploy `Wafer` occurrences | 0 |

Purpose totals are counts of match tokens, not files:

| Purpose | Files | Matches | Runtime reachability |
|---|---:|---:|---|
| Backend unit-test values | 31 | 158 | Test only |
| Frontend component/live-test values | 22 | 276 | Test only; not in the Vite entry graph |
| Provider GraphQL/API fixture and integration assertions | 1 | 132 | `node --test` only; not copied to the final image |
| Documentation and captured router evidence | 9 | 191 | Documentation only |
| Explicit local GraphRAG fixture | 1 | 15 | Opt-in and fail-closed to `app_env=development` |
| Explicit semiconductor seed/demo | 3 | 11 | Opt-in synthetic seed; not in PREP39083 Compose |
| Manual authorization revocation probe | 1 | 3 | Manual DEV probe; merely listed for Ruff checks |
| Manual router evaluation | 1 | 8 | Explicit evaluation command; not PREP smoke |
| Static domain-vocabulary rejection regex | 1 | 1 | Guard, not target metadata |

## Complete file/line inventory

Line lists identify every matching line. A line can contain more than one match token.

### Runtime source, explicit fixtures, seed, and validators

| File | Matching lines | Classification / use |
|---|---|---|
| `backend/src/datariver/local_graphrag_fixture.py` | 57,72,80,84,91,93,117,131,138,147,149,154,160,161 | Explicit local GraphRAG Node/Relation/provenance fixture; development-only guard; no automatic PREP import |
| `backend/src/datariver/seed/semiconductor.py` | 23,24,61,69 | Optional synthetic seed pack; requires `SEED_PROFILE=semiconductor`; PREP example defaults do not enable it |
| `scripts/generate_semiconductor_seed.py` | 198,234,289 | Local DataHub/PostgreSQL demo generator; owns only the synthetic seed namespace |
| `seed/semiconductor/data/catalog_assets.csv` | 2,6 | Synthetic seed data |
| `scripts/probe_policy_revocation.py` | 296,303,319 | Manual authorization/revocation probe against explicitly seeded assets; not called by PREP deploy |
| `scripts/verify_chat_knowledge_router.mjs` | 13,33,38,51,68,80,81,82 | Manual Router 60+8 evaluation questions; no creation or fallback behavior |
| `scripts/verify_static.py` | 8182 | Regex that rejects domain vocabulary in selected production K9 modules |

### Provider/API, Node/Relation, provenance, replay, authorization, and cleanup tests

| File | Matching lines | Classification / use |
|---|---|---|
| `frontend/poc-server.providers.test.mjs` | 17,21,22,25,26,113,125,130,137,154,172,194,216,217,219,221,223,237,239,241,243,250,251,274,278,295,297,301,316,349,350,352,353,354,356,357,363,385,386,417,419,550,609,671,672,676,677,678,684,693,694,697,698,723,740,770,772,783,787,788,789,796,836,839,847,878,882,892,902,908,918,934,1015,1023,1025,1026,1027,1047,1070,1190,1229,1235,1260,1320,1327,1332,1345,1393,1394,1398,1436,1437,1441,1466,1544,1575,1579,1590,1640,1652,1720,1902,1908,1913,1962,2009,2034,2035,2036,2084 | Self-contained provider test server and assertions: GraphQL/API payload, Catalog, glossary, Node/Relation projection, replay/idempotence, authorization and cleanup. Not imported by Product and not copied to final OCI |
| `frontend/poc-catalog-performance.test.mjs` | 220,293,329,330,349,487 | Provider performance/last-good test fixture |
| `frontend/poc-k9-managed-graphs.test.mjs` | 68 | Negative domain-hardcoding assertion |
| `frontend/src/poc/pocApi.live.test.ts` | 41,42,44,45,52,56,258,270,278,282,286,301,303,305,399,435,443,458,514,530,545,706,844,845,852,853,855,857,889,892,897,917,930,1105,1117,1211,1250,1605,1637,1638,1641,1645,1656,1668,2003,2004,2009,2088 | In-process API/live fixture covering Catalog, governance, projection and replay |

### Backend unit tests

| File | Matching lines | Classification / use |
|---|---|---|
| `backend/tests/unit/test_bulk_registration_service.py` | 218,236,248,260 | Registration fixture |
| `backend/tests/unit/test_catalog_description_service.py` | 122,124,139,194,225,255,475 | Catalog mutation/auth fixture |
| `backend/tests/unit/test_catalog_export_csv.py` | 26,30,57,61 | CSV fixture |
| `backend/tests/unit/test_catalog_export_service.py` | 138,200,211,249,267,282 | Export authorization/bounds fixture |
| `backend/tests/unit/test_catalog_export_worker.py` | 60,200,210,288 | Export worker/replay fixture |
| `backend/tests/unit/test_catalog_export_xlsx.py` | 49 | XLSX fixture |
| `backend/tests/unit/test_catalog_metadata_candidate_service.py` | 193,393,401 | Typed metadata candidate fixture |
| `backend/tests/unit/test_catalog_metadata_compiler.py` | 318,323 | GlossaryTerm compiler fixture |
| `backend/tests/unit/test_catalog_metadata_upload_parser.py` | 76 | Upload parser fixture |
| `backend/tests/unit/test_catalog_metadata_xlsx_upload_parser.py` | 55 | XLSX parser fixture |
| `backend/tests/unit/test_catalog_presenter.py` | 16,17,24,37,44 | Catalog presentation fixture |
| `backend/tests/unit/test_catalog_search_fields.py` | 31,100,106,118 | Search matching fixture |
| `backend/tests/unit/test_catalog_service.py` | 127,967,980,989,1051,1060,1071,1077,1090,1098,1115,1122,1129,1134,1146,1370,1372,1374,1378 | Catalog read/auth/cache fixture |
| `backend/tests/unit/test_catalog_sync_service.py` | 138,140 | Sync/replay fixture |
| `backend/tests/unit/test_change_request_system_directory.py` | 413,443,486,494 | CR/System fixture |
| `backend/tests/unit/test_chat_service.py` | 1040,1907,2062,2877 | Chat fixture |
| `backend/tests/unit/test_datahub_gateway.py` | 822,862,863,870,891,900,901 | DataHub GraphQL response fixture |
| `backend/tests/unit/test_governance.py` | 535 | Governance fixture |
| `backend/tests/unit/test_governance_apply.py` | 232 | GlossaryTerm mutation payload fixture |
| `backend/tests/unit/test_knowledge_pipeline.py` | 48,130,132,135,144,151,157,177,197,220,223,247,299,338,529,643,1115 | Node/Relation/provenance/parser fixture |
| `backend/tests/unit/test_local_graphrag_fixture.py` | 32 | Explicit local fixture test |
| `backend/tests/unit/test_local_ollama_chat_composer.py` | 35,37 | Local provider prompt fixture |
| `backend/tests/unit/test_manual_metadata_apply_service.py` | 74,81,369,374,377,380,383,537,540,541,542,543 | Apply/replay/audit fixture |
| `backend/tests/unit/test_manual_metadata_reports.py` | 77 | Receipt fixture |
| `backend/tests/unit/test_manual_metadata_submission_service.py` | 65,106,273,275,276,324,327,329,355,368,373,398,403,488,516,525,546,636 | Submission/receipt/cleanup fixture |
| `backend/tests/unit/test_openai_compatible_knowledge.py` | 163,165,182,201,235,238,240,740 | Provider composition fixture |
| `backend/tests/unit/test_registration_candidate_service.py` | 243,362,363 | Registration candidate fixture |
| `backend/tests/unit/test_typed_bulk_registration_service.py` | 101 | Typed bulk fixture |
| `backend/tests/unit/test_typed_upload_parser.py` | 65 | Upload fixture |
| `backend/tests/unit/test_typed_xlsx_upload_parser.py` | 129,211,247 | XLSX fixture |
| `backend/tests/unit/test_upload_validation.py` | 187,473,493,534,559,585,614,638 | Upload validation fixture |

### Frontend component tests

| File | Matching lines | Classification / use |
|---|---|---|
| `frontend/src/api/client.test.ts` | 83 | API client test |
| `frontend/src/components/layout/AppShell.test.tsx` | 35,37,48,54,64,75,78,81,83,85,86,90,111,112 | Search UI test |
| `frontend/src/features/DomainNeutralCopy.test.tsx` | 20,30 | Negative domain-copy test |
| `frontend/src/features/admin/PocGlossaryPage.test.tsx` | 10,11,12,26,28,29,31,37,39,40,41,42,63,65,67,71,72,73,74 | Glossary UI fixture |
| `frontend/src/features/catalog/CatalogExportControl.test.tsx` | 29,44,89,118,140,155,181,214,223 | Export UI fixture |
| `frontend/src/features/catalog/CatalogWorkspace.test.tsx` | 35,37,45,51,105,106,115,118,121,123,151,152,163,169,176,178,180,181,187,188,566,575,633,649,657,666,729,731,745,747,759,761,766,771,773,786,789,816,817,843 | Catalog/lineage UI fixture |
| `frontend/src/features/catalog/catalogExportApi.test.ts` | 22 | Export API fixture |
| `frontend/src/features/chat/ChatPage.test.tsx` | 184,214 | Chat UI fixture |
| `frontend/src/features/governance/ChangeRequestCreateDialog.test.tsx` | 98,100,103,105,107,110,186,188,203,206,213,215,223,225,226,240,242,258,264,270,281,294,296,297,298,299,305,448,473,553,554,574,610,611 | CR authoring fixture |
| `frontend/src/features/governance/GovernancePage.test.tsx` | 167,169,486,489,492,502,503,504,513,514,519,521,522,700,705,707,709,800 | Governance/mapping fixture |
| `frontend/src/features/knowledge/KnowledgeChatPage.test.tsx` | 37,38 | Knowledge Chat fixture |
| `frontend/src/features/knowledge/studio/knowledgeStudioApi.test.ts` | 577,583 | Knowledge Studio fixture |
| `frontend/src/features/quality/QualityDashboardTab.test.tsx` | 24,26,114 | Quality UI fixture |
| `frontend/src/features/quality/QualityPage.test.tsx` | 68,81,92,93,216,250,251,252,261,262,497,564,567,568,574,575,730 | Quality UI fixture |
| `frontend/src/features/registration/RegistrationColumnDescriptionEditor.test.tsx` | 19 | Registration UI fixture |
| `frontend/src/features/registration/RegistrationControlledMetadataEditor.test.tsx` | 8,9,17,19 | Registration metadata fixture |
| `frontend/src/features/registration/RegistrationDescriptionEditor.test.tsx` | 16,64,89,150 | Registration description fixture |
| `frontend/src/features/registration/RegistrationWorkbench.test.tsx` | 191,206,226,229,231,449,451,452,458,466,505,506,511,512,534,1137,1142,1184,1203,1239,1254,1293,1301,1382,1470 | Registration workbench fixture |
| `frontend/src/poc/PocApp.test.tsx` | 209 | POC route test |

### Documentation and captured evidence

| File | Matching lines | Classification / use |
|---|---|---|
| `docs/12_ACCEPTANCE_REPORT.md` | 336 | Historical example |
| `docs/40_PORTABLE_CONFIGURATION_AND_CHAT_PARITY_EXECUTION_CHECKLIST.md` | 54 | Historical checklist/example |
| `docs/42_DOMAIN_NEUTRAL_UI_COPY_INVENTORY.md` | 20,51 | Domain-neutrality guard documentation; explicitly permits test values |
| `docs/evidence/chat-knowledge-router/router-60.json` | 44,49,604,610,611,612,613,614,633,638,644,645,646,647,648,808,813,819,820,821,822,823,1242,1247,1253,1254,1255,1256,1257,2401,2409,2410,2411,2412,2413,2414,2415,2416,2417,2418,2419,2420,2421,2422,2423,2424,2425,2426,2427,2428,2481,2486,2495,2496,2497,2498,2499,2500,2501,2502,2503,2504,2505,2506,2507,2508,2509,2510,2511,2512,2513,2514 | Captured router evaluation evidence |
| `docs/evidence/chat-knowledge-router/router-boundary.json` | 264,269,291,296,302,303,304,305,306,325,330,337,338,339,340,341,342,343,344,345,346 | Captured router boundary evidence |
| `docs/evidence/kg2-semantic-model-v2/router-60.json` | 45,50,610,616,617,618,619,620,639,644,649,650,651,652,653,810,815,821,822,823,824,825,1244,1249,1255,1256,1257,1258,1259,2386,2387,2388,2389,2390,2391,2392,2393,2394,2395,2396,2397,2398,2399,2400,2401,2402,2403,2404,2405,2458,2463,2473,2474,2475,2476,2477,2478,2479,2480,2481,2482,2483,2484,2485,2486,2487,2488,2489,2490,2491,2492 | Captured historical router evidence |
| `docs/evidence/kg2-semantic-model-v2/router-boundary.json` | 263,268,290,295,300,301,302,303,304,323,328,335,336,337,338,339,340,341,342,343,344 | Captured historical boundary evidence |
| `docs/evidence/cytoscape-graph-visualization/README.md` | 124 | Historical example |
| `docs/evidence/cytoscape-interaction-force-layout/README.md` | 137 | Historical example |

## PREP smoke call path

The exact entry-to-failure path is:

1. `./scripts/prep39083 deploy` enters `scripts/prep39083`, which executes
   `uv run --frozen python scripts/prep39083_deploy.py deploy`.
2. `main()` loads the release and environment, then calls `deploy()`.
3. `deploy()` preserves state, reconciles bootstrap identities, starts the exact Product, checks
   `/healthz`, advances the attempt to `SMOKE_RUNNING`, then calls `run_smoke()`.
4. `run_smoke()` invokes `node scripts/smoke_prep39083.mjs` with loopback transport, the exact
   public request Origin, administrator identity, a private temporary password file, K9 mode,
   bounded timeout, and sanitized output/failure paths.
5. The smoke performs, in order:
   - `GET /healthz`;
   - `POST /auth/login`;
   - `GET /poc-api/datahub/tree?parent_kind=ROOT&refresh=true&limit=1`;
   - `GET /poc-api/datahub/catalog?limit=1`;
   - `GET /poc-api/knowledge/managed-assets` and local readiness/error inspection;
   - `GET /api/v1/change-history/summary?week_start=<runtime week>`;
   - `POST /poc-api/llm/chat` with the domain-neutral GENERAL question
     `데이터 계보가 무엇인지 일반적으로 설명해줘.`;
   - `POST /auth/logout` in `finally`.
6. On a failure, the Node smoke writes only a typed bounded failure record. `run_smoke()` maps that
   classification to the deploy gate, and `deploy()` advances the attempt to `SMOKE_FAILED`.

Smoke entity type: none.  
Smoke exact entity URN: none.  
URN creation source: none.  
Runtime discovery: the Catalog and K9 source paths consume provider-returned inventory; there is no
fixed-URN fallback.  
Entity create/mutation/replay/provenance/cleanup sequence: not part of PREP smoke. The smoke is a
bounded read/readiness check and logout only.  
`urn:li:glossaryTerm:wafer` used in the failed smoke request: no, for every audited historical and
current implementation of this PREP smoke.

The K9 collector's direct GlossaryTerm resolution is also target-independent: it receives the exact
Term URN from runtime Dataset/Column assignments and passes that runtime value to the DataHub
GraphQL query. It has no `Wafer` constant or fallback.

## History finding

- `bf6e7c12d0a28cff35c687e2010f34261b17c73e` introduced the explicitly synthetic
  semiconductor seed.
- `4400897af83d30dd430d244c5ddd9396bef8cec9` added the manual seeded-data policy revocation probe.
- `5034d13a85ccd4e95725127162ebef2b62718d39` introduced the provider test server's
  `wafer_events` and `urn:li:glossaryTerm:wafer` response fixtures.
- `41d0783dccbe01380533e0ca4cfbe7d7c5c9a64f` extended the same test server with glossary
  assignment behavior. It remained in `frontend/poc-server.providers.test.mjs`.
- `03c0eb77dfd14f797ad8258bb3b40b4948ed5b9b` added a separately executable local GraphRAG
  development fixture.
- `12acfcef91b5384dec9c83df0ff4648a4fcb1078` added explicit router evaluation questions.
- `fab42bd03eb8cbe9b3bcbff6c4cfdb2cf5e5fc6c` introduced the one-command PREP smoke and the
  broad `PREP_RUNTIME_SMOKE_FAILED` fallback, but did not add `Wafer` to the smoke.
- `46500c130de9c8bebedd143eca946b5d9166e63b` removed the broad fallback and added typed smoke
  classifications. Both commits are ancestors of Product `80618b60...`.

There is no history in which `Wafer` moved from those fixtures into
`scripts/smoke_prep39083.mjs`, `scripts/prep39083_deploy.py`, `frontend/poc-prep-bootstrap.mjs`,
or a K9 runtime module.

## Bounded additional target-data scan

The audit also scanned PREP runtime inputs and final-image COPY sources for fixed GlossaryTerm,
GlossaryNode, Dataset, SchemaField, Tag, platformInstance, schema/table, Node and Relation
identifiers plus common sample-domain names. Findings:

- No fixed target Dataset, schema, table, GlossaryTerm, GlossaryNode, Tag, or platformInstance
  identifier exists in the PREP smoke.
- No business-domain `Wafer` value exists in any module explicitly copied by the final Docker
  stage.
- `frontend/poc-k10-portability.mjs` contains a self-contained `k10.customer` simulation fixture.
  It is an explicit manual portability simulator, is not imported by the Product, and is not copied
  into the POC runtime image. It is outside this audit's K6/follow-up boundary and was not changed.
- The fixed managed-graph names and Airflow DAG allowlist are deployment-owned protocol identities,
  not assumptions about target DataHub business metadata.
- Generic URN family prefixes and classification Tag vocabulary are validation/security protocol
  constants, not target resource identifiers.

No remaining hardcoded target-business-data dependency was found in a PREP-runtime-reachable path.

## Verification

Executed from the clean audit worktree:

```text
node --test scripts/smoke_prep39083.test.mjs
29 passed, 0 failed

uv run --frozen --extra dev pytest -q \
  backend/tests/unit/test_prep39083_deploy.py \
  backend/tests/unit/test_prep39083_handoff_contract.py
110 passed

uv run --frozen --extra dev python scripts/verify_static.py
PASS
```

Additional source/release proof:

- Product-to-Handoff PREP runtime input diff: `NONE`.
- Final Docker stage copies selected runtime modules and `dist-poc`; it does not copy
  `poc-server.providers.test.mjs`, backend seeds, local GraphRAG fixture, or manual probes.
- The Vite POC entry graph starts at `poc.html` / `src/poc/main.tsx`; test modules are not imported.
- Repository-wide `entityExists` occurrence count: zero in current source and searched history.
- No PREP, DataHub, Docker container, volume, secret, identity, or user metadata was accessed or
  changed by this audit.

## Decision and next action

Product files changed: none. The Product remains `80618b6039bf994585a2a3ff623b44c1e16efeb5`.
There is no smoke fixture to rename or clean up, and no authorization boundary to widen.

PREP readiness is not asserted by this source audit. The exact next action is a read-only operator
handoff of the preserved failing Product SHA plus the original smoke invocation/stderr or sanitized
failure record that produced `PREP_RUNTIME_SMOKE_FAILED`. That evidence must identify which real
smoke endpoint failed. Do not rerun deploy, create `Wafer` metadata, reset state, or modify
authorization to manufacture a pass.
