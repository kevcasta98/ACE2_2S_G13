#include "config.h"
#include "modelos.h"
#include "control_central.h"
#include "cola_grua.h"
#include "inventario.h"
#include "consola.h"
#include "pesaje.h"
#include "seguridad.h"
#include "garita.h"
#include "ruta.h"
#include "transferencia.h"
#include "grua.h"
#include "patio_fisico.h"

void setup() {
  Serial.begin(9600);

  inicializarSeguridad();
  inicializarGarita();
  inicializarRuta();
  inicializarPesaje();
  inicializarTransferencia();
  inicializarGrua();
  inicializarPatioFisico();
  inicializarInventario();
  inicializarControlCentral();
  inicializarConsola();
}

void loop() {
  actualizarSeguridad();
  actualizarGarita();
  actualizarRuta();
  actualizarPesaje();
  actualizarTransferencia();
  actualizarGrua();
  actualizarPatioFisico();
  actualizarControlCentral();
  actualizarConsola();
}