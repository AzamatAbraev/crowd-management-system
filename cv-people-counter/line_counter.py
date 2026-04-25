"""
Line-crossing people counter — entrance/exit door mode.

Camera looks at a doorway (ideally top-down or angled).
A horizontal counting line is drawn across the frame at LINE_RATIO * frame_height.
YOLOv8 detects persons; ByteTrack assigns stable IDs across frames.
When a tracked person's centroid crosses the line it triggers an entry or exit event
and immediately publishes one MQTT telemetry message (delta = +1 or -1).

State machine per track_id
───────────────────────────
  first seen below line  →  state = "below"  (no event)
  first seen above line  →  state = "above"  (no event)
  "above" → "below"      →  ENTRY event  (if ENTRY_DIRECTION = "top_to_bottom")
  "below" → "above"      →  EXIT  event  (if ENTRY_DIRECTION = "top_to_bottom")

A ±CROSSING_BUFFER pixel band around the line acts as hysteresis: while the centroid
is inside the band the state does not change, preventing oscillation when someone
pauses in the doorway.
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

        # Discard the first several frames — camera sensor needs time to adjust exposure
        logger.info("Warming up camera …")
        for _ in range(20):
            cap.read()

        logger.info("Line-crossing counter started  (press Q in preview window to quit)")

        try:
            while True:
                ok, frame = cap.read()
                if not ok:
                    time.sleep(0.05)
                    continue

                h, w   = frame.shape[:2]
                line_y = int(h * config.LINE_RATIO)
                buf    = config.CROSSING_BUFFER

                # Run detection + ByteTrack tracking
                results = self.model.track(
                    frame,
                    persist=True,
                    classes=[0],               # class 0 = person (COCO)
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

                        # Resolve current zone (buffer band keeps previous state)
                        if cy < line_y - buf:
                            zone: str = "above"
                        elif cy > line_y + buf:
                            zone = "below"
                        else:
                            zone = self._states.get(tid, "above")  # stay put while in band

                        prev = self._states.get(tid)
                        if prev is not None and zone != prev:
                            self._on_crossing(tid, prev, zone)
                        self._states[tid] = zone

                        # Draw bounding box + centroid
                        color = _C_ABOVE if zone == "above" else _C_BELOW
                        x1, y1, x2, y2 = map(int, box)
                        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                        cv2.circle(frame, (cx, cy), 5, color, -1)
                        cv2.putText(frame, f"ID {tid}", (x1, y1 - 8),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)

                # Remove state entries for tracks that have left the frame
                for tid in list(self._states):
                    if tid not in active_ids:
                        del self._states[tid]
                        self._last_cross.pop(tid, None)

                if config.SHOW_PREVIEW:
                    self._draw_ui(frame, h, w, line_y, buf)
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

        if config.ENTRY_DIRECTION == "top_to_bottom":
            is_entry = (prev == "above" and curr == "below")
        else:
            is_entry = (prev == "below" and curr == "above")

        if is_entry:
            self.entry_count += 1
            logger.info("ENTRY  | entries=%d  exits=%d", self.entry_count, self.exit_count)
            self.mqtt.publish_telemetry(delta=+1)
        else:
            self.exit_count += 1
            logger.info("EXIT   | entries=%d  exits=%d", self.entry_count, self.exit_count)
            self.mqtt.publish_telemetry(delta=-1)

    # ── Preview drawing ───────────────────────────────────────────────────────

    def _draw_ui(self, frame, h, w, line_y, buf):
        self._fps_buf.append(time.time())
        fps = 0.0
        if len(self._fps_buf) > 1:
            fps = (len(self._fps_buf) - 1) / (self._fps_buf[-1] - self._fps_buf[0])

        # Counting line + hysteresis band
        cv2.line(frame, (0, line_y),       (w, line_y),       _C_LINE,   2)
        cv2.line(frame, (0, line_y - buf), (w, line_y - buf), _C_BUFFER, 1)
        cv2.line(frame, (0, line_y + buf), (w, line_y + buf), _C_BUFFER, 1)

        # Direction arrow on the line
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
