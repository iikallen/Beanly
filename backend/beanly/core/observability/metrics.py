from threading import Lock

from opentelemetry import metrics as otel_metrics
from opentelemetry.metrics import Observation


class BeanlyMetrics:
    def __init__(self) -> None:
        meter = otel_metrics.get_meter("beanly")
        self.http_requests = meter.create_counter("http.requests.total")
        self.http_5xx = meter.create_counter("http.5xx.total")
        self.http_429 = meter.create_counter("http.429.total")
        self.http_duration = meter.create_histogram("http.request.duration", unit="ms")
        self.db_errors = meter.create_counter("db.errors.total")
        self.db_pool_wait = meter.create_histogram("db.pool.wait", unit="ms")
        self.outbox_processed = meter.create_counter("outbox.events.processed.total")
        self.integration_duration = meter.create_histogram(
            "integration.job.duration", unit="ms"
        )
        self.integration_retries = meter.create_counter("integration.retries.total")
        self.integration_provider_errors = meter.create_counter(
            "integration.provider.errors.total"
        )
        self.payment_completed = meter.create_counter("payment.completed.total")
        self.payment_failed = meter.create_counter("payment.failed.total")
        self.inventory_sales = meter.create_counter("inventory.sale.post.total")
        self.negative_stock = meter.create_counter("inventory.negative_stock.total")
        self.pos_offline_sessions_started = meter.create_counter(
            "pos.offline.sessions.started.total"
        )
        self.pos_offline_sync = meter.create_counter("pos.offline.sync.total")
        self.pos_offline_orders_synced = meter.create_counter("pos.offline.orders.synced.total")
        self.pos_offline_payments_synced = meter.create_counter("pos.offline.payments.synced.total")
        self.pos_offline_conflicts = meter.create_counter("pos.offline.conflicts.total")
        self.pos_offline_sync_duration = meter.create_histogram(
            "pos.offline.sync.duration", unit="s"
        )
        self.pos_offline_payment_delay = meter.create_histogram(
            "pos.offline.payment.delay", unit="s"
        )
        self._lock = Lock()
        self._queue_values: dict[str, float] = {
            "outbox_pending": 0,
            "outbox_oldest_pending_seconds": 0,
            "outbox_dead_lettered": 0,
            "integration_jobs_pending": 0,
            "integration_dead_lettered": 0,
            "integration_oldest_pending_seconds": 0,
            "db_connections": 0,
            "db_pool_checked_out": 0,
        }
        for name in self._queue_values:
            meter.create_observable_gauge(
                name.replace("_", "."),
                callbacks=[self._gauge(name)],
            )

    def _gauge(self, name: str):
        def observe(_: object) -> list[Observation]:
            with self._lock:
                return [Observation(self._queue_values[name])]

        return observe

    def set_queue(self, **values: float | int) -> None:
        with self._lock:
            for name, value in values.items():
                if name in self._queue_values:
                    self._queue_values[name] = float(value)

    def record_http(self, method: str, route: str, status: int, duration_ms: int) -> None:
        attributes = {"http.request.method": method, "http.route": route}
        self.http_requests.add(1, attributes)
        self.http_duration.record(duration_ms, attributes)
        if status >= 500:
            self.http_5xx.add(1, attributes)
        if status == 429:
            self.http_429.add(1, attributes)

    def set_db_pool(self, *, connections: int, checked_out: int) -> None:
        self.set_queue(
            db_connections=connections,
            db_pool_checked_out=checked_out,
        )


metrics = BeanlyMetrics()
