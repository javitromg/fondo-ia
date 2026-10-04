#!/bin/sh
# Arranque en Linux o en la nube (el equivalente a INICIAR.bat).
# Si el programa sale con código 3 es que pidió reiniciarse para aplicar una actualización: se vuelve a lanzar.
# Con cualquier otro código se sale, y el servidor decide si lo reinicia (en Railway: reinicio "on failure").
while true; do
  python -m fondo auto
  codigo=$?
  [ "$codigo" -eq 3 ] && continue
  exit "$codigo"
done
