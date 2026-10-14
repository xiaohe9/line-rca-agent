"""Publish simulated line telemetry to the broker.

Stands in for an edge gateway reading a PLC. Every message is labelled `source: simulated`
on the wire, and the readings walk around the same baselines the seeded dataset uses, so a
live run tells the same story as the recorded one rather than contradicting it.

    python -m line_rca_api.ingest.simulator
"""

from __future__ import annotations

import contextlib
import logging
import random
import signal
import time
from datetime import UTC, datetime

import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion

from line_rca_api.config import get_settings
from line_rca_api.ingest.collector import broker_endpoint
from line_rca_api.ingest.messages import TelemetryMessage, encode_message, topic_for

logger = logging.getLogger("line_rca_api.ingest.simulator")

SEED = 20261014

#: station, metric, baseline, jitter, and whether the station is degraded.
#: 镀膜 vibration drifts well above its baseline, matching the seeded failure story.
STATIONS: tuple[tuple[str, str, float, float, bool], ...] = (
    ("镀膜", "temperatureC", 68.0, 1.2, True),
    ("镀膜", "vibrationMm", 0.06, 0.008, True),
    ("镀膜", "beltSpeed", 1.00, 0.02, False),
    ("蚀刻", "temperatureC", 66.0, 1.0, False),
    ("蚀刻", "vibrationMm", 0.05, 0.006, False),
    ("封装", "temperatureC", 70.0, 1.1, False),
    ("封装", "vibrationMm", 0.04, 0.005, False),
    ("贴片", "beltSpeed", 1.02, 0.02, False),
)

DEGRADED_FACTOR = {"vibrationMm": 3.3, "temperatureC": 1.05}


def reading_for(
    rng: random.Random, station: str, metric: str, baseline: float, jitter: float, degraded: bool
) -> float:
    factor = DEGRADED_FACTOR.get(metric, 1.2) if degraded else 1.0
    return round(baseline * factor + rng.uniform(-jitter, jitter), 4)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = get_settings()
    host, port = broker_endpoint(settings.mqtt_url)

    rng = random.Random(SEED)  # noqa: S311 (deterministic simulation, not security)
    client = mqtt.Client(CallbackAPIVersion.VERSION2, client_id="line-rca-simulator")
    client.connect(host, port, keepalive=30)
    client.loop_start()

    stop = False

    def _stop(signum: int, frame: object) -> None:
        nonlocal stop
        stop = True

    for signal_name in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(ValueError, OSError):
            signal.signal(signal_name, _stop)

    logger.info(
        "publishing simulated telemetry to %s:%s every %ss (Ctrl-C to stop)",
        host,
        port,
        settings.simulator_interval_seconds,
    )
    published = 0
    try:
        while not stop:
            for station, metric, baseline, jitter, degraded in STATIONS:
                message = TelemetryMessage(
                    station=station,
                    metric=metric,
                    value=reading_for(rng, station, metric, baseline, jitter, degraded),
                    baseline=baseline,
                    recorded_at=datetime.now(UTC),
                )
                client.publish(topic_for(station), encode_message(message), qos=1)
                published += 1
            logger.info("published %d message(s) so far", published)
            time.sleep(settings.simulator_interval_seconds)
    finally:
        client.loop_stop()
        client.disconnect()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
