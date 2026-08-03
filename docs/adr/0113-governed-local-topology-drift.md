# ADR-0113: Governed local topology drift

- Status: Accepted for P0-C1 source implementation; runtime reconciliation open
- Date: 2026-08-03
- Owners: DataRiver application, security and operations owners

## Context

The ignored `AppliedState` records which local Airflow, DataHub, Redis, object-storage, gateway and
graph capabilities an operator selected. Compose containers can outlive a later source or
configuration change, however, so a healthy container is not proof that it still belongs to the
selected topology. On the Mac development host, Neo4j and APISIX were running while
`local_graph=false` and `local_gateway=false`; the graph environment also selected the local
Compose endpoint. Silently treating those containers as selected would make stale state look
correct, while stopping them automatically could remove a dependency that is still in use.

## Decision

The existing update workflow performs a read-only local-topology audit after Compose configuration
and the existing running-service query, but before confirmation, build-capacity locking, local
reranker reconciliation or any Docker, service or AppliedState mutation.

The audit queries only the exact `datariver-next` and `datariver-local-connectors` Compose project
labels. DataHub keeps its existing provider-health probe and is not inferred from container names.
Video, trading and every unrelated project are outside the query boundary. Known Compose services
are projected to fixed logical keys; an unknown running service increments a bounded count without
retaining or printing its name. Raw labels, container IDs, image references, paths, environment
values and provider stdout/stderr are never operator evidence. Each private project query has one
fixed 20-second timeout and no retry; process, timeout or evidence failure stops with a fixed
sanitized classification.

Evidence keeps four independent classes:

- `expected-missing`: an AppliedState-selected service has no running container;
- `unexpected-running`: a known unselected service is running, or a selected service has duplicate
  running containers;
- `selected-unhealthy`: a selected running service with a Docker health contract is `starting` or
  `unhealthy`; and
- `intent-mismatch`: persisted topology and an allowlisted unambiguous environment intent disagree.

Graph intent is local only when projection is enabled and the credential-free Neo4j URI selects the
Compose `neo4j:7687` endpoint. The environment intent is never unioned into the AppliedState
expected set. Thus `local_graph=false` plus the local graph intent reports both runtime drift and
intent drift instead of silently adopting Neo4j. APISIX has no equivalent authoritative enable
value; a configured port is not treated as adoption intent.

Any non-empty class, duplicate or unknown-running count fails with the fixed
`LOCAL_TOPOLOGY_DRIFT` classification. Query or evidence failures are also sanitized and fail
closed. The audit performs no auto-stop, auto-adopt, restart, removal or AppliedState write.
Reconciliation is a separate governed operation: an accountable operator must choose the intended
topology, prove endpoint and health contracts and use the repository state writer rather than edit
the JSON file directly.

## Compatibility

- `development_cycle.py dev-publish`, `workflow_update_restart.py`, `prep-update` and `prep-check`
  keep their names and existing arguments.
- No environment key, Compose file, Dockerfile, service profile or required daily input changes.
- Optional worker intent continues to come from its existing explicit enable flag; one-shot and
  unselected exited containers are not reported as missing.
- Running services without a Docker healthcheck are accepted as running; services that define a
  healthcheck must reach `healthy`.

## Runtime and evidence boundary

Source tests prove allowlisting, the four classifications, project exclusion, output sanitization
and the pre-mutation workflow position. They do not reconcile the currently observed Neo4j,
APISIX or Airflow state. Neo4j adoption, the APISIX retain/adopt/stop decision and Airflow scheduler
recovery remain separately reviewed runtime gates. There is no auto-stop architecture.
