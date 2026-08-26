// pesaje.h
#ifndef PESAJE_H
#define PESAJE_H
void inicializarPesaje();
void actualizarPesaje();
bool pesajeListo();      // true cuando ya hay una medición válida
float obtenerPesoMedido();
#endif