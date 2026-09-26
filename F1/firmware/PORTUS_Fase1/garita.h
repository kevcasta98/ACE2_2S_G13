// garita.h
#ifndef GARITA_H
#define GARITA_H
#include <Arduino.h>

void inicializarGarita();
void actualizarGarita();
bool hayCamionEnGarita();
String obtenerUidLeido();
void abrirTalanquera();
void cerrarTalanquera();
bool nuevoIngresoAutorizado(); // true una vez, cuando se autoriza el acceso
#endif