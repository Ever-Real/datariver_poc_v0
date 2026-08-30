# PREP manual-deploy K9 generation-reconcile evidence

Recorded: 2026-08-31 (Asia/Seoul)  
Product: `374f307567bfd93a8a23416af6abf49e33e13cc3`

## Frozen Product scope

This Product is the exact descendant of the previously published strict-CSP Handoff
`abfd1c1402c7f5d80c8fcff3e8f29f2d021b0090`. It contains the bounded K9 semantic-generation
reconciliation commits `432edbeb89f80dfdff4e448ec2b44f632cc881ea`,
`31b22833adfdf9e8a69ecfd4204b1303e6059b90` and
`6a726c65f16d0905e2042d2ee8f31b5f2a59cc3f`, followed only by the Home schema-summary readability
commit `374f307567bfd93a8a23416af6abf49e33e13cc3`. No later Product source commit is included.

The K9 correction reconciles against the shared active semantic pointer, coalesces the same
generation, queues one follow-up for a distinct newer generation, re-resolves the latest active
generation, preserves the daily boundary, and keeps the accepted graph/LKG and successful schedule
receipt on failure. It does not reset a graph, delete an LKG, patch an index database, extend a
timeout, skip smoke, or force a current pointer.

The existing `dev` worktree at
`/Users/everreal/orca/workspaces/datariver-k9-implementation/CHAT-KG-Router-GPT56-Sol` was preserved
at `b61f0cc074462024484b5d848ab847962306c5db` with its three pre-existing tracked Dashboard changes.
No stash, reset, restore, checkout, clean, commit, overwrite, branch move or worktree removal was
performed. The Product artifact was built from a separate clean temporary `dev` clone whose HEAD
and `origin/dev` both exactly matched the Product.

## Reused local verification

- K9/state/contract plus server focused verification: PASS.
- Same/newer/latest generation, distinct-generation race, coalescing, next daily boundary and
  failure/LKG preservation: PASS.
- Full POC Node: `232 PASS / 13 isolated PostgreSQL skip / 0 FAIL`.
- Home schema-summary readability: focused `7/7 PASS`; typecheck and production build PASS.
- Product source did not change after those checks, so the complete application regression was not
  repeated for this release-only closeout.

## Exact build-once artifact

- image: `datariver-poc:374f307567bfd93a8a23416af6abf49e33e13cc3`
- platform: `linux/amd64`
- archive: `datariver-poc-374f307567bfd93a8a23416af6abf49e33e13cc3-linux-amd64.tar`
- archive SHA-256: `1ecc2e9d308a364540811a250aa6ac378f8478ab3ed975fea5a8a0993b33244b`
- child manifest: `sha256:ce6ee262380033c70baff1884dd023d503c86cf6abb3e9a66b4c337da1563b57`
- config: `sha256:4829dcbeccd352992f7fff7632997af5afda1e70761e454151102d6f9da23d8a`
- OCI revision: `374f307567bfd93a8a23416af6abf49e33e13cc3`
- runtime: Node `v22.19.0`, user `1000:1000`, command `node poc-server.mjs`
- required Product runtime files and Node server entrypoint: PASS

The artifact was created once through `scripts/prep39083_product_artifact.py`. Independent checksum,
image platform/config/revision and bounded runtime-file inspection passed. No earlier OCI was reused,
no frontend-only image was accepted, and no target-side source build fallback is permitted.

## Runtime boundaries preserved

- Last TEST accepted Product: `9fb8aba7b0b23a63a803cf6d5fcbca1852c3bf01`.
- TEST WSL/Linux endpoint `100.84.101.79`: `BLOCKED_EXTERNAL_TEST_CONNECTIVITY`; the online Windows
  peer is not substituted for it.
- Actual PREP doctor, deploy, smoke, K9 alignment and same-command rerun: **NOT EXECUTED** by the
  Control Plane. They remain manual operator actions.
- Actual PREP artifact transfer method: existing user-approved method required; no new transport was
  invented and no archive was transferred by the Control Plane.
- Reset/resecret: NONE.
- Persistent volume or accepted-state mutation: NONE.
- User DataHub metadata mutation: NONE.
- `origin/main`: unchanged at `17f32a52de79077c433bf0beaabac81a48e46062`.

The target continues to use the checksum-pinned archive, `docker load`, `pull_policy: never`, and
Compose `up --no-build` through the canonical `./scripts/prep39083` wrapper. The target must not run
Docker/Compose build, mutable pull, reset, resecret, volume deletion or a direct database patch.
