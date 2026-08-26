// inventario.h
#ifndef INVENTARIO_H
#define INVENTARIO_H
#include "modelos.h"

enum EstadoPosicion { POS_LIBRE, POS_RESERVADA, POS_OCUPADA, POS_BLOQUEADA };

void inicializarInventario();
EstadoPosicion estadoDePosicion(int posicion);
int buscarPosicionLibre();
void reservarPosicion(int posicion);
void confirmarOcupacion(int posicion, String idContenedor);
void liberarPosicion(int posicion);
void marcarBloqueada(int posicion);
#endif