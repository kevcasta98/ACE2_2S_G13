#include "control_central.h"
#include "config.h"
#include "garita.h"
#include "ruta.h"
#include "pesaje.h"
#include "transferencia.h"
#include "grua.h"
#include "cola_grua.h"
#include "inventario.h"

// --- Camiones y manifiestos precargados (datos locales de la Fase 1) ---
static Camion baseCamiones[TOTAL_CAMIONES] = {
    {"EA225305", "C-101", 500.0, true},
    {"99A08729", "C-202", 520.0, true},
    {"E116F9B0", "C-303", 500.0, false}};

static Manifiesto baseManifiestos[MAX_OPERACIONES_PRECARGADAS] = {
    {0, 0, DEPOSITO, 5.0, Manifiesto::PENDIENTE},
    {1, 1, RETIRO, 5.0, Manifiesto::PENDIENTE},
    // TODO: completar hasta 6-8 operaciones (mezcla depósito/retiro)
};

// --- Turnos activos (recurso central de concurrencia) ---
#define MAX_TURNOS_ACTIVOS 3
static Turno turnos[MAX_TURNOS_ACTIVOS];
static bool turnoOcupado[MAX_TURNOS_ACTIVOS] = {false, false, false};

// --- Búsqueda de un slot libre para crear un nuevo turno ---
static int buscarSlotLibre()
{
    for (int i = 0; i < MAX_TURNOS_ACTIVOS; i++)
    {
        if (!turnoOcupado[i])
            return i;
    }
    return -1; // sin capacidad: la garita debe rechazar el ingreso
}

static int buscarCamionPorRfid(String rfid)
{
    for (int i = 0; i < TOTAL_CAMIONES; i++)
    {
        if (baseCamiones[i].rfid == rfid)
            return i;
    }
    return -1;
}

static int buscarManifiestoPendiente(int idCamion)
{
    int encontrado = -1;
    for (int i = 0; i < MAX_OPERACIONES_PRECARGADAS; i++)
    {
        if (baseManifiestos[i].idCamion == idCamion &&
            baseManifiestos[i].estado == Manifiesto::PENDIENTE)
        {
            if (encontrado != -1)
                return -2; // más de un manifiesto pendiente = rechazo
            encontrado = i;
        }
    }
    return encontrado; // -1 = ninguno, -2 = ambiguo, >=0 = índice válido
}

void inicializarControlCentral()
{
    for (int i = 0; i < MAX_TURNOS_ACTIVOS; i++)
    {
        turnoOcupado[i] = false;
    }
}

// --- Intento de creación de un turno nuevo desde la garita ---
static void intentarCrearTurno()
{
    if (!hayCamionEnGarita())
        return;

    String uid = obtenerUidLeido();
    int idCamion = buscarCamionPorRfid(uid);

    if (idCamion == -1)
    {
        // RFID no reconocido -> la propia garita.cpp debe mostrar el rechazo
        return;
    }
    if (!baseCamiones[idCamion].autorizadoLocalmente)
    {
        return; // camión no autorizado
    }

    int idManifiesto = buscarManifiestoPendiente(idCamion);
    if (idManifiesto < 0)
    {
        return; // sin manifiesto o ambiguo -> rechazo
    }

    int slot = buscarSlotLibre();
    if (slot == -1)
    {
        return; // sin capacidad -> el camión espera
    }

    // TODO: validar según tipo de operación que exista posición
    // accesible (depósito) o que el contenedor exista en patio (retiro),
    // usando inventario.h antes de aceptar.

    Turno nuevo;
    nuevo.idCamion = idCamion;
    nuevo.idManifiesto = idManifiesto;
    nuevo.estacionActual = GARITA;
    nuevo.siguienteEstacion = PESAJE_INICIAL;
    nuevo.pesajeInicial = 0;
    nuevo.pesajeFinal = 0;
    nuevo.posicionPatioAsignada = -1;
    nuevo.trabajoGruaAsignado = false;

    turnos[slot] = nuevo;
    turnoOcupado[slot] = true;
    baseManifiestos[idManifiesto].estado = Manifiesto::EN_PROCESO;

    abrirTalanquera();
}

// --- Avance de un turno individual, un paso por llamada (no bloqueante) ---
static void actualizarTurno(int i)
{
    Turno &t = turnos[i];

    switch (t.estacionActual)
    {

    case GARITA:
        if (hayCamionEnGarita())
        {
            t.estacionActual = PESAJE_INICIAL;
        }
        break;

    case PESAJE_INICIAL:
        if (pesajeListo())
        {
            t.pesajeInicial = obtenerPesoMedido();
            // TODO: comparar contra manifiesto + tolerancia
            bool pesoValido = true; // placeholder hasta tener la comparación real
            if (pesoValido)
            {
                continuarRutaNormal();
                t.estacionActual = TRANSFERENCIA;
            }
            else
            {
                desviarARamal();
                t.estacionActual = RETENIDO;
            }
        }
        break;

    case TRANSFERENCIA:
        if (!zonaTransferenciaOcupada() && camionDetectadoEnTransferencia())
        {
            // TODO: reservar posición en inventario.h y encolar trabajo en cola_grua.h
            TrabajoGrua trabajo = {TRABAJO_DEPOSITO, i, -1, t.posicionPatioAsignada};
            encolarTrabajo(trabajo);
            t.trabajoGruaAsignado = true;
            t.estacionActual = GRUA_PATIO;
        }
        break;

    case GRUA_PATIO:
        // Espera a que la cola de grúa confirme que su trabajo terminó
        if (t.trabajoGruaAsignado && gruaOciosa())
        {
            // TODO: confirmar físicamente colocación antes de avanzar
            t.estacionActual = PESAJE_FINAL;
        }
        break;

    case PESAJE_FINAL:
        if (pesajeListo())
        {
            t.pesajeFinal = obtenerPesoMedido();
            // TODO: comparar contra tara / peso esperado
            t.estacionActual = SALIDA;
        }
        break;

    case SALIDA:
        // TODO: validar mismo camión, abrir puerta y esperar que salga
        t.estacionActual = CERRADO;
        break;

    case RETENIDO:
        // Turno queda bloqueado en Fase 1: no se reincorpora (según enunciado)
        break;

    case CERRADO:
        baseManifiestos[t.idManifiesto].estado = Manifiesto::COMPLETADO;
        turnoOcupado[i] = false; // libera el slot para un nuevo camión
        break;

    default:
        break;
    }
}

void actualizarControlCentral()
{
    intentarCrearTurno();

    for (int i = 0; i < MAX_TURNOS_ACTIVOS; i++)
    {
        if (turnoOcupado[i])
        {
            actualizarTurno(i);
        }
    }
}

int totalTurnosActivos()
{
    int total = 0;
    for (int i = 0; i < MAX_TURNOS_ACTIVOS; i++)
    {
        if (turnoOcupado[i])
            total++;
    }
    return total;
}

Turno obtenerTurno(int indice)
{
    return turnos[indice];
}