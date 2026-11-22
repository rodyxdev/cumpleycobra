# Proxy con lista blanca para el paso BUILD (fase 3). Se conecta a dos redes: la interna `cc-build`
# (donde corre pip) y la de salida. Ver squid.conf.
#
# En la VM el firewall solo deja salir al 443: startup.sh copia los certificados de la VM a certs/
# y aquí apt pasa a HTTPS (las firmas de los paquetes se verifican igual). En una laptop, certs/
# queda vacío y apt usa el espejo por defecto.
FROM debian:12-slim
COPY certs/ /tmp/certs/
RUN if [ -f /tmp/certs/ca-certificates.crt ]; then \
        mkdir -p /etc/ssl/certs && cp /tmp/certs/ca-certificates.crt /etc/ssl/certs/ca-certificates.crt \
        && sed -i 's#http://deb.debian.org#https://deb.debian.org#g' /etc/apt/sources.list.d/debian.sources; \
    fi \
    && apt-get update \
    && apt-get install -y --no-install-recommends squid \
    && rm -rf /var/lib/apt/lists/* /tmp/certs
COPY squid.conf /etc/squid/squid.conf
USER proxy
EXPOSE 3128
CMD ["squid", "-N", "-f", "/etc/squid/squid.conf"]
