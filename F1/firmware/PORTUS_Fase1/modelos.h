// modelos.h
#ifndef MODELOS_H
#define MODELOS_H
#include <Arduino.h>

struct Camion
{
    String rfid;
    String placa;
    float tara;
    bool autorizadoLocalmente;
};

struct Contenedor
{
    String id;
    float pesoDeclarado;
    int posicionPatio;
    enum
    {
        LIBRE,
        EN_PATIO,
        EN_TRANSITO
    } estado;
};

enum TipoOperacion
{
    DEPOSITO,
    RETIRO
};

struct Manifiesto
{
    int idCamion;
    int idContenedor;
    TipoOperacion tipo;
    float tolerancia;
    enum
    {
        PENDIENTE,
        EN_PROCESO,
        COMPLETADO
    } estado;
};

enum EstacionTurno
{
    ESPERA,
    GARITA,
    PESAJE_INICIAL,
    TRANSFERENCIA,
    GRUA_PATIO,
    PESAJE_FINAL,
    SALIDA,
    RETENIDO,
    CERRADO
};

struct Turno
{
    int idCamion;
    int idManifiesto;
    EstacionTurno estacionActual;
    EstacionTurno siguienteEstacion;
    float pesajeInicial;
    float pesajeFinal;
    int posicionPatioAsignada;
    bool trabajoGruaAsignado;
};

#endif