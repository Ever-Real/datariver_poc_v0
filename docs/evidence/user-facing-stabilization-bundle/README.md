# User-facing stabilization bundle evidence

Date: 2026-08-30

## Scope

This Evidence binds the cumulative Product checkpoint
`44fc36b4e7dc64ea7bf08ab3791a2d9874eb1343`. It contains only the four
stabilization deltas after the last TEST-accepted Handoff
`7cae417b36c2befa61e4819820842e29afbfd6e6`:

- bounded initial Glossary and Search table-detail reads;
- bounded Chat route classification and timing attribution;
- Home Change Request aggregation, new-chat search, Dataset detail modal and
  canonical authorized/current Glossary total;
- exact Table-to-System mapping diagnostics and the existing administrator
  remediation route.

The prior TEST result is not inherited by this descendant Product. Actual PREP
and Actual OPS were not executed. No user metadata was mutated by the local
verification.

## Preserved contracts

- Business metadata names, URNs, provider counts and TEST host addresses are
  not runtime constants.
- Home reuses the canonical authorized/current Glossary total; it does not
  derive a total from the current page.
- Change Detection keeps exact Dataset URN and System UUID identity plus the
  existing ETag/CAS API. It adds no fuzzy or display-name fallback and does not
  widen authorization.
- Provider timeouts and AbortSignal behavior remain bounded. Secondary Search
  panels cannot erase the authorized base detail and retain typed errors.
- Chat keeps GENERAL, VECTOR and GRAPH routing and does not trade recall or
  evidence coverage for a phrase-specific fast path.
- Existing accepted-state ownership, Product-owned PostgreSQL integrity, K9
  source consistency and the no-build exact-artifact deployment contract are
  unchanged.

## Local verification

| Gate | Result |
| --- | --- |
| POC server | 218 PASS; 10 explicit external PostgreSQL opt-in skips |
| Frontend Vitest | 745 PASS in 94 files |
| TypeScript | PASS |
| ESLint | PASS |
| POC build | PASS |
| Application build | PASS |
| Static/source and migration integrity | PASS |
| Exact OCI runtime inventory | PASS; non-root `1000:1000` |

Focused Change Detection verification additionally passed the exact server
mapping test and 24 component tests. Home focused verification passed 8
Dashboard tests, 76 App/Chat/API tests and 29 provider tests. The previously
closed timeout and Chat source corrections were not reopened for redundant
audit.

## Exact build-once artifact

The clean Product was built once for `linux/amd64`. The approved export command
saved and inspected that already-built image; it did not rebuild, pull or load
an image.

| Identity | Exact value |
| --- | --- |
| Product | `44fc36b4e7dc64ea7bf08ab3791a2d9874eb1343` |
| Image | `datariver-poc:44fc36b4e7dc64ea7bf08ab3791a2d9874eb1343` |
| Child manifest | `sha256:794c3601b8200cd77e7fdb61dde309aa623beb7576a950e7d9df01c99e54fe5d` |
| Config digest | `sha256:46e8a9ac364d7da337becd754ec2688847c4e3647fa6ede23280ade575eb57ae` |
| Archive SHA-256 | `c04af3a2da52d06b1aece4a31a03067c91ab8737cd07f5edfbe73ef8d7430d3d` |
| Platform | `linux/amd64` |
| OCI revision | exact Product SHA |

The archive is an ignored release artifact. It must be transported separately
and staged at the exact path pinned by the descendant Handoff. A prior
TEST-approved or Wave artifact is not eligible for this Product.

## Pending TEST acceptance

The accepted TEST state must be preserved. The descendant Handoff must use the
canonical `./scripts/prep39083 deploy` path, verify the exact archive without a
build fallback, and then prove 6/6 smoke plus the same-command rerun. Runtime
acceptance must also cover initial Glossary pagination, Search base and lazy
panels, the frozen Chat timing matrix, Home workflows and exact-mapping
remediation. Reset, resecret, volume deletion, duplicate identities and user
metadata mutation remain prohibited.

Until those runtime and available browser checks pass, the current Product is
`LOCAL_VERIFIED`; it is not `TEST_PC_ACCEPTED`, `PREP_READY` or
`PREP_DEPLOY_SUCCESS`.
