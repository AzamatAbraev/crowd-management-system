#include <ESP8266WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <time.h>

const char* DEVICE_ID  = "esp8266_real_device";
const char* FIRMWARE   = "2.1.0";
const char* SITE       = "main_campus";
const char* BUILDING   = "library";
const char* FLOOR      = "floor_1";
const char* ROOM       = "113";

const char* WIFI_SSID   = "****";
const char* WIFI_PASS   = "****";
const char* MQTT_SERVER = "172.16.16.211"; //need to adjust ip accordingly
const int   MQTT_PORT   = 1883;

char topicTelemetry[128];
char topicStatus[128];

const int TRIG1 = 5;   // D1 — outer sensor
const int ECHO1 = 4;   // D2
const int TRIG2 = 12;  // D5 — inner sensor
const int ECHO2 = 14;  // D6

const int           THRESHOLD_CM  = 30;
const unsigned long TIMEOUT_MS    = 2000;
const unsigned long COOLDOWN_MS   = 800;
const unsigned long SENSOR_GAP_MS = 60;

enum State { IDLE, ENTRY_S1_TRIGGERED, EXIT_S2_TRIGGERED };
State state = IDLE;

int           localCount    = 0;
unsigned long triggerTime   = 0;
unsigned long cooldownUntil = 0;
int           seqNumber     = 0;

WiFiClient   espClient;
PubSubClient mqttClient(espClient);

void syncTime() {
  configTime(0, 0, "pool.ntp.org", "time.nist.gov");
  Serial.print("Syncing NTP");
  time_t now = time(nullptr);
  while (now < 1000000000UL) {
    delay(200);
    Serial.print(".");
    now = time(nullptr);
  }
  Serial.println(" OK");
}

void getTimestampISO(char* buf, size_t len) {
  time_t now = time(nullptr);
  struct tm* t = gmtime(&now);
  strftime(buf, len, "%Y-%m-%dT%H:%M:%S.000Z", t);
}

void setupWifi() {
  Serial.print("\nConnecting to WiFi: ");
  Serial.println(WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.print("\nWiFi connected. IP: ");
  Serial.println(WiFi.localIP());
}

void publishBirth() {
  char tsISO[32];
  getTimestampISO(tsISO, sizeof(tsISO));

  StaticJsonDocument<256> doc;
  doc["v"]              = 1;
  doc["device_id"]      = DEVICE_ID;
  doc["type"]           = "birth";
  doc["status"]         = "online";
  doc["firmware"]       = FIRMWARE;
  doc["timestamp_iso"]  = tsISO;
  doc["timestamp_unix"] = (unsigned long)time(nullptr);

  char buf[256];
  serializeJson(doc, buf);
  mqttClient.publish(topicStatus, buf, true);  // retained
  Serial.print("Birth: "); Serial.println(buf);
}

void publishTelemetry(int delta) {
  char tsISO[32];
  getTimestampISO(tsISO, sizeof(tsISO));

  StaticJsonDocument<320> doc;
  doc["v"]              = 1;
  doc["device_id"]      = DEVICE_ID;
  doc["type"]           = "telemetry";
  doc["seq"]            = ++seqNumber;
  doc["timestamp_iso"]  = tsISO;
  doc["timestamp_unix"] = (unsigned long)time(nullptr);

  JsonObject payload     = doc.createNestedObject("payload");
  payload["direction"]   = (delta > 0) ? "entry" : "exit";
  payload["count_delta"] = delta;
  payload["misfire"]     = false;

  JsonObject meta  = doc.createNestedObject("meta");
  meta["firmware"] = FIRMWARE;
  meta["rssi"]     = (int)WiFi.RSSI();
  meta["uptime_s"] = (unsigned long)(millis() / 1000);

  char buf[320];
  serializeJson(doc, buf);

  if (mqttClient.publish(topicTelemetry, buf)) {
    Serial.print("Telemetry: "); Serial.println(buf);
  } else {
    Serial.println("MQTT publish failed!");
  }
}

void reconnect() {
  char tsISO[32];
  getTimestampISO(tsISO, sizeof(tsISO));

  StaticJsonDocument<256> lwtDoc;
  lwtDoc["v"]              = 1;
  lwtDoc["device_id"]      = DEVICE_ID;
  lwtDoc["type"]           = "death";
  lwtDoc["status"]         = "offline";
  lwtDoc["reason"]         = "unexpected_disconnect";
  lwtDoc["timestamp_iso"]  = tsISO;
  lwtDoc["timestamp_unix"] = (unsigned long)time(nullptr);

  char lwtBuf[256];
  serializeJson(lwtDoc, lwtBuf);

  while (!mqttClient.connected()) {
    Serial.print("Connecting to MQTT... ");
    if (mqttClient.connect(DEVICE_ID, nullptr, nullptr, topicStatus, 1, true, lwtBuf)) {
      Serial.println("connected.");
      publishBirth();
    } else {
      Serial.print("failed, rc=");
      Serial.print(mqttClient.state());
      Serial.println(". Retrying in 5s...");
      delay(5000);
    }
  }
}

float getDistance(int trig, int echo) {
  digitalWrite(trig, LOW);
  delayMicroseconds(2);
  digitalWrite(trig, HIGH);
  delayMicroseconds(10);
  digitalWrite(trig, LOW);
  long duration = pulseIn(echo, HIGH, 25000);
  if (duration == 0) return 999.0f;
  return duration * 0.034f / 2.0f;
}

float getStableDistance(int trig, int echo) {
  float d1 = getDistance(trig, echo);
  delay(10);
  float d2 = getDistance(trig, echo);
  return (d1 + d2) / 2.0f;
}

void setup() {
  Serial.begin(115200);

  pinMode(TRIG1, OUTPUT); pinMode(ECHO1, INPUT);
  pinMode(TRIG2, OUTPUT); pinMode(ECHO2, INPUT);

  snprintf(topicTelemetry, sizeof(topicTelemetry),
    "wiut/%s/%s/%s/%s/ultrasonic/%s/telemetry",
    SITE, BUILDING, FLOOR, ROOM, DEVICE_ID);
  snprintf(topicStatus, sizeof(topicStatus),
    "wiut/%s/%s/%s/%s/ultrasonic/%s/status",
    SITE, BUILDING, FLOOR, ROOM, DEVICE_ID);

  setupWifi();
  syncTime();

  mqttClient.setServer(MQTT_SERVER, MQTT_PORT);
  mqttClient.setBufferSize(512); 

  Serial.println("\n--- People Counter Active ---");
  Serial.print("Telemetry: "); Serial.println(topicTelemetry);
  Serial.print("Status:    "); Serial.println(topicStatus);
}

void loop() {
  if (!mqttClient.connected()) reconnect();
  mqttClient.loop();

  if (millis() < cooldownUntil) return;

  float d1 = getStableDistance(TRIG1, ECHO1);
  delay(SENSOR_GAP_MS);
  float d2 = getStableDistance(TRIG2, ECHO2);

  unsigned long now = millis();

  switch (state) {
    case IDLE:
      if (d1 < THRESHOLD_CM) {
        state = ENTRY_S1_TRIGGERED;
        triggerTime = now;
        Serial.println("Outer sensor triggered");
      } else if (d2 < THRESHOLD_CM) {
        state = EXIT_S2_TRIGGERED;
        triggerTime = now;
        Serial.println("Inner sensor triggered");
      }
      break;

    case ENTRY_S1_TRIGGERED:
      if (d2 < THRESHOLD_CM) {
        localCount++;
        Serial.print(">>> ENTRY. Local count: "); Serial.println(localCount);
        publishTelemetry(1);
        state = IDLE;
        cooldownUntil = now + COOLDOWN_MS;
      } else if (now - triggerTime > TIMEOUT_MS) {
        state = IDLE;
      }
      break;

    case EXIT_S2_TRIGGERED:
      if (d1 < THRESHOLD_CM) {
        if (localCount > 0) localCount--;
        Serial.print("<<< EXIT. Local count: "); Serial.println(localCount);
        publishTelemetry(-1);
        state = IDLE;
        cooldownUntil = now + COOLDOWN_MS;
      } else if (now - triggerTime > TIMEOUT_MS) {
        state = IDLE;
      }
      break;
  }
}
