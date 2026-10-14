"""Wire format for inbound line telemetry.

Parsing is a pure function over (topic, payload) so it can be tested exhaustively without a
broker. Everything a collector does with a bad message — reject it, log it, keep going — is a
decision made here rather than scattered through the MQTT callbacks.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

TOPIC_PREFIX = "line"
TOPIC_SUFFIX = "telemetry"
#: `line/<station>/telemetry`
SUBSCRIPTION = f"{TOPIC_PREFIX}/+/telemetry"

REQUIRED_FIELDS = ("metric", "value")


class MessageError(ValueError):
    """A message that cannot be trusted. The collector logs it and moves on."""


@dataclass(frozen=True, slots=True)
class TelemetryMessage:
    station: str
    metric: str
    value: float
    baseline: float
    recorded_at: datetime


def topic_for(station: str) -> str:
    return f"{TOPIC_PREFIX}/{station}/{TOPIC_SUFFIX}"


def station_from_topic(topic: str) -> str | None:
    parts = topic.split("/")
    if len(parts) != 3 or parts[0] != TOPIC_PREFIX or parts[2] != TOPIC_SUFFIX:
        return None
    return parts[1] or None


def _as_float(body: dict[str, Any], key: str) -> float:
    raw = body.get(key)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise MessageError(f"field '{key}' must be a number, got {type(raw).__name__}")
    return float(raw)


def _as_timestamp(raw: Any) -> datetime:
    if raw is None:
        # A device that does not timestamp its own readings is normal; the collector's clock
        # is the best available answer, and it is recorded rather than silently invented.
        return datetime.now(UTC)
    if not isinstance(raw, str):
        raise MessageError("field 'recordedAt' must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MessageError(f"field 'recordedAt' is not ISO-8601: {raw!r}") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def parse_message(topic: str, payload: bytes) -> TelemetryMessage:
    """Turn one MQTT message into a row, or raise `MessageError`."""
    station = station_from_topic(topic)
    if station is None:
        raise MessageError(f"unexpected topic: {topic!r}")

    try:
        decoded = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MessageError(f"payload is not UTF-8: {exc}") from exc

    try:
        body = json.loads(decoded)
    except json.JSONDecodeError as exc:
        raise MessageError(f"payload is not JSON: {exc}") from exc
    if not isinstance(body, dict):
        raise MessageError("payload must be a JSON object")

    missing = [name for name in REQUIRED_FIELDS if name not in body]
    if missing:
        raise MessageError(f"missing required field(s): {', '.join(missing)}")

    metric = body.get("metric")
    if not isinstance(metric, str) or not metric.strip():
        raise MessageError("field 'metric' must be a non-empty string")

    # The baseline is carried on the wire rather than looked up: a reading is meaningless
    # without the value it should be compared against, and the device knows its own setpoint.
    return TelemetryMessage(
        station=station,
        metric=metric.strip(),
        value=_as_float(body, "value"),
        baseline=_as_float(body, "baseline") if "baseline" in body else 0.0,
        recorded_at=_as_timestamp(body.get("recordedAt")),
    )


def encode_message(message: TelemetryMessage) -> bytes:
    """The publisher side of the same contract, so both ends cannot drift apart."""
    return json.dumps(
        {
            "metric": message.metric,
            "value": message.value,
            "baseline": message.baseline,
            "recordedAt": message.recorded_at.isoformat(),
            "source": "simulated",
        },
        ensure_ascii=False,
    ).encode("utf-8")
