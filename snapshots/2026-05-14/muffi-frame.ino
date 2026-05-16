/**
 * Muffi Photo Frame ❤️
 * Waveshare ESP32-C6 1.47inch Display-M
 * LovyanGFX + JPEGDEC
 * BOOT-Knopf (GPIO9) = nächstes Bild
 */

#include <LovyanGFX.hpp>
#include <WiFi.h>
#include <WiFiUdp.h>
#include <ArduinoOTA.h>
#include <HTTPClient.h>
#include <JPEGDEC.h>
#include <ArduinoJson.h>

// ============ EINSTELLUNGEN ============
const char* WIFI_SSID     = "Papa Wlan";
const char* WIFI_PASSWORD = "Andre123456";
const char* SERVER_BASE   = "http://frame-server.local:8765"; // redacted for public repo
#define DEFAULT_REFRESH_MS   (5 * 60 * 1000UL)
#define BUTTON_PIN   9    // BOOT-Knopf
#define SERVO_PIN    3    // SG90 Signal
#define SERVO_FREQ   50   // 50Hz
#define SERVO_HOCHFORMAT   1638  // 0°  (~500µs  von 20ms)
#define SERVO_QUERFORMAT   4915  // 90° (~1500µs von 20ms)
// =======================================

class LGFX : public lgfx::LGFX_Device {
  lgfx::Panel_ST7789  _panel;
  lgfx::Bus_SPI       _bus;
  lgfx::Light_PWM     _light;
public:
  LGFX() {
    { auto cfg = _bus.config();
      cfg.spi_host  = SPI2_HOST;
      cfg.spi_mode  = 0;
      cfg.freq_write= 40000000;
      cfg.pin_sclk  = 7;
      cfg.pin_mosi  = 6;
      cfg.pin_miso  = -1;
      cfg.pin_dc    = 15;
      _bus.config(cfg); _panel.setBus(&_bus); }
    { auto cfg = _panel.config();
      cfg.pin_cs   = 14;
      cfg.pin_rst  = 21;
      cfg.pin_busy = -1;
      cfg.panel_width  = 172;
      cfg.panel_height = 320;
      cfg.offset_x     = 34;
      cfg.offset_y     = 0;
      cfg.invert       = true;
      cfg.rgb_order    = false;
      _panel.config(cfg); }
    { auto cfg = _light.config();
      cfg.pin_bl      = 22;
      cfg.invert      = false;
      cfg.freq        = 44100;
      cfg.pwm_channel = 7;
      _light.config(cfg); _panel.setLight(&_light); }
    setPanel(&_panel);
  }
};

LGFX tft;
JPEGDEC jpeg;

void showStatus(const char* msg, uint16_t color = TFT_WHITE);

// Bilderliste
struct PhotoInfo {
  String name;
  bool   landscape;
};
PhotoInfo fileList[200];
int       fileCount  = 0;
int       currentIdx = 0;

uint8_t* jpegBuf = nullptr;
size_t   jpegLen = 0;

// Button
unsigned long lastButtonMs  = 0;
unsigned long buttonPressMs = 0;
bool          buttonHeld    = false;
int           currentRotation = 0; // 0=Hochformat, 1=Querformat

// Dynamischer Refresh (via Server-Config)
unsigned long refreshMs = DEFAULT_REFRESH_MS;
unsigned long lastRefresh = 0;
unsigned long lastWiFiRetryMs = 0;
unsigned long lastNoPhotoRetryMs = 0;
bool otaReady = false;

void setupOTA() {
  if (otaReady) return;

  ArduinoOTA.setHostname("muffi-frame");

  ArduinoOTA.onStart([]() {
    showStatus("OTA Update...", TFT_CYAN);
  });

  ArduinoOTA.onEnd([]() {
    showStatus("OTA Fertig", TFT_GREEN);
    delay(800);
  });

  ArduinoOTA.onError([](ota_error_t) {
    showStatus("OTA Fehler", TFT_RED);
  });

  ArduinoOTA.begin();
  otaReady = true;
  Serial.println("OTA bereit");
}

bool connectWiFi(uint32_t timeoutMs = 30000) {
  if (WiFi.status() == WL_CONNECTED) return true;

  showStatus("Verbinde WLAN...", TFT_WHITE);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  unsigned long start = millis();
  while (WiFi.status() != WL_CONNECTED && (millis() - start) < timeoutMs) {
    delay(300);
  }

  if (WiFi.status() == WL_CONNECTED) {
    showStatus("WLAN OK", TFT_GREEN);
    Serial.println("WLAN OK: " + WiFi.localIP().toString());
    setupOTA();
    delay(400);
    return true;
  }

  showStatus("WLAN Fehler!", TFT_RED);
  Serial.println("WLAN Verbindung fehlgeschlagen");
  return false;
}

bool ensureWiFiConnected() {
  if (WiFi.status() == WL_CONNECTED) return true;

  if (millis() - lastWiFiRetryMs < 5000) {
    return false;
  }
  lastWiFiRetryMs = millis();
  return connectWiFi(10000);
}

// Servo auf Position fahren und dann Signal abschalten (kein Zittern)
void servoMove(int position) {
  ledcWrite(SERVO_PIN, position);
  delay(600);          // warten bis er da ist
  ledcWrite(SERVO_PIN, 0); // Signal aus = kein Brummen
}

int jpegDraw(JPEGDRAW* pDraw) {
  tft.pushImage(pDraw->x, pDraw->y, pDraw->iWidth, pDraw->iHeight, pDraw->pPixels);
  return 1;
}

void showStatus(const char* msg, uint16_t color) {
  tft.fillScreen(TFT_BLACK);
  tft.setTextColor(color);
  tft.setTextSize(2);
  tft.setCursor(5, tft.height() / 2 - 10);
  tft.print(msg);
}

// Dateiliste vom Server holen
bool refreshFileList() {
  HTTPClient http;
  http.begin(String(SERVER_BASE) + "/list");
  http.setTimeout(8000);
  int code = http.GET();
  if (code != 200) { http.end(); return false; }
  String body = http.getString();
  http.end();

  JsonDocument doc;
  if (deserializeJson(doc, body)) return false;

  JsonArray arr = doc["files"].as<JsonArray>();
  fileCount = 0;
  for (JsonVariant v : arr) {
    if (fileCount >= 200) break;
    fileList[fileCount].name      = v["name"].as<String>();
    fileList[fileCount].landscape = String(v["orientation"].as<String>()) == "landscape";
    fileCount++;
  }
  Serial.println("Dateien: " + String(fileCount));
  return fileCount > 0;
}

void showImage(int idx) {
  if (idx < 0 || idx >= fileCount) return;
  String filename = fileList[idx].name;
  bool   isLandscape = fileList[idx].landscape;

  // Servo + Display Rotation automatisch setzen
  int newRotation = isLandscape ? 1 : 0;
  if (newRotation != currentRotation) {
    // Erst Servo drehen, dann Bild laden
    Serial.println(isLandscape ? "Servo → Querformat" : "Servo → Hochformat");
    servoMove(isLandscape ? SERVO_QUERFORMAT : SERVO_HOCHFORMAT);
  }
  tft.setRotation(newRotation);
  currentRotation = newRotation;

  String url = String(SERVER_BASE) + "/" + filename;
  Serial.println("Lade [" + String(idx+1) + "/" + String(fileCount) + "]: " + filename);

  // Bildnummer anzeigen während geladen wird
  tft.fillScreen(TFT_BLACK);
  tft.setTextColor(TFT_WHITE);
  tft.setTextSize(2);
  tft.setCursor(5, tft.height()/2 - 20);
  tft.print("Lade...");
  tft.setCursor(5, tft.height()/2 + 5);
  tft.setTextSize(1);
  tft.printf("%d / %d", idx+1, fileCount);

  HTTPClient http;
  http.begin(url);
  http.setTimeout(15000);
  int code = http.GET();
  if (code != 200) {
    http.end();
    showStatus("HTTP Fehler!", TFT_RED);
    return;
  }

  int size = http.getSize();
  if (size <= 0 || size > 400000) {
    http.end();
    showStatus("Groesse Fehler!", TFT_YELLOW);
    return;
  }

  if (jpegBuf) { free(jpegBuf); jpegBuf = nullptr; }
  jpegBuf = (uint8_t*)malloc(size);
  if (!jpegBuf) {
    http.end();
    showStatus("RAM voll!", TFT_RED);
    return;
  }

  WiFiClient* stream = http.getStreamPtr();
  size_t got = 0;
  unsigned long t = millis();
  while (got < (size_t)size && millis() - t < 15000) {
    int r = stream->readBytes(jpegBuf + got, size - got);
    if (r > 0) got += r;
  }
  http.end();

  tft.fillScreen(TFT_BLACK);
  if (jpeg.openRAM(jpegBuf, got, jpegDraw)) {
    jpeg.setPixelType(RGB565_BIG_ENDIAN);
    int offX = max(0, (int)(tft.width()  - jpeg.getWidth())  / 2);
    int offY = max(0, (int)(tft.height() - jpeg.getHeight()) / 2);
    jpeg.decode(offX, offY, 0);
    jpeg.close();

    // Kleiner Bildnummer-Indikator unten rechts
    tft.setTextColor(0x2104); // sehr dunkelgrau
    tft.setTextSize(1);
    tft.setCursor(tft.width() - 32, tft.height() - 10);
    tft.printf("%d/%d", idx+1, fileCount);
  } else {
    showStatus("JPEG Fehler!", TFT_RED);
  }
}

bool refreshSettingsFromServer() {
  HTTPClient http;
  http.begin(String(SERVER_BASE) + "/api/config");
  http.setTimeout(5000);
  int code = http.GET();
  if (code != 200) { http.end(); return false; }

  String body = http.getString();
  http.end();

  JsonDocument doc;
  if (deserializeJson(doc, body)) return false;

  unsigned long newMs = doc["refreshMs"] | DEFAULT_REFRESH_MS;
  // Schutz: nicht kleiner als 10s, nicht größer als 24h
  if (newMs < 10000UL) newMs = 10000UL;
  if (newMs > 24UL * 60UL * 60UL * 1000UL) newMs = 24UL * 60UL * 60UL * 1000UL;

  if (newMs != refreshMs) {
    refreshMs = newMs;
    Serial.println("Neues Refresh-Intervall: " + String(refreshMs / 1000UL) + "s");
  }
  return true;
}

void setup() {
  Serial.begin(115200);
  delay(500);

  pinMode(BUTTON_PIN, INPUT_PULLUP);

  // Servo initialisieren
  ledcAttach(SERVO_PIN, SERVO_FREQ, 16);
  servoMove(SERVO_HOCHFORMAT); // Startposition = Hochformat
  delay(200);

  tft.init();
  tft.setRotation(0);
  tft.setBrightness(220);
  connectWiFi();

  showStatus("Lade Settings...", TFT_GREEN);
  if (!refreshSettingsFromServer()) {
    showStatus("Settings lokal", TFT_YELLOW);
    delay(300);
  }

  showStatus("Lade Liste...", TFT_GREEN);
  if (refreshFileList()) {
    currentIdx = fileCount - 1; // neuestes Bild zuerst
    showImage(currentIdx);
  } else {
    showStatus("Kein Foto!", TFT_YELLOW);
  }
}

void loop() {
  if (WiFi.status() == WL_CONNECTED && otaReady) {
    ArduinoOTA.handle();
  } else {
    ensureWiFiConnected();
  }

  // Wenn wir aktuell kein Foto haben: schneller nachfassen (alle 10s)
  if (fileCount == 0 && millis() - lastNoPhotoRetryMs > 10000) {
    lastNoPhotoRetryMs = millis();
    if (ensureWiFiConnected()) {
      refreshSettingsFromServer();
      if (refreshFileList() && fileCount > 0) {
        currentIdx = fileCount - 1;
        showImage(currentIdx);
      } else {
        showStatus("WLAN OK, kein Foto", TFT_YELLOW);
      }
    } else {
      showStatus("WLAN reconnect...", TFT_YELLOW);
    }
  }

  // Button: kurz = nächstes Bild, lang (>1s) = Rotation
  if (digitalRead(BUTTON_PIN) == LOW) {
    if (!buttonHeld) {
      buttonHeld    = true;
      buttonPressMs = millis();
    }
  } else {
    if (buttonHeld) {
      buttonHeld = false;
      unsigned long held = millis() - buttonPressMs;
      if (millis() - lastButtonMs > 300) {
        lastButtonMs = millis();
        if (held > 1000) {
          // Lang gedrückt → Rotation manuell überschreiben
          currentRotation = (currentRotation == 0) ? 1 : 0;
          tft.setRotation(currentRotation);
          Serial.println(currentRotation == 1 ? "Manuell: Querformat" : "Manuell: Hochformat");
          if (fileCount > 0) {
            showImage(currentIdx);
          }
        } else {
          // Kurz gedrückt → nächstes Bild
          Serial.println("Nächstes Bild");
          if (ensureWiFiConnected() && refreshFileList() && fileCount > 0) {
            currentIdx = (currentIdx + 1) % fileCount;
            showImage(currentIdx);
          } else {
            showStatus("Kein WLAN/Fotos", TFT_YELLOW);
          }
        }
      }
    }
  }

  // Automatisch anhand Server-Setting Liste neu laden
  if (millis() - lastRefresh > refreshMs) {
    lastRefresh = millis();
    if (!ensureWiFiConnected()) {
      showStatus("WLAN reconnect...", TFT_YELLOW);
      delay(100);
      return;
    }

    refreshSettingsFromServer();
    int oldCount = fileCount;
    bool ok = refreshFileList();
    if (!ok && fileCount == 0) {
      showStatus("Kein Foto!", TFT_YELLOW);
      return;
    }
    // Nur wechseln wenn neues Bild dazugekommen
    if (fileCount > oldCount) {
      currentIdx = fileCount - 1;
      showImage(currentIdx);
    }
  }

  delay(50);
}
