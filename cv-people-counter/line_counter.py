"""
Line-crossing people counter — entrance/exit door or corridor/path mode.

Supports two line orientations (LINE_ORIENTATION in config.py):

  "horizontal" — line spans the full frame width (top-down doorway camera).
      Zones: "above" / "below".  Entry direction: top_to_bottom or bottom_to_top.

  "vertical"   — line spans the full frame height (side-view corridor camera).
      Zones: "left" / "right".   Entry direction: left_to_right or right_to_left.

YOLOv8 detects persons; ByteTrack assigns stable IDs across frames.
When a tracked person's centroid crosses the line it triggers an entry or exit event
and immediately publishes one MQTT telemetry message (delta = +1 or -1).

A ±CROSSING_BUFFER pixel band around the line acts as hysteresis: while the centroid
is inside the band the state does not change, preventing oscillation when someone
pauses at the line.
"""

import logging
import sys
import time
from collections import deque
from typing import Dict, Tuple

import cv2
import numpy as np
from ultralytics import YOLO

import config
from mqtt_client import MQTTPublisher

logger = logging.getLogger(__name__)

# BGR colours used in the preview window
_C_LINE    = (0,  220,   0)   # green  — counting line
_C_BUFFER  = (0,  180, 255)   # orange — hysteresis band
_C_ABOVE   = (0,  255,   0)   # green  — box for person above line
_C_BELOW   = (0,   80, 255)   # red    — box for person below line
_C_TEXT    = (255, 255, 255)  # white
_C_BG      = (0,    0,   0)   # black  — overlay background


def _centroid(box: np.ndarray) -> Tuple[int, int]:
    x1, y1, x2, y2 = box
    return int((x1 + x2) / 2), int((y1 + y2) / 2)


class LineCrossingCounter:
    def __init__(self, mqtt: MQTTPublisher):
        self.mqtt        = mqtt
        self.model       = YOLO(config.YOLO_MODEL)
        self.entry_count = 0
        self.exit_count  = 0
        self._states: Dict[int, str] = {}        # track_id → "above" | "below"
        self._last_cross: Dict[int, float] = {}  # track_id → timestamp of last crossing
        self._fps_buf: deque = deque(maxlen=30)

    def run(self):
        backend = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY
        cap = cv2.VideoCapture(config.CAMERA_INDEX, backend)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH,  config.FRAME_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.FRAME_HEIGHT)

        if not cap.isOpened():
            raise RuntimeError(f"Cannot open camera {config.CAMERA_INDEX}")

        vertical = (config.LINE_ORIENTATION == "vertical")

        # Discard the first several frames — camera sensor needs time to adjust exposure
        logger.info("Warming up camera …")
        for _ in range(20):
            cap.read()

        logger.info("Line-crossing counter started  orientation=%s  (press Q to quit)",
                    config.LINE_ORIENTATION)

        try:
            while True:
                ok, frame = cap.read()
                if not ok:
                    time.sleep(0.05)
                    continue

                h, w = frame.shape[:2]
                buf  = config.CROSSING_BUFFER

                # Line position in pixels
                line_x = int(w * config.LINE_RATIO) if vertical else None
                line_y = int(h * config.LINE_RATIO) if not vertical else None

                results = self.model.track(
                    frame,
                    persist=True,
                    classes=[0],
                    conf=config.CONFIDENCE,
                    tracker="bytetrack.yaml",
                    verbose=False,
                )

                active_ids: set = set()

                if results[0].boxes.id is not None:
                    boxes     = results[0].boxes.xyxy.cpu().numpy()
                    track_ids = results[0].boxes.id.cpu().numpy().astype(int)

                    for box, tid in zip(boxes, track_ids):
                        cx, cy = _centroid(box)
                        active_ids.add(tid)

                        # Resolve zone — buffer band keeps the previous state (hysteresis)
                        if vertical:
                            if cx < line_x - buf:
                                zone: str = "left"
                            elif cx > line_x + buf:
                                zone = "right"
                            else:
                                zone = self._states.get(tid, "left")
                        else:
                            if cy < line_y - buf:
                                zone = "above"
                            elif cy > line_y + buf:
                                zone = "below"
                            else:
                                zone = self._states.get(tid, "above")

                        prev = self._states.get(tid)
                        if prev is not None and zone != prev:
                            self._on_crossing(tid, prev, zone)
                        self._states[tid] = zone

                        # Colour by zone
                        if vertical:
                            color = _C_ABOVE if zone == "left" else _C_BELOW
                        else:
                            color = _C_ABOVE if zone == "above" else _C_BELOW

                        x1, y1, x2, y2 = map(int, box)
                        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                        cv2.circle(frame, (cx, cy), 5, color, -1)
                        cv2.putText(frame, f"ID {tid}", (x1, y1 - 8),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)

                for tid in list(self._states):
                    if tid not in active_ids:
                        del self._states[tid]
                        self._last_cross.pop(tid, None)

                if config.SHOW_PREVIEW:
                    self._draw_ui(frame, h, w, line_x, line_y, buf)
                    cv2.imshow(config.WINDOW_NAME, frame)
                    if cv2.waitKey(1) & 0xFF == ord('q'):
                        break
        finally:
            cap.release()
            cv2.destroyAllWindows()

    # ── Event handling ────────────────────────────────────────────────────────

    def _on_crossing(self, tid: int, prev: str, curr: str):
        """Called on every state transition — guards against jitter via cooldown."""
        now = time.time()
        last = self._last_cross.get(tid, 0.0)
        if config.CROSS_COOLDOWN_S > 0 and (now - last) < config.CROSS_COOLDOWN_S:
            logger.debug("Crossing ignored (cooldown) | tid=%d | %.1fs since last", tid, now - last)
            return

        self._last_cross[tid] = now

        direction = config.ENTRY_DIRECTION
        if direction == "top_to_bottom":
            is_entry = (prev == "above" and curr == "below")
        elif direction == "bottom_to_top":
            is_entry = (prev == "below" and curr == "above")
        elif direction == "left_to_right":
            is_entry = (prev == "left" and curr == "right")
        else:  # right_to_left
            is_entry = (prev == "right" and curr == "left")

        if is_entry:
            self.entry_count += 1
            logger.info("ENTRY  | entries=%d  exits=%d", self.entry_count, self.exit_count)
            self.mqtt.publish_telemetry(delta=+1)
        else:
            self.exit_count += 1
            logger.info("EXIT   | entries=%d  exits=%d", self.entry_count, self.exit_count)
            self.mqtt.publish_telemetry(delta=-1)

    # ── Preview drawing ───────────────────────────────────────────────────────

    def _draw_ui(self, frame, h, w, line_x, line_y, buf):
        self._fps_buf.append(time.time())
        fps = 0.0
        if len(self._fps_buf) > 1:
            fps = (len(self._fps_buf) - 1) / (self._fps_buf[-1] - self._fps_buf[0])

        if config.LINE_ORIENTATION == "vertical":
            # Vertical counting line + hysteresis band
            cv2.line(frame, (line_x,       0), (line_x,       h), _C_LINE,   2)
            cv2.line(frame, (line_x - buf, 0), (line_x - buf, h), _C_BUFFER, 1)
            cv2.line(frame, (line_x + buf, 0), (line_x + buf, h), _C_BUFFER, 1)

            label = "→ ENTRY" if config.ENTRY_DIRECTION == "left_to_right" else "← ENTRY"
            cv2.putText(frame, label, (line_x + 8, h // 2),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.65, _C_LINE, 2)
        else:
            # Horizontal counting line + hysteresis band
            cv2.line(frame, (0, line_y),       (w, line_y),       _C_LINE,   2)
            cv2.line(frame, (0, line_y - buf), (w, line_y - buf), _C_BUFFER, 1)
            cv2.line(frame, (0, line_y + buf), (w, line_y + buf), _C_BUFFER, 1)

            label = "↓ ENTRY" if config.ENTRY_DIRECTION == "top_to_bottom" else "↑ ENTRY"
            cv2.putText(frame, label, (w // 2 - 45, line_y - 12),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.65, _C_LINE, 2)

        # Semi-transparent stats panel
        panel = frame.copy()
        cv2.rectangle(panel, (0, 0), (270, 115), _C_BG, -1)
        cv2.addWeighted(panel, 0.45, frame, 0.55, 0, frame)

        cv2.putText(frame, f"ENTRIES : {self.entry_count}", (10,  35),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.85, _C_ABOVE, 2)
        cv2.putText(frame, f"EXITS   : {self.exit_count}",  (10,  72),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.85, _C_BELOW, 2)
        cv2.putText(frame, f"FPS     : {fps:4.1f}",         (10, 105),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, _C_TEXT,  1)
