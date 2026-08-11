ARG NODE_IMAGE=node:22.19.0-bookworm-slim
FROM ${NODE_IMAGE} AS build

WORKDIR /source/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --ignore-scripts
COPY frontend/ ./
RUN npm run build:poc

FROM ${NODE_IMAGE}

ARG POC_SOURCE_COMMIT=unrecorded
LABEL org.opencontainers.image.title="DataRiver 06111 Hybrid POC" \
      org.opencontainers.image.description="Original DataRiver Web UI with a no-auth server-side provider gateway" \
      org.opencontainers.image.revision="${POC_SOURCE_COMMIT}" \
      io.datariver.release-type="STATIC_POC" \
      io.datariver.source-base="06111ae9d94bb423adbd62d31cc56fc43feafd66" \
      io.datariver.authentication="NONE" \
      io.datariver.canonical-data="NONE" \
      io.datariver.external-integrations="OPTIONAL_LIVE_PROVIDERS"

WORKDIR /app
COPY --from=build /source/frontend/dist-poc/ ./dist-poc/
COPY frontend/poc-server.mjs ./poc-server.mjs

ENV POC_SERVER_HOST=0.0.0.0 \
    POC_SERVER_PORT=8080

USER node
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=6 \
  CMD node -e "fetch('http://127.0.0.1:8080/healthz').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

ENTRYPOINT []
CMD ["node", "poc-server.mjs"]
