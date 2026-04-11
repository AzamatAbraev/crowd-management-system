# Crowd Management System

A real-time occupancy monitoring platform for university campuses. IoT sensors deployed at room entrances detect people entering and exiting, publish events over MQTT, and feed a live dashboard showing occupancy across buildings and floors.

## Repositories

| Component | Repository |
|---|---|
| API | [crowd-management-api](https://github.com/AzamatAbraev/crowd-management-api) |
| Gateway | [crowd-management-gateway](https://github.com/AzamatAbraev/crowd-management-gateway) |
| Frontend | [crowd-management-ui](https://github.com/AzamatAbraev/crowd-management-ui) |
| IoT Simulator | [crowd-management-iot-simulator](https://github.com/AzamatAbraev/crowd-management-iot-simulator) |

## Getting Started

> [!WARNING]
> Do not clone with the standard `git clone` command. Use `--recurse-submodules` or submodule folders will be empty.

### Prerequisites

- Docker and Docker Compose
- Git

### Clone

```bash
git clone --recurse-submodules git@github.com:AzamatAbraev/crowd-management-system.git
cd crowd-management-system
```

If you already cloned without the flag:

```bash
git submodule update --init --recursive
```

### Start

```bash
bash start-all.sh
```

This starts all services in dependency order. Allow ~60 seconds for Keycloak to initialize on first run.

| URL | Service |
|---|---|
| http://localhost:5173 | Frontend |
| http://localhost:8082 | Gateway |
| http://localhost:8080 | Keycloak Admin |
| http://localhost:3000 | Grafana |

### Stop

```bash
bash stop-all.sh
```

## How It Works

1. **ESP8266 sensors** are mounted in doorways with two ultrasonic sensors. A state machine detects the order of triggers to determine entry vs. exit and publishes a `+1` or `-1` delta over MQTT.

2. **MQTT Broker** (Mosquitto) receives telemetry on topics structured as:
   ```
   wiut/{site}/{building}/{floor}/{room}/ultrasonic/{device_id}/telemetry
   wiut/{site}/{building}/{floor}/{room}/ultrasonic/{device_id}/status
   ```

3. **API** subscribes to all telemetry and status topics, maintains live occupancy counts per room/floor/building, writes time-series data to InfluxDB, and exposes a REST API.

4. **Gateway** handles OAuth2 login via Keycloak, manages user sessions, and proxies all frontend requests to the API with token relay.

5. **Frontend** polls the API for live counts and renders occupancy views for campus, building, and room levels alongside timetable and historical analytics.

6. **IoT Simulator** can run instead of (or alongside) real hardware, simulating 31 devices with realistic burst, idle, and misfire behaviour for testing.

## MQTT Payload Format

```json
{
  "v": 1,
  "device_id": "esp8266_01",
  "type": "telemetry",
  "seq": 42,
  "timestamp_iso": "2026-04-11T14:30:00.000Z",
  "timestamp_unix": 1744390200,
  "payload": {
    "direction": "entry",
    "count_delta": 1,
    "misfire": false
  },
  "meta": {
    "firmware": "2.1.0",
    "rssi": -65,
    "uptime_s": 3600
  }
}
```

## ESP8266 Firmware

The Arduino sketch is in `people_counter_esp8266/`. Before flashing, update the following constants at the top of the file to match the physical device's location and your network:

```cpp
const char* DEVICE_ID  = "esp8266_real_device";   // must match a device in the simulator config
const char* SITE       = "main_campus";
const char* BUILDING   = "library";
const char* FLOOR      = "floor_1";
const char* ROOM       = "113";

const char* WIFI_SSID   = "your_ssid";
const char* WIFI_PASS   = "your_password";
const char* MQTT_SERVER = "your_broker_ip";
```

Required Arduino libraries: `ESP8266WiFi`, `PubSubClient`, `ArduinoJson`.

## Roles

| Role | Access |
|---|---|
| `theking` | Full admin + Grafana admin |
| `system_admin` | System administration |
| `facility_manager` | Device and building management |
| `standard_viewer` | View occupancy and analytics |

Roles are configured in Keycloak and imported automatically from `keycloak-docker/realm-export.json` on first start.
