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

// NUEVAS variables para el tiempo ciego de la talanquera
unsigned long tiempoInicioApertura = 0;
const unsigned long tiempoCiego = 3000; // 3 segundos de gracia antes de leer el sensor

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
          Serial.println("\n[1] Camion detectado (RFID)");
          
          rfid.PICC_HaltA();
          rfid.PCD_StopCrypto1();

          abrirTalanquera();
          
          // Guardamos el momento exacto en que se abrió y pasamos al tiempo ciego
          tiempoInicioApertura = millis();
          estadoActual = TIEMPO_CIEGO_ARRANQUE;
          Serial.println("[2] Talanquera abierta. Dando 3 segundos de gracia al conductor...");
        }
      }
      break;

    case TIEMPO_CIEGO_ARRANQUE:
      // Ignoramos el sensor por 3 segundos para darle tiempo al camión de avanzar
      if (millis() - tiempoInicioApertura >= tiempoCiego) {
        Serial.println("[3] Tiempo ciego terminado. Activando lectura del sensor infrarrojo.");
        estadoActual = TALANQUERA_ABIERTA;
      }
      break;

    case TALANQUERA_ABIERTA:
      // Ahora sí, esperamos a que el sensor detecte físicamente la masa del camión
      if (estadoSensor == LOW) {
        Serial.println("[4] Camion detectado cruzando la garita.");
        estadoActual = CAMION_CRUZANDO;
      }
      break;

    case CAMION_CRUZANDO:
      // Esperamos a que el sensor vuelva a HIGH (el camión terminó de pasar)
      if (estadoSensor == HIGH) {
        Serial.println("[5] Camion libero el sensor. Cerrando talanquera.");
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