// cola_grua.cpp
#include "cola_grua.h"

void inicializarColaGrua() {}
void encolarTrabajo(TrabajoGrua trabajo) {}
bool hayTrabajoPendiente() { return false; }
TrabajoGrua obtenerSiguienteTrabajo()
{
    TrabajoGrua vacio = {TRABAJO_DEPOSITO, -1, -1, -1};
    return vacio;
}
void completarTrabajoActual() {}