#include <SPI.h>
#include <MFRC522.h>
#include <Servo.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <HX711.h>
#include <string.h>
#include <stdlib.h>

// ============================================================
// PORTUS - SISTEMA INTEGRADO
// Arduino Mega 2560
// Version Fase 2 v0.2 (RAM optimizada): conserva toda la logica estable de Fase 1
// conserva la logica de v0.1 y mueve mensajes Serial constantes a FLASH con F().
// Agrega protocolo serial PORTUS para Raspberry Pi:
// v0.3: agrega eventos estructurados de GARITA/RFID para MQTT.
// v0.4: la validacion de acceso pasa al servidor. El Mega conserva
//       los enclavamientos fisicos y cachea la operacion autorizada
//       para poder completar turnos ya ingresados si se pierde red.
// v0.5: publica EVT PESAJE estructurado y aplica canal rojo despues
//       del pesaje de entrada. SQLite/servidor conserva el estado
//       documental, el turno y la plaza logica de retencion.
// v0.6: agrega AgujaLiberar remoto con ACK/NACK, tercer estado fisico
//       de la aguja y reanudacion segura de turnos retenidos.
// v0.9: eventos TRANSFERENCIA/SALIDA confirmados para sincronizar turnos;
// v1.0 F3: iluminación D34, baliza D35, GaritaResultado, timeout manual;
//       no modifica logica ni pines de grua.
// receptor no bloqueante + CRC-16/CCITT + secuencia + ACK/NACK
// + PING/PONG + heartbeat cada 5 s.
// Los comandos manuales de Fase 1 se conservan temporalmente.
// ============================================================

// -------------------- RFID RC522 -----------------------------
const byte PIN_RFID_SS = 53;
const byte PIN_RFID_RST = 49;
MFRC522 rfid(PIN_RFID_SS, PIN_RFID_RST);

const byte NUM_CAMIONES = 6;

struct Camion {
  byte id;
  byte uid[4];
  const char *placa;
  float tara;
  bool autorizado;
};

// Placas internas de demostracion.
// Si luego tienen placas reales, solo se cambian aqui.
Camion camiones[NUM_CAMIONES] = {
  {1, {0x32, 0x2C, 0x45, 0x07}, "CAM-01", 23.9, true},
  {2, {0xEA, 0x22, 0x53, 0x05}, "CAM-02", 23.9, true},
  {3, {0x40, 0x9A, 0x95, 0x58}, "CAM-03", 23.9, true},
  {4, {0xE1, 0x58, 0xF3, 0xB0}, "CAM-04", 23.9, true},
  {5, {0xE1, 0x16, 0xF9, 0xB0}, "CAM-05", 23.9, true},
  {6, {0x59, 0xCF, 0x92, 0x29}, "CAM-06", 23.9, true}
};

// -------------------- LCD I2C -------------------------------
LiquidCrystal_I2C lcdGarita(0x27, 16, 2);
LiquidCrystal_I2C lcdSalida(0x23, 16, 2);

// -------------------- Servomotores --------------------------
Servo servoEntrada;
Servo servoDesviador;
Servo servoSalida;

const byte PIN_ENTRADA = 3;
const byte PIN_DESVIADOR = 5;
const byte PIN_SALIDA = 6;

const int ENTRADA_CERRADA = 90;
const int ENTRADA_ABIERTA = 180;
const int RUTA_NORMAL = 90;
const int RUTA_RETENIDA = 180;
const int RUTA_LIBERAR = 0;
const int SALIDA_CERRADA = 90;
const int SALIDA_ABIERTA = 0;

// -------------------- Semaforos -----------------------------
const byte GARITA_ROJO = 26;
const byte GARITA_VERDE = 27;
const byte TRANSFERENCIA_ROJO = 24;
const byte TRANSFERENCIA_VERDE = 25;
const byte SALIDA_ROJO = 22;
const byte SALIDA_VERDE = 23;
// Fase 3 - libre de las conexiones actuales. NO alimentar tira LED desde Mega.
const byte PIN_ILUMINACION = 34;  // señal lógica a módulo MOSFET/relé
const byte PIN_BALIZA_CLIMA = 35; // LED ámbar con resistencia adecuada
bool luzEncendida = true;
bool fotoEnCurso = false;
bool balizaClima = false;
unsigned long ultimoComandoServidorF3 = 0;
unsigned long ultimoParpadeoBaliza = 0;
bool nivelBaliza = false;
const unsigned long MAX_TIEMPO_COMUNICACION_F3 = 15000UL;
unsigned long esperaVerificacionF3 = 10000UL;
bool garitaEsperandoManual = false;
char placaF3[17] = "";
bool placaVerificadaF3 = false;
bool segundoFactorCompletadoF3 = false;
void actualizarSalidasFase3();
void enviarEventoIluminacionF3();

enum ColorSemaforo { APAGADO, ROJO, AMARILLO, VERDE };

// -------------------- Sensores IR ---------------------------
const byte SENSOR_ENTRADA = 28;
const byte SENSOR_SALIDA = 29;
const byte SENSOR_ESPERA = 30;
const byte SENSOR_RETENIDOS = 31;
const unsigned long TIEMPO_FILTRO_IR = 250;

struct SensorFiltrado {
  byte pin;
  bool lecturaAnterior;
  bool estadoEstable;
  unsigned long momentoCambio;
};

SensorFiltrado irEntrada = {SENSOR_ENTRADA, false, false, 0};
SensorFiltrado irSalida = {SENSOR_SALIDA, false, false, 0};
SensorFiltrado irEspera = {SENSOR_ESPERA, false, false, 0};
SensorFiltrado irRetenidos = {SENSOR_RETENIDOS, false, false, 0};

// -------------------- Operaciones / turnos ------------------
enum TipoOperacion {
  OPERACION_DEPOSITO,
  OPERACION_RETIRO
};

enum TipoPesaje {
  PESAJE_INICIAL,
  PESAJE_FINAL
};

enum EstadoTurno {
  TURNO_SIN_INICIAR,
  TURNO_ESPERANDO_PESAJE_INICIAL,
  TURNO_APROBADO_TRANSFERENCIA,
  TURNO_EN_TRANSFERENCIA,
  TURNO_ESPERANDO_PESAJE_FINAL,
  TURNO_LISTO_SALIDA,
  TURNO_RETENIDO,
  TURNO_SALIENDO,
  TURNO_FINALIZADO
};

enum EstadoManifiesto {
  MANIFIESTO_PENDIENTE,
  MANIFIESTO_EN_CURSO,
  MANIFIESTO_RETENIDO,
  MANIFIESTO_FINALIZADO
};

enum UbicacionContenedor {
  CONTENEDOR_EN_CAMION,
  CONTENEDOR_EN_PATIO,
  CONTENEDOR_EN_TRANSFERENCIA,
  CONTENEDOR_UBICACION_DESCONOCIDA
};

struct Contenedor {
  byte id;
  float pesoDeclarado;
  UbicacionContenedor ubicacion;
};

struct Manifiesto {
  int id;
  byte camionId;
  byte contenedorId;
  TipoOperacion operacion;
  float pesoDeclarado;
  float tolerancia;
  bool canalRojo;
  EstadoManifiesto estado;
};

struct Turno {
  int id;
  int manifiestoIndex;
  EstadoTurno estado;
};

// Todos los contenedores fisicos utilizados en las pruebas pesan
// aproximadamente lo mismo. La ubicacion es informacion local;
// el controlador de la grua podra sincronizarla posteriormente.
const byte NUM_CONTENEDORES = 6;
Contenedor contenedores[NUM_CONTENEDORES] = {
  {1, 13.3, CONTENEDOR_EN_PATIO},
  {2, 13.3, CONTENEDOR_EN_CAMION},
  {3, 13.3, CONTENEDOR_EN_PATIO},
  {4, 13.3, CONTENEDOR_EN_PATIO},
  {5, 13.3, CONTENEDOR_EN_CAMION},
  {6, 13.3, CONTENEDOR_EN_CAMION}
};

// Fase 2 v0.4: estos seis registros YA NO son manifiestos precargados.
// Son un cache operativo, un slot por camion, que se llena solamente
// cuando la Raspberry autoriza el ingreso mediante AbrirTalanquera.
// De esta forma la fuente de verdad documental pasa a SQLite/servidor,
// mientras el Mega conserva la ultima informacion necesaria para
// completar de forma segura un turno que ya ingreso.
const byte NUM_MANIFIESTOS = NUM_CAMIONES;
Manifiesto manifiestos[NUM_MANIFIESTOS] = {
  {0, 1, 0, OPERACION_DEPOSITO, 0.0, 0.0, false, MANIFIESTO_FINALIZADO},
  {0, 2, 0, OPERACION_DEPOSITO, 0.0, 0.0, false, MANIFIESTO_FINALIZADO},
  {0, 3, 0, OPERACION_DEPOSITO, 0.0, 0.0, false, MANIFIESTO_FINALIZADO},
  {0, 4, 0, OPERACION_DEPOSITO, 0.0, 0.0, false, MANIFIESTO_FINALIZADO},
  {0, 5, 0, OPERACION_DEPOSITO, 0.0, 0.0, false, MANIFIESTO_FINALIZADO},
  {0, 6, 0, OPERACION_DEPOSITO, 0.0, 0.0, false, MANIFIESTO_FINALIZADO}
};

Turno turnos[NUM_CAMIONES] = {
  {0, -1, TURNO_SIN_INICIAR},
  {0, -1, TURNO_SIN_INICIAR},
  {0, -1, TURNO_SIN_INICIAR},
  {0, -1, TURNO_SIN_INICIAR},
  {0, -1, TURNO_SIN_INICIAR},
  {0, -1, TURNO_SIN_INICIAR}
};

int siguienteTurnoId = 1;

// El manifiesto se selecciona al leer el RFID, pero solo pasa a
// EN_CURSO cuando el camion cruza completamente la talanquera.
int manifiestoCandidatoActual = -1;
int turnoServidorCandidato = 0;

int camionEnTransferencia = 0;
int camionEnSalida = 0;
int camionRetenidoEsperandoConfirmacion = 0;
int camionLiberandoRetenido = 0;

// -------------------- Protocolo serial Fase 2 ----------------
// Trama:
// $PORTUS|ORIGEN|SEQ|TIPO|NOMBRE|DATOS|CRC\n
//
// ORIGEN:
// S = Server (Raspberry Pi)
// C = Controller (Arduino Mega)
//
// El CRC se calcula sobre todo el cuerpo sin '$' y sin el
// separador final que antecede al CRC.
// Ejemplo de cuerpo:
// PORTUS|S|1|CMD|PING|
//
// Durante esta version de integracion se mantienen los mensajes
// de diagnostico de Fase 1 en texto plano. La Raspberry debe
// considerar trama de protocolo solo una linea que comience con
// "$PORTUS|".
const size_t PORTUS_RX_MAX = 256;
char portusRxBuffer[PORTUS_RX_MAX];
size_t portusRxPos = 0;
bool portusRecibiendoTrama = false;

unsigned long secuenciaControladorPortus = 1;
unsigned long ultimoHeartbeatPortus = 0;
const unsigned long INTERVALO_HEARTBEAT_PORTUS = 5000UL;

// -------------------- Pesaje dinamico -----------------------
const byte PIN_HX711_DT = 32;
const byte PIN_HX711_SCK = 33;
const float FACTOR_CALIBRACION = 706.0;

const float UMBRAL_INICIO_PESAJE = 8.0;
const float UMBRAL_FIN_PESAJE = 5.0;
const float UMBRAL_CERO_REARME = 5.0;
const float PESO_MINIMO_MESETA = 12.0;
const float RANGO_MAXIMO_ESTABLE = 2.0;

const byte NUM_MUESTRAS_ESTABLES = 9;
const byte LECTURAS_PARA_INICIAR = 3;
const byte LECTURAS_PARA_LIBERAR = 3;
const byte LECTURAS_CERO_REARME = 5;

HX711 bascula;
bool hx711Disponible = false;

enum EstadoBascula { BASCULA_LIBRE, PESAJE_EN_CURSO };
EstadoBascula estadoBascula = BASCULA_LIBRE;

float ventanaPeso[NUM_MUESTRAS_ESTABLES];
byte cantidadMuestrasPeso = 0;
byte lecturasSobreUmbral = 0;
byte lecturasBajoUmbral = 0;
byte lecturasCeroRearme = 0;
bool basculaArmada = false;
bool resultadoPesajeGenerado = false;

int camionPendientePesaje = 0;
TipoPesaje tipoPesajePendiente = PESAJE_INICIAL;
TipoPesaje tipoPesajeActual = PESAJE_INICIAL;

// -------------------- Tiempos -------------------------------
const unsigned long TIEMPO_VALIDACION = 2000;
const unsigned long TIEMPO_RESPUESTA_SERVIDOR = 10000; // parámetro F3 ajustable por GaritaResultado CONFIG
const unsigned long TIEMPO_MAX_PASO = 15000;
const unsigned long TIEMPO_MENSAJE = 1500;

// -------------------- Entrada -------------------------------
enum EstadoEntrada {
  ESPERANDO_RFID,
  VALIDANDO_ENTRADA,
  ENTRADA_DENEGADA,
  ESPERANDO_PASO_ENTRADA,
  CAMION_BAJO_ENTRADA,
  FINALIZANDO_ENTRADA
};

EstadoEntrada estadoEntrada = ESPERANDO_RFID;
unsigned long inicioEstadoEntrada = 0;
int camionActual = 0;

// -------------------- Salida --------------------------------
enum EstadoSalida {
  ESPERANDO_AUTORIZACION_SALIDA,
  VALIDANDO_SALIDA,
  ESPERANDO_PASO_SALIDA,
  CAMION_BAJO_SALIDA,
  FINALIZANDO_SALIDA
};

EstadoSalida estadoSalida = ESPERANDO_AUTORIZACION_SALIDA;
unsigned long inicioEstadoSalida = 0;

// ============================================================
// PROTOTIPOS
// ============================================================
void manejarEntrada();
void prepararSiguienteEntrada();
void iniciarTransferencia();
void finalizarTransferencia();
void autorizarSalida();
void manejarSalida();
void prepararSiguienteSalida();
int leerCamionRFID();
void leerComandosSeriales();
void procesarByteSerial(char caracter);
void procesarComandoLegacy(char comando);
void procesarTramaPortus(char *trama);
uint16_t crc16CcittPortus(const char *texto);
void enviarTramaPortus(const char *tipo, const char *nombre, const char *datos);
void enviarAckPortus(unsigned long secuenciaServidor, const char *nombre, const char *mensaje);
void enviarNackPortus(unsigned long secuenciaServidor, const char *nombre, const char *motivo);
bool obtenerParametroPortus(const char *datos, const char *clave, char *destino, size_t tamDestino);
int extraerNumeroConPrefijo(const char *texto, char prefijo);
const char *textoCausaGarita(const char *causa);
void enviarEventoGaritaRFID(int camion);
void enviarEventoGaritaDecision(int camion, bool autorizada, const char *causa);
void enviarEventoGaritaIngreso(int camion, const char *resultado);
void enviarEventoPesaje(int camion, TipoPesaje tipo, float pesoMedido, float pesoEsperado, float diferencia, const char *resultado);
void enviarEventoAguja(const char *estado, int camion, int turnoId, const char *detalle);
void enviarEventoProceso(const char *nombre, const char *accion, int camion);
void actualizarHeartbeatPortus();
void actualizarPesajeDinamico();
void agregarMuestraPeso(float peso);
bool ventanaDePesoEsEstable();
float calcularMedianaPeso();
void evaluarResultadoPesaje(float pesoMedido);
void retenerCamionPorPesaje(const char *motivo);
bool camionTieneTurnoActivo(int camion);
int buscarCamionEnEstado(EstadoTurno estadoBuscado);
int buscarCamionPorTurnoId(int turnoId);

int buscarManifiestoPendienteParaCamion(int camion);
int obtenerIndiceManifiestoActivo(int camion);
void activarTurnoConManifiesto(int camion, int manifiestoIndex, int turnoServidorId);
void finalizarManifiestoDeCamion(int camion);
void retenerManifiestoDeCamion(int camion);
const char *textoOperacion(TipoOperacion operacion);
const char *textoEstadoManifiesto(EstadoManifiesto estado);
void mostrarManifiestos();

float obtenerPesoEsperado(int camion, TipoPesaje tipo);
const char *textoEstadoTurno(EstadoTurno estado);
void mostrarEstadoTurnos();
void ponerSemaforo(byte pinRojo, byte pinVerde, ColorSemaforo color);
void iniciarSensor(SensorFiltrado &sensor);
bool actualizarSensor(SensorFiltrado &sensor);
void manejarCambioSensorEspera();
void manejarCambioSensorRetenidos();
void mostrarEstadoEspera();
void mostrarEstadoSalidaDisponible();
void mostrarLCD(LiquidCrystal_I2C &lcd, const char *linea1, const char *linea2);
void mostrarCamionEnLCD(int numeroCamion);
void imprimirLinea(LiquidCrystal_I2C &lcd, byte fila, const char *texto);
float valorAbsolutoFloat(float valor);

// ============================================================
// CONFIGURACION
// ============================================================
void setup() {
  Serial.begin(9600);

  pinMode(GARITA_ROJO, OUTPUT);
  pinMode(GARITA_VERDE, OUTPUT);
  pinMode(TRANSFERENCIA_ROJO, OUTPUT);
  pinMode(TRANSFERENCIA_VERDE, OUTPUT);
  pinMode(SALIDA_ROJO, OUTPUT);
  pinMode(SALIDA_VERDE, OUTPUT);
  pinMode(PIN_ILUMINACION, OUTPUT);
  pinMode(PIN_BALIZA_CLIMA, OUTPUT);
  // Seguridad: luz encendida al arranque / falla de servidor.
  digitalWrite(PIN_ILUMINACION, HIGH);
  digitalWrite(PIN_BALIZA_CLIMA, LOW);
  ultimoComandoServidorF3 = millis();

  pinMode(SENSOR_ENTRADA, INPUT);
  pinMode(SENSOR_SALIDA, INPUT);
  pinMode(SENSOR_ESPERA, INPUT);
  pinMode(SENSOR_RETENIDOS, INPUT);

  servoEntrada.attach(PIN_ENTRADA);
  servoDesviador.attach(PIN_DESVIADOR);
  servoSalida.attach(PIN_SALIDA);

  servoEntrada.write(ENTRADA_CERRADA);
  servoDesviador.write(RUTA_NORMAL);
  servoSalida.write(SALIDA_CERRADA);

  ponerSemaforo(GARITA_ROJO, GARITA_VERDE, ROJO);
  ponerSemaforo(TRANSFERENCIA_ROJO, TRANSFERENCIA_VERDE, ROJO);
  ponerSemaforo(SALIDA_ROJO, SALIDA_VERDE, ROJO);

  iniciarSensor(irEntrada);
  iniciarSensor(irSalida);
  iniciarSensor(irEspera);
  iniciarSensor(irRetenidos);

  Wire.begin();
  lcdGarita.init();
  lcdGarita.backlight();
  lcdSalida.init();
  lcdSalida.backlight();

  SPI.begin();
  rfid.PCD_Init();

  bascula.begin(PIN_HX711_DT, PIN_HX711_SCK);
  unsigned long inicioEsperaHX711 = millis();

  while (!bascula.is_ready() && millis() - inicioEsperaHX711 < 2000) {
    delay(10);
  }

  if (bascula.is_ready()) {
    bascula.set_scale(FACTOR_CALIBRACION);
    bascula.tare(20);
    hx711Disponible = true;
    Serial.println(F("HX711 listo. Bascula en cero."));
  } else {
    Serial.println(F("ERROR: HX711 no detectado."));
  }

  mostrarEstadoEspera();
  mostrarEstadoSalidaDisponible();

  Serial.println();
  Serial.println(F("=== PORTUS - SISTEMA INTEGRADO ==="));
  Serial.println(F("A: autorizar salida"));
  Serial.println(F("N: ruta normal manual"));
  Serial.println(F("R: ruta retenida manual"));
  Serial.println(F("T: iniciar transferencia"));
  Serial.println(F("Y: transferencia validando"));
  Serial.println(F("X: detener transferencia"));
  Serial.println(F("F: finalizar transferencia"));
  Serial.println(F("Z: poner bascula en cero"));
  Serial.println(F("S: mostrar estados de turnos"));
  Serial.println(F("M: mostrar manifiestos precargados"));
  Serial.println();
  Serial.println(F("La operacion se obtiene automaticamente del manifiesto."));
  Serial.println(F("Camion 1: prueba de camion identificado SIN manifiesto."));
  Serial.println();
  Serial.println(F("Esperando camion en la zona de espera..."));
  Serial.println(F("Protocolo Fase 2 PORTUS v0.9: GARITA + PESAJE + RETENCIONES + TRANSFERENCIA/SALIDA + ACK/NACK."));
}

void loop() {
  actualizarSensor(irEntrada);
  actualizarSensor(irSalida);

  bool cambioEspera = actualizarSensor(irEspera);
  bool cambioRetenidos = actualizarSensor(irRetenidos);

  if (cambioEspera) manejarCambioSensorEspera();
  if (cambioRetenidos) manejarCambioSensorRetenidos();

  leerComandosSeriales();
  actualizarSalidasFase3();
  manejarEntrada();
  manejarSalida();
  actualizarPesajeDinamico();
  actualizarHeartbeatPortus();
}

// ============================================================
// CONTROL DE ENTRADA
// ============================================================
void manejarEntrada() {
  switch (estadoEntrada) {

    case ESPERANDO_RFID: {
      if (!irEspera.estadoEstable) break;

      // Si un rechazado aun no llego fisicamente al ramal,
      // o el ramal sigue ocupado, no entra otro camion.
      if (camionRetenidoEsperandoConfirmacion != 0 || irRetenidos.estadoEstable) {
        ponerSemaforo(GARITA_ROJO, GARITA_VERDE, AMARILLO);
        mostrarLCD(lcdGarita, "Ramal ocupado", "Espere...");
        break;
      }

      if (camionPendientePesaje != 0 || estadoBascula != BASCULA_LIBRE) {
        ponerSemaforo(GARITA_ROJO, GARITA_VERDE, AMARILLO);
        mostrarLCD(lcdGarita, "Pesaje ocupado", "Espere...");
        break;
      }

      int resultado = leerCamionRFID();

      if (resultado > 0) {
        if (!camiones[resultado - 1].autorizado) {
          Serial.print(F("CAMION "));
          Serial.print(resultado);
          Serial.println(F(" NO AUTORIZADO LOCALMENTE"));
          ponerSemaforo(GARITA_ROJO, GARITA_VERDE, ROJO);
          mostrarLCD(lcdGarita, "NO AUTORIZADO", "Camion bloqueado");
          enviarEventoGaritaDecision(resultado, false, "BLOQUEO_LOCAL");
          inicioEstadoEntrada = millis();
          estadoEntrada = ENTRADA_DENEGADA;
          break;
        }

        if (camionTieneTurnoActivo(resultado)) {
          Serial.print(F("CAMION "));
          Serial.print(resultado);
          Serial.println(F(" YA TIENE UN TURNO ACTIVO"));
          ponerSemaforo(GARITA_ROJO, GARITA_VERDE, ROJO);
          mostrarLCD(lcdGarita, "TURNO ACTIVO", "Ingreso negado");
          enviarEventoGaritaDecision(resultado, false, "TURNO_ACTIVO_LOCAL");
          inicioEstadoEntrada = millis();
          estadoEntrada = ENTRADA_DENEGADA;
          break;
        }

        // La validacion documental YA NO se realiza con registros
        // precargados. El slot del camion queda vacio hasta recibir
        // AbrirTalanquera desde la Raspberry con los datos autorizados.
        camionActual = resultado;
        garitaEsperandoManual = false;
        placaVerificadaF3 = false;
        segundoFactorCompletadoF3 = false;
        placaF3[0] = '\0';
        manifiestoCandidatoActual = resultado - 1;
        turnoServidorCandidato = 0;

        Manifiesto &m = manifiestos[manifiestoCandidatoActual];
        m.id = 0;
        m.camionId = resultado;
        m.contenedorId = 0;
        m.operacion = OPERACION_DEPOSITO;
        m.pesoDeclarado = 0.0;
        m.tolerancia = 0.0;
        m.canalRojo = false;
        m.estado = MANIFIESTO_FINALIZADO;

        Serial.print(F("Camion "));
        Serial.print(camionActual);
        Serial.println(F(" identificado. Esperando decision del servidor..."));

        ponerSemaforo(GARITA_ROJO, GARITA_VERDE, AMARILLO);
        mostrarLCD(lcdGarita, "Validando...", "Servidor PORTUS");

        inicioEstadoEntrada = millis();
        estadoEntrada = VALIDANDO_ENTRADA;
      }
      else if (resultado == -1) {
        Serial.println(F("TARJETA NO AUTORIZADA"));
        ponerSemaforo(GARITA_ROJO, GARITA_VERDE, ROJO);
        mostrarLCD(lcdGarita, "NO AUTORIZADO", "Tarjeta invalida");
        inicioEstadoEntrada = millis();
        estadoEntrada = ENTRADA_DENEGADA;
      }
      break;
    }

    case VALIDANDO_ENTRADA:
      // En Fase 2 la Raspberry decide si el camion puede ingresar.
      // Si no llega una decision, se rechaza el nuevo ingreso; los
      // turnos que ya estan dentro conservan su informacion local.
      if (!garitaEsperandoManual &&
          millis() - inicioEstadoEntrada >= esperaVerificacionF3) {
        // Sin respuesta OCR: exige decisión manual, nunca apertura automática.
        garitaEsperandoManual = true;
        inicioEstadoEntrada = millis();
        mostrarLCD(lcdGarita, "VERIFICACION", "MANUAL / ESPERE");
        Serial.println(F("F3: OCR excedió el tiempo; verificar manualmente"));
      } else if (garitaEsperandoManual &&
                 millis() - inicioEstadoEntrada >= 120000UL) {
        // Expira el intento; el operador deberá repetir la identificación.
        ponerSemaforo(GARITA_ROJO, GARITA_VERDE, ROJO);
        mostrarLCD(lcdGarita, "ACCESO DENEGADO", "TIEMPO VENCIDO");
        enviarEventoGaritaDecision(camionActual, false, "VERIFICACION_EXPIRADA");
        inicioEstadoEntrada = millis();
        estadoEntrada = ENTRADA_DENEGADA;
      }
      break;

    case ENTRADA_DENEGADA:
      if (millis() - inicioEstadoEntrada >= TIEMPO_MENSAJE) {
        prepararSiguienteEntrada();
      }
      break;

    case ESPERANDO_PASO_ENTRADA:
      if (irEntrada.estadoEstable) {
        Serial.println(F("Sensor entrada: OBJETO DETECTADO"));
        Serial.println(F("Camion debajo de la talanquera"));
        mostrarLCD(lcdGarita, "Camion ingresando", "No cerrar");
        estadoEntrada = CAMION_BAJO_ENTRADA;
      }
      else if (millis() - inicioEstadoEntrada >= TIEMPO_MAX_PASO) {
        Serial.println(F("Tiempo agotado. Cerrando entrada"));
        enviarEventoGaritaIngreso(camionActual, "TIEMPO_AGOTADO");
        servoEntrada.write(ENTRADA_CERRADA);
        ponerSemaforo(GARITA_ROJO, GARITA_VERDE, ROJO);
        mostrarLCD(lcdGarita, "Tiempo agotado", "Entrada cerrada");
        inicioEstadoEntrada = millis();
        estadoEntrada = FINALIZANDO_ENTRADA;
      }
      break;

    case CAMION_BAJO_ENTRADA:
      if (!irEntrada.estadoEstable) {
        Serial.println(F("Sensor entrada: LIBRE"));
        Serial.println(F("Camion ingreso completamente"));
        Serial.println(F("Talanquera cerrada"));

        servoEntrada.write(ENTRADA_CERRADA);
        ponerSemaforo(GARITA_ROJO, GARITA_VERDE, ROJO);
        mostrarLCD(lcdGarita, "Ingreso completo", "Ir a pesaje");

        // El turno comienza formalmente solo cuando el camion
        // ya cruzo completamente la talanquera.
        activarTurnoConManifiesto(
          camionActual,
          manifiestoCandidatoActual,
          turnoServidorCandidato
        );

        camionPendientePesaje = camionActual;
        tipoPesajePendiente = PESAJE_INICIAL;

        Serial.print(F("Turno asignado: T"));
        Serial.println(turnos[camionActual - 1].id);

        Serial.print(F("Manifiesto activo: M"));
        Serial.println(
          manifiestos[
            turnos[camionActual - 1].manifiestoIndex
          ].id
        );

        Serial.print(F("Camion pendiente de pesaje inicial: "));
        Serial.println(camionPendientePesaje);
        Serial.print(F("Peso esperado: "));
        Serial.print(obtenerPesoEsperado(camionPendientePesaje, PESAJE_INICIAL), 1);
        Serial.println(F(" g"));

        enviarEventoGaritaIngreso(camionActual, "COMPLETO");

        inicioEstadoEntrada = millis();
        estadoEntrada = FINALIZANDO_ENTRADA;
      }
      break;

    case FINALIZANDO_ENTRADA:
      if (millis() - inicioEstadoEntrada >= TIEMPO_MENSAJE) {
        prepararSiguienteEntrada();
      }
      break;
  }
}

void prepararSiguienteEntrada() {
  camionActual = 0;
  manifiestoCandidatoActual = -1;
  turnoServidorCandidato = 0;
  servoEntrada.write(ENTRADA_CERRADA);
  estadoEntrada = ESPERANDO_RFID;
  mostrarEstadoEspera();

  if (irEspera.estadoEstable) {
    Serial.println(F("Acerque la siguiente tarjeta"));
  } else {
    Serial.println(F("Esperando el siguiente camion"));
  }
}


// ============================================================
// CONTROL DE TRANSFERENCIA
// ============================================================
void iniciarTransferencia() {
  if (camionEnTransferencia != 0) {
    Serial.print(F("Transferencia ocupada por camion "));
    Serial.println(camionEnTransferencia);
    return;
  }

  if (estadoBascula != BASCULA_LIBRE || camionPendientePesaje != 0) {
    Serial.println(F("No se puede iniciar transferencia mientras termina el pesaje."));
    return;
  }

  if (camionRetenidoEsperandoConfirmacion != 0 || irRetenidos.estadoEstable) {
    Serial.println(F("No se puede iniciar transferencia: ramal de retenidos no disponible."));
    return;
  }

  int camion = buscarCamionEnEstado(TURNO_APROBADO_TRANSFERENCIA);

  if (camion == 0) {
    Serial.println(F("No hay camiones aprobados esperando transferencia."));
    return;
  }

  camionEnTransferencia = camion;
  turnos[camion - 1].estado = TURNO_EN_TRANSFERENCIA;

  // Verde unicamente cuando la transferencia realmente fue autorizada.
  ponerSemaforo(TRANSFERENCIA_ROJO, TRANSFERENCIA_VERDE, VERDE);

  Serial.print(F("TRANSFERENCIA AUTORIZADA - Camion "));
  Serial.println(camion);
  Serial.println(F("Realice la operacion con la grua."));
  Serial.println(F("Cuando termine, escriba F."));
  enviarEventoProceso("TRANSFERENCIA", "INICIO", camion);
}

void finalizarTransferencia() {
  if (camionEnTransferencia == 0) {
    Serial.println(F("No hay un camion actualmente en transferencia."));
    return;
  }

  if (estadoBascula != BASCULA_LIBRE || camionPendientePesaje != 0) {
    Serial.println(F("No se puede finalizar: bascula ocupada."));
    return;
  }

  if (camionRetenidoEsperandoConfirmacion != 0 || irRetenidos.estadoEstable) {
    Serial.println(F("No se puede enviar al pesaje final: ramal ocupado."));
    return;
  }

  int camion = camionEnTransferencia;
  camionEnTransferencia = 0;

  turnos[camion - 1].estado = TURNO_ESPERANDO_PESAJE_FINAL;
  camionPendientePesaje = camion;
  tipoPesajePendiente = PESAJE_FINAL;

  ponerSemaforo(TRANSFERENCIA_ROJO, TRANSFERENCIA_VERDE, ROJO);

  Serial.print(F("TRANSFERENCIA FINALIZADA - Camion "));
  Serial.println(camion);
  Serial.println(F("Dirigir camion nuevamente a la bascula."));
  Serial.print(F("Peso esperado en pesaje final: "));
  Serial.print(obtenerPesoEsperado(camion, PESAJE_FINAL), 1);
  Serial.println(F(" g"));

  mostrarLCD(lcdGarita, "Pesaje final", "Dirigir bascula");
  // FIN indica confirmación manual de transferencia, NO confirmación
  // automática de una operación de grúa o posición del inventario.
  enviarEventoProceso("TRANSFERENCIA", "FIN", camion);
}

// ============================================================
// CONTROL DE SALIDA
// ============================================================
void autorizarSalida() {
  if (estadoSalida != ESPERANDO_AUTORIZACION_SALIDA) {
    Serial.println(F("La salida ya esta procesando un camion."));
    return;
  }

  int camion = buscarCamionEnEstado(TURNO_LISTO_SALIDA);

  if (camion == 0) {
    Serial.println(F("SALIDA DENEGADA: no hay camion con pesaje final aprobado."));
    ponerSemaforo(SALIDA_ROJO, SALIDA_VERDE, ROJO);
    mostrarLCD(lcdSalida, "SALIDA BLOQUEADA", "Sin turno valido");
    return;
  }

  camionEnSalida = camion;
  turnos[camion - 1].estado = TURNO_SALIENDO;

  Serial.print(F("Validando salida del camion "));
  Serial.print(camion);
  Serial.println(F("..."));

  ponerSemaforo(SALIDA_ROJO, SALIDA_VERDE, AMARILLO);
  mostrarLCD(lcdSalida, "Validando salida", "Espere...");
  inicioEstadoSalida = millis();
  estadoSalida = VALIDANDO_SALIDA;
}

void manejarSalida() {
  switch (estadoSalida) {
    case ESPERANDO_AUTORIZACION_SALIDA:
      break;

    case VALIDANDO_SALIDA:
      if (irSalida.estadoEstable) {
        Serial.println(F("SALIDA ABORTADA: VEHICULO BAJO PUERTA"));
        servoSalida.write(SALIDA_CERRADA);
        ponerSemaforo(SALIDA_ROJO, SALIDA_VERDE, ROJO);
        if (camionEnSalida >= 1 && camionEnSalida <= NUM_CAMIONES) {
          turnos[camionEnSalida - 1].estado = TURNO_LISTO_SALIDA;
          enviarEventoProceso("SALIDA", "BLOQUEADA_IR", camionEnSalida);
        }
        camionEnSalida = 0;
        estadoSalida = ESPERANDO_AUTORIZACION_SALIDA;
        mostrarLCD(lcdSalida, "SALIDA BLOQUEADA", "Sensor ocupado");
        break;
      }
      if (millis() - inicioEstadoSalida >= TIEMPO_VALIDACION) {
        Serial.print(F("SALIDA AUTORIZADA - Camion "));
        Serial.println(camionEnSalida);
        Serial.println(F("Puerta de salida abierta"));
        Serial.println(F("Esperando paso del camion"));

        servoSalida.write(SALIDA_ABIERTA);
        ponerSemaforo(SALIDA_ROJO, SALIDA_VERDE, VERDE);
        mostrarLCD(lcdSalida, "SALIDA AUTORIZ.", "Puede avanzar");
        enviarEventoProceso("SALIDA", "AUTORIZADA", camionEnSalida);

        inicioEstadoSalida = millis();
        estadoSalida = ESPERANDO_PASO_SALIDA;
      }
      break;

    case ESPERANDO_PASO_SALIDA:
      if (irSalida.estadoEstable) {
        Serial.println(F("Sensor salida: OBJETO DETECTADO"));
        Serial.println(F("Camion debajo de la puerta de salida"));
        mostrarLCD(lcdSalida, "Camion saliendo", "No cerrar");
        estadoSalida = CAMION_BAJO_SALIDA;
      }
      else if (millis() - inicioEstadoSalida >= TIEMPO_MAX_PASO) {
        Serial.println(F("Tiempo agotado. Cerrando salida"));
        enviarEventoProceso("SALIDA", "TIEMPO_AGOTADO", camionEnSalida);
        servoSalida.write(SALIDA_CERRADA);
        ponerSemaforo(SALIDA_ROJO, SALIDA_VERDE, ROJO);

        if (camionEnSalida >= 1 && camionEnSalida <= NUM_CAMIONES) {
          turnos[camionEnSalida - 1].estado = TURNO_LISTO_SALIDA;
        }

        camionEnSalida = 0;
        inicioEstadoSalida = millis();
        estadoSalida = FINALIZANDO_SALIDA;
      }
      break;

    case CAMION_BAJO_SALIDA:
      if (!irSalida.estadoEstable) {
        Serial.println(F("Sensor salida: LIBRE"));
        Serial.println(F("Camion salio completamente"));
        Serial.println(F("Puerta de salida cerrada"));

        servoSalida.write(SALIDA_CERRADA);
        ponerSemaforo(SALIDA_ROJO, SALIDA_VERDE, ROJO);

        if (camionEnSalida >= 1 && camionEnSalida <= NUM_CAMIONES) {
          // Emitir únicamente tras la detección física del IR libre.
          enviarEventoProceso("SALIDA", "COMPLETA", camionEnSalida);
          turnos[camionEnSalida - 1].estado = TURNO_FINALIZADO;
          finalizarManifiestoDeCamion(camionEnSalida);
          Serial.print(F("TURNO FINALIZADO - Camion "));
          Serial.println(camionEnSalida);
        }

        camionEnSalida = 0;
        mostrarLCD(lcdSalida, "Salida completa", "Turno cerrado");

        inicioEstadoSalida = millis();
        estadoSalida = FINALIZANDO_SALIDA;
      }
      break;

    case FINALIZANDO_SALIDA:
      if (millis() - inicioEstadoSalida >= TIEMPO_MENSAJE) {
        prepararSiguienteSalida();
      }
      break;
  }
}

void prepararSiguienteSalida() {
  servoSalida.write(SALIDA_CERRADA);
  ponerSemaforo(SALIDA_ROJO, SALIDA_VERDE, ROJO);
  mostrarEstadoSalidaDisponible();
  Serial.println(F("Escriba A para autorizar una salida habilitada."));
  estadoSalida = ESPERANDO_AUTORIZACION_SALIDA;
}

// ============================================================
// LECTOR RFID
// ============================================================
int leerCamionRFID() {
  if (!rfid.PICC_IsNewCardPresent()) return 0;
  if (!rfid.PICC_ReadCardSerial()) return 0;

  Serial.print(F("UID detectado: "));
  for (byte i = 0; i < rfid.uid.size; i++) {
    if (rfid.uid.uidByte[i] < 0x10) Serial.print('0');
    Serial.print(rfid.uid.uidByte[i], HEX);
    if (i + 1 < rfid.uid.size) Serial.print(' ');
  }
  Serial.println();

  int camion = -1;

  if (rfid.uid.size == 4) {
    for (byte c = 0; c < NUM_CAMIONES; c++) {
      bool coincide = true;

      for (byte i = 0; i < 4; i++) {
        if (rfid.uid.uidByte[i] != camiones[c].uid[i]) {
          coincide = false;
          break;
        }
      }

      if (coincide) {
        camion = c + 1;
        break;
      }
    }
  }

  // Fase 2: cada lectura RFID genera un evento estructurado.
  // Este evento solo informa la identificacion. La autorizacion
  // definitiva de ingreso sera responsabilidad del servidor.
  enviarEventoGaritaRFID(camion);

  rfid.PICC_HaltA();
  rfid.PCD_StopCrypto1();

  return camion;
}

// ============================================================
// COMUNICACION SERIAL - FASE 2 + COMPATIBILIDAD FASE 1
// ============================================================

// Lee solamente los bytes que ya estan disponibles. Nunca espera
// a que una trama termine, por lo que no bloquea el ciclo principal.
void leerComandosSeriales() {
  while (Serial.available() > 0) {
    char caracter = (char)Serial.read();
    procesarByteSerial(caracter);
  }
}


void procesarByteSerial(char caracter) {
  // '$' siempre sincroniza el inicio de una nueva trama.
  // Si una trama anterior llego incompleta, se descarta.
  if (caracter == '$') {
    portusRecibiendoTrama = true;
    portusRxPos = 0;
    portusRxBuffer[portusRxPos++] = caracter;
    return;
  }

  if (portusRecibiendoTrama) {
    // Fin de trama por salto de linea.
    if (caracter == '\n' || caracter == '\r') {
      if (portusRxPos > 0) {
        portusRxBuffer[portusRxPos] = '\0';
        procesarTramaPortus(portusRxBuffer);
      }

      portusRecibiendoTrama = false;
      portusRxPos = 0;
      return;
    }

    // Proteccion ante una trama demasiado larga.
    if (portusRxPos >= PORTUS_RX_MAX - 1) {
      portusRecibiendoTrama = false;
      portusRxPos = 0;
      enviarNackPortus(0, "TRAMA", "BUFFER_RX_LLENO");
      return;
    }

    portusRxBuffer[portusRxPos++] = caracter;
    return;
  }

  // Fuera de una trama PORTUS seguimos aceptando los comandos
  // manuales que ya se utilizaban en Fase 1.
  if (caracter == '\n' || caracter == '\r' ||
      caracter == ' '  || caracter == '\t') {
    return;
  }

  procesarComandoLegacy(caracter);
}


// CRC-16/CCITT-FALSE
// Polinomio: 0x1021
// Inicial:    0xFFFF
// Debe producir exactamente el mismo resultado que protocolo_portus.py.
uint16_t crc16CcittPortus(const char *texto) {
  uint16_t crc = 0xFFFF;

  while (*texto != '\0') {
    crc ^= ((uint16_t)(uint8_t)(*texto)) << 8;

    for (byte bit = 0; bit < 8; bit++) {
      if (crc & 0x8000) {
        crc = (uint16_t)((crc << 1) ^ 0x1021);
      } else {
        crc = (uint16_t)(crc << 1);
      }
    }

    texto++;
  }

  return crc;
}


void procesarTramaPortus(char *trama) {
  // Minimo esperado: $PORTUS|...
  if (strncmp(trama, "$PORTUS|", 8) != 0) {
    enviarNackPortus(0, "TRAMA", "PREFIJO_INVALIDO");
    return;
  }

  // El ultimo '|' separa el cuerpo del CRC.
  char *ultimoSeparador = strrchr(trama, '|');

  if (ultimoSeparador == NULL || ultimoSeparador <= trama + 7) {
    enviarNackPortus(0, "TRAMA", "FORMATO_INVALIDO");
    return;
  }

  char *crcTexto = ultimoSeparador + 1;

  if (strlen(crcTexto) != 4) {
    enviarNackPortus(0, "TRAMA", "CRC_INVALIDO");
    return;
  }

  char *finCrc = NULL;
  unsigned long crcRecibido = strtoul(crcTexto, &finCrc, 16);

  if (finCrc == crcTexto || *finCrc != '\0' || crcRecibido > 0xFFFFUL) {
    enviarNackPortus(0, "TRAMA", "CRC_INVALIDO");
    return;
  }

  // Cortamos temporalmente antes del CRC.
  *ultimoSeparador = '\0';

  // El cuerpo comienza despues de '$'.
  const char *cuerpo = trama + 1;
  uint16_t crcCalculado = crc16CcittPortus(cuerpo);

  if (crcCalculado != (uint16_t)crcRecibido) {
    enviarNackPortus(0, "TRAMA", "CRC_NO_COINCIDE");
    return;
  }

  // El cuerpo valido debe tener exactamente seis campos:
  // PORTUS | ORIGEN | SEQ | TIPO | NOMBRE | DATOS
  char *campos[6];
  byte cantidadCampos = 1;
  campos[0] = trama + 1;

  for (char *p = trama + 1; *p != '\0'; p++) {
    if (*p == '|') {
      if (cantidadCampos >= 6) {
        enviarNackPortus(0, "TRAMA", "FORMATO_INVALIDO");
        return;
      }

      *p = '\0';
      campos[cantidadCampos++] = p + 1;
    }
  }

  if (cantidadCampos != 6) {
    enviarNackPortus(0, "TRAMA", "FORMATO_INVALIDO");
    return;
  }

  if (strcmp(campos[0], "PORTUS") != 0) {
    enviarNackPortus(0, "TRAMA", "PROTOCOLO_INVALIDO");
    return;
  }

  char *finSecuencia = NULL;
  unsigned long secuenciaServidor = strtoul(campos[2], &finSecuencia, 10);

  if (finSecuencia == campos[2] || *finSecuencia != '\0') {
    enviarNackPortus(0, "TRAMA", "SECUENCIA_INVALIDA");
    return;
  }

  if (strcmp(campos[1], "S") != 0) {
    enviarNackPortus(secuenciaServidor, "TRAMA", "ORIGEN_INVALIDO");
    return;
  }

  if (strcmp(campos[3], "CMD") != 0) {
    enviarNackPortus(secuenciaServidor, campos[4], "TIPO_INVALIDO");
    return;
  }
  ultimoComandoServidorF3 = millis();

  // ----------------------------------------------------------
  // CATALOGO DE COMANDOS FASE 2 - GARITA v0.4
  // ----------------------------------------------------------
  if (strcmp(campos[4], "PING") == 0) {
    enviarAckPortus(secuenciaServidor, "PING", "PONG");
    return;
  }

  // ----------------------------------------------------------
  // Fase 3 - comandos nuevos sin esperas bloqueantes
  // ----------------------------------------------------------
  if (strcmp(campos[4], "ILUMINACIONENCENDER") == 0) {
    luzEncendida = true;
    char captura[5];
    if (obtenerParametroPortus(campos[5], "captura", captura, sizeof(captura)))
      fotoEnCurso = strcmp(captura,"1") == 0;
    digitalWrite(PIN_ILUMINACION, HIGH);
    enviarEventoIluminacionF3();
    enviarAckPortus(secuenciaServidor,"ILUMINACIONENCENDER","ACEPTADO");
    return;
  }
  if (strcmp(campos[4], "ILUMINACIONAPAGAR") == 0) {
    char captura[5];
    bool finCaptura = obtenerParametroPortus(campos[5], "captura", captura, sizeof(captura)) && strcmp(captura,"0") == 0;
    if (fotoEnCurso && !finCaptura) {
      enviarNackPortus(secuenciaServidor,"ILUMINACIONAPAGAR","FOTOGRAFIA_EN_CURSO");
      return;
    }
    fotoEnCurso = false;
    luzEncendida = false;
    digitalWrite(PIN_ILUMINACION, LOW);
    enviarEventoIluminacionF3();
    enviarAckPortus(secuenciaServidor,"ILUMINACIONAPAGAR","ACEPTADO");
    return;
  }
  if (strcmp(campos[4], "GARITARESULTADO") == 0) {
    char estadoF3[20];
    if (!obtenerParametroPortus(campos[5], "estado", estadoF3, sizeof(estadoF3))) {
      enviarNackPortus(secuenciaServidor,"GARITARESULTADO","ESTADO_REQUERIDO");return;
    }
    if (strcmp(estadoF3,"CONFIG") == 0) {
      char seg[8];
      if (!obtenerParametroPortus(campos[5], "segundos", seg, sizeof(seg))) {
        enviarNackPortus(secuenciaServidor,"GARITARESULTADO","PARAMETRO_REQUERIDO");return;
      }
      int n=atoi(seg);
      if (n<5 || n>30) {
        enviarNackPortus(secuenciaServidor,"GARITARESULTADO","RANGO_5_30");return;
      }
      esperaVerificacionF3=(unsigned long)n*1000UL;
      enviarAckPortus(secuenciaServidor,"GARITARESULTADO","CONFIGURADO");return;
    }
    if (estadoEntrada != VALIDANDO_ENTRADA || camionActual == 0) {
      enviarNackPortus(secuenciaServidor,"GARITARESULTADO","NO_HAY_VEHICULO_EN_GARITA");return;
    }
    char placa[17];
    placa[0]='\0';
    obtenerParametroPortus(campos[5],"placa",placa,sizeof(placa));
    strncpy(placaF3,placa,sizeof(placaF3)-1);
    placaF3[sizeof(placaF3)-1]='\0';
    if (strcmp(estadoF3,"LEYENDO")==0) {
      garitaEsperandoManual=false;
      // La cámara puede tardar; aguardar su resultado durante el tiempo configurado.
      inicioEstadoEntrada=millis();
      mostrarLCD(lcdGarita,"LEYENDO PLACA","RFID validado");
    } else if (strcmp(estadoF3,"MANUAL")==0) {
      garitaEsperandoManual=true;
      inicioEstadoEntrada=millis();
      mostrarLCD(lcdGarita,"VERIFICACION", "ESPERE OPERADOR");
    } else if (strcmp(estadoF3,"DEGRADADO")==0) {
      garitaEsperandoManual=true;
      inicioEstadoEntrada=millis();
      mostrarLCD(lcdGarita,"MODO DEGRADADO","ESPERE OPERADOR");
    } else if (strcmp(estadoF3,"VERIFICADA")==0) {
      placaVerificadaF3=true;
      segundoFactorCompletadoF3 = true;
      mostrarLCD(lcdGarita,"PLACA VERIFICADA",placaF3);
    } else if (strcmp(estadoF3,"NO_COINCIDE")==0) {
      segundoFactorCompletadoF3 = true;  // autorizado con RT07, no confundible con VERIFICADA
      mostrarLCD(lcdGarita,"PLACA NO COINCIDE",placaF3);
    } else if (strcmp(estadoF3,"RESTRINGIDA")==0) {
      segundoFactorCompletadoF3 = true;  // autorizado con RT08, desvío obligado
      mostrarLCD(lcdGarita,"PLACA RESTRINGIDA",placaF3);
    } else {
      enviarNackPortus(secuenciaServidor,"GARITARESULTADO","RESULTADO_INVALIDO");return;
    }
    enviarAckPortus(secuenciaServidor,"GARITARESULTADO","ACEPTADO");
    return;
  }
  if (strcmp(campos[4],"BALIZACLIMA")==0) {
    char estadoBaliza[8];
    if (!obtenerParametroPortus(campos[5],"estado",estadoBaliza,sizeof(estadoBaliza)) ||
        (strcmp(estadoBaliza,"1")!=0 && strcmp(estadoBaliza,"0")!=0)) {
      enviarNackPortus(secuenciaServidor,"BALIZACLIMA","ESTADO_INVALIDO");return;
    }
    balizaClima = strcmp(estadoBaliza,"1")==0;
    if (!balizaClima) { nivelBaliza=false; digitalWrite(PIN_BALIZA_CLIMA,LOW); }
    enviarAckPortus(secuenciaServidor,"BALIZACLIMA","ACEPTADO");
    return;
  }
  if (strcmp(campos[4], "GRUASUSPENDER")==0 || strcmp(campos[4],"GRUAREANUDAR")==0) {
    // No fingir control de otro Mega. Este comando pertenece al Arduino de grúa.
    enviarNackPortus(secuenciaServidor,campos[4],"GRUA_EN_SEGUNDO_ARDUINO");
    return;
  }

  if (strcmp(campos[4], "ABRIRTALANQUERA") == 0) {
    if (!segundoFactorCompletadoF3) {
      enviarNackPortus(secuenciaServidor, "ABRIRTALANQUERA", "FALTA_VALIDACION_PLACA_O_MANUAL");
      return;
    }
    if (estadoEntrada != VALIDANDO_ENTRADA || camionActual < 1) {
      enviarNackPortus(secuenciaServidor, "ABRIRTALANQUERA", "GARITA_NO_ESPERA_AUTORIZACION");
      return;
    }

    if (irEntrada.estadoEstable) {
      enviarNackPortus(secuenciaServidor, "ABRIRTALANQUERA", "VEHICULO_BAJO_TALANQUERA");
      return;
    }

    if (camionRetenidoEsperandoConfirmacion != 0 ||
        irRetenidos.estadoEstable ||
        camionPendientePesaje != 0 ||
        estadoBascula != BASCULA_LIBRE) {
      enviarNackPortus(secuenciaServidor, "ABRIRTALANQUERA", "SIGUIENTE_ESTACION_OCUPADA");
      return;
    }

    char valorCamion[16];
    char valorManifiesto[16];
    char valorContenedor[16];
    char valorOperacion[16];
    char valorPeso[20];
    char valorTolerancia[20];
    char valorCanal[12];
    char valorTurno[16];

    if (!obtenerParametroPortus(campos[5], "camion", valorCamion, sizeof(valorCamion)) ||
        !obtenerParametroPortus(campos[5], "manifiesto", valorManifiesto, sizeof(valorManifiesto)) ||
        !obtenerParametroPortus(campos[5], "contenedor", valorContenedor, sizeof(valorContenedor)) ||
        !obtenerParametroPortus(campos[5], "operacion", valorOperacion, sizeof(valorOperacion)) ||
        !obtenerParametroPortus(campos[5], "peso", valorPeso, sizeof(valorPeso)) ||
        !obtenerParametroPortus(campos[5], "tolerancia", valorTolerancia, sizeof(valorTolerancia)) ||
        !obtenerParametroPortus(campos[5], "canal", valorCanal, sizeof(valorCanal)) ||
        !obtenerParametroPortus(campos[5], "turno", valorTurno, sizeof(valorTurno))) {
      enviarNackPortus(secuenciaServidor, "ABRIRTALANQUERA", "PARAMETROS_INCOMPLETOS");
      return;
    }

    int numeroCamion = extraerNumeroConPrefijo(valorCamion, 'C');
    // CAM-04 no es un identificador numerico simple; se valida aparte.
    if (strncmp(valorCamion, "CAM-", 4) == 0) {
      numeroCamion = atoi(valorCamion + 4);
    }

    int numeroManifiesto = extraerNumeroConPrefijo(valorManifiesto, 'M');
    int numeroContenedor = extraerNumeroConPrefijo(valorContenedor, 'C');
    int numeroTurno = extraerNumeroConPrefijo(valorTurno, 'T');
    float peso = atof(valorPeso);
    float tolerancia = atof(valorTolerancia);

    if (numeroCamion != camionActual ||
        numeroManifiesto <= 0 ||
        numeroContenedor <= 0 ||
        numeroTurno <= 0 ||
        peso <= 0.0 ||
        tolerancia < 0.0) {
      enviarNackPortus(secuenciaServidor, "ABRIRTALANQUERA", "PARAMETROS_INVALIDOS");
      return;
    }

    TipoOperacion operacion;
    if (strcmp(valorOperacion, "DEPOSITO") == 0) {
      operacion = OPERACION_DEPOSITO;
    } else if (strcmp(valorOperacion, "RETIRO") == 0) {
      operacion = OPERACION_RETIRO;
    } else {
      enviarNackPortus(secuenciaServidor, "ABRIRTALANQUERA", "OPERACION_INVALIDA");
      return;
    }

    bool canalRojo = false;
    if (strcmp(valorCanal, "ROJO") == 0) {
      canalRojo = true;
    } else if (strcmp(valorCanal, "VERDE") != 0) {
      enviarNackPortus(secuenciaServidor, "ABRIRTALANQUERA", "CANAL_INVALIDO");
      return;
    }

    int slot = camionActual - 1;
    Manifiesto &m = manifiestos[slot];
    m.id = numeroManifiesto;
    m.camionId = camionActual;
    m.contenedorId = (byte)numeroContenedor;
    m.operacion = operacion;
    m.pesoDeclarado = peso;
    m.tolerancia = tolerancia;
    m.canalRojo = canalRojo;
    m.estado = MANIFIESTO_PENDIENTE;

    manifiestoCandidatoActual = slot;
    turnoServidorCandidato = numeroTurno;

    Serial.print(F("AUTORIZACION SERVIDOR: M"));
    Serial.print(m.id);
    Serial.print(F(" | C"));
    Serial.print(m.contenedorId);
    Serial.print(F(" | "));
    Serial.print(textoOperacion(m.operacion));
    Serial.print(F(" | canal "));
    Serial.println(m.canalRojo ? "ROJO" : "VERDE");

    servoEntrada.write(ENTRADA_ABIERTA);
    ponerSemaforo(GARITA_ROJO, GARITA_VERDE, VERDE);
    if (placaVerificadaF3 && placaF3[0] != '\0')
      mostrarLCD(lcdGarita,"PLACA VERIFICADA",placaF3);
    else
      mostrarLCD(lcdGarita,"ENTRADA AUTORIZ.","Puede avanzar");
    inicioEstadoEntrada = millis();
    estadoEntrada = ESPERANDO_PASO_ENTRADA;

    enviarEventoGaritaDecision(camionActual, true, "OK");
    enviarAckPortus(secuenciaServidor, "ABRIRTALANQUERA", "ACEPTADO");
    return;
  }


  if (strcmp(campos[4], "AGUJALIBERAR") == 0) {
    if (camionRetenidoEsperandoConfirmacion != 0) {
      enviarNackPortus(secuenciaServidor, "AGUJALIBERAR", "VEHICULO_SOBRE_AGUJA");
      return;
    }

    if (camionLiberandoRetenido != 0) {
      enviarNackPortus(secuenciaServidor, "AGUJALIBERAR", "LIBERACION_EN_CURSO");
      return;
    }

    if (!irRetenidos.estadoEstable) {
      enviarNackPortus(secuenciaServidor, "AGUJALIBERAR", "NO_HAY_VEHICULO_EN_PARQUEO");
      return;
    }

    char valorTurno[16];
    char valorPlaza[8];
    char valorResolucion[16];
    char valorDestino[12];
    char valorNuevoPeso[20];

    if (!obtenerParametroPortus(campos[5], "turno", valorTurno, sizeof(valorTurno)) ||
        !obtenerParametroPortus(campos[5], "plaza", valorPlaza, sizeof(valorPlaza)) ||
        !obtenerParametroPortus(campos[5], "resolucion", valorResolucion, sizeof(valorResolucion)) ||
        !obtenerParametroPortus(campos[5], "destino", valorDestino, sizeof(valorDestino))) {
      enviarNackPortus(secuenciaServidor, "AGUJALIBERAR", "PARAMETROS_INCOMPLETOS");
      return;
    }

    int turnoId = extraerNumeroConPrefijo(valorTurno, 'T');
    int plaza = atoi(valorPlaza);

    if (turnoId <= 0 || plaza < 1 || plaza > 3) {
      enviarNackPortus(secuenciaServidor, "AGUJALIBERAR", "PARAMETROS_INVALIDOS");
      return;
    }

    int camion = buscarCamionPorTurnoId(turnoId);

    // Reconciliación mínima tras reinicio del Mega: si el turno ya existe en
    // SQLite y el vehículo está físicamente en retenidos, el servidor adjunta
    // los datos necesarios para reconstruir el cache operativo antes de liberar.
    if (camion == 0) {
      char valorCamion[16];
      char valorManifiesto[16];
      char valorContenedor[16];
      char valorOperacion[16];
      char valorPeso[20];
      char valorTolerancia[20];
      char valorCanal[12];

      if (!obtenerParametroPortus(campos[5], "camion", valorCamion, sizeof(valorCamion)) ||
          !obtenerParametroPortus(campos[5], "manifiesto", valorManifiesto, sizeof(valorManifiesto)) ||
          !obtenerParametroPortus(campos[5], "contenedor", valorContenedor, sizeof(valorContenedor)) ||
          !obtenerParametroPortus(campos[5], "operacion", valorOperacion, sizeof(valorOperacion)) ||
          !obtenerParametroPortus(campos[5], "peso", valorPeso, sizeof(valorPeso)) ||
          !obtenerParametroPortus(campos[5], "tolerancia", valorTolerancia, sizeof(valorTolerancia)) ||
          !obtenerParametroPortus(campos[5], "canal", valorCanal, sizeof(valorCanal))) {
        enviarNackPortus(secuenciaServidor, "AGUJALIBERAR", "RECONCILIACION_INCOMPLETA");
        return;
      }

      int numeroCamion = 0;
      if (strncmp(valorCamion, "CAM-", 4) == 0) {
        numeroCamion = atoi(valorCamion + 4);
      }
      int numeroManifiesto = extraerNumeroConPrefijo(valorManifiesto, 'M');
      int numeroContenedor = extraerNumeroConPrefijo(valorContenedor, 'C');
      float peso = atof(valorPeso);
      float tolerancia = atof(valorTolerancia);

      TipoOperacion operacionReconstruida;
      if (strcmp(valorOperacion, "DEPOSITO") == 0) {
        operacionReconstruida = OPERACION_DEPOSITO;
      } else if (strcmp(valorOperacion, "RETIRO") == 0) {
        operacionReconstruida = OPERACION_RETIRO;
      } else {
        enviarNackPortus(secuenciaServidor, "AGUJALIBERAR", "OPERACION_INVALIDA");
        return;
      }

      bool canalRojoReconstruido = false;
      if (strcmp(valorCanal, "ROJO") == 0) {
        canalRojoReconstruido = true;
      } else if (strcmp(valorCanal, "VERDE") != 0) {
        enviarNackPortus(secuenciaServidor, "AGUJALIBERAR", "CANAL_INVALIDO");
        return;
      }

      if (numeroCamion < 1 || numeroCamion > NUM_CAMIONES ||
          numeroManifiesto <= 0 || numeroContenedor <= 0 ||
          peso <= 0.0 || tolerancia < 0.0) {
        enviarNackPortus(secuenciaServidor, "AGUJALIBERAR", "RECONCILIACION_INVALIDA");
        return;
      }

      camion = numeroCamion;
      int slot = camion - 1;

      manifiestos[slot].id = numeroManifiesto;
      manifiestos[slot].camionId = camion;
      manifiestos[slot].contenedorId = (byte)numeroContenedor;
      manifiestos[slot].operacion = operacionReconstruida;
      manifiestos[slot].pesoDeclarado = peso;
      manifiestos[slot].tolerancia = tolerancia;
      manifiestos[slot].canalRojo = canalRojoReconstruido;
      manifiestos[slot].estado = MANIFIESTO_RETENIDO;

      turnos[camion - 1].id = turnoId;
      turnos[camion - 1].manifiestoIndex = slot;
      turnos[camion - 1].estado = TURNO_RETENIDO;

      if (turnoId >= siguienteTurnoId) siguienteTurnoId = turnoId + 1;

      Serial.print(F("RECONCILIACION SERVIDOR: T"));
      Serial.print(turnoId);
      Serial.print(F(" | CAM-"));
      if (camion < 10) Serial.print('0');
      Serial.print(camion);
      Serial.print(F(" | M"));
      Serial.println(numeroManifiesto);
    }

    if (turnos[camion - 1].estado != TURNO_RETENIDO) {
      enviarNackPortus(secuenciaServidor, "AGUJALIBERAR", "TURNO_NO_RETENIDO");
      return;
    }

    bool destinoRuta = strcmp(valorDestino, "RUTA") == 0;
    bool destinoSalida = strcmp(valorDestino, "SALIDA") == 0;
    if (!destinoRuta && !destinoSalida) {
      enviarNackPortus(secuenciaServidor, "AGUJALIBERAR", "DESTINO_INVALIDO");
      return;
    }

    bool esAclarar = strcmp(valorResolucion, "ACLARAR") == 0;
    bool esCorregir = strcmp(valorResolucion, "CORREGIR") == 0;
    bool esRechazar = strcmp(valorResolucion, "RECHAZAR") == 0;
    if (!esAclarar && !esCorregir && !esRechazar) {
      enviarNackPortus(secuenciaServidor, "AGUJALIBERAR", "RESOLUCION_INVALIDA");
      return;
    }

    int indiceManifiesto = obtenerIndiceManifiestoActivo(camion);
    if (indiceManifiesto < 0) {
      enviarNackPortus(secuenciaServidor, "AGUJALIBERAR", "MANIFIESTO_NO_DISPONIBLE");
      return;
    }

    if (esCorregir) {
      if (!obtenerParametroPortus(campos[5], "nuevo_peso", valorNuevoPeso, sizeof(valorNuevoPeso))) {
        enviarNackPortus(secuenciaServidor, "AGUJALIBERAR", "NUEVO_PESO_REQUERIDO");
        return;
      }

      float nuevoPeso = atof(valorNuevoPeso);
      if (nuevoPeso <= 0.0) {
        enviarNackPortus(secuenciaServidor, "AGUJALIBERAR", "NUEVO_PESO_INVALIDO");
        return;
      }

      manifiestos[indiceManifiesto].pesoDeclarado = nuevoPeso;
      Serial.print(F("Peso declarado actualizado en cache: "));
      Serial.print(nuevoPeso, 1);
      Serial.println(F(" g"));
    }

    if (esRechazar) {
      // El servidor deja el turno en Anulado. Localmente se habilita solamente
      // el recorrido fisico hacia salida para que el vehiculo pueda abandonar
      // la maqueta sin completar la operacion.
      turnos[camion - 1].estado = TURNO_LISTO_SALIDA;
      manifiestos[indiceManifiesto].estado = MANIFIESTO_FINALIZADO;
    } else if (destinoSalida) {
      turnos[camion - 1].estado = TURNO_LISTO_SALIDA;
      manifiestos[indiceManifiesto].estado = MANIFIESTO_EN_CURSO;
    } else {
      turnos[camion - 1].estado = TURNO_APROBADO_TRANSFERENCIA;
      manifiestos[indiceManifiesto].estado = MANIFIESTO_EN_CURSO;
    }

    camionLiberandoRetenido = camion;
    servoDesviador.write(RUTA_LIBERAR);

    ponerSemaforo(TRANSFERENCIA_ROJO, TRANSFERENCIA_VERDE, AMARILLO);
    if (destinoSalida) {
      ponerSemaforo(SALIDA_ROJO, SALIDA_VERDE, AMARILLO);
    }

    Serial.print(F("AGUJA LIBERAR - T"));
    Serial.print(turnoId);
    Serial.print(F(" | Camion "));
    Serial.print(camion);
    Serial.print(F(" | Plaza "));
    Serial.print(plaza);
    Serial.print(F(" | Resolucion "));
    Serial.println(valorResolucion);

    mostrarLCD(lcdGarita, "RETENCION RESUELTA", "Salga del parqueo");
    mostrarLCD(lcdSalida, "AGUJA LIBERAR", "Vehiculo saliendo");

    enviarEventoAguja("LIBERACION", camion, turnoId, valorResolucion);
    enviarAckPortus(secuenciaServidor, "AGUJALIBERAR", "ACEPTADO");
    return;
  }

  if (strcmp(campos[4], "ABRIRPUERTASALIDA") == 0) {
    // El servidor solicita el movimiento, pero la máquina física sigue
    // evaluando sensor y existencia de un turno habilitado.
    if (irSalida.estadoEstable) {
      enviarNackPortus(secuenciaServidor, "ABRIRPUERTASALIDA", "VEHICULO_BAJO_PUERTA");
      return;
    }
    if (estadoSalida != ESPERANDO_AUTORIZACION_SALIDA) {
      enviarNackPortus(secuenciaServidor, "ABRIRPUERTASALIDA", "SALIDA_OCUPADA");
      return;
    }
    if (buscarCamionEnEstado(TURNO_LISTO_SALIDA) == 0) {
      enviarNackPortus(secuenciaServidor, "ABRIRPUERTASALIDA", "SIN_TURNO_LISTO_SALIDA");
      return;
    }
    autorizarSalida();
    // La puerta abre al completar VALIDANDO_SALIDA. ACK solo acepta la orden.
    enviarAckPortus(secuenciaServidor, "ABRIRPUERTASALIDA", "ACEPTADO");
    return;
  }

  if (strcmp(campos[4], "CERRARTALANQUERA") == 0) {
    if (irEntrada.estadoEstable) {
      enviarNackPortus(secuenciaServidor, "CERRARTALANQUERA", "VEHICULO_BAJO_TALANQUERA");
      return;
    }

    servoEntrada.write(ENTRADA_CERRADA);
    ponerSemaforo(GARITA_ROJO, GARITA_VERDE, ROJO);

    char causa[40];
    bool tieneCausa = obtenerParametroPortus(campos[5], "causa", causa, sizeof(causa));

    if (estadoEntrada == VALIDANDO_ENTRADA && camionActual > 0) {
      const char *causaFinal = tieneCausa ? causa : "RECHAZADO_SERVIDOR";
      Serial.print(F("INGRESO RECHAZADO POR SERVIDOR: "));
      Serial.println(causaFinal);
      mostrarLCD(lcdGarita, textoCausaGarita(causaFinal), "Ingreso negado");
      enviarEventoGaritaDecision(camionActual, false, causaFinal);
      inicioEstadoEntrada = millis();
      estadoEntrada = ENTRADA_DENEGADA;
    }

    enviarAckPortus(secuenciaServidor, "CERRARTALANQUERA", "ACEPTADO");
    return;
  }

  enviarNackPortus(secuenciaServidor, campos[4], "COMANDO_NO_RECONOCIDO");
}


void enviarTramaPortus(
  const char *tipo,
  const char *nombre,
  const char *datos
) {
  char cuerpo[PORTUS_RX_MAX];

  int escritos = snprintf(
    cuerpo,
    sizeof(cuerpo),
    "PORTUS|C|%lu|%s|%s|%s",
    secuenciaControladorPortus,
    tipo,
    nombre,
    datos
  );

  if (escritos < 0 || escritos >= (int)sizeof(cuerpo)) {
    return;
  }

  uint16_t crc = crc16CcittPortus(cuerpo);

  Serial.print('$');
  Serial.print(cuerpo);
  Serial.print('|');

  if (crc < 0x1000) Serial.print('0');
  if (crc < 0x0100) Serial.print('0');
  if (crc < 0x0010) Serial.print('0');

  Serial.println(crc, HEX);

  secuenciaControladorPortus++;

  // 0 se reserva para errores o referencias desconocidas.
  if (secuenciaControladorPortus == 0) {
    secuenciaControladorPortus = 1;
  }
}


void enviarAckPortus(
  unsigned long secuenciaServidor,
  const char *nombre,
  const char *mensaje
) {
  char datos[96];

  snprintf(
    datos,
    sizeof(datos),
    "ref=%lu;msg=%s",
    secuenciaServidor,
    mensaje
  );

  enviarTramaPortus("ACK", nombre, datos);
}


void enviarNackPortus(
  unsigned long secuenciaServidor,
  const char *nombre,
  const char *motivo
) {
  char datos[120];

  snprintf(
    datos,
    sizeof(datos),
    "ref=%lu;motivo=%s",
    secuenciaServidor,
    motivo
  );

  enviarTramaPortus("NACK", nombre, datos);
}


bool obtenerParametroPortus(
  const char *datos,
  const char *clave,
  char *destino,
  size_t tamDestino
) {
  if (datos == NULL || clave == NULL || destino == NULL || tamDestino == 0) {
    return false;
  }

  size_t largoClave = strlen(clave);
  const char *p = datos;

  while (*p != '\0') {
    const char *inicio = p;
    const char *fin = strchr(inicio, ';');
    if (fin == NULL) fin = inicio + strlen(inicio);

    const char *igual = (const char *)memchr(inicio, '=', (size_t)(fin - inicio));
    if (igual != NULL) {
      size_t largoNombre = (size_t)(igual - inicio);
      if (largoNombre == largoClave && strncmp(inicio, clave, largoClave) == 0) {
        const char *valor = igual + 1;
        size_t largoValor = (size_t)(fin - valor);
        if (largoValor >= tamDestino) largoValor = tamDestino - 1;
        memcpy(destino, valor, largoValor);
        destino[largoValor] = '\0';
        return true;
      }
    }

    if (*fin == '\0') break;
    p = fin + 1;
  }

  destino[0] = '\0';
  return false;
}


int extraerNumeroConPrefijo(const char *texto, char prefijo) {
  if (texto == NULL || texto[0] != prefijo) return -1;
  const char *numero = texto + 1;
  if (*numero == '\0') return -1;

  for (const char *p = numero; *p != '\0'; p++) {
    if (*p < '0' || *p > '9') return -1;
  }

  return atoi(numero);
}


const char *textoCausaGarita(const char *causa) {
  if (causa == NULL) return "RECHAZADO";
  if (strcmp(causa, "SIN_CITA") == 0) return "SIN CITA";
  if (strcmp(causa, "FUERA_DE_VENTANA") == 0) return "FUERA VENTANA";
  if (strcmp(causa, "SIN_LEVANTE") == 0) return "SIN LEVANTE";
  if (strcmp(causa, "LEVANTE_RETENIDO") == 0) return "LEVANTE RETEN.";
  if (strcmp(causa, "CAMION_INACTIVO") == 0) return "CAMION INACTIVO";
  if (strcmp(causa, "TURNO_ACTIVO") == 0) return "TURNO ACTIVO";
  if (strcmp(causa, "PARQUEO_LLENO") == 0) return "PARQUEO LLENO";
  if (strcmp(causa, "VARIAS_CITAS") == 0) return "CITAS AMBIGUAS";
  if (strcmp(causa, "DATOS_INVALIDOS") == 0) return "DATOS INVALIDOS";
  return "NO AUTORIZADO";
}


// Genera un evento de GARITA al leer una tarjeta RFID.
// El UID se envia sin espacios para facilitar su procesamiento.
void enviarEventoGaritaRFID(int camion) {
  char uidTexto[24];
  size_t pos = 0;
  uidTexto[0] = '\0';

  for (byte i = 0; i < rfid.uid.size && pos + 2 < sizeof(uidTexto); i++) {
    int escritos = snprintf(
      uidTexto + pos,
      sizeof(uidTexto) - pos,
      "%02X",
      rfid.uid.uidByte[i]
    );

    if (escritos <= 0) break;
    pos += (size_t)escritos;
  }

  char datos[112];

  if (camion >= 1 && camion <= NUM_CAMIONES) {
    snprintf(
      datos,
      sizeof(datos),
      "accion=RFID;uid=%s;camion=CAM-%02d;resultado=IDENTIFICADO",
      uidTexto,
      camion
    );
  } else {
    snprintf(
      datos,
      sizeof(datos),
      "accion=RFID;uid=%s;camion=DESCONOCIDO;resultado=RECHAZADO;causa=RFID_NO_REGISTRADO",
      uidTexto
    );
  }

  enviarTramaPortus("EVT", "GARITA", datos);
}




void enviarEventoGaritaDecision(
  int camion,
  bool autorizada,
  const char *causa
) {
  char datos[150];
  const char *resultado = autorizada ? "AUTORIZADO" : "RECHAZADO";

  if (camion >= 1 && camion <= NUM_CAMIONES) {
    Manifiesto &m = manifiestos[camion - 1];
    if (autorizada && m.id > 0) {
      snprintf(
        datos,
        sizeof(datos),
        "accion=VALIDACION;camion=CAM-%02d;resultado=%s;causa=%s;manifiesto=M%d;turno=T%d",
        camion,
        resultado,
        causa == NULL ? "OK" : causa,
        m.id,
        turnoServidorCandidato
      );
    } else {
      snprintf(
        datos,
        sizeof(datos),
        "accion=VALIDACION;camion=CAM-%02d;resultado=%s;causa=%s",
        camion,
        resultado,
        causa == NULL ? "SIN_CAUSA" : causa
      );
    }
  } else {
    snprintf(
      datos,
      sizeof(datos),
      "accion=VALIDACION;camion=DESCONOCIDO;resultado=%s;causa=%s",
      resultado,
      causa == NULL ? "SIN_CAUSA" : causa
    );
  }

  enviarTramaPortus("EVT", "GARITA", datos);
}


void enviarEventoGaritaIngreso(
  int camion,
  const char *resultado
) {
  char datos[170];

  if (camion < 1 || camion > NUM_CAMIONES) return;

  Manifiesto &m = manifiestos[camion - 1];
  int turnoId = turnos[camion - 1].id;
  if (turnoId <= 0) turnoId = turnoServidorCandidato;

  snprintf(
    datos,
    sizeof(datos),
    "accion=INGRESO;camion=CAM-%02d;resultado=%s;manifiesto=M%d;contenedor=C%d;turno=T%d;operacion=%s;canal=%s",
    camion,
    resultado == NULL ? "DESCONOCIDO" : resultado,
    m.id,
    m.contenedorId,
    turnoId,
    textoOperacion(m.operacion),
    m.canalRojo ? "ROJO" : "VERDE"
  );

  enviarTramaPortus("EVT", "GARITA", datos);
}


void enviarEventoPesaje(
  int camion,
  TipoPesaje tipo,
  float pesoMedido,
  float pesoEsperado,
  float diferencia,
  const char *resultado
) {
  if (camion < 1 || camion > NUM_CAMIONES) return;

  int indiceManifiesto = obtenerIndiceManifiestoActivo(camion);
  if (indiceManifiesto < 0) return;

  Manifiesto &m = manifiestos[indiceManifiesto];
  int turnoId = turnos[camion - 1].id;
  if (turnoId <= 0) return;

  char medidoTexto[16];
  char esperadoTexto[16];
  char diferenciaTexto[16];

  dtostrf(pesoMedido, 0, 1, medidoTexto);
  dtostrf(pesoEsperado, 0, 1, esperadoTexto);
  dtostrf(diferencia, 0, 1, diferenciaTexto);

  char datos[154];
  snprintf(
    datos,
    sizeof(datos),
    "turno=T%d;camion=CAM-%02d;tipo=%s;peso_medido_g=%s;peso_esperado_g=%s;diferencia_g=%s;muestras=%u;resultado=%s;canal=%s",
    turnoId,
    camion,
    tipo == PESAJE_INICIAL ? "ENTRADA" : "SALIDA",
    medidoTexto,
    esperadoTexto,
    diferenciaTexto,
    cantidadMuestrasPeso,
    resultado == NULL ? "DESCONOCIDO" : resultado,
    m.canalRojo ? "ROJO" : "VERDE"
  );

  enviarTramaPortus("EVT", "PESAJE", datos);
}


void enviarEventoAguja(
  const char *estado,
  int camion,
  int turnoId,
  const char *detalle
) {
  char datos[132];

  snprintf(
    datos,
    sizeof(datos),
    "estado=%s;camion=CAM-%02d;turno=T%d;detalle=%s",
    estado == NULL ? "DESCONOCIDO" : estado,
    camion,
    turnoId,
    detalle == NULL ? "" : detalle
  );

  enviarTramaPortus("EVT", "AGUJA", datos);
}


void enviarEventoProceso(
  const char *nombre,
  const char *accion,
  int camion
) {
  if (camion < 1 || camion > NUM_CAMIONES) return;
  int turnoId = turnos[camion - 1].id;
  if (turnoId <= 0) return;
  char datos[100];
  snprintf(datos, sizeof(datos),
    "turno=T%d;camion=CAM-%02d;accion=%s",
    turnoId, camion, accion == NULL ? "DESCONOCIDO" : accion);
  enviarTramaPortus("EVT", nombre, datos);
}

void actualizarHeartbeatPortus() {
  unsigned long ahora = millis();

  if (ahora - ultimoHeartbeatPortus >= INTERVALO_HEARTBEAT_PORTUS) {
    ultimoHeartbeatPortus = ahora;
    enviarTramaPortus("EVT", "ESTADO", "estado=NORMAL");
  }
}


// ============================================================
// COMANDOS MANUALES HEREDADOS DE FASE 1
// ============================================================
void procesarComandoLegacy(char comando) {
  switch (comando) {
    case 'A':
    case 'a':
      autorizarSalida();
      break;

    case 'N':
    case 'n':
      if (camionRetenidoEsperandoConfirmacion != 0) {
        Serial.println(F("Ruta normal bloqueada: el camion rechazado aun no llego al ramal."));
      } else {
        servoDesviador.write(RUTA_NORMAL);
        Serial.println(F("Ruta normal seleccionada"));
      }
      break;

    case 'R':
    case 'r':
      servoDesviador.write(RUTA_RETENIDA);
      Serial.println(F("Ruta retenida seleccionada"));
      break;

    case 'T':
    case 't':
      iniciarTransferencia();
      break;

    case 'Y':
    case 'y':
      if (camionEnTransferencia == 0) {
        Serial.println(F("No hay camion en transferencia."));
      } else {
        ponerSemaforo(TRANSFERENCIA_ROJO, TRANSFERENCIA_VERDE, AMARILLO);
        Serial.print(F("Transferencia validando - Camion "));
        Serial.println(camionEnTransferencia);
      }
      break;

    case 'X':
    case 'x':
      ponerSemaforo(TRANSFERENCIA_ROJO, TRANSFERENCIA_VERDE, ROJO);
      if (camionEnTransferencia != 0) {
        Serial.print(F("Transferencia detenida - Camion "));
        Serial.println(camionEnTransferencia);
        Serial.println(F("El turno sigue EN TRANSFERENCIA."));
        Serial.println(F("Use F solamente cuando la operacion haya terminado."));
      } else {
        Serial.println(F("Transferencia detenida"));
      }
      break;

    case 'F':
    case 'f':
      finalizarTransferencia();
      break;

    case 'Z':
    case 'z':
      if (hx711Disponible &&
          estadoBascula == BASCULA_LIBRE &&
          camionPendientePesaje == 0) {

        Serial.println(F("Realizando tara de la bascula..."));
        bascula.tare(10);
        lecturasCeroRearme = 0;
        basculaArmada = false;
        Serial.println(F("Bascula en cero."));
      } else {
        Serial.println(F("No se puede hacer tara con un pesaje pendiente o en curso."));
      }
      break;

    case 'M':
    case 'm':
      mostrarManifiestos();
      break;

    case 'S':
    case 's':
      mostrarEstadoTurnos();
      break;

    default:
      // Se ignoran caracteres desconocidos en modo legado.
      break;
  }
}


// ============================================================
// PESAJE DINAMICO
// ============================================================
void actualizarPesajeDinamico() {
  if (!hx711Disponible || !bascula.is_ready()) return;

  float pesoActual = bascula.get_units(1);

  // Absorber deriva pequena alrededor de cero.
  if (pesoActual >= -5.0 && pesoActual <= 5.0) {
    pesoActual = 0.0;
  }

  // ----------------------------------------------------------
  // BASCULA LIBRE
  // ----------------------------------------------------------
  if (estadoBascula == BASCULA_LIBRE) {

    if (pesoActual >= -UMBRAL_CERO_REARME &&
        pesoActual <= UMBRAL_CERO_REARME) {

      if (lecturasCeroRearme < LECTURAS_CERO_REARME) {
        lecturasCeroRearme++;
      }

      if (lecturasCeroRearme >= LECTURAS_CERO_REARME) {
        basculaArmada = true;
      }

    } else {

      lecturasCeroRearme = 0;

      if (camionPendientePesaje == 0) {
        basculaArmada = false;
      }
    }

    if (camionPendientePesaje != 0 && basculaArmada) {

      if (pesoActual >= UMBRAL_INICIO_PESAJE) {

        if (lecturasSobreUmbral < LECTURAS_PARA_INICIAR) {
          lecturasSobreUmbral++;
        }

      } else {

        lecturasSobreUmbral = 0;
      }

      if (lecturasSobreUmbral >= LECTURAS_PARA_INICIAR) {

        estadoBascula = PESAJE_EN_CURSO;
        tipoPesajeActual = tipoPesajePendiente;

        basculaArmada = false;
        lecturasCeroRearme = 0;
        lecturasSobreUmbral = 0;
        lecturasBajoUmbral = 0;
        cantidadMuestrasPeso = 0;
        resultadoPesajeGenerado = false;

        Serial.println(F("=== INICIO DE PESAJE DINAMICO ==="));
        Serial.print(F("Camion "));
        Serial.print(camionPendientePesaje);
        Serial.println(F(" confirmado sobre la bascula"));

        Serial.print(F("Tipo de pesaje: "));
        Serial.println(tipoPesajeActual == PESAJE_INICIAL ? "INICIAL" : "FINAL");

        Serial.print(F("Peso esperado: "));
        Serial.print(
          obtenerPesoEsperado(
            camionPendientePesaje,
            tipoPesajeActual
          ),
          1
        );
        Serial.println(F(" g"));

        Serial.println(F("Buscando meseta estable..."));

        mostrarLCD(
          lcdGarita,
          tipoPesajeActual == PESAJE_INICIAL ? "Pesaje inicial" : "Pesaje final",
          "Procesando..."
        );

        // No se descartan muestras iniciales fijas:
        // la propia ventana movil decide si existe una meseta.
        if (pesoActual >= PESO_MINIMO_MESETA) {
          agregarMuestraPeso(pesoActual);
        }
      }
    }

    return;
  }

  // ----------------------------------------------------------
  // PESAJE EN CURSO
  // ----------------------------------------------------------
  Serial.print(F("Peso dinamico: "));
  Serial.print(pesoActual, 1);
  Serial.println(F(" g"));

  if (pesoActual > UMBRAL_FIN_PESAJE) {

    lecturasBajoUmbral = 0;

    if (!resultadoPesajeGenerado &&
        pesoActual >= PESO_MINIMO_MESETA) {

      agregarMuestraPeso(pesoActual);

      if (cantidadMuestrasPeso == NUM_MUESTRAS_ESTABLES &&
          ventanaDePesoEsEstable()) {

        float pesoMediano = calcularMedianaPeso();
        evaluarResultadoPesaje(pesoMediano);
      }
    }

  } else {

    lecturasBajoUmbral++;

    if (lecturasBajoUmbral >= LECTURAS_PARA_LIBERAR) {

      // Si no hubo una ventana estable, el pesaje no es confiable.
      if (!resultadoPesajeGenerado) {
        Serial.println(F("PESAJE INVALIDO: no se encontro una meseta estable"));
        Serial.println(F("El vehiculo paso demasiado rapido o la lectura fue inestable."));

        if (camionPendientePesaje >= 1 && camionPendientePesaje <= NUM_CAMIONES) {
          float esperado = obtenerPesoEsperado(camionPendientePesaje, tipoPesajeActual);
          enviarEventoPesaje(
            camionPendientePesaje,
            tipoPesajeActual,
            0.0,
            esperado,
            esperado,
            "INVALIDO"
          );
        }

        retenerCamionPorPesaje("Sin meseta estable");
      }

      Serial.println(F("=== FIN DE PESAJE DINAMICO ==="));

      estadoBascula = BASCULA_LIBRE;
      basculaArmada = false;
      lecturasCeroRearme = 0;
      lecturasSobreUmbral = 0;
      lecturasBajoUmbral = 0;
      cantidadMuestrasPeso = 0;

      // Se libera la bascula, pero se conserva el estado del turno.
      camionPendientePesaje = 0;
      resultadoPesajeGenerado = false;

      if (estadoEntrada == ESPERANDO_RFID) {
        mostrarEstadoEspera();
      }
    }
  }
}

// ============================================================
// VENTANA MOVIL / ESTABILIDAD
// ============================================================
void agregarMuestraPeso(float peso) {
  if (cantidadMuestrasPeso < NUM_MUESTRAS_ESTABLES) {
    ventanaPeso[cantidadMuestrasPeso] = peso;
    cantidadMuestrasPeso++;
    return;
  }

  for (byte i = 0; i < NUM_MUESTRAS_ESTABLES - 1; i++) {
    ventanaPeso[i] = ventanaPeso[i + 1];
  }

  ventanaPeso[NUM_MUESTRAS_ESTABLES - 1] = peso;
}

bool ventanaDePesoEsEstable() {
  float minimo = ventanaPeso[0];
  float maximo = ventanaPeso[0];

  for (byte i = 1; i < NUM_MUESTRAS_ESTABLES; i++) {
    if (ventanaPeso[i] < minimo) minimo = ventanaPeso[i];
    if (ventanaPeso[i] > maximo) maximo = ventanaPeso[i];
  }

  return (maximo - minimo) <= RANGO_MAXIMO_ESTABLE;
}

float calcularMedianaPeso() {
  float copia[NUM_MUESTRAS_ESTABLES];

  for (byte i = 0; i < NUM_MUESTRAS_ESTABLES; i++) {
    copia[i] = ventanaPeso[i];
  }

  for (byte i = 0; i < NUM_MUESTRAS_ESTABLES - 1; i++) {
    for (byte j = i + 1; j < NUM_MUESTRAS_ESTABLES; j++) {
      if (copia[j] < copia[i]) {
        float temporal = copia[i];
        copia[i] = copia[j];
        copia[j] = temporal;
      }
    }
  }

  return copia[NUM_MUESTRAS_ESTABLES / 2];
}

// ============================================================
// EVALUAR RESULTADO DEL PESAJE
// ============================================================
void evaluarResultadoPesaje(float pesoMedido) {
  resultadoPesajeGenerado = true;

  Serial.print(F("Peso estable obtenido: "));
  Serial.print(pesoMedido, 1);
  Serial.println(F(" g"));

  if (
    camionPendientePesaje < 1 ||
    camionPendientePesaje > NUM_CAMIONES
  ) {
    Serial.println(F("PESAJE RECHAZADO: no existe camion pendiente"));
    servoDesviador.write(RUTA_RETENIDA);
    return;
  }

  int camion = camionPendientePesaje;
  int indiceManifiesto =
    obtenerIndiceManifiestoActivo(camion);

  if (indiceManifiesto < 0) {
    Serial.println(F("PESAJE RECHAZADO: turno sin manifiesto activo"));
    retenerCamionPorPesaje("Turno sin manifiesto");
    return;
  }

  Manifiesto &m =
    manifiestos[indiceManifiesto];

  float tara =
    camiones[camion - 1].tara;

  float pesoEsperado =
    obtenerPesoEsperado(
      camion,
      tipoPesajeActual
    );

  float diferencia =
    valorAbsolutoFloat(
      pesoMedido - pesoEsperado
    );

  Serial.print(F("Turno: T"));
  Serial.println(turnos[camion - 1].id);

  Serial.print(F("Manifiesto: M"));
  Serial.println(m.id);

  Serial.print(F("Operacion: "));
  Serial.println(textoOperacion(m.operacion));

  Serial.print(F("Peso esperado: "));
  Serial.print(pesoEsperado, 1);
  Serial.println(F(" g"));

  bool esperaCargado =
    (
      m.operacion == OPERACION_DEPOSITO &&
      tipoPesajeActual == PESAJE_INICIAL
    )
    ||
    (
      m.operacion == OPERACION_RETIRO &&
      tipoPesajeActual == PESAJE_FINAL
    );

  if (esperaCargado) {
    float pesoContenedorEstimado =
      pesoMedido - tara;

    if (pesoContenedorEstimado < 0.0) {
      pesoContenedorEstimado = 0.0;
      Serial.println(
        F("ADVERTENCIA: peso bruto menor que la tara registrada")
      );
    }

    Serial.print(F("Tara registrada: "));
    Serial.print(tara, 1);
    Serial.println(F(" g"));

    Serial.print(F("Contenedor estimado: "));
    Serial.print(pesoContenedorEstimado, 1);
    Serial.println(F(" g"));

    Serial.print(F("Contenedor declarado: "));
    Serial.print(m.pesoDeclarado, 1);
    Serial.println(F(" g"));
  }

  Serial.print(F("Diferencia: "));
  Serial.print(diferencia, 1);
  Serial.println(F(" g"));

  Serial.print(F("Tolerancia del manifiesto: +/- "));
  Serial.print(m.tolerancia, 1);
  Serial.println(F(" g"));

  // ----------------------------------------------------------
  // APROBADO POR PESO
  // ----------------------------------------------------------
  if (diferencia <= m.tolerancia) {

    // En Fase 2 el canal ROJO no rechaza el ingreso. El camion entra,
    // se pesa y despues del pesaje inicial debe ir al parqueo.
    if (tipoPesajeActual == PESAJE_INICIAL && m.canalRojo) {
      enviarEventoPesaje(
        camion,
        tipoPesajeActual,
        pesoMedido,
        pesoEsperado,
        diferencia,
        "CANAL_ROJO"
      );

      Serial.println(F("PESAJE APROBADO, PERO CANAL ROJO - RUTA RETENIDOS"));
      retenerCamionPorPesaje("Canal rojo aduanero");
      return;
    }

    enviarEventoPesaje(
      camion,
      tipoPesajeActual,
      pesoMedido,
      pesoEsperado,
      diferencia,
      "APROBADO"
    );

    servoDesviador.write(RUTA_NORMAL);

    if (tipoPesajeActual == PESAJE_INICIAL) {
      turnos[camion - 1].estado =
        TURNO_APROBADO_TRANSFERENCIA;

      // Se reutiliza el mismo LED RGB existente.
      ponerSemaforo(
        TRANSFERENCIA_ROJO,
        TRANSFERENCIA_VERDE,
        AMARILLO
      );

      Serial.println(
        F("PESAJE INICIAL APROBADO - RUTA NORMAL")
      );

      Serial.println(
        F("Camion habilitado para TRANSFERENCIA.")
      );

      Serial.println(
        F("Esperando comando T para autorizar transferencia.")
      );

      mostrarLCD(
        lcdGarita,
        "PESO APROBADO",
        "Ir transferencia"
      );

    } else {

      turnos[camion - 1].estado =
        TURNO_LISTO_SALIDA;

      ponerSemaforo(
        TRANSFERENCIA_ROJO,
        TRANSFERENCIA_VERDE,
        ROJO
      );

      ponerSemaforo(
        SALIDA_ROJO,
        SALIDA_VERDE,
        AMARILLO
      );

      Serial.println(
        F("PESAJE FINAL APROBADO - RUTA NORMAL")
      );

      Serial.println(
        F("Camion habilitado para SALIDA.")
      );

      Serial.println(
        F("Escriba A cuando llegue a la puerta de salida.")
      );

      mostrarLCD(
        lcdGarita,
        "PESO FINAL OK",
        "Ir a salida"
      );

      mostrarLCD(
        lcdSalida,
        "Camion habilitado",
        "Esperando A"
      );
    }

  } else {

    enviarEventoPesaje(
      camion,
      tipoPesajeActual,
      pesoMedido,
      pesoEsperado,
      diferencia,
      "FUERA_TOLERANCIA"
    );

    Serial.println(
      F("PESAJE RECHAZADO - RUTA RETENIDOS")
    );

    retenerCamionPorPesaje(
      "Peso fuera tolerancia"
    );
  }
}

// ============================================================
// RETENER CAMION
// ============================================================
void retenerCamionPorPesaje(const char *motivo) {
  if (camionPendientePesaje < 1 ||
      camionPendientePesaje > NUM_CAMIONES) {
    return;
  }

  int camion = camionPendientePesaje;

  turnos[camion - 1].estado = TURNO_RETENIDO;
  retenerManifiestoDeCamion(camion);

  camionRetenidoEsperandoConfirmacion = camion;

  if (camionEnTransferencia == camion) {
    camionEnTransferencia = 0;
  }

  servoDesviador.write(RUTA_RETENIDA);

  ponerSemaforo(
    TRANSFERENCIA_ROJO,
    TRANSFERENCIA_VERDE,
    AMARILLO
  );

  ponerSemaforo(
    SALIDA_ROJO,
    SALIDA_VERDE,
    ROJO
  );

  Serial.print(F("Camion "));
  Serial.print(camion);
  Serial.println(F(" marcado como RETENIDO."));

  Serial.print(F("Motivo: "));
  Serial.println(motivo);

  Serial.println(F("Dirigir el camion al ramal de retenidos."));
  Serial.println(F("No puede continuar a transferencia."));
  Serial.println(F("No puede autorizar salida."));
  Serial.println(F("El turno permanece abierto y retenido."));

  bool retencionAduanera =
    motivo != NULL && strcmp(motivo, "Canal rojo aduanero") == 0;

  mostrarLCD(
    lcdGarita,
    retencionAduanera ? "CANAL ROJO" : "PESO RECHAZADO",
    "Ir a retenidos"
  );

  mostrarLCD(
    lcdSalida,
    "TURNO RETENIDO",
    "Sin salida"
  );
}

// ============================================================
// FUNCIONES DE TURNOS Y MANIFIESTOS
// ============================================================

bool camionTieneTurnoActivo(int camion) {
  if (camion < 1 || camion > NUM_CAMIONES) {
    return false;
  }

  EstadoTurno estado =
    turnos[camion - 1].estado;

  return
    estado != TURNO_SIN_INICIAR &&
    estado != TURNO_FINALIZADO;
}


int buscarCamionEnEstado(
  EstadoTurno estadoBuscado
) {
  for (byte i = 0; i < NUM_CAMIONES; i++) {
    if (
      turnos[i].estado ==
      estadoBuscado
    ) {
      return i + 1;
    }
  }

  return 0;
}


int buscarCamionPorTurnoId(int turnoId) {
  if (turnoId <= 0) return 0;

  for (byte i = 0; i < NUM_CAMIONES; i++) {
    if (turnos[i].id == turnoId) {
      return i + 1;
    }
  }

  return 0;
}


int buscarManifiestoPendienteParaCamion(
  int camion
) {
  if (
    camion < 1 ||
    camion > NUM_CAMIONES
  ) {
    return -1;
  }

  for (
    byte i = 0;
    i < NUM_MANIFIESTOS;
    i++
  ) {
    if (
      manifiestos[i].camionId == camion &&
      manifiestos[i].estado ==
        MANIFIESTO_PENDIENTE
    ) {
      return i;
    }
  }

  return -1;
}


int obtenerIndiceManifiestoActivo(
  int camion
) {
  if (
    camion < 1 ||
    camion > NUM_CAMIONES
  ) {
    return -1;
  }

  int indice =
    turnos[camion - 1].manifiestoIndex;

  if (
    indice < 0 ||
    indice >= NUM_MANIFIESTOS
  ) {
    return -1;
  }

  return indice;
}


void activarTurnoConManifiesto(
  int camion,
  int manifiestoIndex,
  int turnoServidorId
) {
  if (
    camion < 1 ||
    camion > NUM_CAMIONES ||
    manifiestoIndex < 0 ||
    manifiestoIndex >= NUM_MANIFIESTOS
  ) {
    return;
  }

  if (turnoServidorId > 0) {
    turnos[camion - 1].id = turnoServidorId;
    if (turnoServidorId >= siguienteTurnoId) {
      siguienteTurnoId = turnoServidorId + 1;
    }
  } else {
    turnos[camion - 1].id = siguienteTurnoId++;
  }

  turnos[camion - 1].manifiestoIndex =
    manifiestoIndex;

  turnos[camion - 1].estado =
    TURNO_ESPERANDO_PESAJE_INICIAL;

  manifiestos[manifiestoIndex].estado =
    MANIFIESTO_EN_CURSO;
}


void finalizarManifiestoDeCamion(
  int camion
) {
  int indice =
    obtenerIndiceManifiestoActivo(
      camion
    );

  if (indice >= 0) {
    manifiestos[indice].estado =
      MANIFIESTO_FINALIZADO;
  }
}


void retenerManifiestoDeCamion(
  int camion
) {
  int indice =
    obtenerIndiceManifiestoActivo(
      camion
    );

  if (indice >= 0) {
    manifiestos[indice].estado =
      MANIFIESTO_RETENIDO;
  }
}


const char *textoOperacion(
  TipoOperacion operacion
) {
  return
    operacion == OPERACION_DEPOSITO
    ? "DEPOSITO"
    : "RETIRO";
}


const char *textoEstadoManifiesto(
  EstadoManifiesto estado
) {
  switch (estado) {
    case MANIFIESTO_PENDIENTE:
      return "PENDIENTE";

    case MANIFIESTO_EN_CURSO:
      return "EN CURSO";

    case MANIFIESTO_RETENIDO:
      return "RETENIDO";

    case MANIFIESTO_FINALIZADO:
      return "FINALIZADO";
  }

  return "DESCONOCIDO";
}


float obtenerPesoEsperado(
  int camion,
  TipoPesaje tipo
) {
  if (
    camion < 1 ||
    camion > NUM_CAMIONES
  ) {
    return 0.0;
  }

  int indiceManifiesto =
    obtenerIndiceManifiestoActivo(
      camion
    );

  if (indiceManifiesto < 0) {
    return 0.0;
  }

  Manifiesto &m =
    manifiestos[indiceManifiesto];

  float tara =
    camiones[camion - 1].tara;

  bool debeEstarCargado =
    (
      m.operacion == OPERACION_DEPOSITO &&
      tipo == PESAJE_INICIAL
    )
    ||
    (
      m.operacion == OPERACION_RETIRO &&
      tipo == PESAJE_FINAL
    );

  if (debeEstarCargado) {
    return
      tara +
      m.pesoDeclarado;
  }

  return tara;
}


const char *textoEstadoTurno(
  EstadoTurno estado
) {
  switch (estado) {
    case TURNO_SIN_INICIAR:
      return "SIN TURNO";

    case TURNO_ESPERANDO_PESAJE_INICIAL:
      return "PESAJE INICIAL";

    case TURNO_APROBADO_TRANSFERENCIA:
      return "ESPERA TRANSFER";

    case TURNO_EN_TRANSFERENCIA:
      return "EN TRANSFER";

    case TURNO_ESPERANDO_PESAJE_FINAL:
      return "PESAJE FINAL";

    case TURNO_LISTO_SALIDA:
      return "LISTO SALIDA";

    case TURNO_RETENIDO:
      return "RETENIDO";

    case TURNO_SALIENDO:
      return "SALIENDO";

    case TURNO_FINALIZADO:
      return "FINALIZADO";
  }

  return "DESCONOCIDO";
}


void mostrarEstadoTurnos() {
  Serial.println();
  Serial.println(
    F("===== ESTADO DE TURNOS =====")
  );

  for (
    byte i = 0;
    i < NUM_CAMIONES;
    i++
  ) {
    int camion =
      i + 1;

    Serial.print(F("Camion "));
    Serial.print(camion);

    Serial.print(F(" ["));
    Serial.print(
      camiones[i].placa
    );
    Serial.print(F("]: "));

    Serial.print(
      textoEstadoTurno(
        turnos[i].estado
      )
    );

    int indice =
      turnos[i].manifiestoIndex;

    if (
      indice >= 0 &&
      indice < NUM_MANIFIESTOS
    ) {
      Serial.print(F(" | T"));
      Serial.print(
        turnos[i].id
      );

      Serial.print(F(" | M"));
      Serial.print(
        manifiestos[indice].id
      );

      Serial.print(F(" | "));
      Serial.print(
        textoOperacion(
          manifiestos[indice].operacion
        )
      );
    }

    Serial.println();
  }

  Serial.print(
    F("Camion en transferencia: ")
  );
  Serial.println(
    camionEnTransferencia
  );

  Serial.print(
    F("Camion pendiente de pesaje: ")
  );
  Serial.println(
    camionPendientePesaje
  );

  Serial.print(
    F("Esperando confirmacion retenidos: ")
  );
  Serial.println(
    camionRetenidoEsperandoConfirmacion
  );

  Serial.print(
    F("Camion en salida: ")
  );
  Serial.println(
    camionEnSalida
  );

  Serial.println(
    F("============================")
  );

  Serial.println();
}


void mostrarManifiestos() {
  Serial.println();
  Serial.println(
    F("===== CACHE OPERATIVO SERVIDOR =====")
  );

  for (
    byte i = 0;
    i < NUM_MANIFIESTOS;
    i++
  ) {
    Manifiesto &m =
      manifiestos[i];

    Serial.print(F("M"));
    Serial.print(m.id);

    Serial.print(F(" | Camion "));
    Serial.print(m.camionId);

    Serial.print(F(" | "));
    Serial.print(
      textoOperacion(
        m.operacion
      )
    );

    Serial.print(F(" | Contenedor C"));
    Serial.print(m.contenedorId);

    Serial.print(F(" | Peso "));
    Serial.print(
      m.pesoDeclarado,
      1
    );
    Serial.print(F(" g"));

    Serial.print(F(" | Tol +/-"));
    Serial.print(
      m.tolerancia,
      1
    );
    Serial.print(F(" g"));

    Serial.print(F(" | "));
    Serial.println(
      textoEstadoManifiesto(
        m.estado
      )
    );
  }

  Serial.println(
    F("Camion 1: sin manifiesto pendiente (prueba de rechazo).")
  );

  Serial.println(
    F("===================================")
  );

  Serial.println();
}


// ============================================================
// FUNCIONES AUXILIARES
// ============================================================
void ponerSemaforo(
  byte pinRojo,
  byte pinVerde,
  ColorSemaforo color
) {
  digitalWrite(
    pinRojo,
    color == ROJO || color == AMARILLO ? HIGH : LOW
  );

  digitalWrite(
    pinVerde,
    color == VERDE || color == AMARILLO ? HIGH : LOW
  );
}

void iniciarSensor(SensorFiltrado &sensor) {
  bool detectado = digitalRead(sensor.pin) == LOW;
  sensor.lecturaAnterior = detectado;
  sensor.estadoEstable = detectado;
  sensor.momentoCambio = millis();
}

bool actualizarSensor(SensorFiltrado &sensor) {
  bool lectura = digitalRead(sensor.pin) == LOW;

  if (lectura != sensor.lecturaAnterior) {
    sensor.lecturaAnterior = lectura;
    sensor.momentoCambio = millis();
  }

  if (
    millis() - sensor.momentoCambio >= TIEMPO_FILTRO_IR &&
    sensor.estadoEstable != lectura
  ) {
    sensor.estadoEstable = lectura;
    return true;
  }

  return false;
}

void manejarCambioSensorEspera() {
  Serial.print(F("Zona de espera: "));
  Serial.println(
    irEspera.estadoEstable
    ? "CAMION DETECTADO"
    : "LIBRE"
  );

  if (estadoEntrada == ESPERANDO_RFID) {
    mostrarEstadoEspera();
  }
}

void manejarCambioSensorRetenidos() {
  Serial.print(F("Zona de retenidos: "));
  Serial.println(
    irRetenidos.estadoEstable
    ? "OCUPADA"
    : "LIBRE"
  );

  if (irRetenidos.estadoEstable) {

    if (camionRetenidoEsperandoConfirmacion != 0) {
      int camion = camionRetenidoEsperandoConfirmacion;

      Serial.print(F("Camion "));
      Serial.print(camion);
      Serial.println(F(" retenido confirmado fisicamente."));
      Serial.println(F("Turno permanece RETENIDO."));
      Serial.println(F("No puede continuar a transferencia."));
      Serial.println(F("No puede cerrar su turno."));

      camionRetenidoEsperandoConfirmacion = 0;

    } else {

      Serial.println(F("Ramal ocupado por un vehiculo."));
    }

    // El camion ya cruzo la aguja y esta dentro del ramal.
    // La aguja puede regresar a normal para futuros turnos.
    servoDesviador.write(RUTA_NORMAL);

    ponerSemaforo(
      TRANSFERENCIA_ROJO,
      TRANSFERENCIA_VERDE,
      ROJO
    );

    Serial.println(F("Desviador regresado a ruta normal."));

    mostrarLCD(
      lcdSalida,
      "RAMAL OCUPADO",
      "Turno retenido"
    );

  } else {

    Serial.println(F("Ramal disponible nuevamente."));

    if (camionLiberandoRetenido != 0) {
      int camion = camionLiberandoRetenido;
      int turnoId = turnos[camion - 1].id;

      Serial.print(F("Camion "));
      Serial.print(camion);
      Serial.println(F(" salio fisicamente del parqueo de retencion."));

      // Con el ramal ya libre, la aguja vuelve a recta.
      servoDesviador.write(RUTA_NORMAL);
      enviarEventoAguja("RECTA", camion, turnoId, "LIBERACION_COMPLETA");
      camionLiberandoRetenido = 0;

      if (turnos[camion - 1].estado == TURNO_APROBADO_TRANSFERENCIA) {
        ponerSemaforo(TRANSFERENCIA_ROJO, TRANSFERENCIA_VERDE, AMARILLO);
        mostrarLCD(lcdGarita, "RETENCION LIBRE", "Ir transferencia");
      } else if (turnos[camion - 1].estado == TURNO_LISTO_SALIDA) {
        ponerSemaforo(SALIDA_ROJO, SALIDA_VERDE, AMARILLO);
        mostrarLCD(lcdSalida, "SALIDA DISPONIBLE", "Esperando A");
      }

      Serial.println(F("Desviador regresado a ruta normal despues de liberar."));
    }

    // Que el sensor quede libre por si solo NO borra TURNO_RETENIDO.
    mostrarEstadoSalidaDisponible();
  }

  if (estadoEntrada == ESPERANDO_RFID) {
    mostrarEstadoEspera();
  }
}

void mostrarEstadoEspera() {
  if (
    camionRetenidoEsperandoConfirmacion != 0 ||
    irRetenidos.estadoEstable
  ) {

    ponerSemaforo(
      GARITA_ROJO,
      GARITA_VERDE,
      AMARILLO
    );

    mostrarLCD(
      lcdGarita,
      "Ramal ocupado",
      "Espere..."
    );

  } else if (
    camionPendientePesaje != 0 ||
    estadoBascula != BASCULA_LIBRE
  ) {

    ponerSemaforo(
      GARITA_ROJO,
      GARITA_VERDE,
      AMARILLO
    );

    mostrarLCD(
      lcdGarita,
      "Pesaje ocupado",
      "Espere..."
    );

  } else if (irEspera.estadoEstable) {

    ponerSemaforo(
      GARITA_ROJO,
      GARITA_VERDE,
      AMARILLO
    );

    mostrarLCD(
      lcdGarita,
      "Camion en espera",
      "Acerque tarjeta"
    );

  } else {

    ponerSemaforo(
      GARITA_ROJO,
      GARITA_VERDE,
      ROJO
    );

    mostrarLCD(
      lcdGarita,
      "PORTUS - GARITA",
      "Esperando camion"
    );
  }
}

void mostrarEstadoSalidaDisponible() {
  if (irRetenidos.estadoEstable) {
    mostrarLCD(
      lcdSalida,
      "RAMAL OCUPADO",
      "Camion retenido"
    );
    return;
  }

  int camionListo =
    buscarCamionEnEstado(
      TURNO_LISTO_SALIDA
    );

  if (camionListo != 0) {
    mostrarLCD(
      lcdSalida,
      "SALIDA DISPONIBLE",
      "Esperando A"
    );
  } else {
    mostrarLCD(
      lcdSalida,
      "PORTUS - SALIDA",
      "Esperando turno"
    );
  }
}

void mostrarLCD(
  LiquidCrystal_I2C &lcd,
  const char *linea1,
  const char *linea2
) {
  imprimirLinea(lcd, 0, linea1);
  imprimirLinea(lcd, 1, linea2);
}

void mostrarCamionEnLCD(int numeroCamion) {
  char linea1[17];
  char linea2[17];
  byte indice = numeroCamion - 1;

  snprintf(
    linea1,
    sizeof(linea1),
    "Camion %d VALID.",
    numeroCamion
  );

  snprintf(
    linea2,
    sizeof(linea2),
    "%02X %02X %02X %02X",
    camiones[indice].uid[0],
    camiones[indice].uid[1],
    camiones[indice].uid[2],
    camiones[indice].uid[3]
  );

  mostrarLCD(
    lcdGarita,
    linea1,
    linea2
  );
}

void imprimirLinea(
  LiquidCrystal_I2C &lcd,
  byte fila,
  const char *texto
) {
  lcd.setCursor(0, fila);

  byte i = 0;

  while (i < 16 && texto[i] != '\0') {
    lcd.print(texto[i]);
    i++;
  }

  while (i < 16) {
    lcd.print(' ');
    i++;
  }
}

float valorAbsolutoFloat(float valor) {
  return valor < 0 ? -valor : valor;
}

// ============================================================
// FASE 3 - Salidas sin delay ni temporizadores bloqueantes
// ============================================================
void enviarEventoIluminacionF3() {
  char datos[56];
  snprintf(datos,sizeof(datos),"encendida=%d;modo=REMOTO",luzEncendida ? 1 : 0);
  enviarTramaPortus("EVT","ILUMINACION",datos);
}
void actualizarSalidasFase3() {
  // Si el servicio/bridge desaparece, fail-safe: iluminación ENCENDIDA.
  if (millis()-ultimoComandoServidorF3 > MAX_TIEMPO_COMUNICACION_F3) {
    luzEncendida=true;
    digitalWrite(PIN_ILUMINACION,HIGH);
  }
  if (balizaClima) {
    if (millis()-ultimoParpadeoBaliza >= 500UL) {
      ultimoParpadeoBaliza=millis();
      nivelBaliza=!nivelBaliza;
      digitalWrite(PIN_BALIZA_CLIMA,nivelBaliza ? HIGH : LOW);
    }
  } else if (nivelBaliza) {
    nivelBaliza=false;
    digitalWrite(PIN_BALIZA_CLIMA,LOW);
  }
}
