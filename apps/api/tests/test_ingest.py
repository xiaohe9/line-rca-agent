"""Telemetry ingest tests.

Two layers, tested separately:

* the wire format, exhaustively and with no broker, because a malformed message must be
  rejected rather than crash a collector that is otherwise doing its job;
* the database write, against the real database, because `source="mqtt"` and the batch
  insert are what the rest of the system reads back.
"""

from __future__ import annotations

import json
import socket
import time
from datetime import UTC, datetime

import pytest

from line_rca_agent.tools import InMemoryToolRegistry
from line_rca_api.config import Settings
from line_rca_api.db.repositories import SqlTelemetryRepository
from line_rca_api.ingest.collector import TelemetryCollector, broker_endpoint
from line_rca_api.ingest.messages import (
    SUBSCRIPTION,
    MessageError,
    TelemetryMessage,
    encode_message,
    parse_message,
    station_from_topic,
    topic_for,
)
from line_rca_api.tools import register_line_tools

VALID = json.dumps(
    {
        "metric": "vibrationMm",
        "value": 0.199,
        "baseline": 0.06,
        "recordedAt": "2026-10-14T09:00:00Z",
    }
).encode()


def test_topic_helpers_round_trip() -> None:
    assert topic_for("镀膜") == "line/镀膜/telemetry"
    assert station_from_topic("line/镀膜/telemetry") == "镀膜"
    assert SUBSCRIPTION == "line/+/telemetry"


@pytest.mark.parametrize(
    "topic",
    ["line/telemetry", "line/镀膜/other", "other/镀膜/telemetry", "line//telemetry", "nonsense"],
)
def test_unexpected_topics_are_rejected(topic: str) -> None:
    assert station_from_topic(topic) is None
    with pytest.raises(MessageError):
        parse_message(topic, VALID)


def test_valid_message_parses() -> None:
    message = parse_message("line/镀膜/telemetry", VALID)

    assert message.station == "镀膜"
    assert message.metric == "vibrationMm"
    assert message.value == 0.199
    assert message.baseline == 0.06
    assert message.recorded_at == datetime(2026, 10, 14, 9, 0, tzinfo=UTC)


def test_encode_and_parse_agree() -> None:
    original = TelemetryMessage(
        "蚀刻", "temperatureC", 66.4, 66.0, datetime(2026, 10, 14, tzinfo=UTC)
    )
    assert parse_message(topic_for("蚀刻"), encode_message(original)) == original


def test_missing_timestamp_is_stamped_not_invented_silently() -> None:
    payload = json.dumps({"metric": "beltSpeed", "value": 1.01, "baseline": 1.0}).encode()
    message = parse_message("line/贴片/telemetry", payload)

    assert message.recorded_at.tzinfo is not None
    assert abs((datetime.now(UTC) - message.recorded_at).total_seconds()) < 5


def test_absent_baseline_defaults_to_zero_rather_than_guessing() -> None:
    payload = json.dumps({"metric": "beltSpeed", "value": 1.01}).encode()
    assert parse_message("line/贴片/telemetry", payload).baseline == 0.0


@pytest.mark.parametrize(
    "payload",
    [
        b"not json",
        b"\xff\xfe not utf-8",
        b"[1, 2, 3]",
        json.dumps({"value": 1.0}).encode(),  # metric missing
        json.dumps({"metric": "x"}).encode(),  # value missing
        json.dumps({"metric": "x", "value": True}).encode(),  # bool is not a number
        json.dumps({"metric": "x", "value": "1.0"}).encode(),
        json.dumps({"metric": "", "value": 1.0}).encode(),
        json.dumps({"metric": "x", "value": 1.0, "recordedAt": "yesterday"}).encode(),
        json.dumps({"metric": "x", "value": 1.0, "recordedAt": 123}).encode(),
    ],
)
def test_malformed_payloads_are_rejected(payload: bytes) -> None:
    with pytest.raises(MessageError):
        parse_message("line/镀膜/telemetry", payload)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("mqtt://localhost:1883", ("localhost", 1883)),
        ("mqtt://mosquitto", ("mosquitto", 1883)),
        ("tcp://10.0.0.5:1884", ("10.0.0.5", 1884)),
    ],
)
def test_broker_endpoint_parsing(url: str, expected: tuple[str, int]) -> None:
    assert broker_endpoint(url) == expected


@pytest.mark.parametrize("url", ["http://localhost:1883", "localhost:1883", "mqtt://"])
def test_broker_endpoint_rejects_nonsense(url: str) -> None:
    with pytest.raises(ValueError, match="LRC_MQTT_URL"):
        broker_endpoint(url)


# --------------------------------------------------------------------------- #
#  database write
# --------------------------------------------------------------------------- #


class _NoDefects:
    """Stands in for the defect repository: registered but never called here."""

    async def recent_batches(self, limit: int = 6) -> list:
        return []

    async def batch_summary(self, batch_id: str) -> None:
        return None

    async def defect_breakdown(self, batch_id: str) -> list:
        return []


class _NoWorkOrders:
    async def create(self, draft: object) -> object:
        raise AssertionError("the telemetry tool must not touch work orders")

    async def list_recent(self, *, status: str | None = None, limit: int = 10) -> list:
        return []

    async def find_similar(self, text: str, *, limit: int = 3) -> list:
        return []


async def test_flush_persists_rows_labelled_as_mqtt(
    prepared_database: str, session_factory
) -> None:  # type: ignore[no-untyped-def]
    collector = TelemetryCollector(
        Settings(database_url=prepared_database, mqtt_url="mqtt://localhost:1883"),
        sessionmaker=session_factory,
    )
    messages = [
        parse_message("line/镀膜/telemetry", VALID),
        parse_message(
            "line/蚀刻/telemetry",
            json.dumps({"metric": "temperatureC", "value": 66.1, "baseline": 66.0}).encode(),
        ),
    ]

    await collector.flush(messages)

    assert collector.accepted == 2
    async with session_factory() as session:
        readings = await SqlTelemetryRepository(session).latest_readings("蚀刻")
    assert any(reading.metric == "temperatureC" and reading.value == 66.1 for reading in readings)


async def test_ingested_values_are_visible_to_the_agents_telemetry_tool(
    prepared_database: str,
    session_factory,  # type: ignore[no-untyped-def]
) -> None:
    """The point of ingest: what the collector writes is what the agent then reasons over."""
    collector = TelemetryCollector(
        Settings(database_url=prepared_database, mqtt_url="mqtt://localhost:1883"),
        sessionmaker=session_factory,
    )
    await collector.flush(
        [
            TelemetryMessage(
                station="封装",
                metric="vibrationMm",
                value=0.21,
                baseline=0.04,
                recorded_at=datetime(2026, 10, 14, 12, 0, tzinfo=UTC),
            )
        ]
    )

    async with session_factory() as session:
        registry = InMemoryToolRegistry()
        register_line_tools(
            registry,
            defects=_NoDefects(),
            telemetry=SqlTelemetryRepository(session),
            work_orders=_NoWorkOrders(),
        )
        tool = registry.get("query_telemetry")
        assert tool is not None
        result = await tool.run({"station": "封装"})

    assert result.ok is True
    assert any(item["metric"] == "vibrationMm" for item in result.data["deviations"])


# --------------------------------------------------------------------------- #
#  broker round trip (needs the compose broker)
# --------------------------------------------------------------------------- #


def _broker_reachable() -> bool:
    with socket.socket() as probe:
        probe.settimeout(1.0)
        return probe.connect_ex(("127.0.0.1", 1883)) == 0


@pytest.mark.skipif(
    not _broker_reachable(),
    reason="no MQTT broker on 127.0.0.1:1883; start it with `docker compose up -d mosquitto`",
)
def test_publish_and_subscribe_round_trip() -> None:
    """Exercises the real wire contract: paho publishes, paho subscribes, parse accepts."""
    import paho.mqtt.client as mqtt

    received: list[TelemetryMessage] = []
    original = TelemetryMessage(
        "镀膜", "vibrationMm", 0.188, 0.06, datetime(2026, 10, 14, 9, 30, tzinfo=UTC)
    )

    def on_message(client, userdata, message) -> None:  # type: ignore[no-untyped-def]
        received.append(parse_message(message.topic, message.payload))
        client.disconnect()

    subscriber = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="line-rca-test-sub")
    subscriber.on_message = on_message
    subscriber.connect("127.0.0.1", 1883, keepalive=10)
    subscriber.subscribe(SUBSCRIPTION, qos=1)
    subscriber.loop_start()

    publisher = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="line-rca-test-pub")
    publisher.connect("127.0.0.1", 1883, keepalive=10)
    publisher.loop_start()
    publisher.publish(topic_for("镀膜"), encode_message(original), qos=1)

    deadline = time.monotonic() + 10
    while not received and time.monotonic() < deadline:
        time.sleep(0.1)

    subscriber.loop_stop()
    publisher.loop_stop()

    assert received == [original]
