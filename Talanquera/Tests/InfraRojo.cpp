// --- Definiciones de Pines ---
// Conectamos el pin 'OUT' o 'DO' (Digital Output) del sensor al pin 8 del Arduino
#define PIN_SENSOR_IR 8

// --- Variables para control de tiempo (sin delay) ---
unsigned long tiempoUltimaImpresion = 0;
const unsigned long intervaloImpresion = 250; // Imprimir estado cada 250 milisegundos

// Variable para guardar el estado anterior y detectar cambios
int estadoAnteriorSensor = -1; 

void setup() {
  Serial.begin(9600);
  
  // Configuramos el pin del sensor como entrada
  pinMode(PIN_SENSOR_IR, INPUT);
  
  Serial.println("===== PRUEBA SENSOR INFRARROJO =====");
  Serial.println("Acerca un objeto al sensor...");
}

void loop() {
  // Leemos el estado del sensor
  // IMPORTANTE: La mayoría de estos sensores dan LOW (0) cuando DETECTAN un objeto, 
  // y HIGH (1) cuando NO hay nada. 
  int estadoActualSensor = digitalRead(PIN_SENSOR_IR);

  // LÓGICA 1: Detectar e imprimir el cambio de estado (cuando entra o sale un objeto)
  if (estadoActualSensor != estadoAnteriorSensor) {
    Serial.print("CAMBIO DETECTADO: ");
    if (estadoActualSensor == LOW) {
      Serial.println("¡Objeto detectado! (Camión presente)");
    } else {
      Serial.println("Vía libre. (Camión ausente)");
    }
    estadoAnteriorSensor = estadoActualSensor;
  }

  // LÓGICA 2: Imprimir el estado continuo sin saturar la consola (No bloqueante)
  if (millis() - tiempoUltimaImpresion >= intervaloImpresion) {
    if (estadoActualSensor == LOW) {
      Serial.println("Estado actual: DETECTANDO");
    } 
    tiempoUltimaImpresion = millis();
  }
  
  // El loop sigue corriendo libremente
}