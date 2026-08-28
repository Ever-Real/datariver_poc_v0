# PREP target-independent GlossaryTerm smoke evidence

Date: 2026-08-28 KST  
Product: `3daf21e43830cc42411c15ed375042feadae661c`  
Status: `HOLD_NOT_PROVEN` — local/source verification is complete; Actual PREP is not executed.

## Corrected audit disposition

- `WAFER_FIXTURE_LEAKAGE_NOT_RUNTIME_REACHABLE`: confirmed.
- Wafer test/DEV fixture dependency: present, but the 17 GlossaryTerm-URN occurrences are isolated
  test values and do not read the external DEV DataHub seed.
- PREP GlossaryTerm coverage before this Product: `MISSING`.
- PREP GlossaryTerm coverage after this Product: implemented and locally verified; Actual PREP is
  not yet verified.
- Historical `PREP_RUNTIME_SMOKE_FAILED`: administrator-login/origin failure, not Wafer and not an
  authorization-scope defect.
- Bulk ingestion: `UNPROVEN`; no preserved evidence links it to that failure.

## DEV seed masking classification

The case-insensitive prefix search returns 17 `urn:li:glossaryTerm:wafer...` occurrences. Sixteen
are the exact `wafer` URN and one is the distinct `waferId` fixture. They are grouped by execution
boundary below.

| Files | Occurrences | Boundary | External DEV seed required | Seed absent result |
|---|---:|---|---|---|
| `frontend/poc-server.providers.test.mjs` | 5 | In-process HTTP/GraphQL provider mock | No | Same result; fixture supplies every response |
| `frontend/src/features/admin/PocGlossaryPage.test.tsx` | 1 | Mocked frontend API | No | Same result |
| `frontend/src/features/catalog/CatalogWorkspace.test.tsx` | 3 | Mocked frontend request layer | No | Same result |
| Six backend unit-test files | 8 | Pure fakes/value objects | No | Same result |

The six backend files are `test_catalog_metadata_candidate_service.py`,
`test_catalog_metadata_compiler.py`, `test_datahub_gateway.py`, `test_governance_apply.py`,
`test_manual_metadata_apply_service.py`, and `test_manual_metadata_submission_service.py`.

Other Wafer-bearing test modules, including `frontend/src/poc/pocApi.live.test.ts`, also use an
in-process mock rather than the external DEV DataHub. Two explicitly manual tools do depend on the
seeded evaluation environment: `scripts/probe_policy_revocation.py` requires seeded assets, and
`scripts/verify_chat_knowledge_router.mjs` asks seed-domain evaluation questions. Neither is
imported by Product, copied into the final OCI, or invoked by PREP deploy/smoke. The explicit
semiconductor seed generator remains a DEV/demo input. Therefore DEV seed data does not mask the
new PREP smoke, while it does remain a declared prerequisite of those manual DEV evaluations.

## Historical broad failure recovery

The failing runtime lineage identifies Product
`99acf0d2a8be977323ead2f8647ef5b2ad77add7`. Its deployer invoked:

```text
node scripts/smoke_prep39083.mjs
  --origin http://127.0.0.1:39083
  --username <operator identity>
  --password-file <private temporary file>
  --k9-mode <tracked mode>
  --readiness-timeout-ms 1200000
  --output runtime/prep39083/smoke.json
```

That Product used the same `--origin` value as both loopback transport and the `Origin` request
header. The exact failure path was:

```text
./scripts/prep39083 deploy
  -> run_smoke()
  -> POST /auth/login
  -> Product exact-origin check
  -> HTTP 403 / ORIGIN_FORBIDDEN
  -> Node error: /auth/login returned HTTP 403
  -> legacy wrapper: PREP_RUNTIME_SMOKE_FAILED
```

The sanitized endpoint/status/nested-code proof is preserved by the later canonical-origin
evidence. Product `2a26dc43f1bac3242811c3803c80dc845884bc80` separated loopback transport from
the exact `POC_PUBLIC_ORIGIN` and classified the same boundary as
`PREP_SMOKE_ADMIN_ORIGIN_FAILED`. No authorization capability was broadened. Wafer, a
GlossaryTerm request, and bulk ingestion were not in that failing call path.

## Product correction

Stage 3 now calls the capability-protected read-only endpoint
`GET /poc-api/datahub/glossary/smoke-target` after the existing bounded DataHub reads.

Selection order:

1. If target-owned optional `PREP_GLOSSARY_TERM_URN` is nonblank, validate and resolve that exact
   canonical GlossaryTerm URN.
2. Otherwise, deterministically discover one `GLOSSARY_TERM` from the configured target DataHub,
   then resolve the exact returned URN.
3. Never fall back to Wafer or another business-domain constant.

The exact lookup verifies `entityExists == true`, entity type `GLOSSARY_TERM`,
`GlossaryTerm.exists == true`, non-removed status when exposed, and bounded basic metadata. The
success receipt records the exact selected URN, selection source, read assertions, and
`mutation_performed=false`. The route is protected by the existing `catalog.read` capability; no
admin fallback or authorization widening was added.

Failures preserve only bounded `substage`, `endpoint`, `operation`, `sanitized_reason`, and nested
error code. Provider response bodies, GraphQL error text, names, descriptions, credentials, and
tokens are not retained. The supported typed failure family distinguishes input, discovery, exact
lookup, not-found/current-state, and response-contract failures.

## Local verification — not Actual PREP

| Gate | Result |
|---|---|
| PREP smoke process | 33/33 PASS |
| Product provider + authorization | 32/32 PASS |
| PREP deploy + handoff | 111/111 PASS |
| ESLint | PASS |
| TypeScript typecheck | PASS |
| Standard application build | PASS |
| POC build | PASS |
| Ruff focused lint | PASS |
| Static/source/migration-checksum contract | PASS |
| Node/Python syntax | PASS |
| Diff check | PASS |
| Exact Product OCI | `linux/amd64`, revision equals Product SHA |
| Exact Product image ID | `sha256:6aa0316a55ad268163453d6fa286789c508377f46891f5f30049b88dd523e463` |

Focused fixtures cover runtime discovery, optional configured selection, exact lookup,
`entityExists=false`, invalid Product response, provider GraphQL failure, sanitized diagnostic
propagation, no mutation, route authorization registration, and deploy-stage projection.

## SHA lineage

```text
892239850fbdc447ad1b45df664ad7382b285385  prior Handoff / current origin/main
  -> 80618b6039bf994585a2a3ff623b44c1e16efeb5  audited K9 Product
  -> d37271fcc6115a1ba394deb9210b9bce6550e0e4  K9 Evidence
  -> 5664dd00659d41c5987ed1c2cb30577dfa4f84ea  K9 Handoff / audit base / origin/dev
  -> 36309b226415f40848ed417fbf16c316b62997c9  Wafer audit Evidence
  -> 3daf21e43830cc42411c15ed375042feadae661c  GlossaryTerm smoke Product
```

Thus “Product files changed: 0” in the first audit meant that commit `36309b2...` added Evidence
only; it did not mean the Product SHA must equal that audit base. `release.json` at the audit base
correctly named ancestor Product `80618b6...`, and the source audit inspected that exact Product
plus its linear Evidence/Handoff descendants. The wrong revision was not audited.

## Actual PREP boundary

Actual PREP service health: `NOT EXECUTED` for this Product.  
Actual PREP deployment/runtime smoke: `NOT EXECUTED`.  
Actual PREP GlossaryTerm smoke: `NOT EXECUTED`.  
Selected Actual PREP GlossaryTerm URN: `NOT AVAILABLE`.  
User metadata modified: `NO` by local work; Actual PREP was not accessed.

The current Orca runtime exposes no registered PREP remote environment or host. In addition,
canonical deployment requires an exact Handoff promoted to `origin/main`, whose movement still
requires explicit user approval under the active release policy. Until both boundaries are
resolved, the only honest readiness value is `HOLD_NOT_PROVEN`.
