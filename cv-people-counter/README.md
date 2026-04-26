# CV People Counter

A Python application that uses a camera and YOLOv8 object detection to count people and publish results over MQTT. It uses the same payload schema as the ESP8266 hardware sensors, so the existing backend processes camera events without modification.

## Operating Modes

| Mode | Use case |
|---|---|
| `line` | Doorway / entrance — counts entries and exits as people cross a virtual line |
| `room` | Whole room overhead — estimates current occupancy from all visible people |

## Current Deployment Note

> **This application is currently being tested on the Windows side of the development machine, not run directly from WSL.**
> The code in this directory is for reference. The active instance runs natively on Windows, connecting to the MQTT broker at the WSL2 IP (`172.26.164.80:1883`) which is reachable directly from Windows via the WSL2 virtual network adapter.

## Prerequisites

- Python 3.10+
- A connected USB or IP camera
- A running MQTT broker (Mosquitto)
- The crowd-management-api backend reachable

### Install dependencies

```bash
cd cv-people-counter
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

| Package | Purpose |
|---|---|
| `ultralytics>=8.0.0` | YOLOv8 model + ByteTrack tracker |
| `opencv-python>=4.8.0` | Camera capture and preview window |
| `paho-mqtt>=2.0.0` | MQTT publish/subscribe |
| `numpy>=1.24.0` | Array operations |

## Running

```bash
python main.py          # uses MODE from config.py
python main.py line     # force line-crossing mode
python main.py room     # force room-occupancy mode
```

Press **Q** in the preview window or **Ctrl+C** to quit. The application publishes an offline status message before exiting.

## Configuration

All settings live in `config.py`. Edit this file before running.

### 1. MQTT Settings

```python
MQTT_NAMESPACE   = "wiut"
MQTT_BROKER_HOST = "172.26.164.80"
MQTT_BROKER_PORT = 1883
```

| Parameter | Description |
|---|---|
| `MQTT_NAMESPACE` | Top-level topic prefix. Must match the backend subscription pattern. |
| `MQTT_BROKER_HOST` | IP or hostname of the MQTT broker. |
| `MQTT_BROKER_PORT` | Default `1883` (unencrypted). |

### 2. Device Identity

These values shape the MQTT topic:

```
wiut/{SITE}/{BUILDING}/{FLOOR}/{ROOM}/{DEVICE_TYPE}/{DEVICE_ID}/telemetry
```

```python
DEVICE_ID   = "camera_01"
DEVICE_TYPE = "camera"
FIRMWARE    = "cv-1.0.0"
SITE        = "main_campus"
BUILDING    = "library"
FLOOR       = "floor_1"
ROOM        = "entrance"
```

- `DEVICE_ID` must be unique across all devices (cameras and ESP8266s).
- `SITE`, `BUILDING`, `FLOOR`, and `ROOM` must match location records in the backend database exactly (case-sensitive).
- `DEVICE_TYPE` should remain `"camera"`.

### 3. Camera Settings

```python
CAMERA_INDEX = 0
FRAME_WIDTH  = 640
FRAME_HEIGHT = 480
```

`CAMERA_INDEX` is the OpenCV camera index — `0` is the first camera, `1` the second, and so on.

For IP cameras, replace the `VideoCapture` call in `line_counter.py` / `room_counter.py` with an RTSP URL:

```python
cap = cv2.VideoCapture("rtsp://user:pass@192.168.1.100/stream")
```

### 4. Detection Model

```python
YOLO_MODEL = "yolov8s.pt"
CONFIDENCE = 0.40
```

| Model | Speed | Accuracy | Recommended for |
|---|---|---|---|
| `yolov8n.pt` | Fastest | Lowest | Low-power hardware (Raspberry Pi) |
| `yolov8s.pt` | Fast | Good | Most deployments (default) |
| `yolov8m.pt` | Moderate | Better | High-accuracy requirements |
| `yolov8l.pt` | Slow | High | Server-class hardware only |

Model files are downloaded automatically on first run. `yolov8n.pt` and `yolov8s.pt` are already included in the repository.

`CONFIDENCE` is the detection threshold (0.0–1.0). Lower values detect more people but produce more false positives; higher values are more precise but may miss partially visible people.

### 5. Line-Crossing Settings (`MODE = "line"`)

```python
LINE_RATIO       = 0.5
CROSSING_BUFFER  = 25
CROSS_COOLDOWN_S = 3.0
ENTRY_DIRECTION  = "top_to_bottom"
```

| Parameter | Description |
|---|---|
| `LINE_RATIO` | Position of the counting line as a fraction of frame height. `0.0` = top, `0.5` = middle, `1.0` = bottom. |
| `CROSSING_BUFFER` | Dead-band in pixels around the line. Prevents oscillation when someone pauses in the doorway. Increase to `40` if you see double-counts; decrease to `10` if slow-movers are missed. |
| `CROSS_COOLDOWN_S` | Minimum seconds before the same tracked person can trigger another crossing. Set to `0` to disable. |
| `ENTRY_DIRECTION` | `"top_to_bottom"` — moving down = entry (corridor at top of frame). `"bottom_to_top"` — moving up = entry (flip if camera faces the other way). |

### 6. Room-Occupancy Settings (`MODE = "room"`)

```python
SMOOTHING_FRAMES   = 5
PUBLISH_INTERVAL_S = 5
```

| Parameter | Description |
|---|---|
| `SMOOTHING_FRAMES` | Moving-average window size. Increase for a more stable reading; decrease for faster reaction to changes. |
| `PUBLISH_INTERVAL_S` | How often the current occupancy is published to MQTT, even when unchanged. |

### 7. Display Settings

```python
SHOW_PREVIEW = True
WINDOW_NAME  = "CV People Counter"
```

Set `SHOW_PREVIEW = False` to run headless on a server without a display.

## MQTT Payload Format

The camera publishes the same schema as ESP8266 hardware sensors:

```json
{
  "v": 1,
  "device_id": "camera_01",
  "type": "telemetry",
  "seq": 7,
  "timestamp_iso": "2026-04-25T10:00:05.123Z",
  "timestamp_unix": 1745575205.123,
  "payload": {
    "direction": "entry",
    "count_delta": 1,
    "misfire": false
  },
  "meta": {
    "firmware": "cv-1.0.0",
    "rssi": 0,
    "uptime_s": 42
  }
}
```

- In `line` mode, `count_delta` is `+1` (entry) or `-1` (exit).
- In `room` mode, `count_delta` is the difference from the previously published occupancy count.

## References & Acknowledgements

No external source code was directly copied into this project. The implementation is original but is built on the APIs, models, and patterns of the following:

| # | Name | What it provides | Link |
|---|---|---|---|
| 1 | **Ultralytics YOLOv8** | YOLO model loading, inference, and the `model.track()` API used for per-frame person detection | https://github.com/ultralytics/ultralytics |
| 2 | **ByteTrack** | Multi-object tracking algorithm (integrated into Ultralytics via `tracker="bytetrack.yaml"`). Original paper: *ByteTrack: Multi-Object Tracking by Associating Every Detection Box*, Zhang et al., ECCV 2022 | https://github.com/ifzhang/ByteTrack |
| 3 | **Eclipse Paho MQTT Python Client** | MQTT publish/subscribe client (`paho.mqtt.client`) used in `mqtt_client.py` | https://github.com/eclipse/paho.mqtt.python |
| 4 | **OpenCV** | Camera capture (`VideoCapture`), frame drawing primitives, and preview window | https://github.com/opencv/opencv |

The virtual-line zone logic (above/below hysteresis buffer, track-state dict) and the MQTT payload schema are written from scratch to match the ESP8266 sensor format used by the rest of the system.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `Cannot open camera 0` | Wrong index or camera in use | Change `CAMERA_INDEX` or close other apps using the camera |
| No people detected | `CONFIDENCE` too high, wrong model, poor lighting | Lower `CONFIDENCE` to `0.30`; try `yolov8n.pt` |
| Double-counting at the door | `CROSSING_BUFFER` or `CROSS_COOLDOWN_S` too low | Set `CROSSING_BUFFER = 40` and `CROSS_COOLDOWN_S = 5.0` |
| MQTT connection refused | Wrong broker IP or broker not running | Check `MQTT_BROKER_HOST` and verify Mosquitto is running |
| Occupancy count lags | `SMOOTHING_FRAMES` too large | Reduce to `2` or `3` |
| No preview window on server | No display environment | Set `SHOW_PREVIEW = False` |

## Quick-Start Checklist

- [ ] Set `MQTT_BROKER_HOST` to your broker's IP address
- [ ] Set `DEVICE_ID` to a unique value not used by any other device
- [ ] Set `SITE`, `BUILDING`, `FLOOR`, `ROOM` to match the location in the backend
- [ ] Set `CAMERA_INDEX` to the correct camera
- [ ] Choose `MODE`: `"line"` for a doorway, `"room"` for whole-room overhead
- [ ] If `line` mode: verify `ENTRY_DIRECTION` matches your camera orientation
- [ ] Set `SHOW_PREVIEW = False` if running on a headless server
- [ ] Run `python main.py` and confirm telemetry appears in the backend dashboard
