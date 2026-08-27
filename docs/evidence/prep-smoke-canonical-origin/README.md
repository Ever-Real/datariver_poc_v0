# PREP authenticated-smoke canonical-origin evidence

Recorded at `2026-08-27T12:07:40Z` for Product
`2a26dc43f1bac3242811c3803c80dc845884bc80` on `dev`. The controlled PREP branch
`origin/main` remained fixed at `2a521eee8d9eaef5bd5d3ae5fd8c946a119393db`.

## Proven root cause and correction

Actual PREP proved that provider preflight, local state services, bootstrap, Web startup, and host
health passed, but authenticated smoke failed at administrator login while the same credential
worked through the browser. The deployer invoked smoke through loopback transport and the smoke
script reused that loopback URL as the HTTP `Origin` header. The Product correctly requires the
request `Origin` to equal the configured `POC_PUBLIC_ORIGIN`; actual PREP uses its approved intranet
origin. The browser therefore passed the exact-origin check while smoke received
`403 ORIGIN_FORBIDDEN`. The old smoke wrapper mislabeled that response as administrator credential
failure.

Smoke now has two explicit, separately validated inputs:

- `--origin` is the host-local transport origin and remains `http://127.0.0.1:39083` in PREP.
- `--request-origin` is the exact canonical `POC_PUBLIC_ORIGIN` from the reconciled effective
  environment.

Every request URL continues to use loopback transport. Login, logout, and GENERAL Chat POST send
only the canonical request origin in their `Origin` header. The Product `assertOrigin()` boundary
was not changed, loopback was not added as an alternate authentication origin, and the tracked
public origin was not changed.

The failure boundary now classifies `403 ORIGIN_FORBIDDEN` as
`PREP_SMOKE_ADMIN_ORIGIN_FAILED`. Only `401 AUTHENTICATION_FAILED` is classified as
`PREP_SMOKE_ADMIN_AUTH_FAILED`; a successful response without an opaque session is a separate
login-contract failure. The sanitized failure receipt contains no password, session cookie, token,
or provider body.

## Runtime and recovery proofs

The smoke-process regression uses loopback request transport with a distinct canonical intranet
origin. It proves canonical-origin login, canonical-origin logout, canonical-origin GENERAL Chat,
loopback host health, and completion through smoke stage 6. Negative cases prove that a loopback
request origin produces the Origin classification and that a wrong password at the canonical
origin produces only the Auth classification.

The actual Product authentication regression uses the same split topology against the server:
correct credentials plus canonical Origin pass; the same credentials plus loopback Origin fail
`ORIGIN_FORBIDDEN`; wrong credentials plus canonical Origin fail `AUTHENTICATION_FAILED`; logout
uses the canonical Origin. No authentication or authorization policy was widened.

The complete isolated Docker state/recovery suite passed against the exact Product commit. Its
current V2 regression creates an owned `SMOKE_FAILED` attempt on the previous release, then resumes
the descendant Product with the same command. It reaches `ACCEPTED`, preserves every generated
ownership secret and volume, leaves the administrator count at one, and retains exactly one
distinct K9 and MCP service identity. The same suite also passed provider-failure zero-mutation,
legacy V1 receipt migration, and historical accepted-state upgrade. No tested path reset a
database, removed a persistent volume, deleted a receipt, or regenerated a preserved secret.

## Verification

- Smoke process contract: `28/28 PASS`.
- Product authentication contract: `10/10 PASS`.
- PREP deploy/handoff focused contracts: `110/110 PASS`.
- Exact Product isolated Docker state/recovery suite: `5/5 PASS`.
- Node Product server: `168/168 PASS`.
- UI: `90 files / 663 tests PASS`.
- ESLint, TypeScript typecheck, standard build, POC build, Ruff lint, strict mypy over `588`
  source files plus the strict deploy script, static verification, Python compile, diff-check, and
  image secret/proxy scan: `PASS`.
- Repository-wide Ruff format check retains three unrelated baseline formatting drifts in
  `test_knowledge_studio_service.py`, `test_local_reranker_service.py`, and
  `test_pilot_release_contract.py`; none is touched by this Product and no global format-all claim
  is made.
- Router/retrieval/reranking/grounding semantics changed: `NO`; Router 60 plus Boundary 8 was not
  rerun.

The exact Product OCI is `linux/amd64`, carries revision
`2a26dc43f1bac3242811c3803c80dc845884bc80`, and has image ID
`sha256:b75b1af0c9b50323c56de07dec5bad935d3d1a5584dc39b923c97201c7e6dacf`. Its pinned Node runtime
imports the provider-preflight module under a read-only, non-root, capability-free disposable
container policy. Image configuration/history contains no provider credential or
credential-bearing proxy value.

The only PREP Product deployment command remains:

```bash
./scripts/prep39083 deploy
```

Actual PREP deployment: **NOT EXECUTED by the DEV Agent**.

Actual OPS deployment: **NOT EXECUTED by the DEV Agent**.
