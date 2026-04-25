# ── MQTT ─────────────────────────────────────────────────────────────────────
MQTT_NAMESPACE   = "wiut"
MQTT_BROKER_HOST = "172.26.164.80"
MQTT_BROKER_PORT = 1883

# ── Device identity (shapes the MQTT topic) ───────────────────────────────────
# Topic produced: wiut/{SITE}/{BUILDING}/{FLOOR}/{ROOM}/{DEVICE_TYPE}/{DEVICE_ID}/telemetry
DEVICE_ID    = "camera_01"
DEVICE_TYPE  = "camera"
FIRMWARE     = "cv-1.0.0"
SITE         = "main_campus"
BUILDING     = "library"
FLOOR        = "floor_1"
ROOM         = "entrance"        # logical label for the door/zone this camera watches

# ── Camera ────────────────────────────────────────────────────────────────────
CAMERA_INDEX = 0
FRAME_WIDTH  = 640
FRAME_HEIGHT = 480

# ── Detection ─────────────────────────────────────────────────────────────────
# yolov8n.pt = fastest (nano).  yolov8s.pt / yolov8m.pt = more accurate.
# The model file is downloaded automatically on first run.
YOLO_MODEL   = "yolov8s.pt"
CONFIDENCE   = 0.40

# ── Mode ──────────────────────────────────────────────────────────────────────
# "line" — entrance door: counts entries/exits as people cross a virtual line
# "room" — whole room:    estimates current occupancy from all visible people
MODE = "room"

# ── Line-crossing settings (used when MODE = "line") ─────────────────────────
# LINE_RATIO: position of the counting line as a fraction of frame height.
#   0.0 = very top of frame   |   1.0 = very bottom   |   0.5 = middle (default)
LINE_RATIO      = 0.5

# Buffer band (pixels) around the line — person must be this far past the line
# before the crossing is registered.  Prevents oscillation when someone pauses.
CROSSING_BUFFER = 25

# Minimum seconds that must pass before the same track ID can trigger a second
# crossing event.  Prevents a person lingering near the line from being counted
# multiple times due to centroid jitter.  Set to 0 to disable.
CROSS_COOLDOWN_S = 3.0

# ENTRY_DIRECTION: which crossing direction counts as "entry".
#   "top_to_bottom" — person moves from top half toward bottom half = entry
#                     (use this when the corridor is at the top of the frame)
#   "bottom_to_top" — person moves from bottom toward top = entry
#                     (flip if your camera faces the other way)
ENTRY_DIRECTION = "top_to_bottom"

# ── Room-occupancy settings (used when MODE = "room") ────────────────────────
SMOOTHING_FRAMES   = 5           # moving-average window to reduce per-frame flicker
PUBLISH_INTERVAL_S = 5           # publish current count every N seconds regardless of change

# ── Display ───────────────────────────────────────────────────────────────────
SHOW_PREVIEW = True
WINDOW_NAME  = "CV People Counter"
