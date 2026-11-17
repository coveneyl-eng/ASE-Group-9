-- Smart City thin slice schema. Runs once on an empty database.
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pgrouting;

-- TimescaleDB ships in the timescale/timescaledb-ha image used by docker compose.
DO $$
BEGIN
    CREATE EXTENSION IF NOT EXISTS timescaledb;
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'timescaledb not available: %', SQLERRM;
END $$;

-- Time series of every reading that crossed the bus
CREATE TABLE IF NOT EXISTS sensor_readings (
    time        timestamptz NOT NULL,
    sensor_id   text        NOT NULL,
    kind        text        NOT NULL,
    value       double precision NOT NULL,
    source      text        NOT NULL,
    geom        geometry(Point, 4326)
);

-- Impacts produced by the Flood Scope Agent
CREATE TABLE IF NOT EXISTS impacts (
    time        timestamptz NOT NULL,
    impact_id   text        NOT NULL,
    event_id    text        NOT NULL,
    asset_id    integer     NOT NULL,
    status      text        NOT NULL CHECK (status IN ('safe', 'caution', 'unsafe'))
);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN
        PERFORM create_hypertable('sensor_readings', 'time', if_not_exists => TRUE);
        PERFORM create_hypertable('impacts', 'time', if_not_exists => TRUE);
    END IF;
END $$;

-- Who approved what (legal audit requirement)
CREATE TABLE IF NOT EXISTS audit_log (
    id          bigserial PRIMARY KEY,
    at          timestamptz NOT NULL DEFAULT now(),
    actor       text NOT NULL,
    role        text NOT NULL,
    action      text NOT NULL,
    payload     jsonb NOT NULL
);

-- Every outbound alert, with sensor-to-alert latency (QoS: <= 5 s for 95%)
CREATE TABLE IF NOT EXISTS notifications (
    id          bigserial PRIMARY KEY,
    at          timestamptz NOT NULL DEFAULT now(),
    trace_id    text NOT NULL,
    channel     text NOT NULL,
    recipient   text NOT NULL,
    text        text NOT NULL,
    latency_ms  double precision NOT NULL,
    delivered   boolean NOT NULL,
    dry_run     boolean NOT NULL
);

-- Decisions per agent (statistics requirement)
CREATE TABLE IF NOT EXISTS agent_decisions (
    id          bigserial PRIMARY KEY,
    at          timestamptz NOT NULL DEFAULT now(),
    agent       text NOT NULL,
    trace_id    text NOT NULL,
    decision    jsonb NOT NULL
);
