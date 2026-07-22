FROM quay.io/keycloak/keycloak:26.7.0@sha256:2eb3cd316835c990e69e26ade292ffa78f6fb0db7d5fc6377463c162e1979ac0 AS builder

ENV KC_DB=postgres \
    KC_HEALTH_ENABLED=true \
    KC_METRICS_ENABLED=true

RUN /opt/keycloak/bin/kc.sh build

FROM quay.io/keycloak/keycloak:26.7.0@sha256:2eb3cd316835c990e69e26ade292ffa78f6fb0db7d5fc6377463c162e1979ac0

COPY --from=builder /opt/keycloak/ /opt/keycloak/
COPY --chown=1000:0 infra/keycloak/themes/datariver /opt/keycloak/themes/datariver

# Keep the upstream non-root runtime explicit for both reviewers and scanners.
USER 1000
