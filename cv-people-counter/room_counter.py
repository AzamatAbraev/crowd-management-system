"""
Room-occupancy people counter — whole-room overhead mode.

Camera looks down at the whole room.
YOLOv8 detects all persons visible in each frame.
A moving-average smoother (window = SMOOTHING_FRAMES) reduces flicker caused by
missed detections or partially visible people.
The current count is published to MQTT every PUBLISH_INTERVAL_S seconds regardless
of whether it changed (delta=0 when stable).  It is also published immediately
whenever the count changes between intervals.
"""

import logging
import sys
import time
from collections import deque
from typing import Deque

import cv2
import numpy as np
from ultralytics import YOLO

import config
from mqtt_client import MQTTPublisher

logger = logging.getLogger(__name__)

_C_BOX  = (0,  200, 255)   # cyan — bounding box
_C_TEXT = (255, 255, 255)  # white
_C_BG   = (0,    0,   0)   # black — overlay panel background


class RoomOccupancyCounter:
    def __init__(self, mqtt: MQTTPublisher):
        self.mqtt          = mqtt
        self.model         = YOLO(config.YOLO_MODEL)
        self._window: Deque[int] = deque(maxlen=config.SMOOTHING_FRAMES)
        self._last_count   = 0    # last count published to MQTT
        self._last_publish = 0.0  # timestamp of last publish
        self._fps_buf: deque = deque(maxlen=30)

    def run(self):
        backend = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY
        cap = cv2.VideoCapture(config.CAMERA_INDEX, backend)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH,  config.FRAME_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.FRAME_HEIGHT)

        if not cap.isOpened():
            raise RuntimeError(f"Cannot open camera {config.CAMERA_INDEX}")

        logger.info("Warming up camera …")
        for _ in range(20):
            cap.read()

        logger.info("Room-occupancy counter started  (press Q in preview window to quit)")

        try:
            while True:
                ok, frame = cap.read()
                if not ok:
                    time.sleep(0.05)
                    continue

                results = self.model(
                    frame,
                    classes=[0],            # class 0 = person
                    conf=config.CONFIDENCE,
                    verbose=False,
                )

                raw = len(results[0].boxes)
                self._window.append(raw)
                smoothed = round(sum(self._window) / len(self._window))

                now = time.time()
                if (now - self._last_publish) >= config.PUBLISH_INTERVAL_S:
                    delta = smoothed - self._last_count
                    self.mqtt.publish_telemetry(delta=delta)
                    self._last_count   = smoothed
                    self._last_publish = now
                    logger.info("PUBLISH | occupancy=%d  delta=%+d", smoothed, delta)

                if config.SHOW_PREVIEW:
                    self._draw_ui(frame, results[0].boxes, raw, smoothed)
                    cv2.imshow(config.WINDOW_NAME, frame)
                    if cv2.waitKey(1) & 0xFF == ord('q'):
                        break
        finally:
            cap.release()
            cv2.destroyAllWindows()

    # ── Preview drawing ───────────────────────────────────────────────────────

    def _draw_ui(self, frame, boxes, raw: int, smoothed: int):
        self._fps_buf.append(time.time())
        fps = 0.0
        if len(self._fps_buf) > 1:
            fps = (len(self._fps_buf) - 1) / (self._fps_buf[-1] - self._fps_buf[0])

        for box in boxes.xyxy.cpu().numpy():
            x1, y1, x2, y2 = map(int, box)
            cv2.rectangle(frame, (x1, y1), (x2, y2), _C_BOX, 2)

        panel = frame.copy()
        cv2.rectangle(panel, (0, 0), (290, 115), _C_BG, -1)
        cv2.addWeighted(panel, 0.45, frame, 0.55, 0, frame)

        cv2.putText(frame, f"OCCUPANCY : {smoothed}", (10,  38),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9,  _C_BOX,  2)
        cv2.putText(frame, f"RAW DETECT: {raw}",      (10,  72),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, _C_TEXT, 1)
        cv2.putText(frame, f"FPS       : {fps:4.1f}", (10, 105),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, _C_TEXT, 1)
