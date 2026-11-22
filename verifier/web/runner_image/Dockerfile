# Lado CONFIABLE del perfil web (portado de v2): navegadores de la imagen oficial de Playwright y el
# paquete de Python de la misma versión (la imagen trae los navegadores pero no el paquete).
# Nunca monta la entrega: la página se sirve en otro contenedor y se visita por la red interna.
FROM mcr.microsoft.com/playwright/python:v1.64.1-noble
RUN pip install --no-cache-dir --break-system-packages playwright==1.64.1
