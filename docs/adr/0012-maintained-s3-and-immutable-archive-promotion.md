# ADR-0012: Maintained S3 targets and immutable-archive promotion

- Status: Accepted
- Date: 2026-07-16
- Refines: ADR-0005, ADR-0010

## Decision

Keep DataRiver provider-neutral at the application boundary. The upload-oriented object-store port
and the `ImmutableArchiveStore` port remain separate even when a deployment selects the same vendor.
They use separate private endpoints or access paths, buckets, credentials, lifecycle rules and
network policies. The upload identity can complete and clean quarantine objects but never writes or
administers the immutable archive. The archive writer cannot delete, shorten retention, bypass a
Legal Hold or administer the target.

SeaweedFS remains the maintained Apache-2.0 local/Pilot default for upload workflow development. It
is not a portable WORM default and it is not promoted to the immutable-archive port until the exact
target version and configuration pass the full ADR-0010 negative conformance and restore suite.

Do not adopt the archived MinIO Community/OSS repository as the default for a new production
deployment. Its official repository became read-only and its final distribution posture moved
toward source-built artifacts. An existing MinIO deployment may be retained only as an explicit,
time-bounded security/legal exception when the deployment owner accepts upstream-fork and AGPL
obligations, owns source builds and security patches, publishes signed digest/SBOM/provenance,
defines a vulnerability-remediation SLA and passes the same Object Lock and restore gates as every
other provider. The product name, an S3 health check or a configured Object Lock flag is never
acceptance evidence.

Production procurement therefore selects a maintained S3-compatible implementation or managed S3
service through a target-specific deployment adapter. Required capabilities are private networking,
TLS, encryption with governed key ownership, versioning, replication across independent failure
domains, checksum-preserving backup/restore, lifecycle controls and compliance-mode Object Lock with
Legal Hold. Cross-border and residency constraints are deployment policy and must be verified from
the actual endpoint and account, not inferred from a vendor name.

## Promotion evidence

A target can back the immutable-archive port only after an accountable reviewer accepts retained,
target-specific evidence for all of the following:

1. immutable image/service version, configuration hash, runtime principal and bucket identity;
2. versioning and compliance-mode retention read-back from a newly written test object;
3. full-content checksum and immutable version-ID equality after write and restore;
4. denied overwrite, protected-version delete, retention shortening and governance-bypass attempts;
5. Legal Hold placement/read-back/release behavior and least-privilege credential negatives;
6. replication and off-host restore drills with measured RPO/RTO;
7. current vulnerability, license, provenance and operational-ownership review.

Missing, stale or contradictory evidence leaves immutable archive and all dependent deletion
automation in `DISABLED_NOT_READY`.

## Rationale

S3 API compatibility does not imply retention semantics, support lifetime or supply-chain
ownership. A provider-neutral port preserves deployment choice while a separate promotion gate
prevents a local development store or a historical product decision from becoming a compliance
claim.

## Consequences

- No object-store brand is hard-coded into domain or application policy.
- Changing the local upload implementation does not change canonical manifests or retention rules.
- A legacy MinIO installation can be migrated or exceptionally sustained without making it the
  portable default.
- Production manifests and provider credentials stay outside the portable source baseline; their
  signed acceptance evidence is part of environment promotion.

## Upstream references reviewed

- <https://github.com/minio/minio>
- <https://github.com/minio/minio/releases>
- <https://github.com/seaweedfs/seaweedfs>
- <https://github.com/seaweedfs/seaweedfs/issues/7194>
- <https://github.com/seaweedfs/seaweedfs/issues/8350>

