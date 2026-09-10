ARG NODE_IMAGE=node:22.19.0-bookworm-slim
FROM ${NODE_IMAGE} AS build
WORKDIR /source
COPY package.json package-lock.json ./
COPY deploy/npm-build.sh /usr/local/bin/datariver-npm-build
# HTTP_PROXY/HTTPS_PROXY/NO_PROXY are Docker's predefined proxy build arguments.
# Deliberately do not redeclare them with ARG: Docker then excludes their values
# from image history and cache metadata. A private, step-local npmrc is removed in
# the same layer so proxy credentials and the bounded TLS relaxation cannot persist.
RUN sh /usr/local/bin/datariver-npm-build ci --ignore-scripts
COPY frontend/ ./frontend/
COPY backend/ ./backend/
RUN npm run build
RUN sh /usr/local/bin/datariver-npm-build prune --omit=dev

FROM ${NODE_IMAGE}
ARG POC_SOURCE_COMMIT=unrecorded
LABEL org.opencontainers.image.title="DataRiver" \
      org.opencontainers.image.description="Node API and React UI with local opaque-session authentication" \
      org.opencontainers.image.revision="${POC_SOURCE_COMMIT}" \
      io.datariver.source.sha256="${POC_SOURCE_COMMIT}" \
      io.datariver.authentication="LOCAL_OPAQUE_SESSION"
WORKDIR /app
COPY --from=build /source/frontend/dist/ ./frontend/dist/
COPY --from=build /source/node_modules/ ./node_modules/
COPY package.json ./package.json
COPY backend/ ./backend/
ENV POC_SERVER_HOST=0.0.0.0 POC_SERVER_PORT=8080
USER node
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=6 \
  CMD node -e "fetch('http://127.0.0.1:8080/healthz').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"
ENTRYPOINT []
CMD ["node", "backend/src/bootstrap.mjs"]
