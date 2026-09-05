#include <Servo.h>
#include <HX711.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <SPI.h>
#include <MFRC522.h>

// ============================================================
// PORTUS - UN SOLO PESAJE
//
// RFID
// 3 SEMAFOROS
// 3 TALANQUERAS
// IR ENTRADA
// 1 HX711 usado en entrada Y salida
// LCD
// SIN GRUA
// ============================================================


// ============================================================
// PINES
// ============================================================

// 74HC595
const byte PIN_DATA  = 8;
const byte PIN_LATCH = 9;
const byte PIN_CLOCK = 10;

// Servos
const byte PIN_T1 = 6 ;
const byte PIN_T3 = 3;
const byte PIN_T2 = 7;

// IR entrada
const byte PIN_IR = 26;
const byte IR_ACTIVO = LOW;

// HX711 único
const byte HX_DOUT = 22;
const byte HX_SCK  = 24;

// RFID RC522
const byte RFID_SS  = 53;
const byte RFID_RST = 49;


// ============================================================
// OBJETOS
// ============================================================

Servo servoT1;
Servo servoT2;
Servo servoT3;

HX711 bascula;

MFRC522 rfid(RFID_SS, RFID_RST);

// LCD I2C: la direccion se detecta automaticamente al iniciar.
LiquidCrystal_I2C* lcd = nullptr;
byte LCD_DIRECCION = 0;
bool LCD_DISPONIBLE = false;


// ============================================================
// PESAJE
// ============================================================

// Factor que te está funcionando mejor
const float FACTOR_CALIBRACION = 363.0;

// Camión vacío
const float VACIO_MIN = 15.0;
const float VACIO_MAX = 24.0;

// Camión con contenedor
const float CARGADO_MIN = 25.0;
const float CARGADO_MAX = 100.0;

// Consideramos que llegó vehículo a partir de aquí
const float PESO_DETECCION = 10.0;


// ============================================================
// TALANQUERA 1
// ============================================================

const int T1_CERRADA = 90;
const int T1_ABIERTA = 180;


// ============================================================
// TALANQUERA 3
// ============================================================

const int T3_CERRADA = 90;
const int T3_ABIERTA = 0;


// ============================================================
// TALANQUERA 2
//
// AHORA USAMOS MICROSEGUNDOS DIRECTAMENTE
// ============================================================

// Centro
const int T2_ESPERA = 90;

// Hacia grúa
const int T2_GRUA = 130;

// Hacia parqueo
const int T2_PARQUEO = 0;


// ============================================================
// SEMAFOROS
// ============================================================

const byte S1_R = 0;
const byte S1_V = 1;

const byte S2_R = 2;
const byte S2_V = 3;

const byte S3_R = 4;
const byte S3_V = 5;

byte salidas595 = 0;


enum Color {
  APAGADO,
  ROJO,
  AMARILLO,
  VERDE
};


// ============================================================
// ESTADOS
// ============================================================

enum Estado {

  ESPERANDO_RFID,

  ENTRADA_ABIERTA,

  ESPERANDO_PESO_ENTRADA,

  ESTABILIZANDO_ENTRADA,

  RUTA_GRUA,

  RUTA_PARQUEO,

  ESPERANDO_RETORNO,

  ESTABILIZANDO_SALIDA,

  SALIDA_ABIERTA,

  SALIDA_NEGADA
};

Estado estado;


// ============================================================
// TIEMPOS
// ============================================================

const unsigned long TIEMPO_CIERRE_T1 = 5000;

const unsigned long TIEMPO_ESTABILIZAR = 2000;

const unsigned long INTERVALO_PESO = 300;

const unsigned long TIEMPO_BASCULA_LIBRE = 1500;

const unsigned long TIEMPO_CIERRE_T3 = 5000;


unsigned long tiempoEstado = 0;

unsigned long ultimaLectura = 0;

unsigned long irLibreDesde = 0;

unsigned long basculaLibreDesde = 0;


// ============================================================
// VARIABLES
// ============================================================

bool camionPasoIR = false;

bool taraRetornoRealizada = false;


// ============================================================
// LCD
// ============================================================

// Busca automaticamente cualquier dispositivo I2C.
// En este circuito el unico dispositivo I2C esperado es la LCD.
byte detectarDireccionLCD() {

  for (byte direccion = 1; direccion < 127; direccion++) {

    Wire.beginTransmission(direccion);
    byte error = Wire.endTransmission();

    if (error == 0) {
      return direccion;
    }
  }

  return 0;
}


void iniciarLCD() {

  Wire.begin();

  LCD_DIRECCION = detectarDireccionLCD();

  if (LCD_DIRECCION == 0) {

    LCD_DISPONIBLE = false;

    Serial.println();
    Serial.println("ERROR LCD: no se encontro ningun dispositivo I2C.");
    Serial.println("Revisa:");
    Serial.println("SDA -> pin 20");
    Serial.println("SCL -> pin 21");
    Serial.println("VCC -> 5V");
    Serial.println("GND -> GND");

    return;
  }

  Serial.print("LCD detectada en direccion 0x");

  if (LCD_DIRECCION < 0x10) {
    Serial.print("0");
  }

  Serial.println(LCD_DIRECCION, HEX);

  lcd = new LiquidCrystal_I2C(
    LCD_DIRECCION,
    16,
    2
  );

  lcd->init();
  lcd->backlight();
  lcd->clear();

  LCD_DISPONIBLE = true;

  lcd->setCursor(0, 0);
  lcd->print("PORTUS");

  lcd->setCursor(0, 1);
  lcd->print("LCD OK");
}


// Imprime el mismo evento en Serial y LCD.
void mostrar(
  const char* linea1,
  const char* linea2
) {

  Serial.println();
  Serial.println("==============================");
  Serial.println(linea1);
  Serial.println(linea2);
  Serial.println("==============================");

  if (!LCD_DISPONIBLE) {
    return;
  }

  lcd->clear();

  lcd->setCursor(0, 0);
  lcd->print(linea1);

  lcd->setCursor(0, 1);
  lcd->print(linea2);
}


// Actualiza continuamente el peso sin limpiar la pantalla
// en cada lectura para evitar parpadeo.
void mostrarPeso(
  const char* titulo,
  float peso
) {

  Serial.print("[LCD] ");
  Serial.print(titulo);
  Serial.print(" | Peso: ");
  Serial.print(peso, 1);
  Serial.println(" g");

  if (!LCD_DISPONIBLE) {
    return;
  }

  lcd->setCursor(0, 0);
  lcd->print("                ");

  lcd->setCursor(0, 0);
  lcd->print(titulo);

  lcd->setCursor(0, 1);
  lcd->print("                ");

  lcd->setCursor(0, 1);
  lcd->print("Peso:");
  lcd->print(peso, 1);
  lcd->print("g");
}


// ============================================================
// 74HC595
// ============================================================

void actualizar595() {

  digitalWrite(
    PIN_LATCH,
    LOW
  );

  shiftOut(
    PIN_DATA,
    PIN_CLOCK,
    MSBFIRST,
    salidas595
  );

  digitalWrite(
    PIN_LATCH,
    HIGH
  );
}


void semaforo(
  byte rojo,
  byte verde,
  Color color
) {

  bitClear(
    salidas595,
    rojo
  );

  bitClear(
    salidas595,
    verde
  );


  if (color == ROJO) {

    bitSet(
      salidas595,
      rojo
    );
  }

  else if (color == VERDE) {

    bitSet(
      salidas595,
      verde
    );
  }

  else if (color == AMARILLO) {

    bitSet(
      salidas595,
      rojo
    );

    bitSet(
      salidas595,
      verde
    );
  }


  actualizar595();
}


void s1(Color c) {
  semaforo(S1_R, S1_V, c);
}

void s2(Color c) {
  semaforo(S2_R, S2_V, c);
}

void s3(Color c) {
  semaforo(S3_R, S3_V, c);
}


// ============================================================
// TALANQUERA 2
// ============================================================

void moverT2(
  int angulo,
  const char* posicion
) {
  Serial.println();

  Serial.println("==============================");

  Serial.print("TALANQUERA 2 -> ");
  Serial.println(posicion);

  Serial.print("ANGULO: ");
  Serial.print(angulo);
  Serial.println(" grados");

  Serial.println("==============================");

  servoT2.write(angulo);
}


// ============================================================
// PESAJE ESTABLE
// ============================================================

bool leerPeso(float &peso) {

  if (
    !bascula.wait_ready_timeout(500)
  ) {

    Serial.println(
      "ERROR: HX711 no responde."
    );

    return false;
  }


  // La misma técnica de tu código estable

  long raw =
    bascula.get_value(10);


  peso =
    (float)raw /
    FACTOR_CALIBRACION;


  // Evita valores negativos por orientación
  peso = fabs(peso);


  Serial.print(
    "RAW: "
  );

  Serial.print(
    raw
  );

  Serial.print(
    " | PESO: "
  );

  Serial.print(
    peso,
    1
  );

  Serial.println(
    " g"
  );


  return true;
}


// ============================================================
// TARA
// ============================================================

void hacerTara() {

  mostrar(
    "Haciendo tara",
    "Quite el peso"
  );


  Serial.println(
    "Realizando tara..."
  );


  if (
    bascula.wait_ready_timeout(2000)
  ) {

    bascula.tare(20);


    Serial.println(
      "TARA TERMINADA"
    );
  }

  else {

    Serial.println(
      "ERROR HX711"
    );
  }
}


// ============================================================
// RFID
// ============================================================

bool rfidArmado = false;

unsigned long rfidLibreDesde = 0;


bool leerRFID() {

  bool tarjeta =
    rfid.PICC_IsNewCardPresent();


  // Antes de aceptar una tarjeta,
  // el lector debe permanecer libre.

  if (!rfidArmado) {

    if (tarjeta) {

      rfidLibreDesde = 0;

      return false;
    }


    if (
      rfidLibreDesde == 0
    ) {

      rfidLibreDesde =
        millis();
    }


    if (
      millis() -
      rfidLibreDesde
      >=
      1500
    ) {

      rfidArmado = true;


      mostrar(
        "RFID LISTO",
        "Acerque tarjeta"
      );


      Serial.println(
        "Esperando tarjeta..."
      );
    }


    return false;
  }


  if (!tarjeta)
    return false;


  if (
    !rfid.PICC_ReadCardSerial()
  ) {

    return false;
  }


  Serial.print(
    "UID: "
  );


  for (
    byte i = 0;
    i < rfid.uid.size;
    i++
  ) {

    if (
      rfid.uid.uidByte[i] < 0x10
    )
      Serial.print("0");


    Serial.print(
      rfid.uid.uidByte[i],
      HEX
    );

    Serial.print(" ");
  }


  Serial.println();


  rfid.PICC_HaltA();

  rfid.PCD_StopCrypto1();


  rfidArmado = false;

  rfidLibreDesde = 0;


  return true;
}


// ============================================================
// REINICIAR CICLO
// ============================================================

void reiniciar() {

  Serial.println();
  Serial.println("##############################");
  Serial.println("NUEVO CICLO PORTUS");
  Serial.println("##############################");


  // --------------------------------
  // Entrada
  // --------------------------------

  servoT1.write(
    T1_CERRADA
  );

  s1(
    AMARILLO
  );


  // --------------------------------
  // Desviador
  // --------------------------------

  moverT2(90,"ESPERA");

  s2(
    AMARILLO
  );


  // --------------------------------
  // Salida
  // --------------------------------

  servoT3.write(
    T3_CERRADA
  );

  s3(
    ROJO
  );


  camionPasoIR = false;

  irLibreDesde = 0;

  basculaLibreDesde = 0;

  taraRetornoRealizada = false;


  rfidArmado = false;

  rfidLibreDesde = 0;


  estado =
    ESPERANDO_RFID;


  mostrar(
    "PORTUS",
    "Preparando RFID"
  );
}


// ============================================================
// SETUP
// ============================================================

void setup() {

  Serial.begin(
    115200
  );


  // ========================================================
  // 74HC595
  // ========================================================

  pinMode(
    PIN_DATA,
    OUTPUT
  );

  pinMode(
    PIN_LATCH,
    OUTPUT
  );

  pinMode(
    PIN_CLOCK,
    OUTPUT
  );


  actualizar595();


  // ========================================================
  // SERVOS
  // ========================================================

  servoT1.attach(
    PIN_T1
  );


  // Rango amplio para SG90
  servoT2.attach(
    PIN_T2
  );


  servoT3.attach(
    PIN_T3
  );


  servoT1.write(
    T1_CERRADA
  );


  servoT2.write(
    T2_ESPERA
  );


  servoT3.write(
    T3_CERRADA
  );


  // ========================================================
  // IR
  // ========================================================

  pinMode(
    PIN_IR,
    INPUT
  );


  // ========================================================
  // LCD
  // ========================================================

  iniciarLCD();


  mostrar(
    "PORTUS",
    "Iniciando..."
  );


  // ========================================================
  // RFID
  // ========================================================

  SPI.begin();

  rfid.PCD_Init();


  Serial.print(
    "RC522 VERSION: 0x"
  );

  Serial.println(
    rfid.PCD_ReadRegister(
      MFRC522::VersionReg
    ),
    HEX
  );


  // ========================================================
  // HX711
  // ========================================================

  bascula.begin(
    HX_DOUT,
    HX_SCK
  );


  Serial.print(
    "HX711: "
  );


  if (
    bascula.wait_ready_timeout(3000)
  ) {

    Serial.println(
      "OK"
    );
  }

  else {

    Serial.println(
      "ERROR"
    );
  }


  hacerTara();


  reiniciar();


  Serial.println();
  Serial.println("COMANDOS:");
  Serial.println("R = reiniciar");
  Serial.println("T = tara");
  Serial.println("G = T2 hacia GRUA");
  Serial.println("P = T2 hacia PARQUEO");
  Serial.println("C = T2 al CENTRO");
  Serial.println("S = saltar a pesaje de salida");
}


// ============================================================
// LOOP
// ============================================================

void loop() {

  // ========================================================
  // RFID
  // ========================================================

  if (
    estado ==
    ESPERANDO_RFID
  ) {

    if (
      leerRFID()
    ) {

      mostrar(
        "RFID ACEPTADO",
        "Puede ingresar"
      );


      s1(
        VERDE
      );


      servoT1.write(
        T1_ABIERTA
      );


      Serial.println(
        "T1 ABIERTA"
      );


      estado =
        ENTRADA_ABIERTA;
    }
  }


  // ========================================================
  // IR + TALANQUERA 1
  // ========================================================

  else if (
    estado ==
    ENTRADA_ABIERTA
  ) {

    bool detectado =
      digitalRead(PIN_IR)
      ==
      IR_ACTIVO;


    if (detectado) {

      irLibreDesde = 0;


      if (!camionPasoIR) {

        camionPasoIR = true;


        mostrar(
          "CAMION ENTRANDO",
          "IR detectado"
        );


        Serial.println(
          "T1 permanece abierta."
        );
      }

    }


    else if (
      camionPasoIR
    ) {

      if (
        irLibreDesde == 0
      ) {

        irLibreDesde =
          millis();


        mostrar(
          "CAMION PASO",
          "Cierre en 5s"
        );
      }


      if (
        millis() -
        irLibreDesde
        >=
        TIEMPO_CIERRE_T1
      ) {

        servoT1.write(
          T1_CERRADA
        );


        s1(
          ROJO
        );


        s2(
          AMARILLO
        );


        Serial.println(
          "T1 CERRADA"
        );


        mostrar(
          "PESAJE ENTRADA",
          "Esperando camion"
        );


        ultimaLectura = 0;


        estado =
          ESPERANDO_PESO_ENTRADA;
      }
    }
  }


  // ========================================================
  // ESPERAR PESAJE DE ENTRADA
  // ========================================================

  else if (
    estado ==
    ESPERANDO_PESO_ENTRADA
  ) {

    if (
      millis() -
      ultimaLectura
      >=
      INTERVALO_PESO
    ) {

      ultimaLectura =
        millis();


      float peso;


      if (
        leerPeso(peso)
      ) {

        // Mostrar TODAS las variaciones
        mostrarPeso(
          "PESAJE ENTRADA",
          peso
        );


        if (
          peso >=
          PESO_DETECCION
        ) {

          mostrar(
            "CAMION DETECTADO",
            "Estabilizando..."
          );


          tiempoEstado =
            millis();


          estado =
            ESTABILIZANDO_ENTRADA;
        }
      }
    }
  }


  // ========================================================
  // ESTABILIZACION ENTRADA
  // ========================================================

  else if (
    estado ==
    ESTABILIZANDO_ENTRADA
  ) {

    // Durante estos 2 segundos seguimos
    // mostrando las variaciones.

    if (
      millis() -
      ultimaLectura
      >=
      INTERVALO_PESO
    ) {

      ultimaLectura =
        millis();


      float peso;


      if (
        leerPeso(peso)
      ) {

        mostrarPeso(
          "ESTABILIZANDO",
          peso
        );
      }
    }


    if (
      millis() -
      tiempoEstado
      >=
      TIEMPO_ESTABILIZAR
    ) {

      float peso;


      if (
        !leerPeso(peso)
      ) {

        return;
      }


      Serial.println();
      Serial.println(
        "===== RESULTADO PESAJE ENTRADA ====="
      );


      Serial.print(
        "Peso final: "
      );

      Serial.println(
        peso,
        1
      );


      // ====================================================
      // CARGADO
      // ====================================================

      if (
        peso >=
        CARGADO_MIN
        &&
        peso <=
        CARGADO_MAX
      ) {

        Serial.println(
          "CAMION CON CONTENEDOR"
        );


        Serial.println(
          "AUTORIZADO HACIA GRUA"
        );


        s2(
          VERDE
        );


        moverT2(
          T2_GRUA,
          "GRUA"
        );


        mostrar(
          "PESO CORRECTO",
          "Ruta a grua"
        );


        basculaLibreDesde = 0;


        estado =
          RUTA_GRUA;
      }


      // ====================================================
      // VACIO
      // ====================================================

      else if (
        peso >=
        VACIO_MIN
        &&
        peso <=
        VACIO_MAX
      ) {

        Serial.println(
          "CAMION VACIO"
        );


        Serial.println(
          "ENVIADO A PARQUEO"
        );


        s2(
          ROJO
        );


        moverT2(
          T2_PARQUEO,
          "PARQUEO"
        );


        mostrar(
          "CAMION VACIO",
          "Ruta parqueo"
        );


        estado =
          RUTA_PARQUEO;
      }


      // ====================================================
      // INVALIDO
      // ====================================================

      else {

        Serial.println(
          "PESO INVALIDO"
        );


        s2(
          ROJO
        );


        moverT2(
          T2_PARQUEO,
          "PARQUEO"
        );


        mostrar(
          "PESO INVALIDO",
          "Ruta parqueo"
        );


        estado =
          RUTA_PARQUEO;
      }
    }
  }


  // ========================================================
  // CAMINO A GRUA
  // ========================================================

  else if (
    estado ==
    RUTA_GRUA
  ) {

    if (
      millis() -
      ultimaLectura
      >=
      INTERVALO_PESO
    ) {

      ultimaLectura =
        millis();


      float peso;


      if (
        leerPeso(peso)
      ) {

        mostrarPeso(
          "SALGA DE P1",
          peso
        );


        // Camión ya retirado de la báscula
        if (
          peso <
          PESO_DETECCION
        ) {

          if (
            basculaLibreDesde == 0
          ) {

            basculaLibreDesde =
              millis();
          }


          if (
            millis() -
            basculaLibreDesde
            >=
            TIEMPO_BASCULA_LIBRE
          ) {

            // Regresar desviador a centro
            moverT2(
              T2_ESPERA,
              "CENTRO"
            );


            s2(
              ROJO
            );


            // Rehacer tara con la báscula ya vacía.
            // Ayuda bastante para el segundo pesaje.
            if (
              !taraRetornoRealizada
            ) {

              Serial.println();
              Serial.println(
                "Bascula libre."
              );

              Serial.println(
                "Reajustando tara para pesaje de salida..."
              );


              bascula.tare(20);


              taraRetornoRealizada =
                true;
            }


            s3(
              ROJO
            );


            servoT3.write(
              T3_CERRADA
            );


            mostrar(
              "RETIRE CONTENEDOR",
              "Vuelva a pesaje"
            );


            Serial.println();
            Serial.println(
              "================================="
            );

            Serial.println(
              "SIMULE EL TRABAJO DE LA GRUA"
            );

            Serial.println(
              "RETIRE EL CONTENEDOR DEL CAMION"
            );

            Serial.println(
              "Y REGRESE A LA MISMA BASCULA"
            );

            Serial.println(
              "================================="
            );


            estado =
              ESPERANDO_RETORNO;


            ultimaLectura = 0;

            basculaLibreDesde = 0;
          }

        } else {

          basculaLibreDesde = 0;
        }
      }
    }
  }


  // ========================================================
  // PARQUEO
  // ========================================================

  else if (
    estado ==
    RUTA_PARQUEO
  ) {

    // Mantener T2 apuntando al parqueo.
    // El usuario puede reiniciar con R.

    mostrar(
      "ENVIADO PARQUEO",
      "Pulse R reinicio"
    );


    estado =
      SALIDA_NEGADA;
  }


  // ========================================================
  // ESPERANDO QUE REGRESE A LA MISMA BASCULA
  // ========================================================

  else if (
    estado ==
    ESPERANDO_RETORNO
  ) {

    if (
      millis() -
      ultimaLectura
      >=
      INTERVALO_PESO
    ) {

      ultimaLectura =
        millis();


      float peso;


      if (
        leerPeso(peso)
      ) {

        // MOSTRAR TODAS LAS VARIACIONES
        mostrarPeso(
          "PESAJE SALIDA",
          peso
        );


        if (
          peso >=
          PESO_DETECCION
        ) {

          Serial.println();
          Serial.println(
            "CAMION DETECTADO DE REGRESO"
          );


          mostrar(
            "CAMION REGRESO",
            "Estabilizando..."
          );


          tiempoEstado =
            millis();


          estado =
            ESTABILIZANDO_SALIDA;
        }
      }
    }
  }


  // ========================================================
  // ESTABILIZACION PESO SALIDA
  // ========================================================

  else if (
    estado ==
    ESTABILIZANDO_SALIDA
  ) {

    if (
      millis() -
      ultimaLectura
      >=
      INTERVALO_PESO
    ) {

      ultimaLectura =
        millis();


      float peso;


      if (
        leerPeso(peso)
      ) {

        // LCD actualizándose todo el tiempo
        mostrarPeso(
          "SALIDA PESANDO",
          peso
        );
      }
    }


    if (
      millis() -
      tiempoEstado
      >=
      TIEMPO_ESTABILIZAR
    ) {

      float peso;


      if (
        !leerPeso(peso)
      ) {

        return;
      }


      Serial.println();
      Serial.println(
        "===== RESULTADO PESAJE SALIDA ====="
      );


      Serial.print(
        "Peso final: "
      );

      Serial.println(
        peso,
        1
      );


      // ====================================================
      // CORRECTO: CAMION VACIO
      // ====================================================

      if (
        peso >=
        VACIO_MIN
        &&
        peso <=
        VACIO_MAX
      ) {

        Serial.println(
          "CAMION VACIO"
        );

        Serial.println(
          "SALIDA AUTORIZADA"
        );


        s3(
          VERDE
        );


        servoT3.write(
          T3_ABIERTA
        );


        mostrar(
          "SALIDA APROBADA",
          "Puede salir"
        );


        basculaLibreDesde = 0;


        estado =
          SALIDA_ABIERTA;
      }


      // ====================================================
      // SIGUE CARGADO / PESO INCORRECTO
      // ====================================================

      else {

        Serial.println(
          "PESO DE SALIDA INCORRECTO"
        );


        Serial.println(
          "SALIDA BLOQUEADA"
        );


        s3(
          ROJO
        );


        servoT3.write(
          T3_CERRADA
        );


        mostrar(
          "SALIDA NEGADA",
          "Peso incorrecto"
        );


        estado =
          SALIDA_NEGADA;
      }
    }
  }


  // ========================================================
  // SALIDA AUTORIZADA
  // ========================================================

  else if (
    estado ==
    SALIDA_ABIERTA
  ) {

    if (
      millis() -
      ultimaLectura
      >=
      INTERVALO_PESO
    ) {

      ultimaLectura =
        millis();


      float peso;


      if (
        leerPeso(peso)
      ) {

        mostrarPeso(
          "CAMION SALIENDO",
          peso
        );


        if (
          peso <
          PESO_DETECCION
        ) {

          if (
            basculaLibreDesde == 0
          ) {

            basculaLibreDesde =
              millis();


            mostrar(
              "CAMION SALIO",
              "Cierre en 5s"
            );
          }


          if (
            millis() -
            basculaLibreDesde
            >=
            TIEMPO_CIERRE_T3
          ) {

            servoT3.write(
              T3_CERRADA
            );


            s3(
              ROJO
            );


            Serial.println(
              "T3 CERRADA"
            );


            Serial.println(
              "CICLO TERMINADO"
            );


            reiniciar();
          }

        } else {

          basculaLibreDesde = 0;
        }
      }
    }
  }


  // ========================================================
  // COMANDOS DE PRUEBA
  // ========================================================

  if (
    Serial.available()
  ) {

    char comando =
      Serial.read();


    // ------------------------------------------------------
    // Reinicio
    // ------------------------------------------------------

    if (
      comando == 'R' ||
      comando == 'r'
    ) {

      reiniciar();
    }


    // ------------------------------------------------------
    // Tara
    // ------------------------------------------------------

    else if (
      comando == 'T' ||
      comando == 't'
    ) {

      hacerTara();
    }


    // ------------------------------------------------------
    // T2 -> GRUA
    // ------------------------------------------------------

    else if (
      comando == 'G' ||
      comando == 'g'
    ) {

      moverT2(
        T2_GRUA,
        "GRUA MANUAL"
      );
    }


    // ------------------------------------------------------
    // T2 -> PARQUEO
    // ------------------------------------------------------

    else if (
      comando == 'P' ||
      comando == 'p'
    ) {

      moverT2(
        T2_PARQUEO,
        "PARQUEO MANUAL"
      );
    }


    // ------------------------------------------------------
    // T2 -> CENTRO
    // ------------------------------------------------------

    else if (
      comando == 'C' ||
      comando == 'c'
    ) {

      moverT2(
        T2_ESPERA,
        "CENTRO MANUAL"
      );
    }


    // ------------------------------------------------------
    // Saltar directamente al pesaje de salida
    // ------------------------------------------------------

    else if (
      comando == 'S' ||
      comando == 's'
    ) {

      Serial.println(
        "SALTANDO A PESAJE DE SALIDA"
      );


      s3(
        ROJO
      );


      servoT3.write(
        T3_CERRADA
      );


      basculaLibreDesde = 0;


      estado =
        ESPERANDO_RETORNO;


      mostrar(
        "PESAJE SALIDA",
        "Coloque camion"
      );
    }
  }
}