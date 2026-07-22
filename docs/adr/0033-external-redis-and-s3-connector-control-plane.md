# ADR-0033: External Redis and S3 connector control plane

- Status: Accepted
- Date: 2026-07-22
- Supersedes local-default portions of: ADR-0003, ADR-0005
- Refines: ADR-0012, ADR-0013, ADR-0028

## Decision

The portable DataRiver Compose project owns DataRiver processes, PostgreSQL and the optional local
Keycloak identity profile. It no longer starts or owns a cache/delivery server or an upload object
store. A deployment connects two independently operated Redis endpoints and one external
S3-compatible upload store. The initial source of connection settings is deployment `.env` plus
mounted secret files. The versioned System Settings control plane may later select a tested
workspace-scoped revision for process startup; literal credentials never enter the browser or
PostgreSQL.

Redis cache and delivery remain separate capabilities:

- cache is TTL-only, memory-bounded and evictable (`allkeys-lfu` or an accepted equivalent);
- delivery uses Redis Streams, `noeviction` and reviewed persistence/recovery policy;
- PostgreSQL outbox, inbox and leased business jobs remain canonical, so Redis loss may delay work
  but cannot become a business-state loss or completion claim.

The application continues to use the provider-neutral S3 adapter. The reference external endpoint
is MinIO-compatible, but no MinIO image, lifecycle policy or administrator credential is bundled.
The private API/worker endpoint, browser-reachable presign endpoint, region, bucket names and
least-privilege secret references are deployment inputs. Registration storage remains distinct
from the future immutable-archive port and cannot be called WORM storage.

PostgreSQL and OIDC are bootstrap dependencies and therefore remain deployment-managed. Redis,
DataHub, S3, Airflow, graph, inference and observability connectors appear in the administrator
inventory with server-owned requirement metadata. Development SAVE/TEST/ACTIVATE retains the
ADR-0028 restart boundary; production rollout still requires a separately accepted configuration
controller and secret-manager integration.

## Compatibility and migration

The Python client already speaks the Redis protocol. The canonical settings are
`REDIS_CACHE_URL`, `REDIS_DELIVERY_URL`, `REDIS_CACHE_SECRET_REF` and
`REDIS_DELIVERY_SECRET_REF`. Legacy `VALKEY_CACHE_*` and `VALKEY_QUEUE_*` names are accepted during
the migration window and their old mounted paths are provided as aliases, but new documentation
and revisions use only the Redis names.

Existing object bytes are not migrated by configuration alone. Before a SeaweedFS-to-MinIO
cutover, operators quiesce new upload completion, copy every manifest-owned object while preserving
bucket/key/content metadata, verify size and SHA-256 against PostgreSQL, exercise multipart/CORS/
copy/presign behavior, record the cut line and prepare a reverse delta-copy rollback. The repository
does not delete the old provider volume.

## Security and availability consequences

- Connector endpoints use the explicit non-internal `connectors` network; PostgreSQL stays on the
  private `data` network and public browser traffic never receives provider credentials.
- Redis and S3 connection tests are fixed server-owned probes. Redis performs authenticated PING;
  S3 conformance remains stronger than an HTTP health response.
- Redis, MinIO and every target image/distribution need deployment-specific license, provenance,
  vulnerability and maintenance approval. Removing bundled images does not waive that gate.
- Externalizing stateful dependencies is not an HA claim. ADR-0013 still requires at least three
  independent failure domains, off-host replicated storage and accepted failover/restore evidence.
- MinIO/S3 is upload storage only. Immutable archive and destructive retention automation remain
  `DISABLED_NOT_READY` until ADR-0010/0012 conformance and restore evidence is accepted.

## Required evidence

1. both Redis endpoints reject embedded credentials, use distinct endpoints/databases and pass the
   required cache/delivery policy inspection plus stop/recovery tests;
2. target MinIO/S3 passes private authenticated bucket, multipart, checksum, copy, CORS and browser
   presign tests with anonymous access denied;
3. configuration revisions retain actor, immutable hash, test evidence, activation evidence and
   process-applied version without persisting a secret value;
4. Compose rendering proves there is no bundled Redis/Valkey/SeaweedFS/MinIO service or volume and
   each runtime process receives only its required secret references;
5. target backup/restore and cross-provider migration evidence records object counts, hashes,
   RPO/RTO and rollback disposition before traffic promotion.

Some S3-compatible Community distributions do not implement per-bucket `PutBucketCors`. Such a
deployment may select `S3_CORS_MANAGEMENT_MODE=external` only when its owner configures an exact
cluster/edge origin allowlist and retains a real browser-style preflight result. The default remains
`bucket`, and an unsupported call fails closed; the flag never permits wildcard CORS or omission of
the conformance gate.
