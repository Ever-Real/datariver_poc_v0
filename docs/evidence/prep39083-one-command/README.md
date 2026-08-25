# PREP39083 one-command handoff evidence

This evidence advances the accepted UX2 Product
`ced6ffeedc9ee9786abc6d12c41c30540201f600` and handoff
`c07f94c58b4ff6c374067e36d1267b395a470090` to the deployment-runtime Product
`fab42bd03eb8cbe9b3bcbff6c4cfdb2cf5e5fc6c`. It verifies the repeatable DEV to
PREP deployment contract from DEV only. No PREP or OPS host was accessed or
mutated.

## Operator contract

The normal PREP path is now:

```bash
git switch dev
git pull --ff-only origin dev

# only on first install or when the deployer names a new required external key
editor deploy/prep39083/.env.prep

./scripts/prep39083 deploy
```

`deploy/prep39083/release.json` supplies Product, Evidence, platform, port and
project identity. The deployer resolves the exact image from rendered Compose;
there is no operator-owned `PRODUCT_SHA` or `IMAGE_REF` shell state.
`scripts/prep39083_release.py` remains the immutable source-check/export/verify
tool and does not build, start, stop, pull or load images.

## Environment and proxy

- `.env.prep` is operator-owned, ignored, mode 0600 and never rewritten.
- `.env.prep.runtime` is deployer-owned, ignored, mode 0600 and preserves
  generated PostgreSQL, Neo4j and MCP secrets across reruns.
- Existing generated values in a legacy `.env.prep` migrate without changing
  that file. Conflicting values fail closed.
- `.env.prep.optional` contains Airflow/MinIO, MCL and monitoring settings. Its
  absence is valid and MCL remains disabled by default.
- `HTTP_PROXY`, `HTTPS_PROXY` and `NO_PROXY` are entered once. Upper/lowercase
  child variables and the required loopback/Compose service exclusions are
  derived without deleting operator exclusions.
- The shell entrypoint uses `uv run --frozen`; the system Python environment is
  outside the contract.
- Docker predefined proxy arguments reach the build without becoming image
  history/cache declarations. npm uses a private step-local npmrc, bounds
  `strict-ssl=false` to dependency installation, restores it to true and removes
  proxy configuration in the same layer. Blank proxy follows normal `npm ci`.

Effective Compose rendering with a credential-free proxy fixture passed. It
proved the build arguments, merged `NO_PROXY`, non-empty automatic image ref and
one exact web/PostgreSQL username/database/password contract. The final exact
no-proxy amd64 build passed; image Env, labels and Docker history contained no
credential-bearing proxy value.

## Bootstrap and database safety

Bootstrap runs through `docker compose run --rm --no-deps web`, inheriting the
same service environment, network and database identity as Product web. It does
not use a raw standalone container or repeat PostgreSQL variables.

A unique, isolated Docker project with a fresh PostgreSQL volume proved:

- initial state inspection;
- one administrator created exactly once from a private temporary password file;
- deterministic, distinct K9 manager and MCP developer Subjects;
- shared canonical PREP Workspace without K9/MCP Subject reuse;
- second reconciliation created no duplicate administrator, service Subject or
  credential;
- service Subjects retained zero active sessions;
- a deliberately wrong application database password returned the classified
  `PREP_LOCAL_DB_CREDENTIAL_MISMATCH` result rather than an unbounded raw `28P01`
  failure.

The deployer never resets an accepted password, removes an accepted volume or
runs `down -v`. A missing accepted-volume secret requires restoration from the
approved target backup; failed-first-install destructive recovery remains outside
automatic deployment.

All isolated simulation containers, networks, volumes, password files and env
files were removed after verification. The pre-existing 39080 container set was
observed unchanged.

## Source and runtime gates

- Deployment/handoff focused tests: 22/22 PASS.
- Target bootstrap tests: 3/3 PASS.
- POC server suite: 122/122 PASS.
- UI suite: 90 files / 658 tests PASS.
- ESLint, TypeScript, POC build, static verification, Ruff, strict mypy, shell
  syntax, Node syntax and diff-check: PASS.
- Effective Compose parse and env ownership/credential projection: PASS.
- Exact `linux/amd64` Docker build and OCI revision: PASS.
- DEV 39083 reconciled to the exact Product, healthy, restart count 0, HTTP 200.
- DEV 39090 dashboard remained HTTP 200.
- Unauthenticated protected API boundary returned HTTP 401.
- Secret scan: no credential or private-key fingerprint added; no proxy secret in
  final image configuration/history or Evidence.

The broad backend suite was additionally observed at 3,890 PASS / 115 SKIP with
55 failures already present in the accepted base. Those failures are unrelated
migration strict-check and host-fixture contracts; this Product changes no backend
production module. They were not hidden, and this bounded deployment workstream
did not expand into repairing unrelated accepted-base debt.

Actual PREP deployment and runtime verification: **NOT EXECUTED**.
Actual OPS deployment and runtime verification: **NOT EXECUTED**.

Result: `PREP_ONE_COMMAND_HANDOFF_READY` after the subsequent release-identity
handoff commit and push to `origin/dev`.
