# ADR-0057: Environment-allowlisted local inference hosts

- Status: Accepted
- Date: 2026-07-28
- Refines: ADR-0023, ADR-0047, ADR-0048

## Context

The portable deployment contract already made Chat, Embedding and Reranker endpoints and model
identities operator-owned environment values. Local adapter validation nevertheless named only
`host.docker.internal` and source-host loopback in application and adapter code. That protected the
development-only HTTP boundary, but prevented a containerized WSL or private development topology
from selecting a different runtime-reachable host without a source change.

## Decision

`LOCAL_INFERENCE_ALLOWED_HOSTS` is the deployment-owned, comma-separated allowlist shared by the
three local inference stages. Every enabled local endpoint must use an exact normalized host from
that list, the fixed HTTP `/v1` contract, port `11434` for Ollama Chat/Embedding, or port `11435`
for the llama.cpp Reranker. Userinfo, query strings, fragments, redirects and environment proxy
inheritance remain forbidden. Source-host development may additionally use exact loopback only
when its explicit launcher-owned mode is active.

Settings, Chat adapters and Knowledge pipeline transports consume the same validated allowlist.
Admin exposes only the redacted effective deployment snapshot. The browser cannot submit a host,
URL, model or credential, and no arbitrary HTTP pass-through is introduced.

The active endpoint and model remain part of each immutable deployment identity. Moving to another
PC therefore requires only the selected ignored environment values, the standard process
recreation, and—when the endpoint or model identity changes—the existing governed profile
bootstrap/approval that writes new profile-version UUIDs back to that environment. It never
requires application source changes or an Admin-side activation database.

## Consequences

- Mac, containerized WSL and private development hosts can use different reachable inference
  names or addresses through ignored environment files.
- An endpoint outside the exact allowlist fails before runtime construction, while each adapter
  independently enforces the same host boundary.
- Fixed ports and paths keep the local transport contract bounded; public/SaaS inference still
  requires the separately authenticated, HTTPS-only intranet provider contract.
- Environment changes are not hot reloads. The managed update workflow recreates affected API and
  Knowledge worker processes and verifies their resulting deployment bindings.
