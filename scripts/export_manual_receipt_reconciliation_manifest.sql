\set ON_ERROR_STOP on
\set QUIET 1
\pset tuples_only on
\pset format unaligned

-- Required psql variables:
--   workspace_id, bucket, prefix, maximum_references (1..1000)
--
-- Example:
-- psql "$DATABASE_URL" \
--   -v workspace_id=91146047-ebce-4c49-894c-3d89ca3ac39f \
--   -v bucket=datariver-infoschema \
--   -v prefix=UPLOAD_METADATA_MANUAL_ \
--   -v maximum_references=1000 \
--   -f scripts/export_manual_receipt_reconciliation_manifest.sql \
--   -o /secure/manual-receipt-db-manifest.json

SELECT (
    :'maximum_references'::integer BETWEEN 1 AND 1000
    AND :'bucket'::text <> ''
    AND :'prefix'::text <> ''
) AS reconciliation_inputs_valid \gset
\if :reconciliation_inputs_valid
\else
    \echo 'maximum_references must be 1..1000 and bucket/prefix must be non-empty'
    SELECT 1 / 0 AS invalid_reconciliation_inputs;
\endif

BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout = '30s';

WITH settings AS (
    SELECT
        :'workspace_id'::uuid AS workspace_id,
        :'bucket'::text AS bucket,
        :'prefix'::text AS prefix,
        :'maximum_references'::integer AS maximum_references
), matching AS (
    SELECT
        submission.id AS submission_id,
        submission.asset_id,
        submission.serial_number,
        submission.object_key AS key,
        submission.csv_size_bytes AS size_bytes,
        submission.csv_sha256 AS sha256,
        submission.source_version,
        submission.provider_source_version
    FROM governance.manual_metadata_submissions AS submission
    WHERE submission.workspace_id = :'workspace_id'::uuid
      AND submission.bucket = :'bucket'::text
      AND left(object_key, length(:'prefix'::text)) = :'prefix'::text
), selected AS (
    SELECT matching.*
    FROM matching
    ORDER BY matching.key, matching.submission_id
    LIMIT (SELECT maximum_references + 1 FROM settings)
), bounded AS (
    SELECT selected.*
    FROM selected
    ORDER BY selected.key, selected.submission_id
    LIMIT (SELECT maximum_references FROM settings)
), stats AS (
    SELECT
        (SELECT count(*) FROM matching) AS total_reference_count,
        (SELECT count(*) FROM selected)
            > (SELECT maximum_references FROM settings) AS database_truncated
)
SELECT jsonb_pretty(
    jsonb_build_object(
        'schema_version', 1,
        'generated_at', transaction_timestamp(),
        'source_database', current_database(),
        'source_wal_lsn', pg_current_wal_lsn(),
        'workspace_id', (SELECT workspace_id FROM settings),
        'bucket', (SELECT bucket FROM settings),
        'prefix', (SELECT prefix FROM settings),
        'maximum_references', (SELECT maximum_references FROM settings),
        'total_reference_count', stats.total_reference_count,
        'database_truncated', stats.database_truncated,
        'references', COALESCE(
            (
                SELECT jsonb_agg(
                    jsonb_build_object(
                        'submission_id', bounded.submission_id,
                        'asset_id', bounded.asset_id,
                        'serial_number', bounded.serial_number,
                        'key', bounded.key,
                        'size_bytes', bounded.size_bytes,
                        'sha256', bounded.sha256,
                        'source_version', bounded.source_version,
                        'provider_source_version', bounded.provider_source_version
                    )
                    ORDER BY bounded.key, bounded.submission_id
                )
                FROM bounded
            ),
            '[]'::jsonb
        )
    )
)
FROM stats;

COMMIT;
