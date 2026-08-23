#include <SPI.h>
#include <MFRC522.h>

#define SS_PIN 53
#define RST_PIN 49

MFRC522 rfid(SS_PIN, RST_PIN);

// Variables para manejar el tiempo sin usar delay()
unsigned long ultimoTiempoLectura = 0;
const unsigned long intervaloCooldown = 1500; // 1.5 segundos de espera entre lecturas

void setup() {
  Serial.begin(9600);
  pinMode(53, OUTPUT);
  digitalWrite(53, HIGH);

  SPI.begin();
  rfid.PCD_Init();

  Serial.println("===== GARITA INICIADA =====");
  Serial.println("Esperando camiones...");
}

void loop() {
  // 1. Verificamos si ya pasó el tiempo de cooldown usando millis()
  // Si no ha pasado, salimos del loop inmediatamente (no bloquea a otros procesos)
  if (millis() - ultimoTiempoLectura < intervaloCooldown) {
    return;
  }

  // 2. Buscamos si hay una tarjeta presente
  if (!rfid.PICC_IsNewCardPresent()) {
    return;
  }

  // 3. Intentamos leerla. Si ocurre el "fallo fantasma" del clon 0x82, 
  // simplemente retornamos en silencio y el loop volverá a intentarlo instantáneamente.
  if (!rfid.PICC_ReadCardSerial()) {
    return;
  }

  // ====== LECTURA EXITOSA ======
  
  // Actualizamos el cronómetro para activar el cooldown
  ultimoTiempoLectura = millis(); 

  Serial.print("Camion detectado. UID: ");
  
  // Imprimir el UID
  for (byte i = 0; i < rfid.uid.size; i++) {
    if (rfid.uid.uidByte[i] < 0x10) {
      Serial.print("0");
    }
    Serial.print(rfid.uid.uidByte[i], HEX);
  }
  Serial.println();

  // Limpiar la comunicación con la tarjeta actual
  rfid.PICC_HaltA();
  rfid.PCD_StopCrypto1();
  
  // AQUÍ IRÍA LA LÓGICA DE TU MÁQUINA DE ESTADOS:
  // validarManifiesto();
  // abrirTalanquera();
}