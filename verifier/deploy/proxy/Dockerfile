# Proxy con lista blanca para el paso BUILD (fase 3). Se conecta a dos redes: la interna `cc-build`
# (donde corre pip) y la de salida. Ver squid.conf.
FROM debian:12-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends squid \
    && rm -rf /var/lib/apt/lists/*
COPY squid.conf /etc/squid/squid.conf
USER proxy
EXPOSE 3128
CMD ["squid", "-N", "-f", "/etc/squid/squid.conf"]
