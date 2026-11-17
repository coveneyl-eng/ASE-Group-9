"""Field sensor simulator: publishes water-level and drain readings over MQTT/TLS to the edge Mosquitto broker.

Usage:
    python -m smartcity.simulators.sensors              # steady normal readings every 5 s
    python -m smartcity.simulators.sensors --flood      # one reading above the flood threshold, then exit
"""
import argparse
import json
import random
import ssl
import time
from datetime import datetime, timezone
from uuid import uuid4

import paho.mqtt.client as mqtt

from smartcity import config

SENSORS = [
    {"sensor_id": "DODDER-RINGSEND", "kind": "water_level_m", "lon": -6.2210, "lat": 53.3385, "normal": 1.1},
    {"sensor_id": "DRAIN-PEARSE-01", "kind": "drain_level_pct", "lon": -6.2290, "lat": 53.3440, "normal": 30.0},
]


def connect() -> mqtt.Client:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"sim-{uuid4().hex[:6]}")
    client.username_pw_set(config.MQTT_USERNAME, config.MQTT_PASSWORD)
    client.tls_set(ca_certs=config.MQTT_CA_FILE, tls_version=ssl.PROTOCOL_TLS_CLIENT)
    client.connect(config.MQTT_HOST, config.MQTT_PORT)
    client.loop_start()
    return client


def reading(sensor: dict, value: float) -> dict:
    return {
        "sensor_id": sensor["sensor_id"], "kind": sensor["kind"], "value": round(value, 3),
        "lon": sensor["lon"], "lat": sensor["lat"], "observed_at": datetime.now(timezone.utc).isoformat(),
        "trace_id": uuid4().hex,
    }


def publish(client: mqtt.Client, payload: dict) -> None:
    topic = f"city/sensors/{payload['kind']}/{payload['sensor_id']}"
    client.publish(topic, json.dumps(payload), qos=1).wait_for_publish(5)
    print("published", topic, payload["value"], payload["trace_id"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--flood", action="store_true", help="send one above-threshold reading and exit")
    parser.add_argument("--level", type=float, default=3.2)
    args = parser.parse_args()
    client = connect()
    try:
        if args.flood:
            publish(client, reading(SENSORS[0], args.level))
            return
        while True:
            for s in SENSORS:
                publish(client, reading(s, s["normal"] * random.uniform(0.9, 1.1)))
            time.sleep(5)
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
