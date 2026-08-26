// config.h
#ifndef CONFIG_H
#define CONFIG_H

// Garita (Kevin)
#define PIN_SS_RFID        53
#define PIN_RST_RFID       49
#define PIN_SERVO_TALANQUERA 9
#define PIN_SENSOR_IR_GARITA 8
#define PIN_LED_ROJO_GARITA    5
#define PIN_LED_AMARILLO_GARITA 6
#define PIN_LED_VERDE_GARITA   7

// Grua (Jose)
#define PIN_STEPPER_IN1 13
#define PIN_STEPPER_IN2 12
#define PIN_STEPPER_IN3 11
#define PIN_STEPPER_IN4 10

// Pesaje (Manuel)
// #define PIN_HX711_DATA_1 
// #define PIN_HX711_CLK   

// Seguridad (Manuel)
// #define PIN_PARO_EMERGENCIA ...

// Cantidades del sistema
#define TOTAL_CAMIONES 3
#define TOTAL_POSICIONES_PATIO 6
#define MIN_OPERACIONES_PRECARGADAS 6
#define MAX_OPERACIONES_PRECARGADAS 8

#endif