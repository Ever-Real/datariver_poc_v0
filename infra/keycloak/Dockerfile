FROM quay.io/keycloak/keycloak:26.7.0 AS builder

ENV KC_DB=postgres \
    KC_HEALTH_ENABLED=true \
    KC_METRICS_ENABLED=true

RUN /opt/keycloak/bin/kc.sh build

FROM quay.io/keycloak/keycloak:26.7.0

COPY --from=builder /opt/keycloak/ /opt/keycloak/
COPY --chown=1000:0 infra/keycloak/themes/datariver /opt/keycloak/themes/datariver

# Keep the upstream non-root runtime explicit for both reviewers and scanners.
USER 1000
