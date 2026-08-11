# syntax=docker/dockerfile:1
FROM node:22.19.0-alpine3.22 AS build

WORKDIR /source/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --ignore-scripts
COPY frontend/ ./
RUN npm run build:poc

FROM nginx:1.30.3-alpine

ARG POC_SOURCE_COMMIT=unrecorded
LABEL org.opencontainers.image.title="DataRiver 06111 Static POC" \
      org.opencontainers.image.description="No-auth synthetic-data presentation POC" \
      org.opencontainers.image.revision="${POC_SOURCE_COMMIT}" \
      io.datariver.release-type="STATIC_POC" \
      io.datariver.source-base="06111ae9d94bb423adbd62d31cc56fc43feafd66" \
      io.datariver.authentication="NONE" \
      io.datariver.canonical-data="NONE" \
      io.datariver.external-integrations="SIMULATED"

COPY deploy/poc/nginx.conf /etc/nginx/nginx.conf
COPY --from=build /source/frontend/dist-poc/ /usr/share/nginx/html/

RUN chown -R nginx:nginx /usr/share/nginx/html

USER nginx
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=6 \
  CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1

ENTRYPOINT []
CMD ["nginx", "-g", "daemon off;"]
