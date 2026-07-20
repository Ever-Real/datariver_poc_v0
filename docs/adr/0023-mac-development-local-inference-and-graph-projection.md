# ADR-0023: Mac development local inference and graph projection sandbox

- Status: Accepted
- Date: 2026-07-20
- Refines: ADR-0011, ADR-0019

## Decision

The Mac development topology may opt in to a native, loopback-only Ollama
process.  DataRiver containers reach it solely through
`http://host.docker.internal:11434/v1`; configuration rejects every other host,
port, path, credential and non-development environment.  The bootstrap selects
the local `datariver-gemma4-dev:0.1` derivative, which reuses the installed
`gemma4:e2b-it-qat` weights and fixes an 8,192-token context through a checked-in
Modelfile. The adapter uses the OpenAI-compatible `/chat/completions` contract
and requires one fixed `submit_grounded_answer` function call.

This function is not executable.  It contains only an answer and IDs from the
already authorized evidence bundle.  The server treats its arguments as
untrusted and retains the existing authorization, evidence-integrity and
citation validation before any response is returned.  No model output can call
HTTP, SQL, Cypher, DataHub, a file system, or a DataRiver mutation.  The local
adapter is development-only and is deliberately separate from the governed
provider/worker promotion path in ADR-0019.  It does not claim production
inference readiness, token accounting, provider attestation, durable dispatch,
streaming, or a grounding score.

When no local retention policy is active, only the existing eligible local
security-administrator path can return an explicitly `EPHEMERAL_NO_STORE`
exchange.  It remains ABAC and evidence validated, and persists no session,
prompt, answer, citation or policy binding.

`compose.graph.yaml` provisions a separate loopback-only Neo4j Community
instance with a Docker-secret-backed password and distinct projection volume.
It is not a DataHub component and must never share a DataHub volume, network
identity, database, or credentials.  PostgreSQL immutable knowledge releases
remain canonical.  Until a future projection adapter loads a shadow graph,
verifies its release hash/count/golden queries and atomically switches the
canonical deployment pointer, Neo4j is only a ready local projection sandbox;
it is not an application query source or mutation target.

## Consequences

- Development Chat can exercise the same OpenAI-compatible function-call shape
  as the operational Gemma-family route, without sending evidence off the Mac.
- Model refusal, malformed tool arguments, timeout, unavailable Ollama or an
  unauthorized citation yield the existing `검증 불가` response rather than a
  fallback model or uncited prose.
- DataHub starts from its official `without-neo4j-m1` composition.  Its lineage
  remains a DataHub concern; the separate Neo4j service is for a future
  DataRiver knowledge projection only.
- Operators may delete and rebuild the Neo4j projection volume.  They must not
  delete PostgreSQL knowledge releases to repair a projection.
- Promotion beyond this local developer environment requires the ADR-0011 and
  ADR-0019 worker, attestation, budget, revalidation, observability and
  negative-security gates.
