# P0-1 Migration Exact Inventory

## Overview
This inventory documents the exact decisions, states, and safety predicates for the 54 intermediate migrations modified in d231f1, resolving the blanket bypasses. It establishes the explicit exact-state checking mechanisms required by the control plane.

## Reconciliation Table

| Migration Path | Guards Changed | Decision | Planned Fixture Family |
| --- | --- | --- | --- |
| backend/alembic/versions/0011_governed_classification_access.py | 1 | EXPLICIT_EXACT_STATE_COMPATIBILITY | backend/tests/unit/test_post_baseline_migration_compatibility.py |
| backend/alembic/versions/0013_catalog_hierarchy_projection.py | 1 | RESTORE_ORIGINAL | backend/tests/unit/test_post_baseline_migration_compatibility.py |
| backend/alembic/versions/0014_catalog_exports.py | 1 | RESTORE_ORIGINAL | backend/tests/unit/test_post_baseline_migration_compatibility.py |
| backend/alembic/versions/0015_governance_target_bindings.py | 1 | RESTORE_ORIGINAL | backend/tests/unit/test_post_baseline_migration_compatibility.py |
| backend/alembic/versions/0016_typed_bulk_registration_foundation.py | 1 | RESTORE_ORIGINAL | backend/tests/unit/test_post_baseline_migration_compatibility.py |
| backend/alembic/versions/0017_candidate_submitted_identity_evidence.py | 1 | RESTORE_ORIGINAL | backend/tests/unit/test_post_baseline_migration_compatibility.py |
| backend/alembic/versions/0018_chat_retention_policy_binding.py | 1 | RESTORE_ORIGINAL | backend/tests/unit/test_post_baseline_migration_compatibility.py |
| backend/alembic/versions/0019_catalog_display_metadata_projection.py | 1 | RESTORE_ORIGINAL | backend/tests/unit/test_post_baseline_migration_compatibility.py |
| backend/alembic/versions/0021_catalog_column_name_projection.py | 1 | RESTORE_ORIGINAL | backend/tests/unit/test_post_baseline_migration_compatibility.py |
| backend/alembic/versions/0022_cr_schedule_and_system_master.py | 1 | RESTORE_ORIGINAL | backend/tests/unit/test_post_baseline_migration_compatibility.py |
| backend/alembic/versions/0023_manual_metadata_submissions.py | 1 | RESTORE_ORIGINAL | backend/tests/unit/test_post_baseline_migration_compatibility.py |
| backend/alembic/versions/0024_manual_metadata_apply_leases.py | 1 | RESTORE_ORIGINAL | backend/tests/unit/test_post_baseline_migration_compatibility.py |
| backend/alembic/versions/0027_change_request_attachments.py | 1 | RESTORE_ORIGINAL | backend/tests/unit/test_post_baseline_migration_compatibility.py |
| backend/alembic/versions/0031_workspace_access_roles.py | 1 | EXPLICIT_EXACT_STATE_COMPATIBILITY | backend/tests/unit/test_post_baseline_migration_compatibility.py |
| backend/alembic/versions/0032_membership_renewal_workflow.py | 1 | EXPLICIT_EXACT_STATE_COMPATIBILITY | backend/tests/unit/test_post_baseline_migration_compatibility.py |
| backend/alembic/versions/0033_change_workflow_role_evidence.py | 1 | RESTORE_ORIGINAL | backend/tests/unit/test_post_baseline_migration_compatibility.py |
| backend/alembic/versions/0034_system_configuration_activation.py | 1 | EXPLICIT_EXACT_STATE_COMPATIBILITY | backend/tests/unit/test_post_baseline_migration_compatibility.py |
| backend/alembic/versions/0035_change_request_rounds_and_test_evidence.py | 1 | EXPLICIT_EXACT_STATE_COMPATIBILITY | backend/tests/unit/test_post_baseline_migration_compatibility.py |
| backend/alembic/versions/0036_typed_xlsx_bulk_registration.py | 1 | RESTORE_ORIGINAL | backend/tests/unit/test_post_baseline_migration_compatibility.py |
| backend/alembic/versions/0037_knowledge_source_graphrag_projection.py | 1 | EXPLICIT_EXACT_STATE_COMPATIBILITY | backend/tests/unit/test_post_baseline_migration_compatibility.py |
| backend/alembic/versions/0041_policy_book_rbac.py | 2 | RESTORE_ORIGINAL | backend/tests/unit/test_access_role_persistence.py |
| backend/alembic/versions/0042_retention_execution_control_plane.py | 7 | RESTORE_ORIGINAL | backend/tests/unit/test_retention_execution_persistence.py |
| backend/alembic/versions/0043_system_configuration_probe_scope.py | 3 | RESTORE_ORIGINAL | backend/tests/unit/test_change_request_system_master_persistence.py |
| backend/alembic/versions/0044_admin_cursor_indexes.py | 3 | RESTORE_ORIGINAL | backend/tests/unit/test_admin_cursor_index_migration.py |
| backend/alembic/versions/0045_bounded_catalog_projection.py | 2 | RESTORE_ORIGINAL | backend/tests/unit/test_catalog_projection_migration.py |
| backend/alembic/versions/0046_registration_execution_controls.py | 1 | RESTORE_ORIGINAL | backend/tests/unit/test_post_baseline_migration_compatibility.py |
| backend/alembic/versions/0047_registration_worker_call_receipts.py | 1 | RESTORE_ORIGINAL | backend/tests/unit/test_post_baseline_migration_compatibility.py; backend/tests/unit/test_registration_worker_receipt_migration_contract.py |
| backend/alembic/versions/0048_governance_apply_lease_fencing.py | 1 | RESTORE_ORIGINAL | backend/tests/unit/test_phase3_security_migration_compatibility.py |
| backend/alembic/versions/0049_change_request_attachment_object_identity.py | 1 | RESTORE_ORIGINAL | backend/tests/unit/test_phase3_security_migration_compatibility.py |
| backend/alembic/versions/0051_typed_catalog_metadata_evidence.py | 2 | RESTORE_ORIGINAL | backend/tests/unit/test_typed_catalog_metadata_persistence.py |
| backend/alembic/versions/0053_reranking_probe_scope.py | 2 | RESTORE_ORIGINAL | backend/tests/unit/test_change_request_system_master_persistence.py (bounded flow fixture required) |
| backend/alembic/versions/0054_add_durable_knowledge_source_jobs.py | 9 | RESTORE_ORIGINAL | backend/tests/unit/test_knowledge_source_job_persistence.py (bounded branch fixture required) |
| backend/alembic/versions/0055_atomic_sharing_invocation_results.py | 2 | RESTORE_ORIGINAL | backend/tests/unit/test_sharing_atomic_persistence.py (bounded branch fixture required) |
| backend/alembic/versions/0056_chat_session_favorites.py | 5 | RESTORE_ORIGINAL | backend/tests/unit/test_chat_retention_persistence.py (bounded branch fixture required) |
| backend/alembic/versions/0057_staged_inference_profile_bindings.py | 1 | RESTORE_ORIGINAL | backend/tests/unit/test_classification_access_persistence.py (bounded branch fixture required) |
| backend/alembic/versions/0059_knowledge_studio_foundation.py | 2 | RESTORE_ORIGINAL | backend/tests/unit/test_knowledge_studio_persistence.py (bounded branch fixture required) |
| backend/alembic/versions/0060_knowledge_studio_abox_bindings.py | 2 | RESTORE_ORIGINAL | backend/tests/unit/test_knowledge_studio_persistence.py (bounded branch fixture required) |
| backend/alembic/versions/0061_knowledge_studio_governed_publication.py | 1 | RESTORE_ORIGINAL | backend/tests/unit/test_knowledge_studio_persistence.py (bounded branch fixture required) |
| backend/alembic/versions/0062_knowledge_qa_domain_archive.py | 2 | RESTORE_ORIGINAL | backend/tests/unit/test_knowledge_studio_persistence.py (bounded branch fixture required) |
| backend/alembic/versions/0063_ontology_builder_and_ingestion_jobs.py | 1 | RESTORE_ORIGINAL | backend/tests/unit/test_knowledge_studio_persistence.py (bounded branch fixture required) |
| backend/alembic/versions/0064_normalize_tbox_hierarchy.py | 2 | RESTORE_ORIGINAL | backend/tests/unit/test_knowledge_studio_persistence.py (bounded branch fixture required) |
| backend/alembic/versions/0065_tbox_unicode_hierarchy_relation.py | 1 | RESTORE_ORIGINAL | backend/tests/unit/test_knowledge_studio_persistence.py (bounded branch fixture required) |
| backend/alembic/versions/0066_knowledge_studio_session_domains.py | 1 | RESTORE_ORIGINAL | backend/tests/unit/test_knowledge_studio_persistence.py (bounded branch fixture required) |
| backend/alembic/versions/0067_quality_control_plane.py | 2 | RESTORE_ORIGINAL | backend/tests/unit/test_quality_persistence.py (bounded branch fixture required) |
| backend/alembic/versions/0068_catalog_profile_projection.py | 2 | RESTORE_ORIGINAL | backend/tests/unit/test_catalog_profile_persistence.py (bounded branch fixture required) |
| backend/alembic/versions/0082_knowledge_source_media_type_vocabulary.py | 1 | RESTORE_ORIGINAL | backend/tests/unit/test_knowledge_source_media_contract.py |
| backend/alembic/versions/0084_governed_knowledge_studio_tbox_proposal_jobs.py | 2 | RESTORE_ORIGINAL | backend/tests/unit/test_knowledge_studio_persistence.py |
| backend/alembic/versions/0087_fix_knowledge_studio_proposal_job_idempotency.py | 2 | RESTORE_ORIGINAL | backend/tests/unit/test_knowledge_studio_persistence.py |
| backend/alembic/versions/0088_restore_knowledge_studio_proposal_contracts.py | 2 | RESTORE_ORIGINAL | backend/tests/unit/test_knowledge_studio_persistence.py |
| backend/alembic/versions/0089_canonical_admin_role_binding.py | 4 | RESTORE_ORIGINAL | backend/tests/unit/test_access_role_persistence.py; backend/tests/unit/test_identity_provisioning_persistence.py |
| backend/alembic/versions/0092_change_request_editable_revisions.py | 2 | RESTORE_ORIGINAL | backend/tests/unit/test_post_baseline_migration_compatibility.py; backend/tests/unit/test_phase3_security_migration_compatibility.py |
| backend/alembic/versions/0093_fix_knowledge_studio_proposal_job_idempotency.py | 5 | RESTORE_ORIGINAL | backend/tests/unit/test_knowledge_studio_persistence.py |
| backend/alembic/versions/0094_align_knowledge_proposal_authorization_scope.py | 4 | RESTORE_ORIGINAL | backend/tests/unit/test_knowledge_studio_persistence.py |
| backend/alembic/versions/0095_fix_tbox_proposal_control_character_guard.py | 4 | RESTORE_ORIGINAL | backend/tests/unit/test_knowledge_studio_persistence.py |

## Detailed File Inventory

### 0011_governed_classification_access.py
- **Pre-d231 Control-Flow Predicate & Guard Location:**
  `backend/alembic/versions/0011_governed_classification_access.py`
  ```python
      if existing_tables:
          if existing_tables != 7:
              raise RuntimeError("The governed classification schema is only partially present.")
          _install_security_contract()
          return
  ```
- **0001 Line/Object Definitions:**
  `authz.classification_access_generations` (Lines 297-308): `workspace_id` (Uuid), `generation` (BigInteger), `updated_at` (DateTime).
  Constraints: `ck_classification_access_generations_generation_nonnegative`, `fk_..._workspace_id_workspaces`, `pk_classification_access_generations`.
  RLS: `ENABLE ROW LEVEL SECURITY`, `FORCE ROW LEVEL SECURITY`.
  Policy: `CREATE POLICY workspace_isolation ON authz.classification_access_generations USING ...`.
  (Also creates `classification_access_policy_versions`, `classification_access_policy_rules`, `restricted_search_grants`, `restricted_search_grant_events`, `inference_provider_generations`, `inference_provider_profile_versions` in 0001 with exact columns, constraints, triggers, and `datariver_app` grants).
- **0001 Early Return & Decision:** Current 0001 matches `existing_tables == 7`, but this helper only verifies table presence, NOT columns, constraints, RLS enable+force, policies, or grants. Thus, it does not prove canonical shape. **Decision: EXPLICIT_EXACT_STATE_COMPATIBILITY**.
- **Compatibility A/B/C:**
  - Predicate A: If exact security shape (all 7 tables, exact columns, `ck_...` constraints, RLS `ENABLE/FORCE`, `workspace_isolation` policies, triggers, and exact `datariver_app` grants) completely matches: return cleanly.
  - Predicate B: If exactly 0 objects present: execute full migration.
  - Predicate C: If partially present or malformed (e.g., 7 tables exist but RLS is missing or columns mismatch): raise RuntimeError("The governed classification schema is only partially present.")
- **Test Harness:** `backend/tests/unit/test_post_baseline_migration_compatibility.py`. Concrete fixture: [NEW FIXTURE REQUIRED]. Implement exact shape helper, mutate a policy or constraint to simulate partial state, and assert `pytest.raises(RuntimeError, match="partially present")`.

### 0013_catalog_hierarchy_projection.py
- **Pre-d231 Control-Flow Predicate & Guard Location:**
  `backend/alembic/versions/0013_catalog_hierarchy_projection.py`
  ```python
      existing_objects = _existing_object_count()
      if existing_objects:
          if existing_objects != EXPECTED_OBJECT_COUNT:
              raise RuntimeError("The catalog hierarchy projection is only partially present.")
          return
  ```
- **0001 Line/Object Definitions:**
  `catalog.assets_projection` (Lines 371-372): `database_name` (String(length=255), null=True), `schema_name` (String(length=255), null=True).
  Index (Lines 387-393): `ix_assets_projection_tree_active` on `('workspace_id', 'platform', 'database_name', 'schema_name', 'name', 'id')`, predicate `deleted_at IS NULL AND lifecycle = 'ACTIVE'`.
- **0001 Early Return & Decision:** Current 0001 creates exactly EXPECTED_OBJECT_COUNT (3) objects, so the original guard bypasses the `raise RuntimeError` and safely returns. **Decision: RESTORE_ORIGINAL**, preserving the original predicate exactly.
- **Compatibility A/B/C:** (N/A, restoring original safe predicate).
- **Test Harness:** `backend/tests/unit/test_post_baseline_migration_compatibility.py`. Concrete fixture: Existing `test_post_baseline_upgrade_fails_if_compatibility_objects_missing` uses `monkeypatch.setattr(module, "_existing_object_count", lambda: 1)` and asserts `pytest.raises(RuntimeError, match="partially present")`.

### 0014_catalog_exports.py
- **Pre-d231 Control-Flow Predicate & Guard Location:**
  `backend/alembic/versions/0014_catalog_exports.py`
  ```python
      existing_objects = _existing_object_count()
      if existing_objects:
          if existing_objects != EXPECTED_OBJECT_COUNT:
              raise RuntimeError("The governed catalog export schema is only partially present.")
          _install_security_contract()
          return
  ```
- **0001 Line/Object Definitions:**
  `catalog.export_requests` (Lines 441-455): `workspace_id` (Uuid, null=False), `requested_by` (Uuid, null=False), `created_at` (DateTime, null=False), `state` (String(length=50), null=False), `file_format` (String(length=50), null=False).
  Constraints: `pk_catalog_export_requests`, `fk_catalog_export_requests_requested_by_subjects`.
  Index (Lines 461-463): `ix_catalog_exports_owner_time` on `('workspace_id', 'requested_by', 'created_at')`.
  RLS: ENABLED + FORCED with `workspace_isolation` and `catalog_export_owner_select` policies. Grants to `datariver_app`.
- **0001 Early Return & Decision:** Current 0001 creates exactly EXPECTED_OBJECT_COUNT (2) objects, taking the complete-state early return. **Decision: RESTORE_ORIGINAL**, preserving original predicate.
- **Compatibility A/B/C:** (N/A, restoring original safe predicate).
- **Test Harness:** `backend/tests/unit/test_post_baseline_migration_compatibility.py`. Concrete fixture: Existing `test_post_baseline_upgrade_fails_if_compatibility_objects_missing` uses `monkeypatch.setattr(module, "_existing_object_count", lambda: 1)` and asserts `pytest.raises(RuntimeError, match="partially present")`.

### 0015_governance_target_bindings.py
- **Pre-d231 Control-Flow Predicate & Guard Location:**
  `backend/alembic/versions/0015_governance_target_bindings.py`
  ```python
      existing_objects = _existing_object_count()
      if existing_objects:
          if existing_objects != EXPECTED_OBJECT_COUNT:
              raise RuntimeError("The governance target binding schema is only partially present.")
          return
  ```
- **0001 Line/Object Definitions:**
  `governance.change_request_items` (Lines 1113-1122): `target_asset_id` (Uuid, null=True), `target_asset_type` (String(length=100), null=True), `target_system_id` (Uuid, null=True), `target_domain_id` (Uuid, null=True), `target_owner_department_id` (Uuid, null=True), `target_classification` (Integer, null=True), `target_lifecycle` (String(length=50), null=True), `target_source_version` (String(length=255), null=True), `target_observed_at` (DateTime, null=True), `target_binding_hash` (String(length=64), null=True).
  Constraints: `ck_change_request_items_target_binding_shape`, `ck_change_request_items_target_classification_range`, `ck_change_request_items_target_binding_hash_sha256`.
  Index: `ix_change_items_target`.
- **0001 Early Return & Decision:** Current 0001 creates exactly 14 expected objects. The guard takes the early return. **Decision: RESTORE_ORIGINAL**, preserving exact predicate.
- **Compatibility A/B/C:** (N/A, restoring original safe predicate).
- **Test Harness:** `backend/tests/unit/test_post_baseline_migration_compatibility.py`. Concrete fixture: Existing `test_post_baseline_upgrade_fails_if_compatibility_objects_missing` uses `monkeypatch.setattr(module, "_existing_object_count", lambda: 1)` and asserts `pytest.raises(RuntimeError, match="partially present")`.

### 0016_typed_bulk_registration_foundation.py
- **Pre-d231 Control-Flow Predicate & Guard Location:**
  `backend/alembic/versions/0016_typed_bulk_registration_foundation.py`
  ```python
      existing_objects = _existing_object_count()
      if existing_objects:
          if existing_objects != EXPECTED_OBJECT_COUNT:
              raise RuntimeError("The typed BULK registration schema is only partially present.")
          _install_security_contract()
          return
  ```
- **0001 Line/Object Definitions:**
  `integration.object_manifests` (Lines 1318): `content_profile` (String(length=100), null=False, server_default='FORMAT_ONLY_V1').
  `integration.upload_preparation_jobs`, `upload_preparation_receipts`, `upload_registration_candidates`, `governance.registration_content_bindings` tables created.
  RLS: ENABLED + FORCED, `workspace_isolation` policies, `ix_upload_preparation_jobs_claim` index.
- **0001 Early Return & Decision:** Current 0001 creates exactly 10 expected objects. Guard skips raise and returns. **Decision: RESTORE_ORIGINAL**, preserving exact predicate.
- **Compatibility A/B/C:** (N/A, restoring original safe predicate).
- **Test Harness:** `backend/tests/unit/test_post_baseline_migration_compatibility.py`. Concrete fixture: Existing `test_post_baseline_upgrade_fails_if_compatibility_objects_missing` uses `monkeypatch.setattr(module, "_existing_object_count", lambda: 1)` and asserts `pytest.raises(RuntimeError, match="partially present")`.

### 0017_candidate_submitted_identity_evidence.py
- **Pre-d231 Control-Flow Predicate & Guard Location:**
  `backend/alembic/versions/0017_candidate_submitted_identity_evidence.py`
  ```python
      existing_objects = _existing_object_count()
      if existing_objects:
          if existing_objects != EXPECTED_OBJECT_COUNT:
              raise RuntimeError(
                  "The submitted candidate identity evidence schema is only partially present."
              )
          _install_immutability_contract()
          return
  ```
- **0001 Line/Object Definitions:**
  `integration.upload_registration_candidates` (Lines 1438-1443): `evidence_version` (String(length=100), null=False, server_default='DATASET_DESCRIPTION_CANDIDATE_V2'), `submitted_platform` (String(length=100), null=True), `submitted_database_name` (String(length=255), null=True), `submitted_schema_name` (String(length=255), null=True), `submitted_table_name` (String(length=500), null=True), `submitted_identity_hash` (String(length=64), null=True).
  Constraints: `ck_upload_registration_candidates_evidence_version_allowlist` and 5 others ensuring submitted shape.
- **0001 Early Return & Decision:** Current 0001 creates exactly 12 expected objects. Guard takes early return. **Decision: RESTORE_ORIGINAL**, preserving exact predicate.
- **Compatibility A/B/C:** (N/A, restoring original safe predicate).
- **Test Harness:** `backend/tests/unit/test_post_baseline_migration_compatibility.py`. Concrete fixture: Existing `test_post_baseline_upgrade_fails_if_compatibility_objects_missing` uses `monkeypatch.setattr(module, "_existing_object_count", lambda: 1)` and asserts `pytest.raises(RuntimeError, match="partially present")`.

### 0018_chat_retention_policy_binding.py
- **Pre-d231 Control-Flow Predicate & Guard Location:**
  `backend/alembic/versions/0018_chat_retention_policy_binding.py`
  ```python
      existing_objects = _existing_object_count()
      if existing_objects:
          if existing_objects != EXPECTED_OBJECT_COUNT:
              raise RuntimeError("The Chat retention binding schema is only partially present.")
          _assert_chat_retention_binding_contract()
          return
  ```
- **0001 Line/Object Definitions:**
  `assistant.chat_sessions` (Lines 1599-1602): `retention_policy_id` (Uuid, null=True), `retention_policy_hash` (String(length=64), null=True), `retention_basis_at` (DateTime, null=True), `retention_binding_version` (String(length=32), null=False, server_default='ACTIVE_POLICY_V1').
  Constraints: `ck_chat_sessions_retention_binding_version_allowlist`, `ck_chat_sessions_retention_binding_shape`, `ck_chat_sessions_retention_policy_hash_sha256`, `ck_chat_sessions_retention_window`.
- **0001 Early Return & Decision:** Current 0001 creates the expected columns/constraints, guard cleanly bypasses the raise. **Decision: RESTORE_ORIGINAL**, preserving exact predicate.
- **Compatibility A/B/C:** (N/A, restoring original safe predicate).
- **Test Harness:** `backend/tests/unit/test_post_baseline_migration_compatibility.py`. Concrete fixture: Existing `test_post_baseline_upgrade_fails_if_compatibility_objects_missing` uses `monkeypatch.setattr(module, "_existing_object_count", lambda: 1)` and asserts `pytest.raises(RuntimeError, match="partially present")`.

### 0019_catalog_display_metadata_projection.py
- **Pre-d231 Control-Flow Predicate & Guard Location:**
  `backend/alembic/versions/0019_catalog_display_metadata_projection.py`
  ```python
      existing_objects = _existing_object_count()
      if existing_objects:
          if existing_objects != EXPECTED_OBJECT_COUNT:
              raise RuntimeError("The catalog display metadata projection is only partially present.")
          return
  ```
- **0001 Line/Object Definitions:**
  Columns in `catalog.assets_projection`: `owner_ref`, `domain_ref`, `tags`, `glossary_terms`, `source_created_at`.
  Constraints on `catalog.assets_projection`: `ck_assets_projection_tags_array`, `ck_assets_projection_glossary_terms_array`.
  `_existing_object_count` executes an explicit SQL query on `information_schema.columns` and `pg_constraint` to validate exact presence.
- **0001 Early Return & Decision:** Current 0001 creates exactly `EXPECTED_OBJECT_COUNT` (5 columns + 2 constraints = 7) objects. The explicit shape query successfully matches exact canonical state and safely returns. **Decision: RESTORE_ORIGINAL**, preserving the original predicate exactly.
- **Compatibility A/B/C:** (N/A, restoring original explicit safe predicate).
- **Test Harness:** `backend/tests/unit/test_post_baseline_migration_compatibility.py`. Concrete fixture: Existing `test_post_baseline_upgrade_fails_if_compatibility_objects_missing` (mutates `_existing_object_count` via monkeypatch and asserts `pytest.raises(RuntimeError, match="partially present")`).

### 0021_catalog_column_name_projection.py
- **Pre-d231 Control-Flow Predicate & Guard Location:**
  `backend/alembic/versions/0021_catalog_column_name_projection.py`
  ```python
      existing_objects = _existing_object_count()
      if existing_objects:
          if existing_objects != EXPECTED_OBJECT_COUNT:
              raise RuntimeError("The catalog column-name projection is only partially present.")
          return
  ```
- **0001 Line/Object Definitions:**
  Columns in `catalog.assets_projection`: `column_names` (postgresql.JSONB, null=False, server_default="[]").
  Constraints: `ck_assets_projection_column_names_array`.
  `_existing_object_count` explicitly queries `information_schema.columns` and `pg_constraint`.
- **0001 Early Return & Decision:** Current 0001 creates exactly `EXPECTED_OBJECT_COUNT` (2) objects, explicitly validating canonical shape and taking the early return. **Decision: RESTORE_ORIGINAL**, preserving exact predicate.
- **Compatibility A/B/C:** (N/A, restoring original explicit safe predicate).
- **Test Harness:** `backend/tests/unit/test_post_baseline_migration_compatibility.py`. Concrete fixture: Existing `test_post_baseline_upgrade_fails_if_compatibility_objects_missing` (mutates count and asserts `RuntimeError`).

### 0022_cr_schedule_and_system_master.py
- **Pre-d231 Control-Flow Predicate & Guard Location:**
  `backend/alembic/versions/0022_cr_schedule_and_system_master.py`
  ```python
      existing_objects = _existing_object_count()
      if existing_objects:
          if existing_objects != EXPECTED_OBJECT_COUNT:
              raise RuntimeError("The Change Request schedule and master system schemas are only partially present.")
          _install_security_contract()
          return
  ```
- **0001 Line/Object Definitions:**
  Columns in `governance.change_requests`: `requested_due_date`, `priority`, `urgency`.
  Constraints in `governance`: `ck_change_requests_priority_vocabulary`, `ck_change_requests_urgency_vocabulary`.
  Tables in `platform`: `data_systems`, `system_schema_scopes`, `system_assignees`, `external_service_profiles`.
  Constraints in `platform`: 9 explicit `ck_...` constraints on the above tables.
  Indexes: 4 explicit `ix_...` indexes.
  Policies: 4 explicit `workspace_isolation` policies.
  `_existing_object_count` explicitly verifies all 26 of these exact facts.
- **0001 Early Return & Decision:** Current 0001 creates exactly EXPECTED_OBJECT_COUNT (26) objects. The explicit shape query successfully matches exact canonical state. **Decision: RESTORE_ORIGINAL**, preserving exact predicate.
- **Compatibility A/B/C:** (N/A, restoring original explicit safe predicate).
- **Test Harness:** `backend/tests/unit/test_post_baseline_migration_compatibility.py`. Concrete fixture: Existing `test_post_baseline_upgrade_fails_if_compatibility_objects_missing` (mutates count and asserts `RuntimeError`).

### 0023_manual_metadata_submissions.py
- **Pre-d231 Control-Flow Predicate & Guard Location:**
  `backend/alembic/versions/0023_manual_metadata_submissions.py`
  ```python
      existing_objects = _existing_object_count()
      if existing_objects:
          if existing_objects != EXPECTED_OBJECT_COUNT:
              raise RuntimeError("The manual metadata submission schema is only partially present.")
          _install_security_contract()
          return
  ```
- **0001 Line/Object Definitions:**
  Table: `governance.manual_metadata_submissions`.
  Constraints: 12 explicit `uq_...`, `fk_...`, and `ck_...` constraints.
  Index: `ix_manual_metadata_submissions_workspace_state`.
  Policy: `workspace_isolation` on `manual_metadata_submissions`.
  `_existing_object_count` explicitly queries `pg_constraint`, `pg_indexes`, `pg_policies` to verify exactly 15 canonical shapes.
- **0001 Early Return & Decision:** Current 0001 creates exactly 15 objects. The explicit shape query returns true. **Decision: RESTORE_ORIGINAL**, preserving exact predicate.
- **Compatibility A/B/C:** (N/A, restoring original explicit safe predicate).
- **Test Harness:** `backend/tests/unit/test_post_baseline_migration_compatibility.py`. Concrete fixture: Existing `test_post_baseline_upgrade_fails_if_compatibility_objects_missing` (mutates count and asserts `RuntimeError`).

### 0024_manual_metadata_apply_leases.py
- **Pre-d231 Control-Flow Predicate & Guard Location:**
  `backend/alembic/versions/0024_manual_metadata_apply_leases.py`
  ```python
      existing_objects = _existing_object_count()
      if existing_objects:
          if existing_objects != EXPECTED_OBJECT_COUNT:
              raise RuntimeError("The manual metadata apply lease schema is only partially present.")
          return
  ```
- **0001 Line/Object Definitions:**
  Columns in `governance.manual_metadata_submissions`: `attempts` (Integer, null=False, default=0), `lease_expires_at` (DateTime, null=True).
  Constraint: `ck_manual_metadata_submissions_attempts_nonnegative`.
  `_existing_object_count` explicitly queries `information_schema.columns` and `pg_constraint`.
- **0001 Early Return & Decision:** Current 0001 creates exactly 3 objects. The explicit shape query successfully matches exact canonical state. **Decision: RESTORE_ORIGINAL**, preserving exact predicate.
- **Compatibility A/B/C:** (N/A, restoring original explicit safe predicate).
- **Test Harness:** `backend/tests/unit/test_post_baseline_migration_compatibility.py`. Concrete fixture: Existing `test_post_baseline_upgrade_fails_if_compatibility_objects_missing` (mutates count and asserts `RuntimeError`).

### 0027_change_request_attachments.py
- **Pre-d231 Control-Flow Predicate & Guard Location:**
  `backend/alembic/versions/0027_change_request_attachments.py`
  ```python
      existing_objects = _existing_object_count()
      if existing_objects:
          if existing_objects != EXPECTED_OBJECT_COUNT:
              raise RuntimeError("The change-request attachment schema is only partially present.")
          _install_security_contract()
          return
  ```
- **0001 Line/Object Definitions:**
  Table: `governance.change_request_attachments`.
  Index: `governance.ix_change_request_attachments_request`.
  Policy: `workspace_isolation` on `change_request_attachments`.
  `_existing_object_count` explicitly queries `pg_class` and `pg_policies` to verify exactly 3 objects.
- **0001 Early Return & Decision:** Current 0001 creates exactly 3 objects. The explicit shape query matches canonical state. **Decision: RESTORE_ORIGINAL**, preserving exact predicate.
- **Compatibility A/B/C:** (N/A, restoring original explicit safe predicate).
- **Test Harness:** `backend/tests/unit/test_post_baseline_migration_compatibility.py`. Concrete fixture: Existing `test_post_baseline_upgrade_fails_if_compatibility_objects_missing` (mutates count and asserts `RuntimeError`).

### 0031_workspace_access_roles.py
- **Pre-d231 Control-Flow Predicate & Guard Location:**
  `backend/alembic/versions/0031_workspace_access_roles.py`
  ```python
      table_exists = op.get_bind().execute(
          sa.text("SELECT (to_regclass('iam.access_roles') IS NOT NULL)::int")
      ).scalar_one()
      if table_exists:
          return
  ```
- **0001 Line/Object Definitions:**
  Table: `iam.access_roles`. Columns: `workspace_id`, `role_key`, `name`, `description`, `clearance`, `groups`.
  Constraints: `ck_access_roles_role_key_shape`, `ck_access_roles_clearance_range`, `fk_access_roles_updater`.
  Index: `ix_access_roles_workspace_active_name`.
  RLS: ENABLED + FORCED, Policy: `workspace_isolation`.
- **0001 Early Return & Decision:** The pre-d231 guard ONLY checks if the table `iam.access_roles` exists, not its columns, constraints, or RLS. It does not prove canonical shape. **Decision: EXPLICIT_EXACT_STATE_COMPATIBILITY**.
- **Compatibility A/B/C:**
  - Predicate A: If exact security shape (table `iam.access_roles`, exact columns, `ck_...` constraints, `ix_...` index, RLS ENABLE/FORCE, `workspace_isolation` policy) completely matches: return cleanly.
  - Predicate B: If exactly 0 objects present: execute full migration.
  - Predicate C: If partially present/malformed (e.g., table exists but columns or RLS missing): raise RuntimeError.
- **Test Harness:** `backend/tests/unit/test_post_baseline_migration_compatibility.py`. Concrete fixture: [NEW FIXTURE REQUIRED]. Implement exact shape helper, mutate to simulate partial state, and assert `pytest.raises(RuntimeError)`.

### 0032_membership_renewal_workflow.py
- **Pre-d231 Control-Flow Predicate & Guard Location:**
  `backend/alembic/versions/0032_membership_renewal_workflow.py`
  ```python
      existing_objects = _existing_object_count()
      if existing_objects:
          if existing_objects != EXPECTED_OBJECT_COUNT:
              raise RuntimeError("The membership renewal schema is only partially present.")
          _install_security_contract()
          return
  ```
- **0001 Line/Object Definitions:**
  Table: `iam.membership_renewal_requests` (12+ columns).
  Column added: `workspace_memberships.access_expires_at`.
  Indexes: `ix_membership_renewals_workspace_state_created`, `uq_membership_renewals_pending_subject`.
  RLS: ENABLED + FORCED, Policy: `workspace_isolation`.
  `_existing_object_count` checks the added column, indexes, and policy, but for `membership_renewal_requests` it ONLY checks `to_regclass(...) IS NOT NULL`, failing to validate inner columns.
- **0001 Early Return & Decision:** Because the helper verifies table existence but not canonical column shapes, it does not prove canonical completeness. **Decision: EXPLICIT_EXACT_STATE_COMPATIBILITY**.
- **Compatibility A/B/C:**
  - Predicate A: If exact security shape (including inner columns of `membership_renewal_requests`, RLS, etc.) matches: return cleanly.
  - Predicate B: If exactly 0 objects present: execute full migration.
  - Predicate C: If partially present/malformed: raise RuntimeError.
- **Test Harness:** `backend/tests/unit/test_post_baseline_migration_compatibility.py`. Concrete fixture: [NEW FIXTURE REQUIRED]. Implement exact shape helper, mutate to simulate partial state, and assert `pytest.raises(RuntimeError)`.

### 0033_change_workflow_role_evidence.py
- **Pre-d231 Control-Flow Predicate & Guard Location:**
  `backend/alembic/versions/0033_change_workflow_role_evidence.py`
  ```python
      existing_objects = _existing_object_count()
      if existing_objects:
          if existing_objects != EXPECTED_OBJECT_COUNT:
              raise RuntimeError("The CR role-authority schema is only partially present.")
          return
  ```
- **0001 Line/Object Definitions:**
  Columns added: `change_request_items.routing_system_id`, `approvals.authority_snapshot`.
  Constraints added: `fk_change_items_routing_system`, `ck_approvals_authority_array`.
  `_existing_object_count` executes a SQL query against `information_schema.columns` and `pg_constraint` explicitly verifying these exact 4 objects.
- **0001 Early Return & Decision:** Current 0001 creates exactly EXPECTED_OBJECT_COUNT (4) objects. The explicit shape query successfully validates canonical shape and safely returns. **Decision: RESTORE_ORIGINAL**, preserving exact predicate.
- **Compatibility A/B/C:** (N/A, restoring original explicit safe predicate).
- **Test Harness:** `backend/tests/unit/test_post_baseline_migration_compatibility.py`. Concrete fixture: Existing `test_post_baseline_upgrade_fails_if_compatibility_objects_missing` (mutates count and asserts `RuntimeError`).

### 0034_system_configuration_activation.py
- **Pre-d231 Control-Flow Predicate & Guard Location:**
  `backend/alembic/versions/0034_system_configuration_activation.py`
  ```python
      existing_objects = _existing_object_count()
      if existing_objects:
          if existing_objects != EXPECTED_OBJECT_COUNT:
              raise RuntimeError("The System Settings activation schema is only partially present.")
          _install_security_contract()
          return
  ```
- **0001 Line/Object Definitions:**
  Column: `external_service_profiles.activated_version`.
  Constraint: `ck_external_service_profiles_activated_version_range`.
  Table: `platform.external_service_profile_versions` (with multiple columns).
  `_existing_object_count` checks table existence for `external_service_profile_versions` using `to_regclass` but omits checking its columns.
- **0001 Early Return & Decision:** Fails to validate canonical column shape of the new table. **Decision: EXPLICIT_EXACT_STATE_COMPATIBILITY**.
- **Compatibility A/B/C:**
  - Predicate A: If exact shape (including columns of `external_service_profile_versions`) matches: return cleanly.
  - Predicate B: If exactly 0 objects present: execute full migration.
  - Predicate C: If partially present/malformed: raise RuntimeError.
- **Test Harness:** `backend/tests/unit/test_post_baseline_migration_compatibility.py`. Concrete fixture: [NEW FIXTURE REQUIRED]. Implement exact shape helper, mutate to simulate partial state, and assert `pytest.raises(RuntimeError)`.

### 0035_change_request_rounds_and_test_evidence.py
- **Pre-d231 Control-Flow Predicate & Guard Location:**
  `backend/alembic/versions/0035_change_request_rounds_and_test_evidence.py`
  ```python
      existing_objects = _existing_object_count()
      if existing_objects:
          if existing_objects != EXPECTED_OBJECT_COUNT:
              raise RuntimeError("The CR revision/test-evidence schema is only partially present.")
          _install_security_contract()
          return
  ```
- **0001 Line/Object Definitions:**
  Tables: `governance.change_request_rounds`, `governance.change_test_runs`.
  `_existing_object_count` checks their existence with `to_regclass` but does not validate inner columns (like `workspace_id`, `round_number`, `test_payload`, etc.).
- **0001 Early Return & Decision:** Fails to validate canonical column shapes of the new tables. **Decision: EXPLICIT_EXACT_STATE_COMPATIBILITY**.
- **Compatibility A/B/C:**
  - Predicate A: If exact shape (including columns of the 2 new tables) matches: return cleanly.
  - Predicate B: If exactly 0 objects present: execute full migration.
  - Predicate C: If partially present/malformed: raise RuntimeError.
- **Test Harness:** `backend/tests/unit/test_post_baseline_migration_compatibility.py`. Concrete fixture: [NEW FIXTURE REQUIRED]. Implement exact shape helper, mutate to simulate partial state, and assert `pytest.raises(RuntimeError)`.

### 0036_typed_xlsx_bulk_registration.py
- **Pre-d231 Control-Flow Predicate & Guard Location:**
  `backend/alembic/versions/0036_typed_xlsx_bulk_registration.py`
  ```python
      existing_objects = _existing_object_count()
      if existing_objects:
          if existing_objects != EXPECTED_OBJECT_COUNT:
              raise RuntimeError("The typed XLSX registration schema is only partially present.")
          _install_security_contract()
          return
  ```
- **0001 Line/Object Definitions:**
  Checks 3 constraints: `ck_object_manifests_content_profile_allowlist`, `ck_upload_preparation_jobs_typed_profile_allowlist`, `ck_upload_preparation_receipts_typed_profile_allowlist`.
  `_existing_object_count` explicitly queries `pg_get_constraintdef(oid) LIKE '%DATASET_DESCRIPTION_XLSX_V1%'` for exactly those 3 constraints.
- **0001 Early Return & Decision:** The explicit constraint definition query successfully validates canonical shape. **Decision: RESTORE_ORIGINAL**, preserving exact predicate.
- **Compatibility A/B/C:** (N/A, restoring original explicit safe predicate).
- **Test Harness:** `backend/tests/unit/test_post_baseline_migration_compatibility.py`. Concrete fixture: Existing `test_post_baseline_upgrade_fails_if_compatibility_objects_missing`.

### 0037_knowledge_source_graphrag_projection.py
- **Pre-d231 Control-Flow Predicate & Guard Location:**
  `backend/alembic/versions/0037_knowledge_source_graphrag_projection.py`
  ```python
      existing_objects = _existing_object_count()
      if existing_objects:
          if existing_objects != EXPECTED_OBJECT_COUNT:
              raise RuntimeError("The Knowledge pipeline schema is only partially present.")
          _install_security_contract()
          return
  ```
- **0001 Line/Object Definitions:**
  Tables created: `source_snapshots`, `source_pages`, `source_page_embeddings`, `extraction_runs`, `graphrag_audits`.
  `_existing_object_count` counts these tables in `pg_class`, but does NOT validate their inner columns.
- **0001 Early Return & Decision:** Fails to validate canonical column shapes of the 5 new tables. **Decision: EXPLICIT_EXACT_STATE_COMPATIBILITY**.
- **Compatibility A/B/C:**
  - Predicate A: If exact shape (including columns of the 5 new tables) matches: return cleanly.
  - Predicate B: If exactly 0 objects present: execute full migration.
  - Predicate C: If partially present/malformed: raise RuntimeError.
- **Test Harness:** `backend/tests/unit/test_post_baseline_migration_compatibility.py`. Concrete fixture: [NEW FIXTURE REQUIRED]. Implement exact shape helper, mutate to simulate partial state, and assert `pytest.raises(RuntimeError)`.

### 0041_policy_book_rbac.py
- **Canonical evidence:** `0001_initial_schema.py` owns all three `_TABLES`; the existing upgrade branch creates only when none exist, reinstalls the idempotent security contract, then validates columns, CHECK/FK/index and exact RLS metadata.
- **Decision: RESTORE_ORIGINAL.** No serialization incompatibility was demonstrated. The repository already has a canonical-positive fixture plus mutated CHECK/FK/index/column/RLS negative fixtures in `test_access_role_persistence.py::test_0041_schema_fingerprint_accepts_metadata_and_rejects_all_table_partial_state`.
- **A/B/C:** all tables plus exact metadata passes; no tables creates normally; a subset of tables or any malformed security fingerprint raises the original typed `RuntimeError`.
- **Observed blocker proof:** current bypass makes that existing negative fixture fail because it prints and continues.

#### 0042_retention_execution_control_plane.py
- **Canonical evidence:** regenerated `0001` owns the retention tables, policy columns and archive vocabulary. Pre-d231 already allowlisted four reviewed semantic catalog fingerprints for additive, regenerated, indexed and typed-Quality canonical states; it also reconciles only the exact legacy archive constraint.
- **Decision: RESTORE_ORIGINAL.** The proposed unnormalized-string redesign would narrow an already reviewed compatibility set without runtime evidence. Restore the service-principal, required-column, archive-contract, fingerprint and partial-schema raises individually.
- **A/B/C:** a fingerprint in `_EXPECTED_SCHEMA_FINGERPRINTS` with exact principal/archive contract passes; absence follows additive creation; mixed table/column presence or malformed principal/archive/fingerprint raises. Downgrade remains the intentional non-destructive no-op owned by 0001.
- **Focused evidence:** `test_retention_execution_persistence.py` pins all four reviewed hashes, archive definitions and non-destructive security contract; add bounded negative fixtures for each restored guard.

### 0043_system_configuration_probe_scope.py
- **Canonical evidence:** `0001` contains the later canonical vocabulary including `RERANKING_INFERENCE`; upgrade already returns for `_CURRENT_SCOPE_DEFINITION` or `_LATER_CANONICAL_SCOPES` and changes only the exact legacy definition.
- **Decision: RESTORE_ORIGINAL.** No compatibility rewrite is required: exact current/later state is already recognized, while missing/unknown constraints must fail closed. Downgrade must retain its evidence-count rejection.
- **A/B/C:** exact current/later is a no-op; exact legacy upgrades; missing/malformed fails. Downgrade proceeds only with zero current-only evidence and an exact current constraint.
- **Focused evidence:** extend `test_change_request_system_master_persistence.py` with exact current/later/legacy/malformed and evidence-bearing downgrade fixtures.

### 0044_admin_cursor_indexes.py
- **Canonical evidence:** `0001` creates all six named indexes with the same ordered terms. `_canonical_term` deliberately handles quoting, parentheses, whitespace and `::text`; structural checks separately pin btree, opclasses, uniqueness, predicates, constraints and sort options.
- **Decision: RESTORE_ORIGINAL.** Replacing the reviewed normalizer with hardcoded raw `pg_get_indexdef()` text would be less portable. Missing indexes are created; only an exact-but-invalid interrupted concurrent build may be dropped and rebuilt; malformed existing indexes must raise.
- **Focused evidence:** `test_admin_cursor_index_migration.py::test_admin_cursor_index_fingerprint_fails_closed` already has six malformed structural/definition fixtures. Current source fails all six solely because d231 prints and continues.

### 0045_bounded_catalog_projection.py
- **Canonical evidence:** `0001` already creates the bounded external URN CHECK, all four provenance booleans with `false` defaults, bounded JSON arrays and sync-run columns/checks. Existing `_canonical` explicitly accepts PostgreSQL's reviewed default spellings.
- **Decision: RESTORE_ORIGINAL.** An oversized external URN is data-integrity failure, not an absent-object migration case; malformed existing provenance columns/constraints likewise fail closed. Absent later columns/checks continue through the existing bounded creation/validation path.
- **A/B/C:** canonical complete state is idempotent; absent owned additions are created; oversized URN or malformed pre-existing column/constraint raises. Downgrade remains non-destructive because current 0001 owns the bounds.
- **Focused evidence:** `test_catalog_projection_migration.py` pins metadata parity, identity preservation and bounded normalization; add direct oversized/malformed negative fixtures.

### 0046_registration_execution_controls.py
- **Guard and pre-d231 control flow:** `_existing_object_count()` counts the six owned
  `manual_metadata_submissions` columns, two evidence tables, the
  `upload_preparation_jobs.next_attempt_at` column and the lease-shape CHECK. The only
  d231 change replaced the `existing_objects != EXPECTED_OBJECT_COUNT` raise with a print.
- **Canonical 0001 recognition:** `0001_initial_schema.py` owns all ten counted artifacts.
  At count 10, the migration does not trust the count alone: it runs
  `_assert_existing_contract()`, reinstalls the idempotent security and typed-BULK binding
  contracts, then runs `_assert_runtime_contract()`. Those assertions pin column types and
  nullability, CHECK/FK/index definitions, RLS enable+force/policies, immutable-evidence
  triggers, functions and effective grants.
- **Decision: RESTORE_ORIGINAL.** Exact canonical state follows the reviewed reassertion
  path. Zero artifacts follows the existing quiescence check and normal creation path.
  Any count from 1 through 9 is an interrupted/partial schema and must raise
  `RuntimeError("The registration execution control schema is only partially present.")`
  before any Alembic mutation.
- **Downgrade/evidence:** downgrade is intentionally a forward-only no-op, preserving
  registration execution evidence.
- **Focused evidence:**
  `test_post_baseline_migration_compatibility.py::{test_post_baseline_upgrade_uses_legacy_path_when_objects_are_absent,test_post_baseline_upgrade_accepts_complete_canonical_schema,test_post_baseline_upgrade_fails_closed_for_partial_schema,test_post_baseline_downgrade_is_compatibility_no_op}`;
  the exact security/runtime contract is additionally pinned by
  `test_manual_metadata_submission_persistence.py` and
  `test_typed_bulk_registration_persistence.py`.

### 0047_registration_worker_call_receipts.py
- **Guard and pre-d231 control flow:** `_existing_object_count()` counts the receipt table
  and its canonical state-shape CHECK. The pre-d231 branches are exactly `2` (assert,
  reinstall, assert, return), `0` (create), and every other value (typed fail-closed).
- **Canonical 0001 recognition:** `0001_initial_schema.py` creates both counted artifacts.
  The complete branch calls `_assert_existing_contract()` and `_assert_runtime_contract()`,
  which pin the persistent plain-table kind, all 15 columns, seven constraints including
  exact CHECK definitions and RESTRICT FK behavior, the partial RUNNING-lease index, forced
  RLS and exact policy count, trigger/function bodies, work-evidence coherence and
  least-privilege grants.
- **Decision: RESTORE_ORIGINAL.** Exact count 2 plus both assertions is the canonical safe
  re-entry. Count 0 performs the normal create path. Count 1 is partial and must raise the
  original `RuntimeError` before `op.create_table`; allowing it to continue attempts to
  create over an existing table and obscures the durable-state defect.
- **Downgrade/evidence:** downgrade remains the intentional forward-only no-op because the
  receipts are compliance evidence.
- **Focused evidence:** the 0/2/1 A/B/C branches and no-op downgrade already run through
  `test_post_baseline_migration_compatibility.py`; exact schema, runtime and effective-grant
  assertions are pinned by
  `test_registration_worker_receipt_migration_contract.py::test_receipt_reentry_assertions_cover_complete_schema_runtime_and_effective_grants`.

### 0048_governance_apply_lease_fencing.py
- **Guard and pre-d231 control flow:** `_column_count()` counts exactly
  `attempt_cycle`, `cycle_attempts`, `lease_token_hash` and `lease_owner_id` on
  `integration.jobs`. Pre-d231 adds them only at count 0 and raises at counts 1–3 before
  running any reconciliation.
- **Canonical 0001 recognition:** `0001_initial_schema.py` owns all four columns plus their
  defaults/nullability, the token/counter/lease CHECKs and
  `fk_jobs_workspace_lease_owner`. Count 4 continues through
  `_assert_columns_and_constraints()`, trigger and grant reinstallers, and
  `_assert_runtime_contract()`; the count is therefore only the branch selector, not the
  final fingerprint.
- **Decision: RESTORE_ORIGINAL.** Exact four-column state is revalidated and its mutable
  security contract reasserted. Zero columns invokes the existing active-work quiescence
  check and normal additive migration. A 1–3 column state is an interrupted security
  migration and must raise
  `RuntimeError("0048 governance apply lease columns are partially present; refusing migration")`.
- **Downgrade/evidence:** the worker claim fence and narrowed mutation boundary are
  forward-only; downgrade stays a non-destructive no-op.
- **Focused evidence:**
  `test_phase3_security_migration_compatibility.py::{test_0048_upgrade_installs_or_reasserts_all_security_contracts,test_0048_upgrade_fails_closed_for_partial_schema,test_0048_worker_fence_is_role_scoped_revocation_safe_and_update_only_for_cr}`.

### 0049_change_request_attachment_object_identity.py
- **Guard and pre-d231 control flow:** `_constraint_count()` is narrowly scoped to the
  unique constraint named `uq_change_request_attachment_object` on
  `governance.change_request_attachments`. Count 0 runs a duplicate `(bucket, object_key)`
  preflight before creating the constraint; count 1 only validates its exact definition;
  any other count is an ambiguous catalog state.
- **Canonical 0001 recognition:** `0001_initial_schema.py` creates the same named unique
  constraint on exactly `(bucket, object_key)`. `_assert_constraint()` requires PostgreSQL's
  normalized `UNIQUE (bucket, object_key)` definition, so a same-name malformed object does
  not pass merely because it was counted.
- **Decision: RESTORE_ORIGINAL.** Exact count 1 plus exact definition is the safe no-op;
  absence performs the duplicate-data preflight and normal addition; an impossible or
  corrupted duplicate-name count must retain the original typed rejection. No new
  compatibility branch is justified.
- **Downgrade/evidence:** stored object evidence depends on the global collision boundary;
  downgrade remains a non-destructive no-op.
- **Focused evidence:**
  `test_phase3_security_migration_compatibility.py::{test_0049_upgrade_installs_or_reasserts_attachment_identity,test_0049_upgrade_fails_closed_for_impossible_duplicate_constraint_name,test_0049_preflight_and_model_bind_global_object_identity}`.

### 0051_typed_catalog_metadata_evidence.py
- **Guards and pre-d231 control flow:** `_artifact_count()` counts the six owned tables plus
  `change_request_items.item_contract_hash` (`_EXPECTED_ARTIFACT_COUNT == 7`). d231 changed
  the partial-state raise in both upgrade and downgrade; it did not alter the separate
  durable-evidence downgrade rejection.
- **Canonical 0001 recognition:** `0001_initial_schema.py` owns all seven artifacts. On
  complete re-entry the migration replaces only the reviewed profile allowlists, reinstalls
  RLS/immutability/grants, then `_assert_contract()` checks forced RLS, policies, constraint
  vocabulary and hashes, triggers, FKs/indexes and upload/application least privilege.
- **Decision: RESTORE_ORIGINAL for both guards.** Count 7 is the exact canonical
  reassertion path; count 0 executes the existing schema creation path; counts 1–6 are
  partial and must raise before any allowlist or schema mutation. On downgrade, count 0 is
  already absent, count 7 may proceed only when `_new_evidence_count() == 0`, and counts
  1–6 must fail before destructive drops.
- **Downgrade/evidence:** retain the unchanged
  `RuntimeError("Revision 0051 cannot be downgraded while typed catalog metadata evidence exists.")`;
  it prevents deletion of durable row/candidate/binding evidence even for an otherwise
  exact schema.
- **Focused evidence:**
  `test_typed_catalog_metadata_persistence.py::{test_0051_upgrade_creates_or_reasserts_complete_contract,test_0051_upgrade_and_downgrade_fail_closed_on_partial_or_durable_evidence,test_0051_migration_is_forced_rls_append_only_and_least_privilege}`.

### 0053_reranking_probe_scope.py
- **Guards and pre-d231 control flow:** the upgrade reads the normalized definition of
  `ck_external_service_profile_versions_test_scope_vocabulary`. Exact `_CURRENT_SCOPES`
  returns; otherwise `_replace()` accepts only exact `_LEGACY_SCOPES`. The downgrade first
  rejects rows carrying `RERANKING_INFERENCE`, then `_replace()` accepts only the exact
  current definition.
- **Canonical 0001 recognition:** `0001_initial_schema.py` owns the exact current CHECK,
  including `RERANKING_INFERENCE`, so the squashed baseline takes the no-op branch. An
  ordinary pre-0053 database owns the exact legacy CHECK and follows the bounded
  replacement path. A missing constraint is not an "absent schema" case: this revision
  transitions a required existing security/evidence vocabulary and must fail closed.
- **Decision: RESTORE_ORIGINAL for both guards.** Exact current is A (no-op); exact legacy
  is B (normal migration); `None`, any unknown definition or a failed read-back is C and
  raises `RuntimeError("The connector probe scope constraint is missing or malformed.")`.
  This is the same reviewed transition family as 0043 but with the 0053 scope sets.
- **Downgrade/evidence:** any `RERANKING_INFERENCE` row must raise the original evidence
  protection error before replacement. With zero such rows, only an exact current CHECK may
  transition to legacy, and `_replace()` verifies the installed definition.
- **Focused evidence:** existing static contract coverage is
  `test_change_request_system_master_persistence.py::test_reranking_probe_scope_migration_matches_runtime_evidence`.
  Add bounded flow fixture
  `test_0053_accepts_current_replaces_legacy_and_rejects_malformed_or_evidence_bearing_downgrade`
  in that same real test module; it should stub `_constraint_definition` and Alembic
  operations to cover exact current, exact legacy, `None`/unknown, post-replacement drift,
  zero-evidence downgrade and evidence-bearing downgrade.

### 0054_add_durable_knowledge_source_jobs.py
- **Nine d231-modified guards and pre-d231 control flow:**
  `_canonical_phase5_contract_exists()` has one explicit absent bridge (`no owned tables`
  and no provenance columns), and otherwise validates the complete durable-Knowledge
  contract. d231 specifically suppressed the partial bridge, partial table set, incomplete
  provenance bridge, claim-policy set, write-fence set, shared-evidence-fence set and
  function-set rejections. It also suppressed `_assert_phase5_privileges()` and the durable
  job downgrade rejection. Other validator checks establish the broader canonical
  fingerprint but are not counted as d231 modifications here.
- **Canonical 0001 recognition:** the initial-schema generator imports the reviewed 0054
  SQL blocks (`_CLAIM_SCOPE_SQL`, `_EVIDENCE_INDEX_SQL`, `_WORKSPACE_DISCOVERY_SQL`,
  `_TRIGGER_SQL`, `_GRANTS_SQL`). Consequently canonical 0001 has the exact three tables,
  provenance bridge, constraint/index sets, RLS/policies, shared evidence fences,
  SECURITY DEFINER functions and unprivileged `datariver_knowledge` role shape expected by
  `_canonical_phase5_contract_exists()`.
- **Decision: RESTORE_ORIGINAL for all nine d231 guards.** A complete fingerprint returns true,
  after which upgrade reapplies the reviewed idempotent index/claim/function/trigger/grant
  boundary and `_assert_phase5_privileges()`. The exact empty bridge returns false and runs
  the normal additive migration. Any bridge-only, subset-table, column, constraint, index,
  RLS/policy, trigger/function, role-membership or privilege deviation is malformed and
  must raise at its existing check; none is an expected squashed-baseline variant.
- **Downgrade/evidence:** any row in `knowledge.source_analysis_jobs` must retain the
  original rejection before table/bridge removal. This preserves jobs, attempts, events and
  their provenance/LKG relationships.
- **Focused evidence:** `test_knowledge_source_job_persistence.py` proves metadata/0001
  ownership, exact generator reuse, canonical re-entry and role fail-closed scope. Add
  `test_0054_exact_canonical_absent_partial_security_and_durable_downgrade_branches` there,
  using the migration's real inspector/connection interface to mutate one representative
  member of each family (bridge/table, constraint/index, RLS/policy, trigger/function,
  principal/grant) and to assert evidence-bearing downgrade rejection.

### 0055_atomic_sharing_invocation_results.py
- **Two d231-modified guards and pre-d231 control flow:** `_canonical_phase6b_contract_exists()` constructs a
  presence vector for every bridge column, the two new tables, two unique indexes, two V2
  function signatures and three evidence triggers. All false is the one valid absent state;
  all true selects canonical re-entry; a mixed vector is partial. The complete path then
  validates exact columns/defaults, constraint and index MD5s, FORCE RLS/policies,
  trigger definitions, SECURITY DEFINER function configuration/execution grants and
  effective least privilege. d231 changed only the mixed-presence rejection and
  `_assert_phase6b_privileges()` rejection; the remaining exact validators and the later
  downgrade guard are supporting contract evidence, not counted as d231 sites.
- **Canonical 0001 recognition:** the initial-schema generator loads the 0055 revision and
  installs the exact Phase 6B boundary, so the squashed baseline satisfies the all-present
  vector and the same fingerprints. No alternate 0001 spelling or schema shape is needed.
- **Decision: RESTORE_ORIGINAL for both d231 guards.** All-present canonical state re-applies
  the idempotent functions, trigger functions and grants, then asserts exactness. All-absent
  performs the additive migration. Mixed presence or any column, table, constraint, index,
  RLS/policy, trigger, function or privilege mismatch must raise its original
  `RuntimeError`; printing allows a malformed authorization/evidence boundary to proceed.
- **Downgrade/evidence:** the existing, non-d231 downgrade rejection when invocation
  evidence or subject-bound V2 grants exist remains required supporting evidence. Only the
  exact empty-evidence/empty-V2-grant state may execute the existing downgrade, preventing
  falsification of retained sharing results.
- **Focused evidence:** `test_sharing_atomic_persistence.py` pins model/0001 parity, exact
  generator reuse, V2 result atomicity and the two canonical assertions. Add
  `test_0055_exact_absent_complete_partial_security_and_evidence_downgrade_branches` there,
  mutating one representative presence, metadata, RLS, function and grant result and
  asserting the durable downgrade guard.

### 0056_chat_session_favorites.py
- **Guards and pre-d231 control flow:** upgrade adds `chat_sessions.is_favorite` only when
  `_column_state()` is absent, accepts evidence-display columns only at count 0 or 2, then
  reinstalls owner policies/grants and `_assert_contract()` verifies the favorite column,
  both display columns and the exact four-table RESTRICTIVE owner-policy map.
- **Canonical 0001 recognition:** 0001 owns `is_favorite` with non-null `false` default,
  both citation display columns and the exact owner RLS policies. Thus it performs no
  additive column mutation, but intentionally reasserts the mutable security boundary.
- **Decision: RESTORE_ORIGINAL for all five guards.** Exact canonical column and owner
  policy state passes. Truly absent favorite/display additions follow the normal additive
  branches. One display column, a malformed favorite column, a missing/unexpected policy
  table, or any wrong role/permissiveness/command/USING/WITH CHECK expression must raise at
  the original check. These are malformed or partial states, not squashed-baseline variants.
- **Downgrade/evidence:** the untouched favorite and display-data guards already reject
  destructive downgrade when user-owned state exists; owner RLS is never removed.
- **Focused evidence:**
  `test_chat_retention_persistence.py::test_chat_favorite_migration_preserves_retention_privilege_boundary`
  pins canonical ownership and policy vocabulary. Add
  `test_0056_accepts_exact_or_absent_and_rejects_partial_columns_or_owner_policy_drift`
  in that module, including both existing evidence-bearing downgrade guards.

### 0057_staged_inference_profile_bindings.py
- **Guard and pre-d231 control flow:** `_staged_schema_state()` returns the exact staged
  columns and constraints. `_is_canonical_schema()` recognizes both provider-specific
  columns, both FKs and the staged-binding CHECK; `_is_legacy_schema()` recognizes the exact
  single-provider predecessor. Every other combination is partial.
- **Canonical 0001 recognition:** regenerated 0001 owns the canonical staged columns, FKs
  and CHECK. That branch reinstalls the policy-activation trigger/function and runs
  `_assert_staged_schema_contract()` before returning. An ordinary pre-0057 database owns
  the exact legacy shape and follows the existing additive transition.
- **Decision: RESTORE_ORIGINAL.** Exact canonical is A; exact legacy is B; any mixed column,
  FK or CHECK set is C and must raise
  `RuntimeError("The staged inference profile binding schema is only partially present.")`
  before an `op.add_column` collision or weakened policy activation.
- **Downgrade/evidence:** the unchanged `_assert_staged_binding_columns_empty()` rejects any
  embedding/reranker binding before dropping staged columns, preserving immutable policy
  evidence.
- **Focused evidence:**
  `test_classification_access_persistence.py::test_staged_inference_binding_migration_is_forward_and_backward_complete`
  pins the state predicates, canonical re-entry and evidence guard. Add bounded flow fixture
  `test_0057_accepts_exact_canonical_migrates_exact_legacy_and_rejects_mixed_state` there.

### 0059_knowledge_studio_foundation.py
- **Exact control flow:** no foundation indicator returns false and performs the additive
  migration. Any indicator requires all five graph columns, three ontology columns and
  `studio_drafts`; the complete branch also requires both exact FK-column sets and FORCE
  RLS on `studio_drafts`.
- **Decision: RESTORE_ORIGINAL (2).** Regenerated 0001 owns that complete shape. A subset
  or missing FK/FORCE-RLS property is partial/security-malformed and must retain the two
  original raises. Complete re-entry runs the existing policy/grant installers; the
  evidence-bearing downgrade rejection remains unchanged.
- **Focused evidence:** `test_knowledge_studio_persistence.py` pins the model, 0001 and
  publication security boundary. Add `test_0059_exact_absent_complete_and_partial_security_branches`.

### 0060_knowledge_studio_abox_bindings.py
- **Exact control flow:** none of the four owned tables is absent; all four with RLS
  enabled+forced on all four is canonical; any table subset or lower RLS count is malformed.
- **Decision: RESTORE_ORIGINAL (2).** 0001 owns all four tables and FORCE RLS. The original
  guards already implement absent -> create, exact -> security re-entry, partial/security
  drift -> fail closed. The existing draft-data downgrade guard remains required.
- **Focused evidence:** `test_knowledge_studio_persistence.py` includes normalized A-Box
  model and RLS assertions; add `test_0060_exact_absent_complete_partial_and_rls_branches`.

### 0061_knowledge_studio_governed_publication.py
- **Exact control flow:** no publication table and no `submitted_preflight_check_id` is the
  absent state. Canonical requires all five tables plus that draft column and
  `graphs.active_studio_release_id`; every mixed state is partial.
- **Decision: RESTORE_ORIGINAL (1).** 0001 owns the exact complete set, so it takes the
  security-policy re-entry path. Absence performs normal creation. A subset must raise
  before table/column collisions. Publication-evidence downgrade protection is unchanged.
- **Focused evidence:** `test_knowledge_studio_persistence.py` pins maker-checker policies,
  immutable publication models and 0001 parity; add
  `test_0061_exact_absent_complete_and_partial_publication_branches`.

### 0062_knowledge_qa_domain_archive.py
- **Exact control flow:** neither archive column is absent; both columns plus
  `ck_graphs_archive_shape` is canonical; one column or a missing CHECK is partial/malformed.
- **Decision: RESTORE_ORIGINAL (2).** 0001 owns both columns and the named CHECK. Canonical
  re-entry only reseeds default domains; absence adds the archive contract; partial states
  must raise. Existing archive/domain downgrade semantics are unchanged.
- **Focused evidence:**
  `test_knowledge_studio_persistence.py::test_qa_domain_seed_and_graph_archive_are_deterministic_and_auditable`;
  add `test_0062_exact_absent_complete_partial_and_missing_check_branches`.

### 0063_ontology_builder_and_ingestion_jobs.py
- **Exact control flow:** no owned table and none of `block_id`, `definition`, `aliases` on
  `tbox_draft_elements` is absent. Canonical requires all three tables and all three columns;
  the later 0064 removal of the former supertype vector-policy column is intentionally not
  part of this predicate.
- **Decision: RESTORE_ORIGINAL (1).** 0001 matches that documented later-canonical shape.
  Any table/column mixture must raise; absence creates; complete re-enters security/grants.
- **Focused evidence:** `test_knowledge_studio_persistence.py` pins builder/ingestion models;
  `test_tbox_baseline_grant_compatibility.py` pins grant parity. Add
  `test_0063_exact_absent_complete_and_partial_builder_branches`.

### 0064_normalize_tbox_hierarchy.py
- **Exact control flow:** no normalized subtype table is absent. Canonical requires all three
  subtype tables and their exact stable/parent/owner/endpoint identity columns; a subset or
  missing required column is partial.
- **Decision: RESTORE_ORIGINAL (2).** 0001 owns that complete normalized hierarchy.
  Canonical re-entry reapplies RLS/grants, absence creates, and partial table/column state
  must raise. Existing evidence-aware downgrade remains separate.
- **Focused evidence:** `test_knowledge_studio_persistence.py` pins subtype tables, FORCE
  RLS and least-privilege grants; add `test_0064_exact_absent_complete_and_partial_hierarchy_branches`.

### 0065_tbox_unicode_hierarchy_relation.py
- **Exact control flow:** absence of `hierarchy_relation` runs the additive transition.
  Presence is canonical only when `ix_tbox_classes_parent` has ordered columns
  `(workspace_id,draft_id,parent_stable_class_id,stable_class_id)`.
- **Decision: RESTORE_ORIGINAL (1).** 0001 owns the column and exact four-term index. A
  missing or differently ordered named index is malformed and must raise, not return true.
- **Downgrade/evidence:** the existing named-relation row count blocks lossy downgrade.
- **Focused evidence:** add `test_0065_accepts_exact_index_migrates_absent_and_rejects_index_drift`
  to `test_knowledge_studio_persistence.py`, including named-relation downgrade evidence.

### 0066_knowledge_studio_session_domains.py
- **Exact control flow:** the absent state has none of vocabulary `created_by`/`version`,
  draft `endpoint_aliases` or proposal `source_reference_document`. Canonical requires all
  four indicators; any non-empty proper subset is partial.
- **Decision: RESTORE_ORIGINAL (1).** 0001 owns the all-present state. Exact absence runs
  the ordered backfill/constraint/FK/index migration; a mixture must raise before duplicate
  additions or incomplete managed-domain attribution.
- **Focused evidence:** `test_knowledge_studio_persistence.py` pins the columns, version
  CHECK and narrow update grant; add `test_0066_exact_absent_complete_and_partial_domain_branches`.

### 0067_quality_control_plane.py
- **Exact control flow:** no Quality table, generation column or retention `resource_type`
  is absent. Canonical requires the complete table set plus both bridge indicators, then a
  catalog fingerprint in the two explicitly reviewed hashes: historical Phase-1 or later
  canonical head.
- **Decision: RESTORE_ORIGINAL (2).** This is already explicit exact-state compatibility,
  including the one intentional later-0001 allowlist. Any subset or any other
  definition/security hash must raise. Empty state follows the normal migration.
- **Downgrade/evidence:** the existing immutable Quality evidence guard is unchanged and
  must precede destructive reversal.
- **Focused evidence:** `test_quality_persistence.py` pins schema hashes, security fences,
  0001 parity and downgrade refusal. Add
  `test_0067_accepts_only_reviewed_hashes_and_rejects_partial_or_unknown_fingerprint`.

### 0068_catalog_profile_projection.py
- **Exact control flow:** none of `_PROFILE_TABLE_NAMES` is absent. All profile tables plus
  exactly `_PROFILE_CATALOG_CONTRACT_HASH` is canonical. A subset or any other catalog
  definition/security fingerprint is malformed.
- **Decision: RESTORE_ORIGINAL (2).** 0001/generator parity is already pinned to that exact
  hash. Empty state migrates; full exact state re-enters; partial/unknown state raises.
- **Downgrade/evidence:** existing immutable Profile and governed-retention evidence guards
  remain required before any destructive reversal.
- **Focused evidence:**
  `test_catalog_profile_persistence.py::{test_0068_pins_profile_security_and_retention_v4,test_0068_downgrade_and_canonical_generator_are_ordered}`;
  add `test_0068_accepts_exact_hash_and_rejects_partial_or_unknown_fingerprint`.

### 0082_knowledge_source_media_type_vocabulary.py
- **d231 guard and exact state machine:** the changed guard rejects a PostgreSQL catalog row
  whose `conname` or `pg_get_constraintdef` is not a string. Valid rows then enter the
  existing classifier, which accepts exactly one current vocabulary CHECK or exactly one
  reviewed legacy PDF CHECK (including the historical double-prefix name); missing,
  multiple/mixed, unexpected-name or malformed-definition states already raise.
- **Decision: RESTORE_ORIGINAL (1).** Canonical 0001 owns the exact current vocabulary and
  is the idempotent no-op. Exact legacy is the normal replacement path. An invalid catalog
  row cannot be converted into a typed constraint object and must raise before classification.
- **Downgrade/evidence:** current-to-legacy downgrade retains the non-PDF row guard and only
  restores the canonical legacy name after exact classification.
- **Focused evidence:** `test_knowledge_source_media_contract.py` already covers supported
  current/legacy states, missing/malformed/mixed rejection, both legacy transitions,
  idempotent current and guarded downgrade. The separate current unconditional `return` at
  the start of `upgrade()` is not a d231 guard change and must be removed or independently
  justified by the correction lane; it contradicts those existing transition fixtures.

### 0084_governed_knowledge_studio_tbox_proposal_jobs.py
- **Exact snapshot contract:** `_revision_0084_function_sql()` requires the embedded 0084
  authorization function to match `_REVISION_0084_AUTHORIZATION_SHA256` and requires exactly
  one start/end boundary in the later shared SQL before substituting the pinned historical
  authorization body. This prevents a current function from being silently back-projected
  as 0084 history.
- **Decision: RESTORE_ORIGINAL (2).** There is no absent-schema compatibility branch: both
  source-snapshot predicates are deterministic build-time migration integrity checks.
  Canonical 0001 is generated by applying the revision-owned SQL in order and does not
  require relaxing either hash/boundary.
- **Downgrade/evidence:** 0084 is forward-only and its existing explicit reconciliation
  guards remain unchanged; source snapshot failure must occur before SQL execution.
- **Focused evidence:**
  `test_knowledge_studio_persistence.py::test_revision_0084_pins_pre_role_authorization_until_revision_0094`
  verifies the historical/current separation. Add bounded mutation assertions for the
  authorization SHA and duplicate/missing boundary.

### 0087_fix_knowledge_studio_proposal_job_idempotency.py
- **Exact snapshot contract:** `fixed_command_function_sql()` must find exactly one next
  function marker, isolate one request function, and match its SHA-256 to the revision-owned
  fixed source. The legacy downgrade source is reconstructed by exact single replacements
  and separately pinned by `_replace_exact` checks.
- **Decision: RESTORE_ORIGINAL (2).** Boundary or hash drift is migration-source corruption,
  never an expected database state or squashed-baseline compatibility case. Both guards
  must fail before upgrade/downgrade executes function SQL.
- **Focused evidence:**
  `test_knowledge_studio_persistence.py::test_proposal_idempotency_fix_is_function_only_reversible_and_canonical`
  pins current/legacy hashes, ordering and 0001. Add boundary/hash mutation assertions.

### 0088_restore_knowledge_studio_proposal_contracts.py
- **Exact snapshot contract:** `_pinned()` accepts exactly one function statement and the
  expected revision-specific SHA for both request and structural-safety functions on
  upgrade and their historical sources on downgrade.
- **Decision: RESTORE_ORIGINAL (2).** The generic helper's boundary and SHA guards apply to
  every invocation; source drift is malformed migration evidence, not a database
  compatibility state. Canonical 0001 generator consumes the same pinned current SQL.
- **Downgrade/evidence:** the existing downgrade SQL first rejects structurally safe
  Proposal evidence that cannot be represented by the legacy function contract.
- **Focused evidence:**
  `test_knowledge_studio_persistence.py::test_proposal_contract_restore_is_pinned_reversible_and_canonical`
  pins upgrade/downgrade hashes and 0001. Add one boundary and one hash mutation per helper.

### 0089_canonical_admin_role_binding.py
- **Exact security snapshots:** `_pinned_capability_actions_json()` requires catalog version,
  canonical hash, recomputed document hash, exactly 64 sorted unique actions. The provisioning
  helper requires one function and the V2/V1 revision SHA. The assembled security contract
  must contain exactly 23 reviewed statements.
- **Decision: RESTORE_ORIGINAL (4).** These are immutable RBAC/provisioning source checks,
  not schema-presence heuristics. Canonical 0001 uses the same capability and security SQL;
  no legitimate baseline path requires a mismatched capability catalog, function source or
  statement boundary to continue.
- **Downgrade/evidence:** the V1 downgrade provisioning body is independently pinned; the
  migration's data/security preconditions remain authoritative.
- **Focused evidence:** `test_access_role_persistence.py` pins the separated canonical-admin
  boundary and statement tuple; `test_identity_provisioning_persistence.py` pins V1/V2
  provisioning. `test_capability_catalog.py` pins the exact 64-action snapshot and hash.

### 0092_change_request_editable_revisions.py
- **Authorization snapshot guard:** the loaded 0091 finalize-attachment function must contain
  exactly eight copies of the current-item scope before 0092 replaces each with the current
  round-item membership scope. Any other count means the historical authorization boundary
  changed and generated SQL cannot be trusted.
- **Exact schema state:** LEGACY is exactly `(0 snapshot columns, no association table, one
  legacy ordinal constraint)`; CURRENT is exactly `(11 snapshot columns, association table,
  no legacy constraint)`. Every other tuple is partial. Canonical 0001 is CURRENT and the
  re-entry branch asserts constraints/FKs/RLS/grants and reinstalls the scoped function;
  exact LEGACY executes preflight/backfill/additive migration.
- **Decision: RESTORE_ORIGINAL (2).** Neither a changed authorization-source boundary nor a
  partial editable-revision tuple is a valid compatibility state. Both must fail before SQL
  generation or mutation.
- **Downgrade/evidence:** existing preconditions reject EDITED history and ambiguous legacy
  ordinal identity before removing association/snapshot state.
- **Focused evidence:**
  `test_post_baseline_migration_compatibility.py::{test_0092_editable_change_request_revision_migration_is_additive_and_fail_closed,test_0092_canonical_reentry_only_reasserts_current_contract}`
  and `test_phase3_security_migration_compatibility.py` pin the eight replacements and 0001.
  The separate current `has_table(...): return` shortcut is not a d231 guard change and must
  be removed or independently justified: it bypasses the required CURRENT fingerprint and
  security reassertion.

### 0093_fix_knowledge_studio_proposal_job_idempotency.py
- **Exact snapshot contract:** the pair splitter requires exactly two functions and one
  marker; `_pinned()` requires exactly one function and each of four current/legacy SHAs.
  Legacy reconstruction requires exactly one replay query and local-idempotency declaration,
  then rejects any residual `idempotency_key_hash` before checking the historical SHA.
- **Decision: RESTORE_ORIGINAL (5).** These source-boundary, current-source, legacy-boundary
  and legacy-completeness checks are the only proof that upgrade installs the four reviewed
  fixes and downgrade restores exactly 0092. No database or squashed-baseline condition can
  justify continuing after one fails.
- **Focused evidence:**
  `test_knowledge_studio_persistence.py::test_proposal_transition_idempotency_fix_is_pinned_and_reversible`
  verifies all eight functions and 0001 ordering; add mutation tests for split, SHA, replay,
  local declaration and residual identifier guards.

### 0094_align_knowledge_proposal_authorization_scope.py
- **Exact authorization snapshots:** the shared support SQL must contain exactly one
  authorization function start/end and exactly one managed-system scope fragment. The
  extracted current function is pinned by `_CURRENT_SHA256`; the exact single replacement
  back to legacy allowed-system scope is pinned by `_LEGACY_SHA256`.
- **Decision: RESTORE_ORIGINAL (4).** Function boundary, managed scope boundary and both
  source hashes protect the authorization transition from attribute-only legacy scope to
  canonical-admin/profile-role/system-assignee scope. Relaxing any one can widen or corrupt
  authorization; canonical 0001 is generated from the same current pinned function.
- **Focused evidence:**
  `test_knowledge_studio_persistence.py::{test_proposal_authorization_scope_is_pinned_reversible_and_canonical,test_revision_0084_pins_pre_role_authorization_until_revision_0094}`;
  add mutation assertions for boundary, scope occurrence and current/legacy SHA.

### 0095_fix_tbox_proposal_control_character_guard.py
- **Exact safety snapshots:** each SQL input must be one function and match its current or
  legacy SHA. Both current source functions must contain exactly one `[[:cntrl:]]` predicate
  before upgrade. Legacy reconstruction performs exactly one replacement per function and
  is independently SHA-pinned.
- **Decision: RESTORE_ORIGINAL (4).** Function/source and finalization/structural predicate
  guards prove that both safety boundaries move together. They are deterministic migration
  source checks, not schema compatibility checks. Canonical 0001 includes the same two
  current functions after the 0094 authorization function.
- **Focused evidence:**
  `test_knowledge_studio_persistence.py::test_proposal_control_guard_is_pinned_reversible_and_canonical`
  verifies current/legacy one-to-one replacement and generated ordering; add mutation
  assertions for both predicate occurrence checks and boundary/SHA helper.
