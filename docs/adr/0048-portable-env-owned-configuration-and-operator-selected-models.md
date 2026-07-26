# ADR-0048: Portable profiles, environment-owned configuration and operator-selected models

- Status: Accepted
- Date: 2026-07-26
- Refines: ADR-0023, ADR-0024, ADR-0034, ADR-0035, ADR-0046, ADR-0047
- Supersedes: ADR-0028 and the source-selected model identities in ADR-0023/ADR-0047

## Context

The existing managed workflow required an explicit profile and correctly bound one ignored
environment file to Compose interpolation and container configuration. Its profile vocabulary was
nevertheless limited to two physical hosts: Apple-Silicon Mac build mode and WSL amd64 offline
preparation. The Mac bootstrap also selected and enabled three model identities. This coupled OS,
architecture, deployment mode, connector placement and inference choice, and made a reusable
project appear to own one developer's model inventory.

Development System Settings also retained a database SAVE/TEST/ACTIVATE path. The deployed Mac and
WSL profiles disabled that path to preserve one live configuration source, but keeping two
authoring surfaces created an ambiguous operator contract.

## Decision

### Portable and compatibility profiles

The completed implementation will require managed fresh and update workflows to use an explicit
named profile. Profile definitions are
typed operator data containing deployment mode, supported OCI architectures and connector
defaults; workflow code does not infer those values from an OS-name branch.

`portable-development` is the general source-build profile. It accepts `linux/arm64` and
`linux/amd64`, uses an external DataHub by default, and does not enable any LLM, graph, gateway or
host-specific connector. `mac-development` and `wsl-preparation` remain compatibility profiles for
their reviewed local and offline topologies. Every profile writes its selected ignored
`.env.<profile>` path to the applied-state record. Compose interpolation and every container
`env_file` receive that same exact path.

### One live configuration source

After Phase 2, an ignored deployment environment file, or the equivalent orchestrator environment, plus mounted
secret references is the only live connector configuration source. The web application and API
never create, edit or synchronize a host environment file.

Admin System Settings is a read-only, redacted inventory over the API process's validated `Settings`
snapshot. It may execute only fixed server-owned probes for a known System identifier. Database
profile SAVE and ACTIVATE are retired from the product UI/API. Existing profile and revision rows
remain historical audit data until a separately reviewed retention/migration change removes them;
they are not loaded into runtime Settings.

Operator workflows own environment application. They compare a non-secret, permission-restricted
configuration fingerprint with the last applied state and recreate only affected processes.
Credential values remain outside the environment file and fingerprint.

### Model identity is operator-owned

After Phase 4, committed source will contain capability schemas, validation boundaries and copy/paste option names,
but no enabled model identity or fallback model. Bootstrap never enables inference or writes a
Chat, Embedding or Reranker model name. A development operator selects only models already present
on that host and records the identities in its ignored environment file.

The fixed local transport boundaries remain security controls rather than model defaults:
containerized local Ollama uses the exact Docker host gateway and port 11434; source-host mode uses
loopback; the bounded llama.cpp reranker bridge binds loopback port 11435. The reranker manager
requires an explicit model argument and resolves that model only through the governed Ollama model
store. It must not create, pull or derive a model.

## Expected consequences after acceptance

- A clean clone has a portable path and cannot silently acquire the original developer's model
  choice.
- Mac and WSL compatibility procedures remain reproducible without becoming universal defaults.
- Admin connection results describe the running deployment snapshot, not a second desired-state
  store or a hot-reload claim.
- Changing deployment configuration requires the operator workflow and an explicit process
  recreation; changing Admin UI state cannot change infrastructure.
- Historical ADR-0028 activation tests remain useful regression evidence for retired behavior but
  no longer define the accepted product path.
- Public or arbitrary inference endpoints, literal browser credentials, runtime URL pass-through
  and model-created mutation/tool paths remain forbidden.

## Required acceptance evidence

1. portable profile tests cover arm64/amd64, build mode and disabled inference;
2. two distinct selected env files render distinct matching Compose/process settings without
   cross-read;
3. tracked runtime source contains no enabled or fallback model identity;
4. Admin has no connector SAVE/ACTIVATE request path and probes only the live validated Settings
   snapshot;
5. an environment-only change recreates the mapped service and updates the applied fingerprint;
6. local Chat, Embedding and Reranker probes name only models found in the operator-provided
   installed inventory.
