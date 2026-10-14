"""Subscribe to line telemetry and persist it.

A separate process rather than an API background task. In a plant the collector sits at the
edge, next to the equipment, and the application reads what it stored; keeping them apart
also means a broker outage cannot take the API down with it.

    python -m line_rca_api.ingest.collector
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
from urllib.parse import urlparse

import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from line_rca_api.config import Settings, get_settings
from line_rca_api.db.models import TelemetrySample
from line_rca_api.db.session import sessionmaker_for
from line_rca_api.ingest.messages import SUBSCRIPTION, MessageError, TelemetryMessage, parse_message

logger = logging.getLogger("line_rca_api.ingest")

#: Flush at most this often, and at most this many rows, so a burst cannot stall the loop.
BATCH_SIZE = 50
FLUSH_INTERVAL_SECONDS = 2.0


def broker_endpoint(url: str) -> tuple[str, int]:
    """Parse `mqtt://host:port` into a host and port paho understands."""
    parsed = urlparse(url)
    if parsed.scheme not in {"mqtt", "tcp"} or not parsed.hostname:
        raise ValueError(f"LRC_MQTT_URL must look like mqtt://host:port, got {url!r}")
    return parsed.hostname, parsed.port or 1883


class TelemetryCollector:
    def __init__(
        self,
        settings: Settings,
        *,
        sessionmaker: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self._settings = settings
        self._sessionmaker: async_sessionmaker[AsyncSession] = sessionmaker or sessionmaker_for(
            settings.database_url
        )
        self._queue: asyncio.Queue[TelemetryMessage] = asyncio.Queue(maxsize=10_000)
        self._loop: asyncio.AbstractEventLoop | None = None
        self.accepted = 0
        self.rejected = 0

    # -- MQTT callbacks run on paho's thread ------------------------------- #
    def _on_connect(self, client, userdata, flags, reason_code, properties=None) -> None:  # type: ignore[no-untyped-def]
        if reason_code != 0:
            logger.error("mqtt connect failed: %s", reason_code)
            return
        client.subscribe(SUBSCRIPTION, qos=1)
        logger.info("subscribed to %s", SUBSCRIPTION)

    def _on_message(self, client, userdata, message) -> None:  # type: ignore[no-untyped-def]
        try:
            parsed = parse_message(message.topic, message.payload)
        except MessageError as exc:
            self.rejected += 1
            logger.warning("dropped telemetry on %s: %s", message.topic, exc)
            return

        if self._loop is None:
            return
        try:
            self._loop.call_soon_threadsafe(self._queue.put_nowait, parsed)
        except RuntimeError:
            # Loop is shutting down; the broker will redeliver or the reading is lost, and
            # that is preferable to blocking paho's network thread.
            self.rejected += 1

    # -- database side ----------------------------------------------------- #
    async def flush(self, pending: list[TelemetryMessage]) -> None:
        """Persist a batch. Public because it is the seam tests and backfills use."""
        if not pending:
            return
        async with self._sessionmaker() as session:
            session.add_all(
                TelemetrySample(
                    station=item.station,
                    metric=item.metric,
                    value=item.value,
                    baseline=item.baseline,
                    recorded_at=item.recorded_at,
                    source="mqtt",
                )
                for item in pending
            )
            await session.commit()
        self.accepted += len(pending)

    async def _drain_forever(self) -> None:
        pending: list[TelemetryMessage] = []
        while True:
            try:
                item = await asyncio.wait_for(self._queue.get(), timeout=FLUSH_INTERVAL_SECONDS)
                pending.append(item)
            except TimeoutError:
                pass

            if len(pending) >= BATCH_SIZE or (pending and self._queue.empty()):
                batch, pending = pending, []
                try:
                    await self.flush(batch)
                except Exception:
                    logger.exception("failed to persist %d telemetry sample(s)", len(batch))

    # -- lifecycle --------------------------------------------------------- #
    async def run(self, *, stop: asyncio.Event | None = None) -> None:
        self._loop = asyncio.get_running_loop()
        host, port = broker_endpoint(self._settings.mqtt_url)

        client = mqtt.Client(CallbackAPIVersion.VERSION2, client_id="line-rca-collector")
        client.on_connect = self._on_connect
        client.on_message = self._on_message
        client.connect_async(host, port, keepalive=30)
        client.loop_start()

        logger.info("collector started against %s:%s", host, port)
        drain = asyncio.create_task(self._drain_forever())
        try:
            if stop is None:
                await asyncio.Event().wait()
            else:
                await stop.wait()
        finally:
            drain.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await drain
            client.loop_stop()
            client.disconnect()
            logger.info("collector stopped: accepted=%d rejected=%d", self.accepted, self.rejected)


async def _main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = get_settings()
    if not settings.database_url:
        logger.error("LRC_DATABASE_URL is not set; the collector has nowhere to write.")
        return 1
    if not settings.mqtt_url:
        logger.error("LRC_MQTT_URL is not set; the collector has nothing to read.")
        return 1

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_name in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):  # SIGTERM is limited on Windows
            loop.add_signal_handler(signal_name, stop.set)

    await TelemetryCollector(settings).run(stop=stop)
    return 0


def main() -> int:
    return asyncio.run(_main())


if __name__ == "__main__":
    raise SystemExit(main())
