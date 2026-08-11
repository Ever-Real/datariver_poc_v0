# DataRiver `06111` static POC agent handoff

Read this file completely before taking any action. This project is a deliberately isolated
derivative and is not the canonical DataRiver repository or a production release.

## 1. Project identity and custody

- Project name: `datariver_poc_v0`
- Project root: `/Volumes/SSD_Mac/workspace/datariver_poc_v0`
- Exact source baseline:
  `06111ae9d94bb423adbd62d31cc56fc43feafd66`
- Baseline branch at creation: local `dev`
- Git remotes at creation: none. The local-clone remote was removed intentionally to prevent an
  accidental push to the canonical repository.
- Clone mode: independent Git object copy (`git clone --no-hardlinks`), not a worktree and not a
  shared-object clone.
- Canonical repository `/Volumes/SSD_Mac/workspace/datariver_v1` is out of scope. Do not read from,
  write to, stage, commit, reset, copy into or otherwise mutate it. All POC work stays below this
  project root.
- The canonical repository had unrelated concurrent working-tree changes when this isolated clone
  was created. None of those working-tree bytes are present here; only the exact committed baseline
  was cloned.

Before work, prove:

```bash
git rev-parse HEAD
git status --short --branch
git remote -v
```

Expected initial identity is exact HEAD `06111ae9d94bb423adbd62d31cc56fc43feafd66`, local branch
`dev`, and no remote. This handoff file itself may be the sole untracked file before implementation.

## 2. User objective

Create a separate, fast, linux/amd64 static demonstration bundle based visually and behaviorally on
DataRiver `06111`. It must be directly reachable by ordinary users at
`http://<operations-pc-ip>:<poc-port>` on an internal network where HTTPS, a DNS domain and SSH
tunnels are unavailable.

This is a presentation POC, not a functional or production DataRiver deployment. The user accepts:

- no login and no user-account behavior;
- no live DataRiver API or database mutation;
- no Keycloak;
- no real external-provider calls; and
- simulated/sample feature flows.

The POC should show how the `06111` platform and the following capabilities behave:

- search and asset detail;
- registration management;
- change management/governance;
- Chat;
- monitoring;
- DataHub-style table, column and lineage views plus clearly simulated admin actions;
- Knowledge management;
- Quality control-plane views; and
- Quality Run/execution progress and results.

## 3. Proven root cause and architecture decision

### 2026-08-11 user-approved hybrid POC scope update

The user subsequently required the POC to connect to separately operated DataHub, Airflow, MinIO
and Chat/Embedding/Reranker services on the internal network, and to start Neo4j with the POC.
That later instruction supersedes this handoff's earlier memory-only/single-static-container rules
only for this isolated POC. The original page components and layout remain mandatory.

Provider credentials remain server-side and must never enter the Vite bundle or browser runtime.
The no-Keycloak browser calls only a same-origin, allowlisted POC gateway. This does not authorize
an anonymous live DataRiver API, a fixed production Subject, a JWT/ABAC/RLS bypass, arbitrary
GraphQL/Cypher/DAG/provider proxying, internet publication, or use of real customer data. Canonical
workflow/control-plane state remains simulated unless a separately approved system owns it.

The original `06111` web SPA initializes OIDC/PKCE and browser Web Crypto. A private-IP HTTP origin
is not a secure context, so `Crypto.subtle` is unavailable. `DEVELOPMENT_ADMIN_PASSWORD_BYPASS_ENABLED`
is not a login, PKCE or Keycloak-origin bypass. Removing Keycloak from the existing Compose file or
changing `.env` cannot make the original SPA operate anonymously.

Do not weaken the live API, JWT validation, ABAC/RLS, Keycloak realm, browser security or release
checksum to escape this constraint. The accepted solution is a separate static POC application
that never instantiates OIDC and never calls the live backend.

## 4. Required isolation and safety rules

1. Preserve the exact baseline commit. Make POC changes only in this isolated project.
2. Do not modify, overwrite or relabel the existing `06111` release archive, checksum, image tags,
   Keycloak volume, PostgreSQL volume or Ops runtime.
3. Do not expose the existing backend anonymously, inject a fixed authenticated Subject, disable
   JWT/ABAC/RLS, edit receipts, stamp migrations or use real user/provider data.
4. Use synthetic, non-sensitive fixture data only. Do not include credentials, tokens, `.env`
   values, customer metadata or captured production responses.
5. The static app must perform no network request except same-origin static assets. It must not
   contact `/api`, Keycloak, DataHub, S3, Chat/LLM, Neo4j, Redis or PostgreSQL.
6. The screen must display a persistent banner such as:
   `POC / NO AUTH / SAMPLE DATA / NOT FOR PRODUCTION`.
7. Use a distinct Compose project, image name, release identity, host port and no named volumes.
8. Keep Ops source-free. Build linux/amd64 elsewhere; Ops receives only an immutable archive,
   checksum and minimal run script/Compose file.
9. Do not add a plugin framework, service mesh, mock server or authentication shim. Prefer a small
   static fixture adapter and the existing frontend structure.

## 5. Recommended implementation boundary

Create a POC-only frontend entry point/build target. It may reuse the `06111` React components,
styles and feature layouts, but it must not mount the normal OIDC provider or normal API client.
Use a compile-time POC boundary or a separate POC entry point; do not insert a runtime login bypass
into the canonical application path.

Recommended minimal structure (adjust only when the existing frontend layout proves a simpler
equivalent):

```text
frontend/src/poc/
  PocApp.tsx
  pocFixtures.ts
  pocApi.ts
  pocRoutes.tsx
  components/PocBanner.tsx
deploy/poc/
  docker-compose.poc.yaml
  POC_LIMITATIONS.md
scripts/
  export_poc_release.sh
  run_poc.sh
```

The fixture adapter should provide deterministic local state for navigation and demonstrations.
Mutating controls may update browser memory only and must reset on refresh. Label every simulated
provider/admin/result state clearly.

If reusing the existing frontend creates extensive OIDC/API coupling, prefer a smaller standalone
React entry point that reproduces the visible shell and selected flows. Do not patch minified
JavaScript inside the existing release image.

## 6. Bundle and runtime contract

Use a derivative identity that cannot be confused with the original release, for example:

```text
source_base=06111ae9d94bb423adbd62d31cc56fc43feafd66
release_type=STATIC_POC
authentication=NONE
canonical_data=NONE
external_integrations=SIMULATED
```

The final bundle should contain only what is required to run one static Web container:

```text
release-poc.tar.gz
release-poc.tar.gz.sha256
images.tar
docker-compose.poc.yaml
run_poc.sh
POC_LIMITATIONS.md
POC_IDENTITY.json
```

Runtime rules:

- one linux/amd64 Web image;
- `pull_policy: never` or equivalent offline behavior;
- one explicit configurable host port, with a suggested default such as `39080`;
- bind to `0.0.0.0` only for this synthetic-data POC;
- no Keycloak/API/PostgreSQL/Redis/worker/provider services;
- no secrets, environment credential files or persistent volumes;
- no privileged mode, host network, Docker socket or writable host bind; and
- a read-only container/root filesystem where the chosen web image supports it.

Ops must verify the archive SHA-256, load the exact image, prove platform `linux/amd64`, and start
the distinct POC project. It must not build source or pull from a registry.

## 7. Minimum feature walkthrough

Provide a deterministic navigation path that can be demonstrated in under ten minutes:

1. Dashboard: POC banner, platform summary and simulated component availability.
2. Search: query, filtered result list and asset detail.
3. Registration: request, validation and completed-state transition in browser memory.
4. Change management: draft, review and approved-state illustration.
5. DataHub-style metadata: dataset, columns and lineage graph; admin action explicitly marked
   simulated.
6. Knowledge: asset/source/publication or Studio-oriented screen using sample evidence.
7. Quality: Rule/Rule Set definition and status.
8. Quality Run: queued/running/completed animation or deterministic step controls and sample
   sanitized results.
9. Chat and monitoring: canned evidence-aware answer and static/simulated metrics.

Do not claim that a displayed result proves a backend, migration, provider or authorization path.

## 8. Acceptance criteria

Source/build acceptance:

- exact baseline ancestry is recorded;
- normal production paths are not modified to bypass authentication;
- focused frontend tests cover navigation, banner, deterministic fixtures and reset behavior;
- typecheck, lint and production POC build pass;
- the generated static files contain no secret-like values or real endpoint URLs; and
- a static scan proves no OIDC/API/provider URL or runtime credential dependency in the POC build.

Target acceptance on an isolated linux/amd64 host:

- archive checksum PASS;
- loaded image platform is `linux/amd64` and exact image ID is recorded;
- `docker compose config` contains exactly one image service, no build, no secrets and no volumes;
- container becomes healthy/running;
- `http://<host-ip>:<poc-port>` opens from another internal PC;
- browser console has no `Crypto.subtle`, OIDC, Keycloak or API error;
- browser Network evidence contains same-origin static assets only;
- the walkthrough above completes with the POC banner always visible; and
- stop/removal deletes only the POC container/network, with no named data volume to remove.

## 9. Explicitly unavailable / not claimed

- authentication, authorization, RLS or user lifecycle;
- persistence or multi-user consistency;
- real registration/governance/Knowledge/Quality commands;
- real Chat/LLM, DataHub, S3, Neo4j, monitoring or lineage integrations;
- database migration, backup or rollback evidence;
- production security, availability, performance or Ops acceptance; and
- equivalence to the functional `06111` runtime.

## 10. Suggested work sequence for the next agent

1. Read this file and the repository `AGENTS.md` completely.
2. Reprove project root, exact HEAD, clean baseline and no Git remote.
3. Inspect only the `06111` frontend composition/OIDC/API boundaries and current feature routes.
4. Produce a short exact-path implementation plan before editing.
5. Implement the smallest POC-only entry point and deterministic fixtures.
6. Run focused frontend tests/type/lint/build.
7. Review generated output for network endpoints, secrets and OIDC/API imports.
8. Add the single-image linux/amd64 offline bundle and target runbook.
9. Record exact file list, commit, image ID, archive checksum and limitations.
10. Stop on any need to touch the canonical repository, live runtime, real data or authentication
    policy.

## 11. Copy/paste start instruction for a new agent

```text
Work only inside /Volumes/SSD_Mac/workspace/datariver_poc_v0.
First read POC_AGENT_HANDOFF.md and AGENTS.md completely, then reprove exact HEAD
06111ae9d94bb423adbd62d31cc56fc43feafd66, clean baseline and no Git remote. Implement the
separate static no-auth, synthetic-data, single-Web-container POC described in the handoff.
Do not access or modify /Volumes/SSD_Mac/workspace/datariver_v1, do not expose the real backend,
do not weaken OIDC/JWT/ABAC/RLS, and do not use real secrets or data. Before editing, report the
exact-path plan; after implementation, report focused tests, linux/amd64 bundle identity,
checksum, browser-network proof and all unavailable capabilities honestly.
```
