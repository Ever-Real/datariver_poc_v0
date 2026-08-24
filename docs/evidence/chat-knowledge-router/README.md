# Chat Knowledge Router / Managed Knowledge Graph / MCP — DEV closeout evidence

- Observed at: `2026-08-24T04:28:28Z`
- Starting Product: `b5f4064a90adb327c32653f84b67e8f482589173`
- Starting Evidence: `318d30ff28453e94717ce99efec63e6957a65a61`
- Final Product: `698669d8e1ded3c9a8927415fbdee377d163ed56`
- Worktree: `Ever-Real/CHAT-KG-Router-GPT56-Sol`
- Environment: local DEV/Product only; PREP and OPS were not executed

The final Product image `datariver-poc:698669d8e1ded3c9a8927415fbdee377d163ed56`
was healthy on `127.0.0.1:39083` and returned HTTP 200. The persistent status dashboard
on `127.0.0.1:39090` returned HTTP 200. The repository had no tracked Product diff after
the final source verification and exact-SHA image build. `frontend/node_modules` remains the
pre-existing local untracked dependency link and is not Product or Evidence.

## Managed graph registry and refresh

No duplicate Studio graph or projection was created. The existing canonical identities were
reconciled into the managed Asset read model:

| Asset | Graph ID | Studio release | Active projection | Version | Nodes | Edges | Status |
|---|---|---|---|---:|---:|---:|---|
| Default Lineage Graph | `01a02d2a-f8a0-7658-b5da-890eccdccf44` | `01a02d2a-f8ad-789f-acb0-7df3ea3d0ef0` | `k9_stage_84100ceffbdf427090639aca8e778a68` | 6 | 1,001 | 1,950 | READY / NO_OP |
| Metadata Master Graph | `01a02d2a-f90d-74fe-bd96-aa596276cb87` | `01a02d2a-f910-73b7-a2f0-a8f5e4698e88` | `k9_stage_e943653f837d4ce68e033063d5827942` | 6 | 12,281 | 24,556 | READY / SUCCESS |

Both Assets report source `DataHub`, refresh mode `DAILY`, schedule `02:00 Asia/Seoul`, next
refresh `2026-08-24T17:00:00.000Z`, and semantic/vector index `READY`. The successful Metadata
Master promotion completed at `2026-08-24T01:29:21.722Z`; the final Lineage NO_OP completed at
`2026-08-24T01:21:00.070Z`. Failed staging observations preserved the previous active pointer.
Final cleanup observation found exactly the two active K9 namespaces, `0` unfinished refresh
runs, 1,001/1,950 Lineage data nodes/edges and 12,281/24,556 Metadata Master data nodes/edges.
Each namespace also contains one non-data release marker, excluded from the published counts.

The real DataHub runtime placeholders used by the curated verifier were:

- `TABLE_A = cost_ledger_lithography`
- `TABLE_B = vw_cost_ledger_lithography`
- `COLUMN_A = business_key`

The verified Lineage projection includes the real dependency path from
`manufacturing_lot_lithography` and `purchase_order_lithography` into
`cost_ledger_lithography`, then to `vw_cost_ledger_lithography`.

## Router and semantic retrieval

[`router-60.json`](router-60.json) is the exact final production-path run through
`/poc-api/llm/chat` in AUTO mode. It records all 60 questions with expected and actual route,
confidence, concepts, relation intent, resolved entities, selected graph, retrieval method,
runtime outcome, routing/retrieval/total latency, authorization, entity resolution, grounding,
and failure reason.

- GENERAL: 20/20
- VECTOR: 20/20
- GRAPH: 20/20
- Total: 60/60
- GENERAL/VECTOR/GRAPH precision and recall: `1.0`
- Confusion matrix: diagonal `20 / 20 / 20`, all off-diagonal values `0`
- Total latency: p50 `23,665 ms`, p95 `41,871 ms`
- Routing latency: p50 `8,084 ms`, p95 `8,785 ms`
- Retrieval latency: p50 `412 ms`, p95 `32,876 ms`
- LLM calls: exactly `2` for each case (one combined semantic plan and one answer generation);
  no separate synonym or graph-selector LLM call

GENERAL cases performed no internal retrieval. VECTOR V18/V19 returned the authorized managed
Default Lineage Asset rather than an unrelated DataHub table. GRAPH cases include actual node and
relation evidence, selected Default Lineage Asset, semantic entity resolution, bounded traversal,
and provenance. Missing semantic matches are represented honestly rather than fabricated.

[`router-boundary.json`](router-boundary.json) is complete for the exact final Product and was
reused without rerunning: 8/8, GENERAL 2/2, VECTOR 3/3, GRAPH 3/3, with precision and recall `1.0`.

Production routing contains no semiconductor-specific decision rule, test-question map, hardcoded
synonym dictionary, or graph-trigger keyword table. DataHub metadata and managed Asset capability
metadata remain the routing/retrieval sources.

## MCP and authorization

[`mcp-benchmark.json`](mcp-benchmark.json) compares 20 native managed-Asset reads with 20 MCP
adapter calls over the same Core Knowledge Service:

- Native: p50 `234 ms`, p95 `270 ms`, error rate `0%`
- MCP: p50 `231 ms`, p95 `265 ms`, error rate `0%`
- Structured result consistency: PASS
- Invalid token: HTTP 401
- Authorization propagation: PASS

The final architecture is `Internal Chat -> Native Adapter` and
`External Agent/Chat -> MCP Adapter`, both over the same Core Knowledge Service. MCP exposes five
closed read-only tools: metadata search, graph Asset discovery, lineage traversal, release snapshot,
and release GraphRAG. It does not duplicate search or graph business logic.

The dedicated MCP subject returned only its two exact authorized Tables,
`cost_ledger_lithography` and `manufacturing_lot_lithography`. A final read-only snapshot/traversal
returned exactly those two nodes and their one permitted dependency edge. The unauthorized
`purchase_order_lithography` and `vw_cost_ledger_lithography` nodes and edges were absent.
The complete server suite also covers the shared semantic-node negative: an authorized Table A and
unauthorized Table B may share a Term, but the Term cannot admit B, B's metadata, or B's edge
transitively. Native and MCP paths both retain this boundary.

## Source and authenticated browser gates

No production source changed after these exact-Product gates, so the existing results were reused:

- Server: 115/115 PASS
- UI: 87 files / 631 tests PASS
- ESLint: PASS
- TypeScript: PASS
- static verification: PASS
- exact Product OCI build: PASS
- `git diff --check`: PASS

Authenticated browser acceptance on the exact Product passed:

- Knowledge Registry showed both managed Assets, source/status/version/counts, DAILY schedule,
  last/next refresh, last result and semantic index; detail and hard reload persisted.
- Chat GENERAL performed no retrieval; VECTOR returned the canonical managed Asset; GRAPH returned
  actual relation evidence, resolved entity and selected graph; Chat hard reload passed.
- Representative Admin/Profile, Search, Change Management and Monitoring journeys passed.
- Authorized positive, unauthorized negative and existence-hiding paths passed.

## Cleanup

The disposable `kgr-eval-20260824` credential was disabled with the Product's governed credential
disable command, its one active session was revoked, active sessions became `0`, and login returned
HTTP 403. Temporary passwords, cookies, service token copies, logs and intermediate verifier files
were removed after Evidence capture. Canonical DataHub data, the two managed graph Assets, active
projections, durable refresh receipts and persistent service identities were preserved. The
runtime compose override remains only because it is the active local DEV runtime configuration,
not a disposable test fixture.

## Final decision

All DEV/Product gates required for this workstream are `COMPLETE_RUNTIME_VERIFIED`. The Knowledge
roadmap remains closed. PREP and OPS were not executed, and all existing HOLDs remain unchanged.
