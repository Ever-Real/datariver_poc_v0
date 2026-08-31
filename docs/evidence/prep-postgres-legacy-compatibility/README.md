# PREP PostgreSQL legacy-compatibility evidence

Recorded: 2026-08-31 (Asia/Seoul)  
Product: `631a4f5df4dd64104a0668490e4f942d78af587c`

## Preserved failed release and bounded correction

The failed PREP release remains unchanged: Product
`374f307567bfd93a8a23416af6abf49e33e13cc3`, Evidence
`0bd912cab7f4b4e1d280cf3a5262970fa00c6ed2` and Handoff
`a18894df792e0b476bacf2ab5f1274b198c29444`. Its PREP database, artifact, tag and failed receipt
were not accessed or modified.

Source history and migrations `001` through `003` reproduce the reported PREP surface exactly as
the canonical pre-schema-receipt V1 state: 15 owned tables, 162 columns, 86 constraints, 34 indexes,
2 non-internal triggers, 1 function, no `poc_local_security_events`, no
`poc_chat_messages.discovery_json`, and no schema-contract receipts. Its exact structural
fingerprint is `8d9d48438541c838e93b19dc6651305e34040b0a995764727c172b39d0948bd1`.

The existing classifier already recognizes only that complete signature as `V1_RECEIPT_PENDING`.
The correction makes this exact state enter the existing transactional receipt-and-forward-migration
path before the current-schema integrity gate. It reuses canonical migrations `004` through `007`;
it does not introduce duplicate DDL, broaden fingerprint acceptance, treat `poc_state.version` as a
schema revision, or accept an unknown/partial/drifted/newer schema.

## Data and failure safety

The isolated PostgreSQL 17 / pgvector fixture starts from the exact historical V1 DDL and includes
representative catalog embedding, local credential/hash, local session, table grant, chat
session/message, change-history, K9 policy/run, and all seven reported `poc_state` runtime scopes
with their existing CAS versions. Initialization migrates it to the exact V5 fingerprint
`94708241e9aae3f87a89388a9c86adac3214054c0a37be0f7595544e012eabc5` and preserves those rows and
versions. It creates the immutable V1 through V5 schema receipts only after the applicable schema
integrity checks pass.

The final V5 surface is 16 tables, 171 columns, 94 constraints, 36 indexes, 4 non-internal triggers
and 3 functions. A same-command initialization rerun produces no duplicate DDL, receipt rewrite,
row mutation or state reset. Unknown missing tables, unexpected columns, type drift, constraint
drift, newer unsupported states and legacy-looking fingerprint mismatches remain fail-closed.
Transactional failure coverage confirms no premature receipt or partial migration survives.

## Verification

- PostgreSQL schema-integrity unit tests: `10/10 PASS`.
- Isolated PostgreSQL 17 / pgvector schema-integrity tests: `11/11 PASS`.
- State/security focused tests: `32/32 PASS`.
- Full POC Node suite with isolated PostgreSQL: `247 tests / 246 PASS / 1 isolated Airflow skip / 0 FAIL`.
- PREP deploy/handoff tests: `132 PASS`.
- Touched-file ESLint: PASS.
- `scripts/verify_static.py`: PASS.

The isolated database containers were removed after verification. No Actual PREP command, manual
DDL, reset, resecret, volume deletion, receipt patch or user-metadata mutation was performed.

## Exact build-once artifact

- image: `datariver-poc:631a4f5df4dd64104a0668490e4f942d78af587c`
- platform: `linux/amd64`
- archive: `datariver-poc-631a4f5df4dd64104a0668490e4f942d78af587c-linux-amd64.tar`
- archive size: `124296704` bytes
- archive SHA-256: `72eb1622ff09084b138f315ca189729a750b16bf08442de27c2e742febb172d0`
- manifest: `sha256:74fda2a2271c7b89875baebd493bb35adcf78d0d932931e503c123f090a8579e`
- config: `sha256:4722c074662f582a0eeafefd983420786269733369f674d97cc550cfb49ab106`
- OCI revision: `631a4f5df4dd64104a0668490e4f942d78af587c`
- runtime command: `node poc-server.mjs`
- required Node Product runtime files and entrypoint preflight: PASS

The artifact was created once by `scripts/prep39083_product_artifact.py` from a separate clean
exact `dev` clone. No previous OCI, frontend-only image, manual Dockerfile or target-side build was
used. Actual PREP doctor, deploy, smoke and rerun are **NOT EXECUTED** and remain manual operator
actions.

The unrelated dirty `dev` worktree at
`/Users/everreal/orca/workspaces/datariver-k9-implementation/CHAT-KG-Router-GPT56-Sol` remains
preserved without stash, reset, restore, checkout, clean, commit, overwrite, branch movement or
removal. `origin/main` remains unchanged at `17f32a52de79077c433bf0beaabac81a48e46062`.
