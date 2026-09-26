// ============================================================
// PORTUS - Módulo Grúa: Ciclo completo eje X + eje Y + Electroimán
// HOME = posición del patio (deposita) | DERECHA = zona de transferencia (recoge)
// ============================================================

// --- Motor X (ULN2003) ---
const int pinIN1_X = 13;
const int pinIN2_X = 12;
const int pinIN3_X = 11;
const int pinIN4_X = 10;

// --- Motor Y (ULN2003) ---
const int pinIN1_Y = 9;
const int pinIN2_Y = 8;
const int pinIN3_Y = 7;
const int pinIN4_Y = 6;

const int matrizPasos[8][4] = {
  {1, 0, 0, 0},
  {1, 1, 0, 0},
  {0, 1, 0, 0},
  {0, 1, 1, 0},
  {0, 0, 1, 0},
  {0, 0, 1, 1},
  {0, 0, 0, 1},
  {1, 0, 0, 1}
};

// --- Control motor X ---
unsigned long tiempoUltimoPasoX = 0;
const unsigned long velocidadX = 1200;
int pasoActualX = 0;
int direccionX = 0; // 0 = detenido, 1 = hacia transferencia, -1 = hacia HOME

// --- Control motor Y (1 = subir, -1 = bajar) ---
unsigned long tiempoUltimoPasoY = 0;
const unsigned long velocidadY = 1200;
int pasoActualY = 0;
int direccionY = 0;
long pasosRestantesY = 0;        // cuenta regresiva para subir
long pasosBajadaContados = 0;    // cuenta cuántos pasos bajó realmente

const long MARGEN_ALTURA_SEGURA = 200; // pasos extra de margen al subir

// --- Finales de carrera del eje X ---
const int pinFinCarreraIzq = A0; // HOME (patio)
const int pinFinCarreraDer = A1; // Zona de transferencia

// --- Switch de contacto del eje Y (en el cabezal) ---
const int pinContactoY = A2;

// --- Sensor IR de presencia ---
const int pinSensorIR = 4;

// --- Sensores ópticos de columna del patio ---
const int NUM_COLUMNAS = 3;
const int NUM_NIVELES = 2;
const int pinSensorCol[NUM_COLUMNAS] = {2, 3, A3};

enum EstadoPosicion { LIBRE, RESERVADA, OCUPADA, BLOQUEADA };
EstadoPosicion patio[NUM_COLUMNAS][NUM_NIVELES];
int contenedorEnPosicion[NUM_COLUMNAS][NUM_NIVELES];

int columnaDestino = -1;
int nivelDestino = 0;

// --- Protección de pérdida de referencia en X ---
long pasosEnTransitoX = 0;
const long MAX_PASOS_ENTRE_MARCAS = 3000; // ajustar según calibración real

// --- Electroimán (MOSFET) ---
const int pinElectroiman = 5;

// --- Estados del ciclo completo ---
enum EstadoGrua {
  REFERENCIANDO,
  ESPERANDO_CAMION,
  MOVIENDO_A_TRANSFERENCIA,
  BAJANDO_RECOGER,
  AGARRANDO,
  SUBIENDO_CON_CARGA,
  BUSCANDO_COLUMNA,
  MOVIENDO_A_COLUMNA,
  BAJANDO_DEPOSITAR,
  SOLTANDO,
  SUBIENDO_VACIO,
  REGRESANDO_A_HOME,
  PERDIDA_REFERENCIA,
  PATIO_LLENO
};

EstadoGrua estado = REFERENCIANDO;

unsigned long tiempoInicioAccion = 0;
const unsigned long duracionAccionSimulada = 1000;

void setup() {
  Serial.begin(9600);

  pinMode(pinIN1_X, OUTPUT); pinMode(pinIN2_X, OUTPUT);
  pinMode(pinIN3_X, OUTPUT); pinMode(pinIN4_X, OUTPUT);

  pinMode(pinIN1_Y, OUTPUT); pinMode(pinIN2_Y, OUTPUT);
  pinMode(pinIN3_Y, OUTPUT); pinMode(pinIN4_Y, OUTPUT);

  pinMode(pinFinCarreraIzq, INPUT_PULLUP);
  pinMode(pinFinCarreraDer, INPUT_PULLUP);
  pinMode(pinContactoY, INPUT_PULLUP);
  pinMode(pinSensorIR, INPUT);

  for (int i = 0; i < NUM_COLUMNAS; i++) {
    pinMode(pinSensorCol[i], INPUT);
  }

  pinMode(pinElectroiman, OUTPUT);
  digitalWrite(pinElectroiman, LOW);

  inicializarPatio();

  Serial.println("===== PORTUS - Grua: referenciando hacia HOME =====");
  direccionX = -1;
}

void loop() {
  actualizarMotorX();
  actualizarMotorY();
  manejarEstados();
}

// ============================================================
// Inicialización del patio
// ============================================================
void inicializarPatio() {
  for (int col = 0; col < NUM_COLUMNAS; col++) {
    for (int niv = 0; niv < NUM_NIVELES; niv++) {
      patio[col][niv] = LIBRE;
      contenedorEnPosicion[col][niv] = 0;
    }
  }
}

bool buscarPosicionLibre(int &col_out, int &niv_out) {
  for (int col = 0; col < NUM_COLUMNAS; col++) {
    if (patio[col][0] == LIBRE) {
      col_out = col;
      niv_out = 0;
      return true;
    }
  }
  for (int col = 0; col < NUM_COLUMNAS; col++) {
    if (patio[col][0] == OCUPADA && patio[col][1] == LIBRE) {
      col_out = col;
      niv_out = 1;
      return true;
    }
  }
  return false;
}

int leerColumnaActual() {
  for (int col = 0; col < NUM_COLUMNAS; col++) {
    if (digitalRead(pinSensorCol[col]) == LOW) { // ajustar según pruebas
      return col;
    }
  }
  return -1;
}

// ============================================================
// Máquina de estados principal
// ============================================================
void manejarEstados() {
  switch (estado) {

    case REFERENCIANDO:
      if (digitalRead(pinFinCarreraIzq) == LOW) {
        detenerMotorX();
        Serial.println("Referenciado completo. HOME establecido.");
        estado = ESPERANDO_CAMION;
      }
      break;

    case ESPERANDO_CAMION:
      if (camionDetectado()) {
        Serial.println("Camion detectado. Moviendo hacia zona de transferencia...");
        direccionX = 1;
        pasosEnTransitoX = 0;
        estado = MOVIENDO_A_TRANSFERENCIA;
      }
      break;

    case MOVIENDO_A_TRANSFERENCIA:
      if (digitalRead(pinFinCarreraDer) == LOW) {
        detenerMotorX();
        Serial.println("Llego a transferencia. Bajando para recoger...");
        pasosBajadaContados = 0;
        direccionY = -1; // bajar
        estado = BAJANDO_RECOGER;
      }
      break;

    case BAJANDO_RECOGER:
      if (digitalRead(pinContactoY) == LOW) {
        detenerMotorY();
        Serial.print("Contacto detectado. Pasos bajados: ");
        Serial.println(pasosBajadaContados);
        Serial.println("Energizando electroiman...");
        activarElectroiman();
        tiempoInicioAccion = millis();
        estado = AGARRANDO;
      }
      break;

    case AGARRANDO:
      if (millis() - tiempoInicioAccion >= duracionAccionSimulada) {
        Serial.println("Contenedor agarrado. Subiendo a altura segura...");
        direccionY = 1; // subir
        pasosRestantesY = pasosBajadaContados + MARGEN_ALTURA_SEGURA;
        estado = SUBIENDO_CON_CARGA;
      }
      break;

    case SUBIENDO_CON_CARGA:
      if (pasosRestantesY <= 0) {
        detenerMotorY();
        Serial.println("Altura segura alcanzada. Buscando posicion en patio...");
        estado = BUSCANDO_COLUMNA;
      }
      break;

    case BUSCANDO_COLUMNA:
      if (buscarPosicionLibre(columnaDestino, nivelDestino)) {
        Serial.print("Posicion libre encontrada. Columna: ");
        Serial.print(columnaDestino);
        Serial.print(" Nivel: ");
        Serial.println(nivelDestino);

        patio[columnaDestino][nivelDestino] = RESERVADA;

        direccionX = -1; // moviendo desde transferencia hacia HOME/patio
        pasosEnTransitoX = 0;
        estado = MOVIENDO_A_COLUMNA;
      } else {
        Serial.println("Patio lleno. No hay posicion disponible.");
        estado = PATIO_LLENO;
      }
      break;

    case MOVIENDO_A_COLUMNA: {
      int colDetectada = leerColumnaActual();
      if (colDetectada == columnaDestino) {
        detenerMotorX();
        Serial.print("Llego a columna ");
        Serial.println(colDetectada);
        Serial.println("Bajando para depositar...");
        pasosBajadaContados = 0;
        direccionY = -1;
        estado = BAJANDO_DEPOSITAR;
      }
      break;
    }

    case BAJANDO_DEPOSITAR:
      if (digitalRead(pinContactoY) == LOW) {
        detenerMotorY();
        Serial.print("Contacto detectado. Pasos bajados: ");
        Serial.println(pasosBajadaContados);
        Serial.println("Liberando electroiman...");
        desactivarElectroiman();
        tiempoInicioAccion = millis();
        estado = SOLTANDO;
      }
      break;

    case SOLTANDO:
      if (millis() - tiempoInicioAccion >= duracionAccionSimulada) {
        // Confirmar colocación y actualizar inventario
        patio[columnaDestino][nivelDestino] = OCUPADA;
        contenedorEnPosicion[columnaDestino][nivelDestino] = 1; // placeholder de ID real
        Serial.println("Contenedor depositado. Inventario actualizado.");
        Serial.println("Subiendo sin carga...");
        direccionY = 1;
        pasosRestantesY = pasosBajadaContados + MARGEN_ALTURA_SEGURA;
        estado = SUBIENDO_VACIO;
      }
      break;

    case SUBIENDO_VACIO:
      if (pasosRestantesY <= 0) {
        detenerMotorY();
        Serial.println("Regresando a HOME...");
        direccionX = -1;
        pasosEnTransitoX = 0;
        estado = REGRESANDO_A_HOME;
      }
      break;

    case REGRESANDO_A_HOME:
      if (digitalRead(pinFinCarreraIzq) == LOW) {
        detenerMotorX();
        Serial.println("Ciclo completo. Esperando nuevo camion...");
        estado = ESPERANDO_CAMION;
      }
      break;

    case PERDIDA_REFERENCIA:
      Serial.println("ERROR: Perdida de referencia. Re-referenciando...");
      direccionX = -1;
      pasosEnTransitoX = 0;
      estado = REFERENCIANDO;
      break;

    case PATIO_LLENO:
      // Aquí se podría notificar al sistema principal / pantalla
      // Por ahora se queda detenido
      break;
  }

  // --- Verificación de pérdida de referencia en tránsito hacia columna ---
  if (estado == MOVIENDO_A_COLUMNA && pasosEnTransitoX > MAX_PASOS_ENTRE_MARCAS) {
    detenerMotorX();
    estado = PERDIDA_REFERENCIA;
  }
}

// ============================================================
// Sensor de presencia (IR)
// ============================================================
bool camionDetectado() {
  return digitalRead(pinSensorIR) == LOW;
}

// ============================================================
// Electroimán (MOSFET)
// ============================================================
void activarElectroiman() {
  digitalWrite(pinElectroiman, HIGH);
}

void desactivarElectroiman() {
  digitalWrite(pinElectroiman, LOW);
}

// ============================================================
// Motor X (no bloqueante, con protección de límites)
// ============================================================
void actualizarMotorX() {
  if (direccionX == 0) return;

  bool tocoIzquierdo = (digitalRead(pinFinCarreraIzq) == LOW);
  bool tocoDerecho   = (digitalRead(pinFinCarreraDer) == LOW);

  if (tocoIzquierdo && direccionX == -1) { detenerMotorX(); return; }
  if (tocoDerecho && direccionX == 1) { detenerMotorX(); return; }

  if (micros() - tiempoUltimoPasoX >= velocidadX) {
    tiempoUltimoPasoX = micros();

    digitalWrite(pinIN1_X, matrizPasos[pasoActualX][0]);
    digitalWrite(pinIN2_X, matrizPasos[pasoActualX][1]);
    digitalWrite(pinIN3_X, matrizPasos[pasoActualX][2]);
    digitalWrite(pinIN4_X, matrizPasos[pasoActualX][3]);

    pasoActualX += direccionX;
    if (pasoActualX > 7) pasoActualX = 0;
    if (pasoActualX < 0) pasoActualX = 7;

    pasosEnTransitoX++;
  }
}

void detenerMotorX() {
  direccionX = 0;
  digitalWrite(pinIN1_X, LOW);
  digitalWrite(pinIN2_X, LOW);
  digitalWrite(pinIN3_X, LOW);
  digitalWrite(pinIN4_X, LOW);
}

// ============================================================
// Motor Y (no bloqueante) - 1 = subir, -1 = bajar
// ============================================================
void actualizarMotorY() {
  if (direccionY == 0) return;

  if (direccionY == 1 && pasosRestantesY <= 0) {
    detenerMotorY();
    return;
  }
  if (direccionY == -1 && digitalRead(pinContactoY) == LOW) {
    return; // el estado principal se encarga de detenerlo y avanzar de fase
  }

  if (micros() - tiempoUltimoPasoY >= velocidadY) {
    tiempoUltimoPasoY = micros();

    digitalWrite(pinIN1_Y, matrizPasos[pasoActualY][0]);
    digitalWrite(pinIN2_Y, matrizPasos[pasoActualY][1]);
    digitalWrite(pinIN3_Y, matrizPasos[pasoActualY][2]);
    digitalWrite(pinIN4_Y, matrizPasos[pasoActualY][3]);

    pasoActualY += direccionY;
    if (pasoActualY > 7) pasoActualY = 0;
    if (pasoActualY < 0) pasoActualY = 7;

    if (direccionY == 1) pasosRestantesY--;
    if (direccionY == -1) pasosBajadaContados++;
  }
}

void detenerMotorY() {
  direccionY = 0;
  digitalWrite(pinIN1_Y, LOW);
  digitalWrite(pinIN2_Y, LOW);
  digitalWrite(pinIN3_Y, LOW);
  digitalWrite(pinIN4_Y, LOW);
}
