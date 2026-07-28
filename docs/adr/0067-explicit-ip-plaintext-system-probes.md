# ADR-0067: Explicit IP opt-in for isolated-network plaintext system probes

- Status: Accepted
- Date: 2026-07-28
- Refines: ADR-0024, ADR-0046, ADR-0048

## Context

Admin System Settings probes are server-owned, fixed-route diagnostics. Their destination
allowlist prevents the browser from turning the API into an arbitrary URL fetcher, while TLS is
required outside a small source-coded local-development hostname set.

Some isolated preparation environments have neither internal DNS nor a certificate authority.
Their approved DataHub, Airflow, Redis, S3-compatible storage, Neo4j, Prometheus and Grafana
services are reachable only through stable IP addresses and plaintext protocols. Adding those IPs
to the destination allowlist correctly authorizes the destination but cannot express the separate
transport exception. Expanding a source-coded hostname set for each deployment is not portable or
auditable.

## Decision

Add the deployment-owned `SYSTEM_CONFIGURATION_PROBE_PLAINTEXT_ALLOWED_IPS` setting. It is empty by
default and accepts only exact IPv4 or IPv6 literals. Every value must also appear in
`SYSTEM_CONFIGURATION_PROBE_ALLOWED_HOSTS`. Hostnames, URLs, ports, CIDRs, wildcards, duplicate
values and link-local, multicast, unspecified or reserved ranges fail validation.

The setting permits plaintext transport only for the existing fixed Admin probes. It does not let
the browser supply a destination, path, credential, query or command. Exact host allowlisting,
address-range rejection, disabled environment-proxy inheritance, disabled redirects, fixed
timeouts, bounded response bodies, mounted secret references and typed response validation remain
unchanged. One approved IP covers multiple services or ports hosted at that address.

The opt-in applies to OIDC JWKS and the typed DataHub, Airflow, Redis, S3, Neo4j, Prometheus and
Grafana probe adapters. It does not relax the independently reviewed HTTPS-only intranet inference
gateway contract. Production browser-facing URL validation also remains HTTPS-only, and deployment
System Settings probes remain development-environment diagnostics.

## Consequences

- An IP-only isolated environment can test its real connectors without source changes or
  deployment-specific hardcoding.
- Operators must record the exact IP in both allowlists and restart the API after changing the
  ignored environment file.
- The exception authenticates and bounds a diagnostic request but does not encrypt it. A network
  that is not physically or logically trusted must add TLS instead of enabling this option.
- Removing an IP from either list fails closed on the next process start or probe.
