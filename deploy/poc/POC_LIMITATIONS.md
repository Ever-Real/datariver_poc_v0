# DataRiver 06111 static POC limitations

## Permanent presentation notice

Every screen displays `POC / NO AUTH / SAMPLE DATA / NOT FOR PRODUCTION`.
This derivative is a static presentation bundle, not a functional DataRiver deployment and not a
production release.

## What the bundle demonstrates

- deterministic navigation through Dashboard, Search, Registration, Change management,
  DataHub-style metadata/columns/lineage, Knowledge, Quality, Quality Run, Chat and Monitoring;
- synthetic asset, evidence, quality and monitoring fixtures;
- browser-memory-only state transitions that reset when the page is refreshed; and
- one source-free `linux/amd64` static Web container exposed on an explicitly selected host port.

Every displayed provider, administration, workflow or execution result is labeled as sample or
simulated. A displayed completion state does not prove a backend command, provider read-back,
migration, authorization decision or durable record.

## Explicitly unavailable and not claimed

- login, identity, OIDC, Keycloak, JWT, authorization, ABAC, RLS or user lifecycle;
- persistence, multi-user consistency, concurrency or audit durability;
- the live DataRiver API, database mutations or database migration/backup/rollback evidence;
- real Registration, Change, Knowledge, Quality or administration commands;
- real Chat/model, DataHub, S3, Neo4j, Redis, PostgreSQL, Airflow or monitoring connections;
- production security, TLS, availability, performance, recovery or operations acceptance; and
- equivalence to the functional 06111 runtime.

## Network and data boundary

The application contains only synthetic, non-sensitive fixtures and performs no application
network request. Its Content Security Policy sets `connect-src 'none'`; the browser retrieves only
the same-origin HTML, JavaScript and CSS needed to render the static page. The bundle has no secret,
credential environment file, provider URL, persistent volume, privileged mode, host network,
Docker socket or writable host bind.

## Runtime identity

The export process records the exact source commit, `linux/amd64` image ID and archive SHA-256 in
the delivered identity/checksum files. The operations host verifies the checksum before extraction,
loads the bundled image with no build or pull, rechecks image ID and platform, validates that
Compose has one image-only service and then starts the distinct `datariver-static-poc` project.

Suggested URL: `http://<operations-pc-ip>:39080` (override with `POC_PORT`).
