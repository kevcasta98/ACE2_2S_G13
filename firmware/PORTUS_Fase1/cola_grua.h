// cola_grua.h
#ifndef COLA_GRUA_H
#define COLA_GRUA_H
#include "modelos.h"

enum TipoTrabajoGrua
{
    TRABAJO_DEPOSITO,
    TRABAJO_RETIRO,
    TRABAJO_REMOCION
};

struct TrabajoGrua
{
    TipoTrabajoGrua tipo;
    int idTurno;
    int posicionOrigen;
    int posicionDestino;
};

void inicializarColaGrua();
void encolarTrabajo(TrabajoGrua trabajo);
bool hayTrabajoPendiente();
TrabajoGrua obtenerSiguienteTrabajo();
void completarTrabajoActual();
#endif