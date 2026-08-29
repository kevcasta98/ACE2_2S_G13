// garita.cpp
#include "garita.h"
#include "config.h"
#include <SPI.h>
#include <MFRC522.h>
#include <Servo.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>

// --- Objetos de hardware ---
static MFRC522 rfid(PIN_SS_RFID, PIN_RST_RFID);
static Servo miTalanquera;
static LiquidCrystal_I2C lcd(LCD_DIRECCION_I2C, LCD_COLUMNAS, LCD_FILAS);

// --- Variables de control de tiempo (sin delay) ---
static unsigned long ultimoTiempoLectura = 0;
static const unsigned long intervaloCooldown = 1500;

static unsigned long tiempoInicioApertura = 0;
static const unsigned long tiempoCiego = 3000;

static unsigned long tiempoInicioValidacion = 0;
static const unsigned long tiempoValidacion = 1500;

// --- Estado interno de la garita ---
enum EstadoGarita
{
    ESPERANDO_CAMION,
    VALIDANDO_ACCESO,
    TIEMPO_CIEGO_ARRANQUE,
    TALANQUERA_ABIERTA,
    CAMION_CRUZANDO
};
static EstadoGarita estadoActual = ESPERANDO_CAMION;

static String uidPendiente = "";
static bool banderaCamionListo = false; // true cuando el camion ya cruzo completo

// --- Base de datos local de camiones (temporal aqui; luego vendra de control_central) ---
struct CamionLocal
{
    String rfid;
    String placa;
    bool autorizado;
};
static CamionLocal baseDatosCamiones[] = {
    {"EA225305", "C-101", true},
    {"99A08729", "C-202", true},
    {"E116F9B0", "C-303", false}};
static const int TOTAL_CAMIONES_LOCAL = 3;

// --- Funciones internas ---
static void actualizarSemaforo(int rojo, int amarillo, int verde)
{
    digitalWrite(PIN_LED_ROJO_GARITA, rojo);
    digitalWrite(PIN_LED_AMARILLO_GARITA, amarillo);
    digitalWrite(PIN_LED_VERDE_GARITA, verde);
}

static void mostrarLCD(String linea1, String linea2)
{
    lcd.clear();
    lcd.setCursor(0, 0);
    lcd.print(linea1);
    lcd.setCursor(0, 1);
    lcd.print(linea2);
}

void inicializarGarita()
{
    pinMode(PIN_SENSOR_IR_GARITA, INPUT);
    pinMode(PIN_LED_ROJO_GARITA, OUTPUT);
    pinMode(PIN_LED_AMARILLO_GARITA, OUTPUT);
    pinMode(PIN_LED_VERDE_GARITA, OUTPUT);

    pinMode(PIN_SS_RFID, OUTPUT);
    digitalWrite(PIN_SS_RFID, HIGH);

    SPI.begin();
    rfid.PCD_Init();
    miTalanquera.attach(PIN_SERVO_TALANQUERA);
    cerrarTalanquera();

    lcd.init();
    lcd.backlight();
    mostrarLCD("PORTUS - Garita", "Esperando...");

    actualizarSemaforo(HIGH, LOW, LOW);
}

// garita.cpp — agregar esta variable y exponerla
static bool banderaNuevoIngreso = false;
// dentro del case VALIDANDO_ACCESO, en la rama de éxito:
// banderaNuevoIngreso = true;
// función pública:
bool nuevoIngresoAutorizado()
{
    bool valor = banderaNuevoIngreso;
    banderaNuevoIngreso = false; // se consume una sola vez
    return valor;
}

void actualizarGarita()
{
    int estadoSensor = digitalRead(PIN_SENSOR_IR_GARITA);

    switch (estadoActual)
    {

    case ESPERANDO_CAMION:
        banderaCamionListo = false;
        if (millis() - ultimoTiempoLectura >= intervaloCooldown)
        {
            if (rfid.PICC_IsNewCardPresent() && rfid.PICC_ReadCardSerial())
            {

                ultimoTiempoLectura = millis();

                uidPendiente = "";
                for (byte i = 0; i < rfid.uid.size; i++)
                {
                    if (rfid.uid.uidByte[i] < 0x10)
                        uidPendiente += "0";
                    uidPendiente += String(rfid.uid.uidByte[i], HEX);
                }
                uidPendiente.toUpperCase();

                rfid.PICC_HaltA();
                rfid.PCD_StopCrypto1();

                actualizarSemaforo(LOW, HIGH, LOW);
                mostrarLCD("Tarjeta leida", "Validando...");
                tiempoInicioValidacion = millis();
                estadoActual = VALIDANDO_ACCESO;
            }
        }
        break;

    case VALIDANDO_ACCESO:
        if (millis() - tiempoInicioValidacion >= tiempoValidacion)
        {

            bool camionEncontrado = false;
            bool accesoPermitido = false;
            String placaDetectada = "";

            for (int i = 0; i < TOTAL_CAMIONES_LOCAL; i++)
            {
                if (baseDatosCamiones[i].rfid == uidPendiente)
                {
                    camionEncontrado = true;
                    placaDetectada = baseDatosCamiones[i].placa;
                    accesoPermitido = baseDatosCamiones[i].autorizado;
                    break;
                }
            }

            if (camionEncontrado && accesoPermitido)
            {
                mostrarLCD("Acceso: " + placaDetectada, "AUTORIZADO");
                actualizarSemaforo(LOW, LOW, HIGH);
                abrirTalanquera();
                tiempoInicioApertura = millis();
                estadoActual = TIEMPO_CIEGO_ARRANQUE;
            }
            else
            {
                if (!camionEncontrado)
                {
                    mostrarLCD("RECHAZO:", "RFID no valido");
                }
                else
                {
                    mostrarLCD("RECHAZO:", "No autorizado");
                }
                actualizarSemaforo(HIGH, LOW, LOW);
                estadoActual = ESPERANDO_CAMION;
            }
        }
        break;

    case TIEMPO_CIEGO_ARRANQUE:
        if (millis() - tiempoInicioApertura >= tiempoCiego)
        {
            estadoActual = TALANQUERA_ABIERTA;
        }
        break;

    case TALANQUERA_ABIERTA:
        if (estadoSensor == LOW)
        {
            estadoActual = CAMION_CRUZANDO;
        }
        break;

    case CAMION_CRUZANDO:
        if (estadoSensor == HIGH)
        {
            cerrarTalanquera();
            actualizarSemaforo(HIGH, LOW, LOW);
            mostrarLCD("PORTUS - Garita", "Esperando...");
            banderaCamionListo = true; // avisa a control_central que ya cruzo
            estadoActual = ESPERANDO_CAMION;
        }
        break;
    }
}

bool hayCamionEnGarita()
{
    return banderaCamionListo;
}

String obtenerUidLeido()
{
    return uidPendiente;
}

void abrirTalanquera()
{
    miTalanquera.write(90);
}

void cerrarTalanquera()
{
    miTalanquera.write(0);
}