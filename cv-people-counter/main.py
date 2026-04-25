"""
Entry point.  Run with:
    python main.py          # uses MODE from config.py
    python main.py line     # force line-crossing mode
    python main.py room     # force room-occupancy mode
"""

import logging
import signal
import sys

import config
from mqtt_client import MQTTPublisher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else config.MODE

    topic = (
        f"wiut/{config.SITE}/{config.BUILDING}/{config.FLOOR}/"
        f"{config.ROOM}/{config.DEVICE_TYPE}/{config.DEVICE_ID}/telemetry"
    )
    logger.info("CV People Counter starting")
    logger.info("  mode     : %s", mode)
    logger.info("  device   : %s", config.DEVICE_ID)
    logger.info("  topic    : %s", topic)
    logger.info("  model    : %s  confidence=%.2f", config.YOLO_MODEL, config.CONFIDENCE)

    mqtt = MQTTPublisher()
    mqtt.connect()

    def _shutdown(sig, frame):
        logger.info("Shutdown signal received — disconnecting cleanly …")
        mqtt.disconnect()
        sys.exit(0)

    signal.signal(signal.SIGINT,  _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        if mode == "line":
            from line_counter import LineCrossingCounter
            LineCrossingCounter(mqtt).run()
        elif mode == "room":
            from room_counter import RoomOccupancyCounter
            RoomOccupancyCounter(mqtt).run()
        else:
            logger.error("Unknown mode '%s'. Use 'line' or 'room'.", mode)
            sys.exit(1)
    finally:
        mqtt.disconnect()


if __name__ == "__main__":
    main()
