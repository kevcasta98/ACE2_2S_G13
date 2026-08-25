#include <SPI.h>
#include <MFRC522.h>
#include <Servo.h>

// --- Definiciones de Pines ---
#define SS_PIN 53
#define RST_PIN 49
#define PIN_SERVO 9
#define PIN_SENSOR_IR 8

// --- Creación de Objetos ---
MFRC522 rfid(SS_PIN, RST_PIN);
Servo miTalanquera;

// --- Variables para control de tiempo (sin delay) ---
unsigned long ultimoTiempoLectura = 0;
const unsigned long intervaloCooldown = 1500; 
unsigned long tiempoInicioApertura = 0;
const unsigned long tiempoCiego = 3000; 

// --- MODELO DE DATOS: CAMIÓN ---
// Según los requerimientos de PORTUS Fase 1
struct Camion {
  String rfid;
  String placa;
  bool autorizadoLocalmente;
};

// Base de datos pre-cargada con tus 3 tarjetas
Camion baseDatosCamiones[] = {
  {"EA225305", "C-101", true},   // Tarjeta 1: Permitida
  {"99A08729", "C-202", true},   // Tarjeta 2: Permitida
  {"E116F9B0", "C-303", false}   // Tarjeta 3: Denegada 
};
const int TOTAL_CAMIONES = 3;

// --- Estados de la Garita ---
enum EstadoGarita {
  ESPERANDO_CAMION,
  TIEMPO_CIEGO_ARRANQUE,
  TALANQUERA_ABIERTA,
  CAMION_CRUZANDO
};
EstadoGarita estadoActual = ESPERANDO_CAMION;

void setup() {
  Serial.begin(9600);
  pinMode(PIN_SENSOR_IR, INPUT);
  pinMode(53, OUTPUT);
  digitalWrite(53, HIGH);

  SPI.begin();
  rfid.PCD_Init();
  miTalanquera.attach(PIN_SERVO);
  cerrarTalanquera();

  Serial.println("===== SISTEMA DE GARITA PORTUS INICIADO =====");
  Serial.println("Esperando lectura RFID...");
}

void loop() {
  int estadoSensor = digitalRead(PIN_SENSOR_IR);

  // ==========================================
  // MÁQUINA DE ESTADOS DE LA GARITA
  // ==========================================
  
  switch (estadoActual) {
    
    case ESPERANDO_CAMION:
      if (millis() - ultimoTiempoLectura >= intervaloCooldown) {
        if (rfid.PICC_IsNewCardPresent() && rfid.PICC_ReadCardSerial()) {
          
          ultimoTiempoLectura = millis();
          
          // 1. Extraer el UID y convertirlo a String (sin los dos puntos para que sea más fácil comparar)
          String uidLeido = "";
          for (byte i = 0; i < rfid.uid.size; i++) {
            if (rfid.uid.uidByte[i] < 0x10) uidLeido += "0";
            uidLeido += String(rfid.uid.uidByte[i], HEX);
          }
          uidLeido.toUpperCase(); // Convertir a mayúsculas para asegurar la coincidencia

          Serial.println("\n[1] Tarjeta detectada: " + uidLeido);
          
          // Limpiar comunicación
          rfid.PICC_HaltA();
          rfid.PCD_StopCrypto1();

          // 2. Validar en la base de datos local
          bool camionEncontrado = false;
          bool accesoPermitido = false;
          String placaDetectada = "";

          for (int i = 0; i < TOTAL_CAMIONES; i++) {
            if (baseDatosCamiones[i].rfid == uidLeido) {
              camionEncontrado = true;
              placaDetectada = baseDatosCamiones[i].placa;
              accesoPermitido = baseDatosCamiones[i].autorizadoLocalmente;
              break; // Rompemos el ciclo porque ya lo encontramos
            }
          }

          // 3. Tomar decisión
          if (camionEncontrado) {
            Serial.println("Camion identificado: Placa " + placaDetectada);
            
            if (accesoPermitido) {
              Serial.println("ACCESO AUTORIZADO. Abriendo garita...");
              abrirTalanquera();
              tiempoInicioApertura = millis();
              estadoActual = TIEMPO_CIEGO_ARRANQUE;
            } else {
              Serial.println("ACCESO DENEGADO: El camion no esta autorizado localmente.");
              // La talanquera permanece cerrada, mostrando la causa del rechazo según la rúbrica
            }
          } else {
            Serial.println("ACCESO DENEGADO: RFID no reconocido.");
            // Igual, la talanquera permanece cerrada
          }
        }
      }
      break;

    case TIEMPO_CIEGO_ARRANQUE:
      if (millis() - tiempoInicioApertura >= tiempoCiego) {
        estadoActual = TALANQUERA_ABIERTA;
      }
      break;

    case TALANQUERA_ABIERTA:
      if (estadoSensor == LOW) {
        Serial.println("[*] Camion cruzando la garita.");
        estadoActual = CAMION_CRUZANDO;
      }
      break;

    case CAMION_CRUZANDO:
      if (estadoSensor == HIGH) {
        Serial.println("[*] Camion libero el sensor. Cerrando talanquera.");
        cerrarTalanquera();
        estadoActual = ESPERANDO_CAMION; 
        Serial.println("===== LISTO PARA EL SIGUIENTE CAMION =====");
      }
      break;
  }
}

// --- Funciones de acción ---
void abrirTalanquera() {
  miTalanquera.write(90); 
}

void cerrarTalanquera() {
  miTalanquera.write(0); 
}