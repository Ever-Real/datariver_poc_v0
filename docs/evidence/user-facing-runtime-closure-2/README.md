# USER-FACING-RUNTIME-CLOSURE-2 Evidence

Date: 2026-08-30 KST  
Product: `e2df77ba03f519785963cabe46ba997dd115c7ad`  
Starting TEST Handoff: `5d6491554512b002a40f7bb5642dcf64695c9898`  
Actual PREP: not executed  
Actual OPS: not executed

## Bounded Product scope

This Product preserves the previously accepted timeout and Chat-router contracts and adds only the
requested user-facing closure surfaces:

- System creation confirmation/error visibility and concise server-owned immutable code UX;
- authorized Change History event visibility without guessing a missing Table-to-System mapping;
- page-bounded Glossary assignment counts and Home Dataset schema drill-down;
- Governance editor close protection, canonical italic retention, CSP-safe table editing and readable names;
- cursor-append Resource Tree virtualization, bounded detail-history restore, and owner-bound Catalog CSV/XLSX export.

Unmapped Change History events are selected only from the principal's exact current Table authority.
They carry `UNMAPPED`, no System identity, no assignee, no CR link actions, and no authorized linked CR.
System mapping remains exact Dataset URN to canonical System UUID; fuzzy matching was not added.

No GX provider or infrastructure was invented. The repository has no reviewed canonical GX runtime
provider for this release, so GX runtime acceptance remains an explicit product/environment gap.

## Local verification

- focused frontend integration: `140/140 PASS`;
- Node authorization/server/export/glossary/change-history bundle: `70/70 PASS`;
- backend Governance/export/S3: `98/98 PASS`;
- TypeScript typecheck, ESLint, POC build and application build: PASS;
- static/source and accepted migration checksum integrity: PASS;
- changed-diff runtime target-data special cases: `0` (generic synthetic test identities only);
- `git diff --check`: PASS.

The historical broad migration and K9 audits were not repeated. No migration source changed.

## Exact Product artifact

The clean Product was built once for `linux/amd64` and exported without rebuilding:

- image: `datariver-poc:e2df77ba03f519785963cabe46ba997dd115c7ad`;
- OCI revision: `e2df77ba03f519785963cabe46ba997dd115c7ad`;
- archive SHA-256: `79936d719f69744255c977194e4ed1aa21d0bdee07d1356d8a9ba3e103e5931e`;
- child manifest: `sha256:1bcc22ff0c1c118b4a5d56cc61ccbb268a845d7d5f78e9d3c69e9f5540773786`;
- config: `sha256:f0fa8dcc01aa608bab9eed8cda73f8f716bd8a7565491cd845483eb47e82a687`;
- runtime user: `node` (`1000:1000` in the PREP Compose contract).

The archive is ignored and transported separately. TEST must verify checksum, manifest, config,
platform and revision before `docker load`, and start only through Compose `--no-build` with no pull
or rebuild fallback.

## Runtime gates still required

The prior TEST Product `b3538f1c74b2cc077a74fe2c80a91515a1cf31d9` remains the last accepted
runtime until this Product completes accepted-state deploy, 6/6 smoke, same-command rerun and the
bounded browser/API matrix. Source-level results are not represented as TEST acceptance.

TEST validation must preserve existing volumes, secrets, identities and user metadata. Actual PREP
and Actual OPS remain outside this work.
