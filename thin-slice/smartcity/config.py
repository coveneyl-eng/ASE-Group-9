"""Single home for every setting (DRY): values come from environment variables only."""
import os


def env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None:
        raise RuntimeError(f"Missing required environment variable {name}")
    return value


# Kafka event bus
KAFKA_BOOTSTRAP = env("KAFKA_BOOTSTRAP", "localhost:9092")
KAFKA_SECURITY_PROTOCOL = env("KAFKA_SECURITY_PROTOCOL", "PLAINTEXT")  # SASL_SSL in compose
KAFKA_SASL_USERNAME = env("KAFKA_SASL_USERNAME", "")
KAFKA_SASL_PASSWORD = env("KAFKA_SASL_PASSWORD", "")
KAFKA_CA_FILE = env("KAFKA_CA_FILE", "")
KAFKA_REPLICATION = int(env("KAFKA_REPLICATION", "1"))  # 3 on a multi-broker cluster

# MQTT (field network)
MQTT_HOST = env("MQTT_HOST", "localhost")
MQTT_PORT = int(env("MQTT_PORT", "8883"))
MQTT_CA_FILE = env("MQTT_CA_FILE", "certs/ca.crt")
MQTT_USERNAME = env("MQTT_USERNAME", "sensor")
MQTT_PASSWORD = env("MQTT_PASSWORD", "sensor-pass")
MQTT_TOPIC = env("MQTT_TOPIC", "city/sensors/#")

# PostgreSQL / PostGIS / TimescaleDB / pgRouting
DATABASE_URL = env("DATABASE_URL", "postgresql://smartcity:smartcity@localhost:5432/smartcity")

# Flood thresholds (metres above gauge datum); per-sensor overrides live in the DB
FLOOD_THRESHOLD_M = float(env("FLOOD_THRESHOLD_M", "2.5"))

# Auth
JWT_SECRET = env("JWT_SECRET", "dev-only-jwt-signing-key-change-me-0123456789")  # loaded from Key Vault when KEY_VAULT_URL is set
JWT_ISSUER = env("JWT_ISSUER", "smartcity-approval")
KEY_VAULT_URL = env("KEY_VAULT_URL", "")

# Blob storage (Azurite locally, Azure Storage in the cloud)
BLOB_CONNECTION_STRING = env(
    "BLOB_CONNECTION_STRING",
    "DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;"
    "AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;"
    "BlobEndpoint=http://localhost:10000/devstoreaccount1;",
)
BLOB_CONTAINER = env("BLOB_CONTAINER", "reports")

# Outbound notification providers via APIs/notification (dry-run unless credentials are configured)
SMSAPI_TOKEN = env("SMSAPI_TOKEN", "")
SMS_LIVE = env("SMS_LIVE", "0") == "1"  # SMSAPI test mode (validated, not delivered) unless SMS_LIVE=1
GMAIL_CLIENT_SECRET_FILE = env("GMAIL_CLIENT_SECRET_FILE", "")
GMAIL_TOKEN_FILE = env("GMAIL_TOKEN_FILE", "") or None  # token.json from a one-off browser sign-in
NOTIFY_SMS_TO = env("NOTIFY_SMS_TO", "+353000000000")
NOTIFY_EMAIL_TO = env("NOTIFY_EMAIL_TO", "responders@example.ie")

# External city systems: the team's simulated traffic-light control API (APIs/trafficControlAPI.py)
TRAFFIC_LIGHTS_URL = env("TRAFFIC_LIGHTS_URL", "http://localhost:8090")

# Public data sources are called through ../APIs (smartcity/team_apis.py)
OFFLINE = env("OFFLINE", "0") == "1"  # use fixtures instead of live public APIs

# Observability: each process exposes Prometheus metrics on this port
METRICS_PORT = int(env("METRICS_PORT", "0"))

# System-health dashboard: where the WebSocket hub probes the other components ("" = not deployed, skipped)
NOTIFY_URL = env("NOTIFY_URL", "http://localhost:8001")
APPROVAL_URL = env("APPROVAL_URL", "http://localhost:8002")
GATEWAY_URL = env("GATEWAY_URL", "https://localhost:8444")
PROMETHEUS_URL = env("PROMETHEUS_URL", "http://localhost:9090")
GRAFANA_URL = env("GRAFANA_URL", "")
AGENT_METRICS = env("AGENT_METRICS", "")  # "flood-detector=http://host:port/metrics,..."; default compose names
