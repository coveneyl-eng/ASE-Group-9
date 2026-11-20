"""OpenTelemetry metrics + traces, exported for Prometheus to scrape."""
import logging

from opentelemetry import metrics, trace
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.view import ExplicitBucketHistogramAggregation, View
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from prometheus_client import start_http_server

from smartcity import config

_initialised = False


def setup(service_name: str):
    """Initialise logging, OTel metrics (Prometheus exporter) and tracing for one process."""
    global _initialised
    logging.basicConfig(level=logging.INFO, format=f"%(asctime)s {service_name} %(levelname)s %(message)s")
    for noisy in ("azure", "httpx", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    if not _initialised:
        resource = Resource.create({"service.name": service_name})
        latency_buckets = View(instrument_name="smartcity_sensor_to_alert_seconds",
                               aggregation=ExplicitBucketHistogramAggregation([0.1, 0.25, 0.5, 1, 1.5, 2, 3, 5, 10]))
        metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=[PrometheusMetricReader()],
                                                 views=[latency_buckets]))
        trace.set_tracer_provider(TracerProvider(resource=resource))
        if config.METRICS_PORT:
            start_http_server(config.METRICS_PORT)
        _initialised = True
    meter = metrics.get_meter(service_name)
    return {
        "log": logging.getLogger(service_name),
        "tracer": trace.get_tracer(service_name),
        "processed": meter.create_counter("smartcity_messages_processed", description="Messages handled"),
        "latency": meter.create_histogram(
            "smartcity_sensor_to_alert_seconds", unit="s", description="Sensor reading to alert latency"
        ),
    }
