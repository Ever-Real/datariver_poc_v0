\set ON_ERROR_STOP on
\pset tuples_only on
\pset format unaligned

BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;

WITH refs AS (
    -- INITIATED uploads are deliberately excluded: they are not accepted business objects.
    -- Older ACCEPTED rows may lack an actual SHA after a completed provider verification, so
    -- the immutable declared evidence is the compatibility fallback for accepted rows only.
    SELECT
        bucket,
        object_key AS key,
        COALESCE(actual_size_bytes, size_bytes) AS size_bytes,
        COALESCE(actual_sha256, sha256) AS sha256
    FROM integration.object_manifests
    WHERE state = 'ACCEPTED'

    UNION ALL

    SELECT bucket, object_key, size_bytes, content_sha256
    FROM governance.change_request_attachments

    UNION ALL

    SELECT bucket, object_key, csv_size_bytes, csv_sha256
    FROM governance.manual_metadata_submissions

    UNION ALL

    SELECT bucket, object_key, byte_size, content_sha256
    FROM knowledge.source_snapshots

    UNION ALL

    SELECT object_bucket, object_key, size_bytes, content_sha256
    FROM catalog.export_requests
    WHERE object_bucket IS NOT NULL
      AND object_key IS NOT NULL
      AND size_bytes IS NOT NULL
      AND content_sha256 IS NOT NULL
), identities AS (
    SELECT
        bucket,
        key,
        min(size_bytes) AS size_bytes,
        min(sha256) AS sha256,
        count(DISTINCT jsonb_build_array(size_bytes, sha256)) AS evidence_versions
    FROM refs
    GROUP BY bucket, key
), stats AS (
    SELECT
        (SELECT count(*) FROM refs) AS reference_count,
        count(*) AS object_count,
        count(*) FILTER (
            WHERE bucket IS NULL
               OR bucket = ''
               OR key IS NULL
               OR key = ''
               OR size_bytes IS NULL
               OR size_bytes < 0
               OR sha256 IS NULL
               OR sha256 !~ '^[0-9a-f]{64}$'
        ) AS malformed_count,
        count(*) FILTER (WHERE evidence_versions <> 1) AS conflict_count
    FROM identities
)
SELECT jsonb_pretty(
    jsonb_build_object(
        'schema_version', 1,
        'generated_at', transaction_timestamp(),
        'source_database', current_database(),
        'source_wal_lsn', pg_current_wal_lsn(),
        'reference_count', stats.reference_count,
        'object_count', stats.object_count,
        'malformed_count', stats.malformed_count,
        'conflict_count', stats.conflict_count,
        'objects', COALESCE(
            (
                SELECT jsonb_agg(
                    jsonb_build_object(
                        'bucket', bucket,
                        'key', key,
                        'size_bytes', size_bytes,
                        'sha256', sha256
                    )
                    ORDER BY bucket, key
                )
                FROM identities
            ),
            '[]'::jsonb
        )
    )
)
FROM stats;

COMMIT;
