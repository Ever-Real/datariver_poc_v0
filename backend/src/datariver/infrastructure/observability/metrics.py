from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Gauge, Histogram


class HttpMetrics:
    content_type = CONTENT_TYPE_LATEST

    def __init__(self) -> None:
        self._registry = CollectorRegistry(auto_describe=True)
        self._requests = Counter(
            "datariver_http_requests_total",
            "Completed HTTP requests.",
            ("method", "route", "status"),
            registry=self._registry,
        )
        self._duration = Histogram(
            "datariver_http_request_duration_seconds",
            "HTTP request duration in seconds.",
            ("method", "route"),
            buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
            registry=self._registry,
        )
        self._in_flight = Gauge(
            "datariver_http_requests_in_flight",
            "HTTP requests currently being processed.",
            registry=self._registry,
        )
        self._catalog_cache_access = Counter(
            "datariver_catalog_cache_access_total",
            "Catalog cache access outcomes with a bounded cache/outcome vocabulary.",
            ("cache", "outcome"),
            registry=self._registry,
        )
        self._catalog_detail_sources = Counter(
            "datariver_catalog_detail_source_total",
            "Catalog detail responses by bounded source type.",
            ("source",),
            registry=self._registry,
        )
        self._datahub_requests = Counter(
            "datariver_datahub_requests_total",
            "Completed DataHub requests by fixed operation and outcome.",
            ("operation", "outcome"),
            registry=self._registry,
        )
        self._datahub_duration = Histogram(
            "datariver_datahub_request_duration_seconds",
            "DataHub request duration by fixed operation.",
            ("operation",),
            buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60),
            registry=self._registry,
        )
        self._datahub_in_flight = Gauge(
            "datariver_datahub_requests_in_flight",
            "DataHub requests in flight by fixed operation.",
            ("operation",),
            registry=self._registry,
        )
        self._datahub_queue_rejections = Counter(
            "datariver_datahub_queue_rejections_total",
            "DataHub requests rejected by the concurrency bulkhead.",
            ("operation",),
            registry=self._registry,
        )
        self._datahub_circuit_state = Gauge(
            "datariver_datahub_circuit_state",
            "DataHub circuit state: 0=closed, 1=open, 2=half-open.",
            registry=self._registry,
        )
        self._datahub_circuit_state.set(0)
        self._database_pool_connections = Gauge(
            "datariver_database_pool_connections",
            "Current API database pool connections by bounded state.",
            ("state",),
            registry=self._registry,
        )
        self._database_pool_limit = Gauge(
            "datariver_database_pool_limit",
            "Configured API database pool connection limits.",
            ("kind",),
            registry=self._registry,
        )

    def request_started(self) -> None:
        self._in_flight.inc()

    def request_finished(
        self, *, method: str, route: str, status: int, duration_seconds: float
    ) -> None:
        self._in_flight.dec()
        self._requests.labels(method=method, route=route, status=str(status)).inc()
        self._duration.labels(method=method, route=route).observe(duration_seconds)

    def catalog_cache_access(self, *, cache: str, outcome: str) -> None:
        self._catalog_cache_access.labels(cache=cache, outcome=outcome).inc()

    def catalog_detail_source(self, *, source: str) -> None:
        self._catalog_detail_sources.labels(source=source).inc()

    def datahub_request_started(self, *, operation: str) -> None:
        self._datahub_in_flight.labels(operation=operation).inc()

    def datahub_request_finished(
        self, *, operation: str, outcome: str, duration_seconds: float
    ) -> None:
        self._datahub_in_flight.labels(operation=operation).dec()
        self._datahub_requests.labels(operation=operation, outcome=outcome).inc()
        self._datahub_duration.labels(operation=operation).observe(duration_seconds)

    def datahub_queue_rejected(self, *, operation: str) -> None:
        self._datahub_queue_rejections.labels(operation=operation).inc()

    def datahub_circuit_changed(self, *, state: str) -> None:
        values = {"closed": 0, "open": 1, "half_open": 2}
        self._datahub_circuit_state.set(values[state])

    def database_pool_observed(
        self,
        *,
        configured_size: int,
        configured_max_overflow: int,
        checked_in: int,
        checked_out: int,
        overflow: int,
    ) -> None:
        self._database_pool_limit.labels(kind="base").set(configured_size)
        self._database_pool_limit.labels(kind="overflow").set(configured_max_overflow)
        self._database_pool_connections.labels(state="checked_in").set(checked_in)
        self._database_pool_connections.labels(state="checked_out").set(checked_out)
        self._database_pool_connections.labels(state="overflow").set(overflow)

    def render(self) -> bytes:
        from prometheus_client import generate_latest

        return generate_latest(self._registry)
