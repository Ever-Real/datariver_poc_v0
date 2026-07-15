FROM apache/apisix:3.17.0-debian

USER root

RUN cp -a /usr/local/apisix/conf /opt/apisix-conf-dist

COPY docker-entrypoint.sh /usr/local/bin/datariver-apisix-entrypoint
COPY healthcheck.sh /usr/local/bin/datariver-apisix-healthcheck

RUN chmod 0555 /usr/local/bin/datariver-apisix-entrypoint \
        /usr/local/bin/datariver-apisix-healthcheck \
    && chown -R apisix:apisix /opt/apisix-conf-dist

USER apisix

ENTRYPOINT ["/usr/local/bin/datariver-apisix-entrypoint"]
CMD ["docker-start"]
