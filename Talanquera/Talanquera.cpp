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

// --- Variables para control de tiempo (RFID) ---
unsigned long ultimoTiempoLectura = 0;
const unsigned long intervaloCooldown = 1500; 

// --- Variables de Estado ---
enum EstadoGarita {
  ESPERANDO_CAMION,
  TALANQUERA_ABIERTA,
  CAMION_CRUZANDO
};

EstadoGarita estadoActual = ESPERANDO_CAMION;

void setup() {
  Serial.begin(9600);

  // Inicializar pines
  pinMode(PIN_SENSOR_IR, INPUT);
  pinMode(53, OUTPUT);
  digitalWrite(53, HIGH);

  // Inicializar SPI y RFID
  SPI.begin();
  rfid.PCD_Init();

  // Inicializar Servo (Talanquera cerrada por defecto)
  miTalanquera.attach(PIN_SERVO);
  cerrarTalanquera();

  Serial.println("===== SISTEMA DE GARITA PORTUS INICIADO =====");
  Serial.println("Esperando lectura RFID...");
}

void loop() {
  // Leemos el sensor infrarrojo en cada ciclo (LOW = Camión detectado)
  int estadoSensor = digitalRead(PIN_SENSOR_IR);

  // ==========================================
  // MÁQUINA DE ESTADOS DE LA GARITA
  // ==========================================
  
  switch (estadoActual) {
    
    case ESPERANDO_CAMION:
      // Solo en este estado nos importa leer el RFID
      if (millis() - ultimoTiempoLectura >= intervaloCooldown) {
        if (rfid.PICC_IsNewCardPresent() && rfid.PICC_ReadCardSerial()) {
          
          ultimoTiempoLectura = millis();
          Serial.println("\n[1] Camion detectado (RFID)");
          
          // Limpiar comunicación
          rfid.PICC_HaltA();
          rfid.PCD_StopCrypto1();

          // Abrir y cambiar de estado
          abrirTalanquera();
          estadoActual = TALANQUERA_ABIERTA;
          Serial.println("[2] Talanquera abierta. Esperando que el camion avance...");
        }
      }
      break;

    case TALANQUERA_ABIERTA:
      // Esperamos hasta que el sensor IR detecte que el camión empezó a cruzar
      if (estadoSensor == LOW) {
        Serial.println("[3] Camion cruzando la garita (Sensor IR bloqueado).");
        estadoActual = CAMION_CRUZANDO;
      }
      break;

    case CAMION_CRUZANDO:
      // La talanquera sigue abierta. 
      // Esperamos a que el sensor IR vuelva a HIGH (el camión ya pasó completamente)
      if (estadoSensor == HIGH) {
        Serial.println("[4] Camion libero el sensor. Cerrando talanquera.");
        cerrarTalanquera();
        estadoActual = ESPERANDO_CAMION; // Volvemos al inicio
        Serial.println("===== LISTO PARA EL SIGUIENTE CAMION =====");
      }
      break;
  }

  // Aqui deben continuar
}

// --- Funciones de acción ---
void abrirTalanquera() {
  miTalanquera.write(90); 
}

void cerrarTalanquera() {
  miTalanquera.write(0); 
}