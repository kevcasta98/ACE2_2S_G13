// control_central.h
#ifndef CONTROL_CENTRAL_H
#define CONTROL_CENTRAL_H
#include "modelos.h"

void inicializarControlCentral();
void actualizarControlCentral();

// útiles para la consola de supervisión
int totalTurnosActivos();
Turno obtenerTurno(int indice);
#endif