#include <Servo.h>

// Definir el pin donde conectarás el cable de señal del servo (generalmente naranja o amarillo)
// Puedes cambiarlo al pin que mejor te quede en el Mega, los que tienen una tilde (~) son ideales.
#define PIN_SERVO 9

Servo miTalanquera;

// Variables para el control de tiempo sin delay()
unsigned long tiempoUltimoMovimiento = 0;
const unsigned long tiempoApertura = 3000; // Tiempo que la talanquera permanecerá abierta (3 segundos)

// Estados de la talanquera para nuestra pequeña máquina de estados
enum EstadoTalanquera {
  CERRADA,
  ABIERTA
};

EstadoTalanquera estadoActual = CERRADA;

void setup() {
  Serial.begin(9600);
  
  // Conectar el servo al pin y establecer la posición inicial (cerrada)
  miTalanquera.attach(PIN_SERVO);
  miTalanquera.write(0); // 0 grados = Cerrada
  
  Serial.println("Prueba de Servomotor SG90 (Talanquera) iniciada.");
  Serial.println("Enviando comando para abrir...");
  
  // Simulamos que la tarjeta fue aceptada y abrimos la talanquera
  abrirTalanquera();
}

void loop() {
  // LÓGICA NO BLOQUEANTE:
  // Si la talanquera está abierta, verificamos si ya pasó el tiempo para cerrarla
  if (estadoActual == ABIERTA) {
    if (millis() - tiempoUltimoMovimiento >= tiempoApertura) {
      cerrarTalanquera();
    }
  }

  // Aquí tu Arduino Mega es completamente libre de hacer otras cosas, 
  // como leer el RFID, procesar el peso, mover la grúa, etc., miles de veces por segundo.
}

// Funciones de control
void abrirTalanquera() {
  miTalanquera.write(90); // Mueve el servo a 90 grados (abierta)
  estadoActual = ABIERTA;
  tiempoUltimoMovimiento = millis(); // Guardamos el momento exacto en que se abrió
  Serial.println("Talanquera: ABIERTA (90 grados). Esperando 3 segundos...");
}

void cerrarTalanquera() {
  miTalanquera.write(0); // Regresa el servo a 0 grados (cerrada)
  estadoActual = CERRADA;
  Serial.println("Talanquera: CERRADA (0 grados).");
}