"""Thin wrapper over confluent-kafka: publish/consume Pydantic models on named topics."""
import json
import logging
import signal
import threading
from collections.abc import Callable

from confluent_kafka import Consumer, KafkaError, Producer
from pydantic import BaseModel

from smartcity import config
from smartcity.models import TOPICS

log = logging.getLogger("bus")


def _base_conf() -> dict:
    conf = {"bootstrap.servers": config.KAFKA_BOOTSTRAP, "security.protocol": config.KAFKA_SECURITY_PROTOCOL}
    if config.KAFKA_SECURITY_PROTOCOL.startswith("SASL"):
        conf.update(
            {
                "sasl.mechanisms": "PLAIN",
                "sasl.username": config.KAFKA_SASL_USERNAME,
                "sasl.password": config.KAFKA_SASL_PASSWORD,
            }
        )
    if config.KAFKA_CA_FILE:
        conf["ssl.ca.location"] = config.KAFKA_CA_FILE
    return conf


class Publisher:
    def __init__(self):
        self._producer = Producer({**_base_conf(), "linger.ms": 5, "acks": "all"})

    def publish(self, topic: str, message: BaseModel) -> None:
        if not isinstance(message, TOPICS[topic]):
            raise TypeError(f"{topic} expects {TOPICS[topic].__name__}, got {type(message).__name__}")
        self._producer.produce(topic, key=message.id, value=message.model_dump_json().encode())
        self._producer.flush(5)


def consume(group_id: str, topics: list[str], handler: Callable[[str, BaseModel], None], stop=lambda: False):
    """Block forever (or until stop() is true), calling handler(topic, model) for each message.

    On SIGTERM the consumer closes cleanly so it leaves the group at once and a restarted copy resumes from the
    committed offset without waiting for a session timeout (no messages lost, no long rebalance).
    """
    terminated = threading.Event()
    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGTERM, lambda *_: terminated.set())
    consumer = Consumer({**_base_conf(), "group.id": group_id, "auto.offset.reset": "latest",
                         "enable.auto.commit": True})
    consumer.subscribe(topics)
    try:
        while not stop() and not terminated.is_set():
            msg = consumer.poll(0.5)
            if msg is None:
                continue
            if msg.error():
                if msg.error().code() != KafkaError._PARTITION_EOF:
                    log.warning("kafka error: %s", msg.error())
                continue
            topic = msg.topic()
            try:
                model = TOPICS[topic].model_validate(json.loads(msg.value()))
            except Exception as exc:  # bad message must not kill the agent
                log.error("invalid message on %s: %s", topic, exc)
                continue
            try:
                handler(topic, model)
            except Exception:
                log.exception("handler failed for %s", topic)
    finally:
        consumer.close()
