/* PORTUS Fase 3 - estación climatológica ESP32.
 * Bibliotecas: PubSubClient, ArduinoJson 7 y DHT sensor library (Adafruit).
 * Configure WiFi, broker, pines, polaridad de lluvia y calibración LDR abajo.
 */
#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <DHT.h>
#include <Preferences.h>
#include <time.h>

// Credenciales de la red local y dirección/IP de la Raspberry con Mosquitto.
const char* WIFI_SSID = "CAMBIAR_NOMBRE_WIFI";
const char* WIFI_PASSWORD = "CAMBIAR_CLAVE_WIFI";
const char* MQTT_HOST = "192.168.1.83";
const uint16_t MQTT_PORT = 1883;
const char* MQTT_USER = "";       // Dejar vacío si el broker no requiere usuario.
const char* MQTT_PASSWORD = "";

// Pines sugeridos para un ESP32 DevKit. Cambiar según el cableado real.
constexpr uint8_t PIN_DHT = 4;
constexpr uint8_t PIN_LDR = 34;    // ADC1: utilizable mientras WiFi está activo.
constexpr uint8_t PIN_RAIN_DO = 27; // DO del comparador YL-83.
constexpr uint8_t DHT_TYPE = DHT22;

// En muchos módulos YL-83 DO va a LOW cuando detecta agua. Invertir si hace falta.
constexpr uint8_t RAIN_LEVEL_WET = LOW;
// Calibrar con lecturas reales de ADC en oscuridad y con la luz máxima esperada.
constexpr int LDR_DARK_ADC = 3500;
constexpr int LDR_BRIGHT_ADC = 500;

constexpr uint32_t DEFAULT_READ_SECONDS = 5;
constexpr uint32_t DEFAULT_HEARTBEAT_SECONDS = 10;
constexpr uint32_t RECONNECT_MS = 5000;
const char* TOPIC_READING = "portus/estacion/lectura";
const char* TOPIC_STATUS = "portus/estacion/estado";
const char* TOPIC_CONFIG = "portus/estacion/config";

WiFiClient network;
PubSubClient mqtt(network);
DHT dht(PIN_DHT, DHT_TYPE);
Preferences preferences;
String stationId;
uint32_t readSeconds = DEFAULT_READ_SECONDS;
uint32_t heartbeatSeconds = DEFAULT_HEARTBEAT_SECONDS;
uint32_t lastRead = 0;
uint32_t lastHeartbeat = 0;
uint32_t lastReconnectAttempt = 0;
uint32_t lastWifiAttempt = 0;
float lastTemperature = NAN;
float lastHumidity = NAN;
int lastLight = -1;
bool lastRain = false;
bool hasReading = false;

String timestampISO() {
  struct tm now;
  if (!getLocalTime(&now, 20)) return "";
  char value[32];
  // Zona civil configurada abajo como UTC-06:00 (Guatemala).
  strftime(value, sizeof(value), "%Y-%m-%dT%H:%M:%S-06:00", &now);
  return String(value);
}

int readLightPercent() {
  int raw = analogRead(PIN_LDR);
  int low = min(LDR_DARK_ADC, LDR_BRIGHT_ADC);
  int high = max(LDR_DARK_ADC, LDR_BRIGHT_ADC);
  raw = constrain(raw, low, high);
  int percent = map(raw, LDR_DARK_ADC, LDR_BRIGHT_ADC, 0, 100);
  return constrain(percent, 0, 100);
}

void fillEnvelope(JsonDocument& doc, const char* type) {
  doc["id"] = stationId + "-" + String((uint32_t)millis());
  String stamp = timestampISO();
  if (stamp.length()) doc["timestamp"] = stamp;
  doc["origin"] = stationId;
  doc["type"] = type;
  JsonObject data = doc["data"].to<JsonObject>();
  data["estacion_id"] = stationId;
}

void publishReading() {
  // DHT22 puede fallar una muestra; no publicar datos incompletos ni inventados.
  float temperature = dht.readTemperature();
  float humidity = dht.readHumidity();
  if (isnan(temperature) || isnan(humidity)) {
    Serial.println("DHT22: lectura inválida; se conserva la última lectura válida.");
    return;
  }
  lastTemperature = temperature;
  lastHumidity = humidity;
  lastLight = readLightPercent();
  lastRain = digitalRead(PIN_RAIN_DO) == RAIN_LEVEL_WET;
  hasReading = true;

  JsonDocument doc;
  fillEnvelope(doc, "LECTURA");
  JsonObject data = doc["data"].as<JsonObject>();
  data["temperatura"] = lastTemperature;
  data["humedad"] = lastHumidity;
  data["lluvia"] = lastRain;
  data["luz"] = lastLight;
  char payload[256];
  size_t n = serializeJson(doc, payload, sizeof(payload));
  if (mqtt.connected() && n > 0) {
    mqtt.publish(TOPIC_READING, (const uint8_t*)payload, n, false);
    Serial.println(payload);
  }
}

void publishHeartbeat() {
  JsonDocument doc;
  fillEnvelope(doc, "ESTADO");
  JsonObject data = doc["data"].as<JsonObject>();
  data["estado"] = WiFi.status() == WL_CONNECTED && mqtt.connected() ? "OPERATIVA" : "DESCONECTADA";
  data["wifi"] = WiFi.status() == WL_CONNECTED;
  data["mqtt"] = mqtt.connected();
  data["lectura_disponible"] = hasReading;
  if (hasReading) {
    data["temperatura"] = lastTemperature;
    data["humedad"] = lastHumidity;
    data["lluvia"] = lastRain;
    data["luz"] = lastLight;
  }
  char payload[320];
  size_t n = serializeJson(doc, payload, sizeof(payload));
  if (mqtt.connected() && n > 0) mqtt.publish(TOPIC_STATUS, (const uint8_t*)payload, n, false);
}

void onMqttMessage(char* topic, byte* payload, unsigned int length) {
  if (String(topic) != TOPIC_CONFIG || length == 0 || length > 512) return;
  JsonDocument doc;
  if (deserializeJson(doc, payload, length)) return;
  JsonObject data = doc["data"].as<JsonObject>();
  if (data.isNull()) data = doc.as<JsonObject>();
  uint32_t read = data["SegundosLecturaEstacion"] | readSeconds;
  uint32_t beat = data["SegundosLatidoEstacion"] | heartbeatSeconds;
  readSeconds = constrain(read, 2, 60);
  heartbeatSeconds = constrain(beat, 5, 60);
  preferences.putUInt("lectura_s", readSeconds);
  preferences.putUInt("latido_s", heartbeatSeconds);
  Serial.printf("Intervalos: lectura=%lu s, latido=%lu s\n", readSeconds, heartbeatSeconds);
}

void connectWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;
  if (millis() - lastWifiAttempt < RECONNECT_MS) return;
  lastWifiAttempt = millis();
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
}

void connectMqtt() {
  if (WiFi.status() != WL_CONNECTED || mqtt.connected()) return;
  uint32_t now = millis();
  if (now - lastReconnectAttempt < RECONNECT_MS) return;
  lastReconnectAttempt = now;
  bool connected = (strlen(MQTT_USER) == 0)
      ? mqtt.connect(stationId.c_str())
      : mqtt.connect(stationId.c_str(), MQTT_USER, MQTT_PASSWORD);
  if (connected) {
    mqtt.subscribe(TOPIC_CONFIG, 1);
    Serial.println("MQTT conectado; estación suscrita a configuración.");
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_RAIN_DO, INPUT);
  analogReadResolution(12);
  dht.begin();
  preferences.begin("portus-estacion", false);
  readSeconds = constrain(preferences.getUInt("lectura_s", DEFAULT_READ_SECONDS), 2U, 60U);
  heartbeatSeconds = constrain(preferences.getUInt("latido_s", DEFAULT_HEARTBEAT_SECONDS), 5U, 60U);
  stationId = "estacion-" + WiFi.macAddress();
  stationId.replace(":", "");
  setenv("TZ", "UTC+6", 1); // POSIX invierte el signo: UTC+6 significa Guatemala UTC-6.
  tzset();
  configTime(0, 0, "pool.ntp.org", "time.nist.gov");
  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt.setCallback(onMqttMessage);
  mqtt.setBufferSize(512);
  lastWifiAttempt = millis() - RECONNECT_MS;
  lastReconnectAttempt = millis() - RECONNECT_MS;
  connectWiFi();
}

void loop() {
  connectWiFi();
  connectMqtt();
  if (mqtt.connected()) mqtt.loop();

  uint32_t now = millis();
  if (now - lastRead >= readSeconds * 1000UL) {
    lastRead = now;
    publishReading(); // También toma sensores durante cortes de red.
  }
  if (now - lastHeartbeat >= heartbeatSeconds * 1000UL) {
    lastHeartbeat = now;
    publishHeartbeat();
  }
  delay(10);
}
