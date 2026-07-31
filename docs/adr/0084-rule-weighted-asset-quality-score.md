# ADR-0084: Rule-weighted asset Quality score

- Status: Accepted
- Date: 2026-07-31
- Owners: Product, Data Architecture, Application, Data Platform
- Refines: ADR-0077, ADR-0081

## Context

ADR-0081 added the latest Quality score to Catalog search and the asset-centric Quality
workspace. The first read model selected only the newest successful Validation Run for an asset.
Because one Run belongs to one Rule Set Version, that value could omit other active Rule Sets
applied to the same table.

Users interpret the table badge as the table's current aggregate Quality condition. An arithmetic
mean of Rule Set percentages would also give a small Rule Set the same weight as a large Rule Set
and would not represent the proportion of evaluated Rules that passed.

## Decision

For each visible asset, the read model:

1. selects every `ACTIVE` Rule Set and its current `ACTIVE` Version;
2. selects the most recently completed `SUCCEEDED` Run for each Rule Set;
3. pools the selected Runs' passed, advisory-failed and blocking-failed Rule counts; and
4. calculates basis points as:

   `sum(passed Rules) / sum(all evaluated Rules) * 10,000`

The aggregate outcome is `FAIL` when any pooled Rule has a blocking failure, `WARN` when there is
no blocking failure and at least one advisory failure, and `PASS` when every pooled Rule passed.
Archived Rule Sets, superseded Versions and unsuccessful Runs do not contribute. A newer failed,
queued or running Run does not erase the last successful evidence. An asset with no successful Run
for any active Rule Set has no score or outcome.

This is a Rule-weighted pass rate, not an arithmetic mean of per-Rule-Set percentages and not a
row-level data-validity percentage. The API field names remain compatible:
`latest_score_basis_points` and `latest_quality_outcome` now describe the aggregate built from the
latest successful evidence for the active Rule Sets.

## Consequences

- Catalog and Quality asset badges represent all currently active, successfully evaluated Rule
  Sets rather than whichever Rule Set happened to run most recently.
- Rule Sets with more Rules contribute proportionally more evaluated evidence.
- Existing API and frontend contracts remain compatible; no database migration is required.
- The asset's applied Rule Set count still exposes whether Rule Sets exist, while detailed Run
  history remains the place to investigate missing or failed execution evidence.
