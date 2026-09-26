#include <Servo.h>

// --- Definiciones de Pines ---
#define PIN_SERVO_1 9     
#define PIN_SERVO_2 10    
#define PIN_SENSOR_IR 7   

// Pines para los Semáforos 
#define PIN_LATCH 8       
#define PIN_CLOCK 11     
#define PIN_DATA 12      

// --- Estados Binarios de los Colores ---
const byte APAGADO =  B00000000;
const byte ROJO =     B00000001; 
const byte VERDE =    B00000010;
const byte AMARILLO = B00000011;

// --- Creación de Objetos ---
Servo talanquera1;
Servo talanquera2;

// --- Variables para control de tiempo e iteración ---
unsigned long tiempoReferencia = 0; 
const unsigned long tiempoSimulacionPesaje = 4000; 
const unsigned long tiempoSalidaCamion = 4000;     
const unsigned long tiempoReinicioCiclo = 2000;    

bool turnoIzquierda = true; 

// --- Máquina de Estados del Sistema ---
enum EstadoSistema {
  ESPERANDO_INGRESO,
  CRUZANDO_INGRESO,
  SIMULANDO_PESAJE,
  SALIDA_AUTORIZADA,
  REINICIANDO_SISTEMA
};
EstadoSistema estadoActual = ESPERANDO_INGRESO;

void setup() {
  Serial.begin(9600);
  pinMode(PIN_SENSOR_IR, INPUT);
  
  pinMode(PIN_LATCH, OUTPUT);
  pinMode(PIN_CLOCK, OUTPUT);
  pinMode(PIN_DATA, OUTPUT);

  talanquera1.attach(PIN_SERVO_1);
  talanquera2.attach(PIN_SERVO_2);

  // Configuración Inicial
  centrarTalanquera2();
  abrirTalanquera1();
  actualizarSemaforos(VERDE, ROJO); 

  Serial.println("===== SISTEMA DE PESAJE INICIADO =====");
  Serial.println("Talanquera 1 ABIERTA (90 grados). Esperando vehiculo...");
}

void loop() {
  int estadoSensorIR = digitalRead(PIN_SENSOR_IR);
  
  switch (estadoActual) {
    
    case ESPERANDO_INGRESO:
      if (estadoSensorIR == LOW) { 
        Serial.println("[*] Vehiculo detectado. Cruzando Talanquera 1...");
        estadoActual = CRUZANDO_INGRESO;
      }
      break;

    case CRUZANDO_INGRESO:
      if (estadoSensorIR == HIGH) { 
        Serial.println("[*] Vehiculo paso. Cerrando T1 e iniciando pesaje...");
        
        cerrarTalanquera1();
        actualizarSemaforos(ROJO, AMARILLO); 
        
        tiempoReferencia = millis();
        estadoActual = SIMULANDO_PESAJE; 
      }
      break;

    case SIMULANDO_PESAJE:
      if (millis() - tiempoReferencia >= tiempoSimulacionPesaje) {
        actualizarSemaforos(ROJO, VERDE); 
        
        if (turnoIzquierda) {
          Serial.println("[*] Pesaje validado. Semáforo 2 VERDE. Dirigiendo a la IZQUIERDA.");
          apuntarIzquierdaTalanquera2();
        } else {
          Serial.println("[*] Pesaje validado. Semáforo 2 VERDE. Dirigiendo a la DERECHA.");
          apuntarDerechaTalanquera2();
        }
        
        tiempoReferencia = millis();
        estadoActual = SALIDA_AUTORIZADA;
      }
      break;

    case SALIDA_AUTORIZADA:
      if (millis() - tiempoReferencia >= tiempoSalidaCamion) {
        Serial.println("[*] Vehiculo salio. Centrando sistema...");
        
        centrarTalanquera2();
        actualizarSemaforos(ROJO, ROJO); 
        
        turnoIzquierda = !turnoIzquierda; 
        
        tiempoReferencia = millis();
        estadoActual = REINICIANDO_SISTEMA;
      }
      break;

    case REINICIANDO_SISTEMA:
      if (millis() - tiempoReferencia >= tiempoReinicioCiclo) {
        Serial.println("===== LISTO PARA NUEVO VEHICULO =====");
        
        abrirTalanquera1();
        actualizarSemaforos(VERDE, ROJO);
        
        estadoActual = ESPERANDO_INGRESO;
      }
      break;
  }
}

// --- Funciones de Control de Hardware ---

void abrirTalanquera1() { talanquera1.write(90); }
void cerrarTalanquera1() { talanquera1.write(0); }

// Talanquera 2: 90 grados es el centro
void centrarTalanquera2() { talanquera2.write(67); }
void apuntarIzquierdaTalanquera2() { talanquera2.write(150); }
void apuntarDerechaTalanquera2() { talanquera2.write(0); }

// Función para semáforos
void actualizarSemaforos(byte estadoTalanquera1, byte estadoTalanquera2) {
  digitalWrite(PIN_LATCH, LOW);
  shiftOut(PIN_DATA, PIN_CLOCK, MSBFIRST, estadoTalanquera2);
  shiftOut(PIN_DATA, PIN_CLOCK, MSBFIRST, estadoTalanquera1);
  digitalWrite(PIN_LATCH, HIGH);
}