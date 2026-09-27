# Backend de Cumple&Cobra para Railway (se construye desde la raíz del repositorio).
#
# UN solo proceso y UN solo worker de uvicorn: los candados por tarea (asyncio.Lock), el candado del
# release (threading.Lock, una secuencia del árbitro), los retos SEP-10 pendientes, las cachés y
# state.json viven en la memoria de ese proceso. Con dos workers o dos réplicas, dos procesos podrían
# contar envíos, firmar release o escribir state.json a la vez sin verse.
FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    PIP_NO_CACHE_DIR=1 \
    STATE_FILE=/data/state.json

WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install -r backend/requirements.txt
COPY backend backend

# Railway inyecta PORT. El middleware lee X-Real-IP, que su proxy sobrescribe con la IP del cliente.
# No confiar en todas las fuentes de cabeceras reenviadas de uvicorn.
CMD ["sh", "-c", "exec uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --proxy-headers --no-server-header"]
