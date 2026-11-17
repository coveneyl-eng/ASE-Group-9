"""MQTT bridge: subscribes to the field broker (MQTT over TLS, QoS 1) and republishes to Kafka flood.readings."""
import json
import ssl

import paho.mqtt.client as mqtt

from smartcity import bus, config, telemetry
from smartcity.models import SensorReading

t = telemetry.setup("mqtt-bridge")
publisher = bus.Publisher()


def on_connect(client, userdata, flags, reason_code, properties):
    t["log"].info("connected to MQTT %s:%s (%s)", config.MQTT_HOST, config.MQTT_PORT, reason_code)
    client.subscribe(config.MQTT_TOPIC, qos=1)


def on_message(client, userdata, msg):
    try:
        data = json.loads(msg.payload)
        reading = SensorReading(source="mqtt", **data)
    except Exception as exc:
        t["log"].error("rejected MQTT payload on %s: %s", msg.topic, exc)
        return
    publisher.publish("flood.readings", reading)
    t["processed"].add(1, {"topic": "flood.readings"})
    t["log"].info("bridged %s=%s trace=%s", reading.sensor_id, reading.value, reading.trace_id)


def main():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="mqtt-kafka-bridge")
    client.username_pw_set(config.MQTT_USERNAME, config.MQTT_PASSWORD)
    client.tls_set(ca_certs=config.MQTT_CA_FILE, tls_version=ssl.PROTOCOL_TLS_CLIENT)
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(config.MQTT_HOST, config.MQTT_PORT)
    client.loop_forever()


if __name__ == "__main__":
    main()
