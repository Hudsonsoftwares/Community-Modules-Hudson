FROM odoo:18.0

USER root

# ── System deps required by OCA / custom addons + curl for health checks ─────
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        libcairo2-dev \
        libpango-1.0-0 \
        libpangocairo-1.0-0 \
        libgdk-pixbuf2.0-0 \
        poppler-utils \
        libzbar0 \
        git \
    && rm -rf /var/lib/apt/lists/*

# ── Extra Python deps from custom addons ─────────────────────────────────────
COPY custom-addons-requirements.txt /tmp/custom-addons-requirements.txt
RUN pip3 install --no-cache-dir --break-system-packages -r /tmp/custom-addons-requirements.txt \
    && rm /tmp/custom-addons-requirements.txt

# ── Copy all custom addons into the container ────────────────────────────────
COPY addons/ /mnt/extra-addons/

# ── Copy Odoo configuration ─────────────────────────────────────────────────
COPY odoo.conf /etc/odoo/odoo.conf

# ── Copy entrypoint wrapper ─────────────────────────────────────────────────
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# ── Fix ownership ────────────────────────────────────────────────────────────
RUN chown -R odoo:odoo /mnt/extra-addons /etc/odoo

# ── Limit math library threads to save RAM on small instances ────────────────
ENV OPENBLAS_NUM_THREADS=1 \
    OMP_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    NUMEXPR_NUM_THREADS=1 \
    VECLIB_MAXIMUM_THREADS=1

USER odoo

# ── Render uses $PORT, but expose defaults for local dev ─────────────────────
EXPOSE 8069 8072

# ── Health check (Render also pings the service, but this helps locally) ─────
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8069}/web/login || exit 1

ENTRYPOINT ["/entrypoint.sh"]

