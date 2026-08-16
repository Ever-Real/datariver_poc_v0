# DEV PHASE 1C-1 System master and exact Table ↔ System runtime evidence

- Product SHA: `60f5f270a56130f2ed96236d9286d0903e3360db`
- Fresh observation: `2026-08-16T19:35:47+0900` (`Asia/Seoul`)
- Target: authoritative local DEV Node POC only
- Slice status: `COMPLETE_RUNTIME_VERIFIED`
- Overall Account/Auth status: `PARTIAL`
- Publication: held; no push, PREP mutation or OPS mutation

## Policy realignment result

The PHASE 1B-R read-only audit confirmed that the existing 15-capability policy, request-scoped
principal and 51-route registry remain reusable. It also confirmed that the old Catalog/read
projection uses Responsible System as data visibility and therefore does **not** satisfy the latest
explicit Table-grant/security-grade policy. This slice does not relabel that old behavior as complete.

PHASE 1C-1 adds only the prerequisite System master and exact Table ↔ System contract:

- existing access-document System records remain the System and responsibility authority;
- exact current DataHub `TABLE` URNs map N:M to active System IDs in bounded
  `poc_state` scope `table-system-mappings-v1`;
- schema is a search/bulk-selection filter only and creates no inheritance rule;
- update preserves stable System ID/code and increments its version;
- UI delete archives (`active=false`) and deactivates dependent current assignments/legacy scopes
  without deleting historical identities;
- inactive exact mapping rows are retained as lifecycle evidence;
- legacy schema scopes remain compatibility/history and were not migrated or deleted.

The mapping scope stores no user, role, capability, responsibility, Table grant or security-policy
authority. No table, migration, dependency, service, container, IAM, workspace, OIDC, Keycloak,
policy engine or permission database was added.

## Runtime image and packaging correction

The first source-built image at intermediate commit `a9bb7f0` exposed a real packaging defect:
`poc-table-system-mappings.mjs` was not copied into the runtime stage. The Web container failed
closed with `ERR_MODULE_NOT_FOUND`; no supporting service or DB was recreated. The canonical
tracked Dockerfile was corrected by commit `71d17a7` and the Web image alone was rebuilt/recreated.

Final observation:

| Field | Result |
|---|---|
| Web OCI revision | `60f5f270a56130f2ed96236d9286d0903e3360db` |
| Image | `sha256:332e11280e60a9d11f15320c06899b1af66a5f70b595526798399f265fdc4fb1` |
| Health | `healthy`; `/healthz` HTTP `200` |
| Web host publish | `127.0.0.1:39083` |
| Airflow host publish | `127.0.0.1:18888` |
| PostgreSQL / Neo4j / Redis | loopback only (`15432` / `17475` / `16379`) |

The ignored deployment `.env` was absent from this worktree. Runtime values were not printed or
reconstructed as tracked config; the existing container environment was passed only in memory to
the Web-only Compose build/recreate process. The final image revision equals the committed Product
SHA.

## Backend runtime and security evidence

Fresh admin/viewer credentials were created through the official access CAS/bootstrap path. Their
passwords and cookies were not recorded in this evidence. The exact runtime results were:

| Check | Result |
|---|---:|
| anonymous mapping read | `401` |
| viewer mapping read / mutation | `403` / `403` |
| wrong Origin | `403` |
| body/header/query authority spoof | `400` / `400` / `400` |
| admin inventory read | `200`; 1,002 current DataHub Tables |
| exact Table assign after synchronous current-provider inventory confirmation | `200` |
| stale `If-Match` retry | `409` |
| non-current Table identity | `400`; mapping CAS version unchanged |
| exact Table remove | `200` |
| concurrent admin/viewer `/auth/me` | distinct server-held subjects and roles |

The final assign/remove operation left one inactive lifecycle row at mapping scope version `4` and zero
active mappings. Every validation credential was disabled with its current version and every active
validation session was revoked. Final storage observations were:

- login-enabled credentials: `0`
- active sessions: `0`
- active exact Table ↔ System mappings: `0`
- MCL ledger events: `46`
- MCL checkpoints: `2`
- CR link events: `4`

One one-time UI validation password was rendered by a transient browser inspection response during
the test. It was immediately treated as compromised: the clipboard was cleared, the credential was
disabled and its session was revoked before evidence closeout. The value is not repeated in source,
Git, evidence or logs and cannot authenticate after cleanup.

## Admin UI evidence

The deployed production build was inspected through a real browser session. The server-held admin
profile exposed the Admin menu, and the System screen rendered:

- stable System master rows and current responsibility assignments;
- System add, metadata update and archive controls;
- exact Table management dialog with 1,002 current `TABLE` rows;
- search plus schema, System and `normal/restricted/credential` filters;
- checkbox selection, Shift range selection and current-result bulk selection;
- multiple target Systems, assign/remove choice and bounded reason input;
- an explicit statement that schema selection creates no future inheritance.

The browser session was revoked and its validation tab was finalized. System update/archive client
semantics and mapping selection behavior are covered by the focused frontend/live-adapter tests;
the backend exact mapping mutation was separately exercised against the deployed runtime above.

## Existing runtime regression

One fresh authenticated read pass returned HTTP `200` JSON for:

```text
/auth/me
/poc-api/capabilities
/poc-api/datahub/catalog?limit=5
/poc-api/datahub/tree
/poc-api/datahub/facets
/poc-api/datahub/dashboard
/poc-api/state/core
/api/v1/change-history/events?limit=5
/api/v1/change-history/summary?week_start=2026-08-10
/api/v1/change-history/weekly?week_start=2026-08-10
```

Authenticated unknown API returned JSON `404`; missing Airflow service credential returned `401`.
The regression credential was then disabled and its session revoked. Scheduler/MCL remained disabled
and unbound; no MCL capture, CR mutation, provider mutation, PREP mutation or OPS mutation occurred.

## Static validation at the Product SHA

```text
cd frontend
npm run test:poc-server  # 65/65 PASS
npm test                 # 86 files, 586/586 PASS
npm run typecheck        # PASS
npm run lint             # PASS
npm run build:poc        # PASS; pre-existing >500 kB warning remains

docker compose --env-file deploy/poc/.env.example \
  -f deploy/poc/docker-compose.poc.yaml config --quiet

AIRFLOW_USERNAME=PLACEHOLDER AIRFLOW_PASSWORD=PLACEHOLDER \
POC_AIRFLOW_SERVICE_TOKEN=PLACEHOLDER COMPOSE_PROFILES=airflow \
docker compose --env-file deploy/poc/.env.example \
  -f deploy/poc/docker-compose.poc.yaml \
  -f deploy/poc/docker-compose.airflow.yaml config --quiet

git diff --check d3c974fd078b07abd2148a0c536debd38228bbdb..60f5f270a56130f2ed96236d9286d0903e3360db
git diff --exit-code d3c974fd078b07abd2148a0c536debd38228bbdb..60f5f270a56130f2ed96236d9286d0903e3360db -- frontend/package-lock.json
```

Changed-document link validation passed. Added-line secret/private-key/conflict scans found zero
findings. The only added concrete URL/IP is an invalid-Origin loopback negative-test fixture.

## Fresh Validator

The first fresh review correctly rejected Product `71d17a7`: mapping PATCH used the availability
oriented last-good Catalog projection, so a deleted or type-changed Table could be accepted while a
refresh ran asynchronously. Product `60f5f27` separates the contracts:

- GET retains the bounded last-good inventory availability behavior;
- PATCH synchronously completes a current DataHub inventory refresh;
- only identities currently classified as `TABLE` can reach the mapping command/CAS write;
- deleted, TABLE-to-VIEW and provider-unavailable tests assert rejection and an unchanged mapping
  version.

The read-only Validator follow-up passed Product `60f5f27` with no remaining blocker in this slice.
It independently confirmed the source order (refresh/current-TABLE checks before command/CAS), the
unchanged-version negative tests, `65/65` focused server tests, deployed source checksum equality,
exact OCI revision, healthy runtime, anonymous `401`, one retained inactive mapping, zero active
mappings/credentials/sessions, and unchanged MCL/checkpoint/CR-link counts. Its canonical
recommendation is `AUTH-1C-1 = COMPLETE_RUNTIME_VERIFIED`; overall Account/Auth remains `PARTIAL`.

## Remaining policy slices

- `AUTH-1C-2`: explicit User ↔ Table grants, user maximum security grade, Responsible System/
  priority administration and credential/session management.
- `AUTH-1C-3`: bounded fixed Feature/Role/Security-grade matrix.
- `AUTH-1C-4`: one CR responsible System plus Developer/Steward/Manager lane alignment while
  preserving historical hashes and receipts.
- `AUTH-1D`: enforce grant/grade before search/count/vector ranking/Chat context/graph traversal
  across every data surface.
- The first synchronous current-provider mapping refresh took several minutes in this DEV runtime.
  Correctness is fail-closed, but management-operation latency remains an optimization target; it
  must not be reduced by reintroducing stale identity acceptance.
- Remote-host network denial remains `TARGET_RECHECK_REQUIRED`; loopback binding is verified locally.
