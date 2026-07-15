# syntax=docker/dockerfile:1.7
FROM node:22.19.0-bookworm-slim AS build

WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund

COPY frontend/ ./
ARG VITE_API_BASE_URL=/api/v1
ARG VITE_OIDC_AUTHORITY
ARG VITE_OIDC_CLIENT_ID=datariver-web
ARG VITE_OIDC_REDIRECT_URI
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL \
    VITE_OIDC_AUTHORITY=$VITE_OIDC_AUTHORITY \
    VITE_OIDC_CLIENT_ID=$VITE_OIDC_CLIENT_ID \
    VITE_OIDC_REDIRECT_URI=$VITE_OIDC_REDIRECT_URI
RUN npm run build

FROM nginx:1.30.3-alpine3.23

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
