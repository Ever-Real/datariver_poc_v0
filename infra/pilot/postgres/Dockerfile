FROM pgvector/pgvector:0.8.2-pg17-bookworm@sha256:feb68f4f15446397d8cac7f4fe48fe4586de83160d1fc48b46283312d1a33966

# The isolated target has no source checkout. Embed only the reviewed database
# initialization hooks; Alembic remains a separate one-shot backend container.
COPY --chmod=0555 infra/postgres/init/ /docker-entrypoint-initdb.d/
