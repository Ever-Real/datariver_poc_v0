WITH cutover AS (
  SELECT
    (SELECT count(*) FROM integration.outbox_events
      WHERE published_at IS NULL AND dead_lettered_at IS NULL) AS unpublished_outbox,
    (SELECT count(*) FROM integration.outbox_events
      WHERE dead_lettered_at IS NOT NULL) AS dead_lettered_outbox,
    (SELECT count(*) FROM integration.outbox_events
      WHERE lease_until > CURRENT_TIMESTAMP) AS active_outbox_leases,
    (SELECT count(*) FROM integration.jobs
      WHERE state NOT IN ('COMPLETED', 'FAILED')) AS incomplete_jobs,
    (SELECT count(*) FROM integration.jobs
      WHERE lease_until > CURRENT_TIMESTAMP) AS active_job_leases,
    (SELECT count(*) FROM integration.object_manifests
      WHERE state IN ('COMPLETION_QUEUED', 'COMPLETING')) AS incomplete_object_jobs,
    (SELECT count(*) FROM integration.object_manifests
      WHERE processing_lease_until > CURRENT_TIMESTAMP) AS active_object_leases,
    (SELECT count(*) FROM integration.upload_preparation_jobs
      WHERE state IN ('QUEUED', 'PREPARING')) AS incomplete_preparation_jobs,
    (SELECT count(*) FROM integration.upload_preparation_jobs
      WHERE lease_until > CURRENT_TIMESTAMP) AS active_preparation_leases,
    (SELECT count(*) FROM governance.change_requests
      WHERE state IN ('APPLY_QUEUED', 'APPLYING')) AS incomplete_governance_jobs,
    (SELECT count(*) FROM governance.manual_metadata_submissions
      WHERE state IN ('QUEUED', 'APPLYING')) AS incomplete_manual_metadata_jobs,
    (SELECT count(*) FROM governance.manual_metadata_submissions
      WHERE lease_expires_at > CURRENT_TIMESTAMP) AS active_manual_metadata_leases
)
SELECT jsonb_build_object(
  'captured_at', CURRENT_TIMESTAMP,
  'unpublished_outbox', unpublished_outbox,
  'dead_lettered_outbox', dead_lettered_outbox,
  'active_outbox_leases', active_outbox_leases,
  'incomplete_jobs', incomplete_jobs,
  'active_job_leases', active_job_leases,
  'incomplete_object_jobs', incomplete_object_jobs,
  'active_object_leases', active_object_leases,
  'incomplete_preparation_jobs', incomplete_preparation_jobs,
  'active_preparation_leases', active_preparation_leases,
  'incomplete_governance_jobs', incomplete_governance_jobs,
  'incomplete_manual_metadata_jobs', incomplete_manual_metadata_jobs,
  'active_manual_metadata_leases', active_manual_metadata_leases,
  'cutover_gate_passed',
    unpublished_outbox = 0
    AND dead_lettered_outbox = 0
    AND active_outbox_leases = 0
    AND incomplete_jobs = 0
    AND active_job_leases = 0
    AND incomplete_object_jobs = 0
    AND active_object_leases = 0
    AND incomplete_preparation_jobs = 0
    AND active_preparation_leases = 0
    AND incomplete_governance_jobs = 0
    AND incomplete_manual_metadata_jobs = 0
    AND active_manual_metadata_leases = 0
)::text
FROM cutover;
