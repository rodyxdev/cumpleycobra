#!/usr/bin/env bash
# Script de arranque de la VM del verificador (fase 3). Lo ejecuta Google Compute Engine como root
# en cada arranque (las VMs Spot se detienen y vuelven a arrancar). Es idempotente.
#
# La VM no tiene cuenta de servicio ni scopes: no puede leer nada de Google Cloud. Lo único sensible
# que recibe es el token de la cola, en el metadato personalizado `verifier-queue-token`; los
# contenedores no pueden leer metadatos (regla DOCKER-USER de abajo).
#
# El código del verificador NO se clona aquí (el repositorio puede ser privado y no queremos
# credenciales en la VM): lo copia `deploy.ps1` por IAP a /opt/cyc. Hasta entonces, el trabajador espera.
set -euo pipefail
exec > >(logger -t cyc-startup) 2>&1

META=http://metadata.google.internal/computeMetadata/v1/instance/attributes
meta() { curl -fsS -H "Metadata-Flavor: Google" "$META/$1" || true; }

# --- 1. Docker y gVisor --------------------------------------------------------------------
# Debian 12 en GCE usa https://deb.debian.org; el firewall solo deja salir al 443.
if ! command -v docker >/dev/null; then
  apt-get update
  apt-get install -y --no-install-recommends docker.io python3-venv curl gnupg ca-certificates iptables
fi
if ! command -v runsc >/dev/null; then
  # Instalación documentada en gvisor.dev (repositorio apt firmado).
  curl -fsSL https://gvisor.dev/archive.key | gpg --batch --yes --dearmor -o /usr/share/keyrings/gvisor-archive-keyring.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/gvisor-archive-keyring.gpg] https://storage.googleapis.com/gvisor/releases release main" \
    > /etc/apt/sources.list.d/gvisor.list
  apt-get update
  apt-get install -y runsc
  runsc install          # registra el runtime "runsc" en /etc/docker/daemon.json
  systemctl restart docker
fi

# --- 2. Red: metadatos, host y salida del build ------------------------------------------------
# Ningún contenedor habla con el servidor de metadatos ni con servicios del host.
iptables -C DOCKER-USER -d 169.254.169.254 -j DROP 2>/dev/null || iptables -I DOCKER-USER -d 169.254.169.254 -j DROP
for ifc in docker0 br+; do
  iptables -C INPUT -i "$ifc" -j DROP 2>/dev/null || iptables -I INPUT -i "$ifc" -j DROP
done
# Red interna sin ruta a internet para el paso BUILD; su única salida es el proxy con lista blanca.
docker network inspect cc-build >/dev/null 2>&1 || docker network create --internal cc-build
# Red de salida del proxy, con subred fija. El proxy necesita DNS, y en GCE el DNS es el servidor de
# metadatos: solo esta red puede hablarle, y solo al puerto 53. El HTTP de metadatos (tokens y el
# token de la cola) sigue bloqueado para todos los contenedores.
SALIDA=172.30.250.0/24
docker network inspect cc-salida >/dev/null 2>&1 || docker network create --subnet "$SALIDA" cc-salida
for proto in udp tcp; do
  iptables -C DOCKER-USER -s "$SALIDA" -d 169.254.169.254 -p "$proto" --dport 53 -j ACCEPT 2>/dev/null \
    || iptables -I DOCKER-USER -s "$SALIDA" -d 169.254.169.254 -p "$proto" --dport 53 -j ACCEPT
done

# --- 3. Código, imágenes y proxy ---------------------------------------------------------------
until [ -f /opt/cyc/verifier/worker.py ]; do
  echo "esperando el código del verificador en /opt/cyc (deploy.ps1)"; sleep 30
done
cd /opt/cyc
# Con la red del host (el DNS de los contenedores es el de metadatos, bloqueado) y apt por HTTPS.
cp /etc/ssl/certs/ca-certificates.crt verifier/deploy/proxy/certs/ca-certificates.crt
docker build -q --network host -t cyc-proxy verifier/deploy/proxy >/dev/null
if ! docker ps --format '{{.Names}}' | grep -qx cyc-proxy; then
  docker rm -f cyc-proxy >/dev/null 2>&1 || true
  docker run -d --name cyc-proxy --restart unless-stopped --read-only --tmpfs /var/spool/squid --tmpfs /var/log/squid \
    --cap-drop ALL --security-opt no-new-privileges --network cc-salida cyc-proxy
  docker network connect --alias proxy cc-build cyc-proxy
fi
docker pull -q python:3.12-slim >/dev/null
# Imagen de los tests ocultos (pytest). Se construye aquí con la red del host: los contenedores
# del build de Docker no pasan por el proxy y el DNS de la VM (metadatos) les queda bloqueado.
docker build -q --network host -t cumpleycobra-runner:vm verifier/sandbox/runner_image >/dev/null

if [ ! -x /opt/cyc/.venv/bin/python ]; then
  python3 -m venv /opt/cyc/.venv
  /opt/cyc/.venv/bin/pip install -q -r verifier/deploy/requirements-worker.txt
fi

# --- 4. Trabajador -----------------------------------------------------------------------------
umask 077
cat > /etc/cyc-verificador.env <<ENV
VERIFIER_API_URL=$(meta verifier-api-url)
VERIFIER_QUEUE_TOKEN=$(meta verifier-queue-token)
VERIFIER_WORK_DIR=/var/lib/cyc/verifier
SANDBOX_RUNTIME=runsc
RUNNER_IMAGE=cumpleycobra-runner:vm
BUILD_NETWORK=cc-build
BUILD_PROXY_CONTAINER=cyc-proxy
PYTHONIOENCODING=utf-8
ENV
install -m 0644 verifier/deploy/cyc-verificador.service /etc/systemd/system/cyc-verificador.service
systemctl daemon-reload
systemctl enable --now cyc-verificador
systemctl restart cyc-verificador
echo "verificador listo"
