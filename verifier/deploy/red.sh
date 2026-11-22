#!/usr/bin/env bash
# Reglas de red de la VM del verificador (fase 3). Las corre `cyc-red.service` ANTES de que arranque
# Docker en cada encendido: la VM se apaga y enciende sola, y las reglas de iptables no sobreviven a
# un reinicio. Sin esto, los contenedores que Docker levanta al arrancar (el proxy) tendrían unos
# segundos sin las reglas. Si este script falla, Docker no arranca (RequiredBy=docker.service).
#
# - Ningún contenedor habla con el servidor de metadatos (tokens de Google y el token de la cola),
#   salvo la red del proxy (cc-salida, 172.30.250.0/24), y solo al DNS (puerto 53).
# - Ningún contenedor habla con servicios del host.
# Docker conserva la cadena DOCKER-USER si ya existe: solo le agrega su RETURN al final.
set -euo pipefail

SALIDA=172.30.250.0/24
META=169.254.169.254

iptables -N DOCKER-USER 2>/dev/null || true
iptables -F DOCKER-USER
for proto in udp tcp; do
  iptables -A DOCKER-USER -s "$SALIDA" -d "$META" -p "$proto" --dport 53 -j ACCEPT
done
iptables -A DOCKER-USER -d "$META" -j DROP
iptables -A DOCKER-USER -j RETURN

for ifc in docker0 br+; do
  iptables -C INPUT -i "$ifc" -j DROP 2>/dev/null || iptables -I INPUT -i "$ifc" -j DROP
done
