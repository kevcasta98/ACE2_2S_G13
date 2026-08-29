#include <SPI.h>
#include <MFRC522.h>
#include <Servo.h>

// --- Definiciones de Pines ---
#define SS_PIN 53
#define RST_PIN 5
#define PIN_SERVO 9
#define PIN_SENSOR_IR 8

// Pines del Semáforo (Puedes usar los pines PWM o digitales libres)
#define PIN_LED_ROJO 5
#define PIN_LED_AMARILLO 6
#define PIN_LED_VERDE 7

// --- Creación de Objetos ---
MFRC522 rfid(SS_PIN, RST_PIN);
Servo miTalanquera;

// --- Variables para control de tiempo (sin delay) ---
unsigned long ultimoTiempoLectura = 0;
const unsigned long intervaloCooldown = 1500; 

unsigned long tiempoInicioApertura = 0;
const unsigned long tiempoCiego = 3000; 

// Variables para el efecto del semáforo amarillo
unsigned long tiempoInicioValidacion = 0;
const unsigned long tiempoValidacion = 1500; // 1.5 seg de luz amarilla
String uidPendiente = "";

// --- MODELO DE DATOS: CAMIÓN ---
struct Camion {
  String rfid;
  String placa;
  bool autorizadoLocalmente;
};

Camion baseDatosCamiones[] = {
  {"EA225305", "C-101", true},
  {"99A08729", "C-202", true},
  {"E116F9B0", "C-303", false}
};
const int TOTAL_CAMIONES = 3;

// --- Estados de la Garita ---
enum EstadoGarita {
  ESPERANDO_CAMION,
  VALIDANDO_ACCESO,
  TIEMPO_CIEGO_ARRANQUE,
  TALANQUERA_ABIERTA,
  CAMION_CRUZANDO
};
EstadoGarita estadoActual = ESPERANDO_CAMION;

void setup() {
  Serial.begin(9600);
  pinMode(PIN_SENSOR_IR, INPUT);
  
  // Configurar pines del semáforo
  pinMode(PIN_LED_ROJO, OUTPUT);
  pinMode(PIN_LED_AMARILLO, OUTPUT);
  pinMode(PIN_LED_VERDE, OUTPUT);

  pinMode(53, OUTPUT);
  digitalWrite(53, HIGH);

  SPI.begin();
  rfid.PCD_Init();
  miTalanquera.attach(PIN_SERVO);
  cerrarTalanquera();

  // Estado inicial: Vehículo debe permanecer detenido[cite: 1]
  actualizarSemaforo(HIGH, LOW, LOW);

  Serial.println("===== SISTEMA DE GARITA PORTUS INICIADO =====");
  Serial.println("Semaforo: ROJO. Esperando lectura RFID...");
}

void loop() {
  int estadoSensor = digitalRead(PIN_SENSOR_IR);
  
  switch (estadoActual) {
    
    case ESPERANDO_CAMION:
      if (millis() - ultimoTiempoLectura >= intervaloCooldown) {
        if (rfid.PICC_IsNewCardPresent() && rfid.PICC_ReadCardSerial()) {
          
          ultimoTiempoLectura = millis();
          
          // Extraer UID
          uidPendiente = "";
          for (byte i = 0; i < rfid.uid.size; i++) {
            if (rfid.uid.uidByte[i] < 0x10) uidPendiente += "0";
            uidPendiente += String(rfid.uid.uidByte[i], HEX);
          }
          uidPendiente.toUpperCase(); 

          rfid.PICC_HaltA();
          rfid.PCD_StopCrypto1();

          // Cambiar a luz amarilla: Estación realizando validación[cite: 1]
          actualizarSemaforo(LOW, HIGH, LOW);
          tiempoInicioValidacion = millis();
          estadoActual = VALIDANDO_ACCESO;
          
          Serial.println("\n[1] Tarjeta leida. Semaforo AMARILLO (Validando...)");
        }
      }
      break;

    case VALIDANDO_ACCESO:
      // Esperamos 1.5 segundos para que la luz amarilla sea visible
      if (millis() - tiempoInicioValidacion >= tiempoValidacion) {
        
        bool camionEncontrado = false;
        bool accesoPermitido = false;
        String placaDetectada = "";

        for (int i = 0; i < TOTAL_CAMIONES; i++) {
          if (baseDatosCamiones[i].rfid == uidPendiente) {
            camionEncontrado = true;
            placaDetectada = baseDatosCamiones[i].placa;
            accesoPermitido = baseDatosCamiones[i].autorizadoLocalmente;
            break; 
          }
        }

        if (camionEncontrado && accesoPermitido) {
          Serial.println("ACCESO AUTORIZADO: Placa " + placaDetectada);
          // Operación autorizada: Luz verde y abrir[cite: 1]
          actualizarSemaforo(LOW, LOW, HIGH);
          abrirTalanquera();
          tiempoInicioApertura = millis();
          estadoActual = TIEMPO_CIEGO_ARRANQUE;
        } else {
          // Si no está registrado o no está autorizado, vuelve a rojo
          if (!camionEncontrado) {
            Serial.println("RECHAZO: RFID no reconocido.");
          } else {
            Serial.println("RECHAZO: Camion no autorizado.");
          }
          actualizarSemaforo(HIGH, LOW, LOW);
          estadoActual = ESPERANDO_CAMION;
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
        
        // Vuelve a rojo al cerrar
        actualizarSemaforo(HIGH, LOW, LOW);
        estadoActual = ESPERANDO_CAMION; 
        Serial.println("Semaforo: ROJO. ===== LISTO PARA EL SIGUIENTE CAMION =====");
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

// Función auxiliar para controlar las 3 luces fácilmente
void actualizarSemaforo(int rojo, int amarillo, int verde) {
  digitalWrite(PIN_LED_ROJO, rojo);
  digitalWrite(PIN_LED_AMARILLO, amarillo);
  digitalWrite(PIN_LED_VERDE, verde);
}