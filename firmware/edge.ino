/*
 * Aevum Edge - device firmware (Seeed XIAO ESP32-S3)
 * Qwen Cloud Global AI Hackathon - EdgeAgent track (Track 5)
 *
 * Edge: read sensors over I2C, extract features on-device, enforce consent,
 *       degrade gracefully when offline.
 * Cloud: Qwen reasons over the features and returns a diagnosis-free
 *        wellbeing flag (see backend/app.py).
 *
 * Raw PPG / motion waveforms NEVER leave the device - only derived features.
 *
 * Libraries (Arduino Library Manager):
 *   - SparkFun MAX3010x Pulse and Proximity Sensor Library   (MAX30102)
 *   - Adafruit MPU6050  +  Adafruit Unified Sensor           (MPU-6050)
 *   - Adafruit BME280 Library                                (BME280)
 *   - ArduinoJson
 *   (WiFi + HTTPClient ship with the ESP32 Arduino core)
 *
 * One shared 3.3V I2C bus.  XIAO ESP32-S3: SDA = D4, SCL = D5.
 *   MAX30102 0x57  ·  MPU-6050 0x68  ·  BME280 0x76
 */

#include <Wire.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include "MAX30105.h"
#include "heartRate.h"
#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>
#include <Adafruit_BME280.h>

// ----------------------------- CONFIG: edit these -----------------------------
const char* WIFI_SSID     = "YOUR_WIFI";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";
const char* BACKEND_URL   = "https://YOUR-FUNCTION-URL/assess";  // Alibaba Cloud HTTP trigger
const char* CONSENT_TOKEN = "demo-consent-granted";              // absent/invalid => backend refuses

// Personal resting baseline. The cloud compares live readings against this.
const float BASE_HR   = 64.0;   // bpm
const float BASE_TEMP = 33.5;   // degrees C, skin/contact (MAX30102 on-die sensor)
// ------------------------------------------------------------------------------

MAX30105 ppg;
Adafruit_MPU6050 imu;
Adafruit_BME280 bme;

// Heart-rate estimation state (rolling average of recent beats)
const byte RATE_SIZE = 8;
byte rates[RATE_SIZE];
byte rateSpot = 0;
long lastBeat = 0;
float beatsPerMinute = 0;
int beatAvg = 0;

void connectWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  unsigned long t0 = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t0 < 8000) delay(250);
}

void setup() {
  Serial.begin(115200);
  delay(300);
  Wire.begin();                                  // SDA = D4, SCL = D5 on the XIAO ESP32-S3

  if (!ppg.begin(Wire, I2C_SPEED_FAST)) Serial.println("MAX30102 not found (check 0x57)");
  ppg.setup();                                   // sensible default PPG config
  ppg.setPulseAmplitudeRed(0x0A);
  ppg.enableDIETEMPRDY();                         // enable the on-die temperature reading

  if (!imu.begin())     Serial.println("MPU-6050 not found (check 0x68)");
  if (!bme.begin(0x76)) Serial.println("BME280 not found (check 0x76)");

  connectWiFi();
  Serial.println("Aevum Edge ready.");
}

// Collect one ~4 s measurement window and reduce it to a few derived features.
void sampleWindow(float &hr, float &motion, float &skinTemp,
                  float &ambTemp, float &ambHum) {
  unsigned long t0 = millis();
  float motionPeak = 0;

  while (millis() - t0 < 4000) {
    long ir = ppg.getIR();
    if (checkForBeat(ir)) {                       // SparkFun beat detector
      long delta = millis() - lastBeat;
      lastBeat = millis();
      beatsPerMinute = 60.0 / (delta / 1000.0);
      if (beatsPerMinute > 30 && beatsPerMinute < 220) {
        rates[rateSpot++] = (byte)beatsPerMinute;
        rateSpot %= RATE_SIZE;
        int sum = 0;
        for (byte i = 0; i < RATE_SIZE; i++) sum += rates[i];
        beatAvg = sum / RATE_SIZE;
      }
    }

    sensors_event_t a, g, t;
    imu.getEvent(&a, &g, &t);
    float mag = sqrt(a.acceleration.x * a.acceleration.x +
                     a.acceleration.y * a.acceleration.y +
                     a.acceleration.z * a.acceleration.z);
    float dynamic = fabs(mag - 9.81);             // movement above gravity
    if (dynamic > motionPeak) motionPeak = dynamic;

    delay(20);
  }

  hr       = beatAvg;
  motion   = motionPeak;
  skinTemp = ppg.readTemperature();               // MAX30102 die temp = contact-temp proxy
  ambTemp  = bme.readTemperature();
  ambHum   = bme.readHumidity();
}

// Offline fallback: a simple, transparent local rule used when the cloud is unreachable.
String localFallback(float hr, float skinTemp) {
  if (hr > BASE_HR + 20 || skinTemp > BASE_TEMP + 1.0) return "watch";
  return "steady";
}

void loop() {
  float hr, motion, skinTemp, ambTemp, ambHum;
  sampleWindow(hr, motion, skinTemp, ambTemp, ambHum);

  // Build the payload - derived features only.
  StaticJsonDocument<512> body;
  body["consent_token"]   = CONSENT_TOKEN;
  body["heart_rate_bpm"]  = hr;
  body["motion_index"]    = motion;
  body["skin_temp_c"]     = skinTemp;
  body["ambient_temp_c"]  = ambTemp;
  body["ambient_hum_pct"] = ambHum;
  JsonObject base = body.createNestedObject("baseline");
  base["heart_rate_bpm"] = BASE_HR;
  base["skin_temp_c"]    = BASE_TEMP;
  String payload;
  serializeJson(body, payload);

  String status = "steady", nudge = "", explanation = "";

  if (WiFi.status() == WL_CONNECTED) {
    HTTPClient http;
    http.begin(BACKEND_URL);
    http.addHeader("Content-Type", "application/json");
    int code = http.POST(payload);
    if (code == 200) {
      StaticJsonDocument<1024> res;
      if (!deserializeJson(res, http.getString())) {
        status      = (const char*)(res["status"]      | "steady");
        nudge       = (const char*)(res["nudge"]       | "");
        explanation = (const char*)(res["explanation"] | "");
      }
    } else {
      status = localFallback(hr, skinTemp);       // graceful degradation
      nudge  = "(offline) " + status;
    }
    http.end();
  } else {
    status = localFallback(hr, skinTemp);          // graceful degradation
    nudge  = "(offline) " + status;
  }

  Serial.printf("HR %.0f  skin %.1fC  amb %.1fC/%.0f%%  motion %.2f  ->  %s\n",
                hr, skinTemp, ambTemp, ambHum, motion, status.c_str());
  if (nudge.length())       Serial.println("  nudge: " + nudge);
  if (explanation.length()) Serial.println("  why:   " + explanation);

  delay(15000);                                    // assess every ~15 s for the demo
}
