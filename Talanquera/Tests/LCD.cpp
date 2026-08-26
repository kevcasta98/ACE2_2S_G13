#include <Wire.h>
#include <LiquidCrystal_I2C.h>

// El primer parámetro es la dirección I2C (usualmente 0x27 o 0x3F)
// El segundo es el número de columnas (16) y el tercero el de filas (2)
LiquidCrystal_I2C lcd(0x27, 16, 2);

unsigned long tiempoUltimaActualizacion = 0;
int contador = 0;

void setup() {
  // Inicializar la pantalla y encender la luz de fondo
  lcd.init();
  lcd.backlight();
  
  // Posicionar el cursor en la primera columna (0) de la primera fila (0)
  lcd.setCursor(0, 0);
  lcd.print("PORTUS - Garita");
}

void loop() {
  // Actualizamos el contador cada segundo sin bloquear el procesador
  if (millis() - tiempoUltimaActualizacion >= 1000) {
    tiempoUltimaActualizacion = millis();
    
    // Posicionar el cursor en la primera columna (0) de la segunda fila (1)
    lcd.setCursor(0, 1);
    lcd.print("Prueba: ");
    lcd.print(contador);
    
    contador++;
  }
}