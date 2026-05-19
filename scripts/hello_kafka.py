"""Day 1 thin slice — prove the local Kafka stack works end to end.

Produces one JSON message to a topic, consumes it back, and verifies the
round-trip. Run with the stack up (`make up`):

    uv run python scripts/hello_kafka.py
"""

from __future__ import annotations

import json
import sys
import uuid

from confluent_kafka import Consumer, KafkaError, Producer

BOOTSTRAP_SERVERS = "localhost:9092"
TOPIC = "polaris.hello"


def produce_one() -> dict:
    """Send one JSON message to TOPIC; block until the broker acks it."""
    producer = Producer({"bootstrap.servers": BOOTSTRAP_SERVERS})
    payload = {"id": str(uuid.uuid4()), "text": "hello from Polaris Day 1"}

    acked: list[bool] = []

    def on_delivery(err: KafkaError | None, msg) -> None:
        if err is not None:
            print(f"  delivery FAILED: {err}", file=sys.stderr)
            return
        print(f"  delivered to {msg.topic()} [partition {msg.partition()}] @ offset {msg.offset()}")
        acked.append(True)

    producer.produce(TOPIC, value=json.dumps(payload).encode(), callback=on_delivery)
    producer.flush(timeout=10)

    if not acked:
        raise RuntimeError("message not delivered — is the Kafka stack up? (`make up`)")
    return payload


def consume_one() -> dict:
    """Subscribe to TOPIC and poll until one message is read; return its payload."""
    consumer = Consumer(
        {
            "bootstrap.servers": BOOTSTRAP_SERVERS,
            "group.id": "polaris-hello-consumer",
            "auto.offset.reset": "earliest",
        }
    )
    consumer.subscribe([TOPIC])
    try:
        for _ in range(30):  # poll up to ~30s
            msg = consumer.poll(timeout=1.0)
            if msg is None:
                continue
            if msg.error():
                raise RuntimeError(f"consume error: {msg.error()}")
            return json.loads(msg.value())
        raise RuntimeError("no message read within 30s")
    finally:
        consumer.close()


def main() -> None:
    print("PRODUCING")
    sent = produce_one()
    print(f"  payload: {sent}\n")

    print("CONSUMING")
    got = consume_one()
    print(f"  payload: {got}\n")

    if got["id"] != sent["id"]:
        raise SystemExit("round-trip MISMATCH — produced and consumed ids differ")
    print("round-trip OK — local Kafka stack is working.")


if __name__ == "__main__":
    main()
