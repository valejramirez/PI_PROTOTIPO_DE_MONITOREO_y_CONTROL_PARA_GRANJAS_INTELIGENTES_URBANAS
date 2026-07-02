# Guia de puesta en marcha - Sistema de control de macetas

Para una Raspberry Pi 4B con Raspberry Pi OS ya instalado.

## 0. Copiar el proyecto a la Pi

Copia la carpeta `tesis/` completa al home del usuario, por ejemplo a
`/home/pi/tesis/`. Debe contener:

    main.py  control.py  hardware.py  config_loader.py  models.py
    config.toml  requirements.txt

## 1. Habilitar I2C

Los sensores (PCF8591, BH1750) van por I2C. Hay que habilitarlo:

    sudo raspi-config
    # Interface Options -> I2C -> Yes -> Finish

Reiniciar si lo pide. Verificar que los dispositivos aparecen:

    sudo apt update
    sudo apt install -y i2c-tools python3-venv libgpiod2
    i2cdetect -y 1

Deberias ver las direcciones de tus dispositivos: 0x48 (ADC), 0x23 y 0x5C
(los dos BH1750). Si alguna no aparece, es problema de cableado, no de software.

## 2. Crear el entorno virtual e instalar dependencias

    cd /home/pi/tesis
    python3 -m venv venv
    source venv/bin/activate
    pip install --upgrade pip
    pip install -r requirements.txt

## 3. Proteger los reles durante el arranque (IMPORTANTE)

Los modulos de rele son activos-en-bajo (activa_bajo=true para bomba, luces y
valvulas). Durante el arranque de la Pi, antes de que corra el script, esos
GPIO estan en estado bajo por defecto = rele ENCENDIDO. Para evitar que la
bomba y las luces se activen solas durante el boot, forzar el nivel alto desde
el firmware.

Editar el archivo de arranque (en Bookworm es /boot/firmware/config.txt; en
versiones anteriores /boot/config.txt):

    sudo nano /boot/firmware/config.txt

Agregar al final:

    # Reles activos-en-bajo: forzar HIGH (apagado) desde el boot
    gpio=24=op,dh
    gpio=26,19=op,dh
    gpio=22,17=op,dh

    24 = bomba
    26, 19 = luces maceta1 y maceta2
    22, 17 = valvulas maceta1 y maceta2

Los ventiladores (23 y 25) son activos-en-alto: su estado seguro es LOW, que
es el default del kernel, no necesitan linea.

Guardar y reiniciar:  sudo reboot

## 4. Correr el programa manualmente

    cd /home/pi/tesis
    source venv/bin/activate
    python main.py

Para detenerlo: Ctrl + C. El bloque `finally` apaga todos los actuadores y
libera los GPIO limpiamente.

## Notas

- El intervalo de lectura esta en 1800 s (30 min) en config.toml. Para probar
  rapido, bajalo temporalmente a 10 o 20 y volve a subirlo despues.
- El CSV se guarda como `registro_con_DLI.csv` en la misma carpeta.
- Si `i2cdetect` no muestra un sensor, el codigo no crashea: esa lectura
  devuelve None y se registra la alerta correspondiente.
