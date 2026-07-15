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

    def request_started(self) -> None:
        self._in_flight.inc()

    def request_finished(
        self, *, method: str, route: str, status: int, duration_seconds: float
    ) -> None:
        self._in_flight.dec()
        self._requests.labels(method=method, route=route, status=str(status)).inc()
        self._duration.labels(method=method, route=route).observe(duration_seconds)

    def render(self) -> bytes:
        from prometheus_client import generate_latest

        return generate_latest(self._registry)
