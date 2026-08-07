
FROM node:22.19.0-bookworm-slim@sha256:4a4884e8a44826194dff92ba316264f392056cbe243dcc9fd3551e71cea02b90 AS build

WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
COPY offline_npm/ /offline_npm/
RUN set -eux; \
    MODULES_TAR=$(find /offline_npm -maxdepth 1 -name 'datariver-npm-modules-linux-x86_64-*.tar.gz' 2>/dev/null | sort | tail -1); \
    if [ -n "$MODULES_TAR" ] && [ -f "$MODULES_TAR" ]; then \
        echo "Extracting offline node_modules..."; \
        tar -xzf "$MODULES_TAR" -C /app; \
    else \
        echo "No offline modules found, running online npm ci..."; \
        npm ci --ignore-scripts --no-audit --no-fund; \
    fi
COPY frontend/ ./
RUN npm run build

FROM nginx:1.30.3-alpine3.23@sha256:0d3b80406a13a767339fbe2f41406d6c7da727ab89cf8fae399e81f780f814d1

ENV NGINX_ENVSUBST_OUTPUT_DIR=/tmp/nginx/conf.d
COPY frontend/nginx-main.conf /etc/nginx/nginx.conf
COPY frontend/nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --chmod=0555 frontend/docker-entrypoint.sh /usr/local/bin/datariver-entrypoint
COPY --from=build /app/dist /usr/share/nginx/html
RUN chown -R nginx:nginx /usr/share/nginx/html /var/cache/nginx /var/run
USER nginx
EXPOSE 8080
ENTRYPOINT ["/usr/local/bin/datariver-entrypoint"]
CMD ["nginx", "-g", "daemon off;"]
