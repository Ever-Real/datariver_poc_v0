# ADR-0095: External Monitoring dashboard links

- Status: Accepted
- Date: 2026-07-31
- Owners: Product, Application, Security Architecture
- Refines: ADR-0048, ADR-0090

## Context

ADR-0090 introduced ordered Workspace Monitoring tabs and restricted saved URLs to the
deployment-owned Grafana origin. Monitoring views are not necessarily Grafana pages: an operator
may need to register another observability product, a vendor status view or an internal dashboard.
Treating every registered link as an iframe or connector endpoint would nevertheless widen the
browser and deployment trust boundary.

## Decision

1. An administrator with fresh `MONITORING_CONFIGURATION_UPDATE` assurance may save up to eight
   ordered, credential-free HTTP(S) Dashboard Links from any origin. Active-content schemes,
   embedded username/password values, blank links and URLs over the existing bound remain invalid.
2. A saved Dashboard Link is non-secret presentation metadata. DataRiver does not fetch, probe,
   proxy, authenticate to or derive a connector from it.
3. Registration never grants iframe permission. The server emits a sandboxed iframe descriptor
   only when the existing deployment-owned Grafana exact-origin, explicit-enable, evidence and CSP
   gates all pass. Every other Dashboard Link is rendered as a new-window link with
   `noopener noreferrer`.
4. The browser continues to render only the server-returned descriptor. It cannot promote a saved
   external link into a frame or widen `frame-src`.
5. User-facing copy uses the provider-neutral label **Dashboard Link**. Grafana is mentioned only
   where the deployment-specific embed control itself is being described.

## Consequences

- A Workspace may organize Monitoring tabs for heterogeneous observability products without
  changing connector or deployment configuration.
- Arbitrary origins remain outside the DataRiver document and network execution boundary unless
  an operator separately changes the deployment-owned iframe policy.
- Existing Grafana tabs and the versioned `platform.monitoring_configurations` schema remain
  compatible; no migration is required.
