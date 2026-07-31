# ADR-0090: Governed workspace monitoring dashboard tabs

## Status

Accepted — 2026-07-31

## Context

The Monitoring page exposed one deployment-owned Grafana page and repeated current platform
capability observations below it. Operators need several named Grafana dashboards in one
Monitoring workspace, while eligible administrators need to maintain their order and presentation
without turning the browser into an arbitrary iframe or connector-configuration authority.

Grafana documents are normally cross-origin, so the DataRiver browser cannot safely inspect their
document height. The existing disabled-first embed contract also requires an exact deployment-owned
origin, explicit enablement, SSO/frame-policy evidence and matching web CSP.

## Decision

1. `platform.monitoring_configurations` owns one versioned, RLS-protected presentation document per
   Workspace. It stores at most eight ordered, non-secret dashboard descriptors: server identifier,
   bounded label, full URL and an explicit `480..2000` pixel page height. It also records the
   canonical payload hash, last administrator and timestamps.
2. A submitted dashboard URL is accepted only when its credential-free HTTP(S) origin exactly
   matches the deployment-owned `UI_GRAFANA_URL` or `GRAFANA_EMBED_BASE_URL` origin. Database state
   may select pages under that origin; it cannot establish a new Grafana host, enable embedding,
   supply credentials or change CSP.
3. `GET /capabilities` remains protected by `operations.read` and returns the sanitized, ordered
   Monitoring configuration. When no Workspace row exists, `UI_GRAFANA_URL` is presented as one
   backward-compatible default tab.
4. `PUT /admin/monitoring-configuration` replaces the ordered document with an `If-Match`
   precondition. The route requires an eligible human administrator and the fresh assurance that
   yields `MONITORING_CONFIGURATION_UPDATE`. The ordinary page shows the edit affordance only from
   the server-derived administrator context; OIDC role strings or browser state do not grant it.
5. An iframe descriptor is returned only when the existing exact-origin deployment embed gate
   passes for that dashboard URL. Otherwise the same server-owned descriptor is an external link.
   Every iframe remains sandboxed and uses `no-referrer`.
6. Current capability observations belong to Admin **System settings**, where the deployment
   inventory and live server observations can be reviewed together. The ordinary Monitoring page
   is reserved for the configured dashboard tabs.
7. Dashboard height is explicit and bounded because cross-origin frame contents cannot be measured
   by DataRiver. The selected height grows the page downward instead of forcing the dashboard into
   the previous fixed-height panel.

## Consequences

- Administrators can maintain several Workspace-specific dashboard views without weakening the
  deployment-owned connector, secret, frame-policy or CSP boundary.
- A deployment without an approved Grafana origin can keep or clear an empty tab document but
  cannot save a dashboard URL. Operators must configure the origin through the existing deployment
  workflow first.
- Updates are optimistic and auditable through the authorization decision plus updater, version and
  payload-hash evidence. General System Settings remains a read-only deployment inventory under
  ADR-0048; this ADR introduces only the bounded Monitoring presentation aggregate.
