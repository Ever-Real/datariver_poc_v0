# ADR-0008: DataHub v1.6.0 stable release contract

- Status: Accepted
- Date: 2026-07-16

## Decision

Support the external DataHub stable release `v1.6.0` as the production catalog-provider contract.
Release candidates, `head`, `latest` and other mutable tags are prohibited in production. The
external DataHub deployment owner pins every component by OCI digest and retains the reviewed bill
of materials. The verified multi-platform index digests are recorded in
`infra/contracts/datahub-v1.6.0-images.json`.

DataRiver continues not to start, migrate or delete DataHub. It reports a degraded DataHub
capability when `/config` reports a different version. Production configuration must use enforcement
mode, which prevents search enrichment, synchronization and governed metadata application from
crossing an unapproved provider contract. Development may use report mode to diagnose a mismatch
without pretending that it is production-compatible.

## Rationale

A mutable image tag can change independently of the reviewed application and an RC can expose a
different GraphQL/aspect contract. A tag alone is therefore not release evidence. DataRiver still
needs a runtime version check because an immutable external deployment can be pointed at the wrong
endpoint after promotion.

## Consequences

- The external deployment repository owns the actual DataHub Compose/Helm image references; this
  repository owns the expected API contract and verified digest BOM.
- Promotion requires live scan, detail, lineage, aspect apply and read-back tests against the pinned
  target. Matching `/config` alone is necessary but not sufficient contract evidence.
- A version mismatch is a sanitized `VERSION_MISMATCH`; provider payloads and tokens are not logged
  or returned.
- Changing the supported DataHub release requires a new ADR, refreshed immutable digests, rollback
  evidence and provider contract tests.
