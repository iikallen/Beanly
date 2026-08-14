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
        self.integration_duration = meter.create_histogram("integration.job.duration", unit="ms")
        self.integration_retries = meter.create_counter("integration.retries.total")
        self.integration_provider_errors = meter.create_counter("integration.provider.errors.total")
        self.payment_completed = meter.create_counter("payment.completed.total")
        self.payment_failed = meter.create_counter("payment.failed.total")
        self.inventory_sales = meter.create_counter("inventory.sale.post.total")
        self.refund_completed = meter.create_counter("refund.completed.total")
        self.refund_failed = meter.create_counter("refund.failed.total")
        self.refund_amount = meter.create_counter("refund.amount.minor.total")
        self.fiscal_refund_jobs = meter.create_counter("fiscal.refund.jobs.total")
        self.fiscal_receipts = meter.create_counter("fiscal.receipts.total")
        self.fiscal_receipt_success = meter.create_counter("fiscal.receipt.success.total")
        self.fiscal_receipt_failed = meter.create_counter("fiscal.receipt.failed.total")
        self.fiscal_receipt_unknown = meter.create_counter("fiscal.receipt.unknown.total")
        self.fiscal_receipt_duration = meter.create_histogram("fiscal.receipt.duration", unit="s")
        self.nkt_requests = meter.create_counter("nkt.requests.total")
        self.nkt_cache_hits = meter.create_counter("nkt.cache.hits.total")
        self.nkt_rate_limit = meter.create_counter("nkt.rate_limit.total")
        self.onboarding_started = meter.create_counter("onboarding.started.total")
        self.onboarding_completed = meter.create_counter("onboarding.completed.total")
        self.onboarding_time_to_pos_ready = meter.create_histogram(
            "onboarding.time_to_pos_ready", unit="s"
        )
        self.onboarding_time_to_first_sale = meter.create_histogram(
            "onboarding.time_to_first_sale", unit="s"
        )
        self.menu_import_started = meter.create_counter("menu_import.started.total")
        self.menu_import_applied = meter.create_counter("menu_import.applied.total")
        self.menu_import_failed = meter.create_counter("menu_import.failed.total")
        self.menu_import_entities = meter.create_counter("menu_import.entities.total")
        self.menu_import_errors = meter.create_counter("menu_import.errors.total")
        self.ai_menu_extraction = meter.create_counter("ai_menu_extraction.total")
        self.ai_menu_extraction_review_rate = meter.create_histogram(
            "ai_menu_extraction.review_rate"
        )
        self.promotions_active = meter.create_up_down_counter("promotions_active")
        self.promotion_evaluations_total = meter.create_counter("promotion_evaluations_total")
        self.promotion_matches_total = meter.create_counter("promotion_matches_total")
        self.discount_applications_total = meter.create_counter("discount_applications_total")
        self.discount_amount_total = meter.create_counter("discount_amount_total")
        self.promo_code_attempts_total = meter.create_counter("promo_code_attempts_total")
        self.promo_code_rejected_total = meter.create_counter("promo_code_rejected_total")
        self.custom_discount_total = meter.create_counter("custom_discount_total")
        self.pricing_duration_seconds = meter.create_histogram("pricing_duration_seconds", unit="s")
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
        self.cash_drawer_sessions = meter.create_counter("cash.drawer_sessions.total")
        self.cash_drawer_variance_minor = meter.create_histogram(
            "cash.drawer_variance_minor"
        )
        self.cash_drawer_variance_rate = meter.create_histogram(
            "cash.drawer_variance_rate"
        )
        self.cash_sales_minor = meter.create_counter("cash.sales_minor.total")
        self.cash_refunds_minor = meter.create_counter("cash.refunds_minor.total")
        self.cash_pay_in_minor = meter.create_counter("cash.pay_in_minor.total")
        self.cash_pay_out_minor = meter.create_counter("cash.pay_out_minor.total")
        self.kitchen_tickets = meter.create_counter("kitchen.tickets.total")
        self.kitchen_tickets_ready = meter.create_counter("kitchen.tickets.ready.total")
        self.kitchen_tickets_completed = meter.create_counter(
            "kitchen.tickets.completed.total"
        )
        self.kitchen_queue_seconds = meter.create_histogram("kitchen.queue_seconds", unit="s")
        self.kitchen_prep_seconds = meter.create_histogram("kitchen.prep_seconds", unit="s")
        self.kitchen_ready_to_pickup_seconds = meter.create_histogram(
            "kitchen.ready_to_pickup_seconds", unit="s"
        )
        self.kitchen_late_tickets = meter.create_counter("kitchen.late_tickets.total")
        self._lock = Lock()
        self._queue_values: dict[str, float] = {
            "outbox_pending": 0,
            "outbox_oldest_pending_seconds": 0,
            "outbox_dead_lettered": 0,
            "integration_jobs_pending": 0,
            "integration_dead_lettered": 0,
            "integration_oldest_pending_seconds": 0,
            "fiscal_pending_count": 0,
            "fiscal_oldest_pending_seconds": 0,
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
