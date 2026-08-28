#include <SPI.h>
#include <MFRC522.h>

#define RST_PIN 5 // Pin RST
#define SS_PIN 53 // SDA en Pin 53 del arduino

MFRC522 mfrc522(SS_PIN, RST_PIN);

void setup()
{
    pinMode(53, OUTPUT);   
    digitalWrite(53, HIGH); 

    Serial.begin(9600);
    while (!Serial)
        ;

    SPI.begin();

    // intento de reducir el spi del bus
    SPI.beginTransaction(SPISettings(4000000, MSBFIRST, SPI_MODE0));

    // Forzar un reset físico por hardware antes de iniciar
    digitalWrite(RST_PIN, LOW);
    delay(50);          // SOLO PARA PRUEBAS NO ES PARTE DEL CODIGO PRINCIPAL
    digitalWrite(RST_PIN, HIGH);
    delay(50);           // SOLO PARA PRUEBAS NO ES PARTE DEL CODIGO PRINCIPAL

    mfrc522.PCD_Init(); 
    delay(100);         // SOLO PARA PRUEBAS NO ES PARTE DEL CODIGO PRINCIPAL

    Serial.println(F("=============================="));
    Serial.println(F("Modo de Prueba para el RFID"));
    Serial.println(F("Acercar una tarjeta"));
    Serial.println(F("=============================="));
}

void loop()
{
    byte version = mfrc522.PCD_ReadRegister(mfrc522.VersionReg);
    if (version == 0x00 || version == 0xFF)
    {
        digitalWrite(RST_PIN, LOW);
        delay(10);           // SOLO PARA PRUEBAS NO ES PARTE DEL CODIGO PRINCIPAL
        digitalWrite(RST_PIN, HIGH);
        delay(10);           // SOLO PARA PRUEBAS NO ES PARTE DEL CODIGO PRINCIPAL
        mfrc522.PCD_Init();
        return; 
    }

    if (!mfrc522.PICC_IsNewCardPresent())
    {
        return;
    }

    if (!mfrc522.PICC_ReadCardSerial())
    {
        return;
    }

    Serial.print(F("¡TARJETA DETECTADA! UID:"));
    for (byte i = 0; i < mfrc522.uid.size; i++)
    {
        Serial.print(mfrc522.uid.uidByte[i] < 0x10 ? " 0" : " ");
        Serial.print(mfrc522.uid.uidByte[i], HEX);
    }
    Serial.println();

    mfrc522.PICC_HaltA();
    mfrc522.PCD_StopCrypto1();
    delay(500);         // SOLO PARA PRUEBAS NO ES PARTE DEL CODIGO PRINCIPAL
}