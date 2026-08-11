from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from opentelemetry import metrics, trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from beanly.core.config.settings import Settings

_configured = False
_tracer_provider: TracerProvider | None = None
_meter_provider: MeterProvider | None = None


def configure_telemetry(
    settings: Settings,
    *,
    app: Any | None = None,
    engine: Any | None = None,
    service_name: str | None = None,
) -> None:
    global _configured, _meter_provider, _tracer_provider
    if _configured or not settings.otel_enabled:
        return
    from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.instrumentation.redis import RedisInstrumentor
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

    resource = Resource.create(
        {
            "service.name": service_name or settings.service_name,
            "service.version": settings.git_sha,
            "deployment.environment.name": settings.environment,
        }
    )
    endpoint = settings.otel_exporter_otlp_endpoint
    insecure = _otlp_is_insecure(endpoint)
    _tracer_provider = TracerProvider(resource=resource)
    _tracer_provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, insecure=insecure))
    )
    trace.set_tracer_provider(_tracer_provider)
    reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=endpoint, insecure=insecure)
    )
    _meter_provider = MeterProvider(resource=resource, metric_readers=[reader])
    metrics.set_meter_provider(_meter_provider)
    if app is not None:
        FastAPIInstrumentor.instrument_app(
            app,
            excluded_urls="/health/live,/health/ready",
        )
    if engine is not None:
        SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)
    HTTPXClientInstrumentor().instrument()
    RedisInstrumentor().instrument()
    _configured = True


def _otlp_is_insecure(endpoint: str | None) -> bool:
    return bool(endpoint and endpoint.startswith("http://"))


@contextmanager
def traced(name: str, **attributes: object) -> Iterator[None]:
    with trace.get_tracer("beanly").start_as_current_span(name) as span:
        for key, value in attributes.items():
            if value is not None:
                span.set_attribute(key, value)
        yield


def shutdown_telemetry() -> None:
    if _meter_provider is not None:
        _meter_provider.shutdown()
    if _tracer_provider is not None:
        _tracer_provider.shutdown()
