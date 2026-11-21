# Imagen donde corren los tests ocultos. Solo trae la infraestructura de test:
# las dependencias de la entrega se instalan aparte (paso BUILD) en un volumen.
FROM python:3.12-slim
RUN pip install --no-cache-dir --disable-pip-version-check \
        pytest==9.2.0 \
        pytest-timeout==2.4.0 \
        httpx==0.28.1
