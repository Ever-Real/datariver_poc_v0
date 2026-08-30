BEGIN;

ALTER TABLE poc_chat_messages
  ADD COLUMN discovery_json jsonb,
  ADD CONSTRAINT ck_poc_chat_message_discovery CHECK (
    discovery_json IS NULL OR (
      jsonb_typeof(discovery_json) = 'object'
      AND octet_length(discovery_json::text) <= 1048576
    )
  );

INSERT INTO poc_state (scope, value) VALUES (
  'product-owned-schema-contract-v5',
  '{"contract":"DATARIVER_POC_POSTGRES_OWNED_SCHEMA_V5","revision":5,"fingerprint":"94708241e9aae3f87a89388a9c86adac3214054c0a37be0f7595544e012eabc5"}'::jsonb
);

COMMIT;
