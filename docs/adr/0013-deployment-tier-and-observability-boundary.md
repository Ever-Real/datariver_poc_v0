# ADR-0013: Truthful deployment tier and observability boundary

- Status: Accepted
- Date: 2026-07-16
- Refines: ADR-0001, ADR-0003

## Decision

Label the repository's Docker Compose and host-development topology **Single-node Pilot**. Multiple
containers, API processes or replicas on one physical host do not change that label. The portable
repository must not advertise HA merely because replica, Patroni, PgBouncer, Kubernetes or HPA
configuration exists.

An environment may be accepted as HA only when it runs across at least three independent physical
servers or VMs with separately reviewable failure domains and off-host replicated/distributed
storage. The complete dependency path must avoid a single host: ingress, API scheduling, identity,
PostgreSQL quorum/failover, queue/cache role, object storage, secrets, telemetry and backup/restore.
Promotion additionally requires automated failover and restore drills, measured SLO evidence,
capacity headroom and an accountable sign-off tied to immutable deployment artifacts. Until then the
visible label remains Single-node Pilot or an explicitly non-HA candidate label.

Use OpenTelemetry Collector as the vendor-neutral telemetry boundary. The standard self-managed
logical stack is:

- OTel Collector for receive/process/export and trace/log correlation;
- Prometheus and Alertmanager for metrics and alert routing;
- Grafana for controlled visualization;
- Tempo for traces and Loki for logs.

These names define interoperable roles, not an instruction to expose all components or to make them
canonical. When an approved enterprise Datadog, Splunk or equivalent service already exists, prefer
an OTel Collector exporter adapter and keep application instrumentation vendor-neutral. Provider
credentials are mounted only into the Collector or its egress boundary, not application code.

The current repository exposes protected bounded-label Prometheus application metrics but does not
deploy or claim the complete stack. A deployment chooses retention, replication, encryption,
residency, HA and license-compliant distributions. Grafana/Loki/Tempo AGPL and any enterprise terms
require the environment's legal and distribution review before promotion.

## Telemetry data policy

Telemetry is operational evidence, never a catalog, policy or audit source of truth. Exporters and
processors must drop or redact prompts, generated text, raw evidence, query text, URNs, access
tokens, secrets, object keys carrying sensitive names and unbounded workspace/user/resource labels.
Metrics use bounded dimensions; logs and traces use correlation IDs and pseudonymous identifiers
only when operationally necessary. CONFIDENTIAL/RESTRICTED content is not exported to a telemetry
provider merely because that provider is approved for ordinary infrastructure logs.

## Acceptance evidence

- Single-node Pilot: documented backup, restore and restart procedure; no HA claim.
- HA candidate: three independent nodes/failure domains and off-host storage are installed, but the
  label still does not claim accepted HA.
- HA accepted: host-loss, database leader-loss, queue/cache degradation, object-store recovery,
  telemetry-backend failure and network-partition drills meet the approved SLO/RPO/RTO and retain
  immutable evidence.
- Observability accepted: authenticated private endpoints, least-privilege exporters, redaction
  tests, cardinality budgets, alert ownership, retention/residency review and failure isolation all
  pass.

## Consequences

- The current Compose topology remains useful for development and a controlled Pilot without
  creating a misleading production-availability claim.
- API replica count and database `max_connections` remain calculated deployment inputs, not portable
  source defaults or HA evidence.
- Telemetry backends can change without application-layer vendor coupling.
- Monitoring failure cannot make a canonical operation fail closed unless a separately approved
  security policy explicitly requires that signal; applications buffer or degrade observability
  without leaking protected payloads.

## Upstream references reviewed

- <https://opentelemetry.io/docs/collector/>
- <https://opentelemetry.io/docs/collector/components/exporter/>
- <https://grafana.com/licensing/>
- <https://grafana.com/oss/tempo/>

