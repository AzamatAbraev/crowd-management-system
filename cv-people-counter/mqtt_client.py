"""
MQTT publisher — emits the exact same payload schema as the ESP8266 devices so the
existing Spring Boot backend processes camera events without any changes.

Topic: wiut/{site}/{building}/{floor}/{room}/{device_type}/{device_id}/telemetry
       wiut/{site}/{building}/{floor}/{room}/{device_type}/{device_id}/status
"""

import json
import time
import threading
import logging
from typing import Optional
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

import config

logger = logging.getLogger(__name__)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class MQTTPublisher:
    def __init__(self):
        self._seq       = 0
        self._start     = time.time()
        self._lock      = threading.Lock()
        self._connected = False

        self._client = mqtt.Client(
            client_id=config.DEVICE_ID,
            protocol=mqtt.MQTTv311,
            clean_session=True,
        )
        self._client.on_connect    = self._on_connect
        self._client.on_disconnect = self._on_disconnect

        # LWT — broker publishes this automatically if we drop without a clean disconnect
        self._client.will_set(
            topic=self._topic("status"),
            payload=self._status_payload("offline", "unexpected_disconnect"),
            qos=1,
            retain=True,
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def connect(self):
        """Connect with exponential-backoff retry (mirrors iot-simulator behaviour)."""
        wait, max_wait = 1, 60
        while True:
            try:
                logger.info("Connecting to MQTT broker %s:%d …",
                            config.MQTT_BROKER_HOST, config.MQTT_BROKER_PORT)
                self._client.connect(
                    config.MQTT_BROKER_HOST, config.MQTT_BROKER_PORT, keepalive=30
                )
                self._client.loop_start()
                deadline = time.time() + 10
                while not self._connected and time.time() < deadline:
                    time.sleep(0.1)
                if self._connected:
                    self._publish_birth()
                    return
                raise ConnectionError("Timed out waiting for CONNACK")
            except Exception as exc:
                logger.warning("MQTT connect failed: %s  — retry in %ds", exc, wait)
                time.sleep(wait)
                wait = min(wait * 2, max_wait)

    def disconnect(self):
        self._publish("status", self._status_payload("offline", "clean_shutdown"), retain=True)
        time.sleep(0.3)
        self._client.loop_stop()
        self._client.disconnect()

    def publish_telemetry(self, delta: int, misfire: bool = False):
        """
        Publish one telemetry event.  delta = +1 (entry) or -1 (exit) for line mode;
        any integer for room mode (bulk occupancy change).
        """
        with self._lock:
            self._seq += 1
            seq = self._seq

        payload = json.dumps({
            "v":             1,
            "device_id":     config.DEVICE_ID,
            "type":          "telemetry",
            "seq":           seq,
            "timestamp_iso": _utc_iso(),
            "timestamp_unix": time.time(),
            "payload": {
                "direction":   "entry" if delta > 0 else "exit",
                "count_delta": delta,
                "misfire":     misfire,
            },
            "meta": {
                "firmware": config.FIRMWARE,
                "rssi":     0,           # not applicable for a camera device
                "uptime_s": int(time.time() - self._start),
            },
        })
        self._publish("telemetry", payload)
        logger.info("TELEMETRY | delta=%+d | seq=%d | direction=%s",
                    delta, seq, "entry" if delta > 0 else "exit")

    # ── Internals ─────────────────────────────────────────────────────────────

    def _topic(self, suffix: str) -> str:
        return (
            f"{config.MQTT_NAMESPACE}/{config.SITE}/{config.BUILDING}/"
            f"{config.FLOOR}/{config.ROOM}/{config.DEVICE_TYPE}/"
            f"{config.DEVICE_ID}/{suffix}"
        )

    def _publish(self, suffix: str, payload: str, retain: bool = False):
        self._client.publish(self._topic(suffix), payload, qos=1, retain=retain)

    def _status_payload(self, status: str, reason: Optional[str] = None) -> str:
        msg = {
            "v":             1,
            "device_id":     config.DEVICE_ID,
            "type":          "birth" if status == "online" else "death",
            "status":        status,
            "firmware":      config.FIRMWARE,
            "timestamp_iso": _utc_iso(),
            "timestamp_unix": time.time(),
        }
        if reason:
            msg["reason"] = reason
        return json.dumps(msg)

    def _publish_birth(self):
        self._publish("status", self._status_payload("online"), retain=True)
        logger.info("Birth published | device=%s | topic=%s",
                    config.DEVICE_ID, self._topic("status"))

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self._connected = True
            logger.info("MQTT connected")
        else:
            logger.error("MQTT connection refused rc=%d", rc)

    def _on_disconnect(self, client, userdata, rc):
        self._connected = False
        if rc != 0:
            logger.warning("Unexpected MQTT disconnect rc=%d — paho will auto-reconnect", rc)
