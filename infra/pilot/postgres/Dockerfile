FROM postgres:17.10-bookworm@sha256:4f736ae292687621d4dbe0d499ffd024a36bd2ee7d8ca6f2ccd4c800f047b394

# The isolated target has no source checkout. Embed only the reviewed database
# initialization hooks; Alembic remains a separate one-shot backend container.
COPY --chmod=0555 infra/postgres/init/ /docker-entrypoint-initdb.d/
