# TEST rerun K9 query-boundary evidence

Date: 2026-08-30

## Scope

This Evidence binds Product
`b3538f1c74b2cc077a74fe2c80a91515a1cf31d9`. The preceding Product
`44fc36b4e7dc64ea7bf08ab3791a2d9874eb1343` completed its first canonical TEST
deployment, but its same-command rerun failed closed during K9 metadata
collection with `GLOSSARY_ASSIGNMENT_COUNT_MISMATCH`.

The failure was caused by a query-boundary regression: the bounded Glossary UI
query was also supplied to the K9 metadata collector, while K9 requires the
complete assignment and relationship projection for its reconciliation
invariants. The first Glossary Term therefore lacked the declared assignment
totals and failed before Term registration.

The Product delta separates the two contracts. The UI query remains bounded;
the K9 collector uses a dedicated complete query. It does not weaken assignment
reconciliation, pagination completeness, authorization, currentness, source
consistency, semantic promotion, or LKG preservation.

## Focused verification

| Gate | Result |
| --- | --- |
| K9 contracts and query-boundary tests | 57 PASS |
| Provider gateway tests | 29 PASS |
| Node syntax check | PASS |
| TypeScript | PASS |
| ESLint | PASS |
| POC build | PASS |
| Static/source and migration integrity | PASS |

The regression test proves that the UI Glossary query excludes the expensive
assignment/relationship fields, the K9 query includes its required complete
projection, and the K9 collector is wired only to the complete query.

## Exact build-once artifact

The clean Product image was built once for `linux/amd64` and exported without a
rebuild or mutable pull.

| Identity | Exact value |
| --- | --- |
| Product | `b3538f1c74b2cc077a74fe2c80a91515a1cf31d9` |
| Image | `datariver-poc:b3538f1c74b2cc077a74fe2c80a91515a1cf31d9` |
| Child manifest | `sha256:ba87b35e34ce0723b7032cfc79db8c0fad4c46596a9421992893d7d921955c4d` |
| Config digest | `sha256:81f9dfc12dffdfd999d910708bd53f5494e085f327aebaa4442e23e901129722` |
| Archive SHA-256 | `589279db1e18112394ccfc30a77cad150b25008c5d3003fe3a1a25603b70a345` |
| Platform | `linux/amd64` |
| OCI revision | exact Product SHA |

## TEST acceptance boundary

The TEST persistent state, runtime secrets, accepted marker, and failed deploy
attempt remain intact. The descendant Handoff must resume with the canonical
`./scripts/prep39083 deploy` command and prove a complete 6/6 pass followed by
one same-command rerun. No reset, resecret, volume deletion, source rebuild, or
user DataHub metadata mutation is authorized.

Until both TEST runs pass, the current release state remains
`CURRENT_TEST_RELEASE_PARTIAL`. Actual PREP and Actual OPS were not executed.
