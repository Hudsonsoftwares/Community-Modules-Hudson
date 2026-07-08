#!/bin/bash
set -e

ODOO_CONF="/etc/odoo/odoo.conf"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

log "=== Odoo Entrypoint Starting ==="

# ── Parse DATABASE_URL if provided (Render PostgreSQL format) ────────────────
# Formats supported:
#   postgres://user:password@host:port/dbname
#   postgres://user:password@host:port/dbname?sslmode=require
#   postgresql://user:password@host:port/dbname
if [ -n "$DATABASE_URL" ]; then
    log "DATABASE_URL detected, parsing connection details..."

    # Strip the postgres:// or postgresql:// prefix
    DB_URL="${DATABASE_URL#*://}"

    # Extract user:password@host:port/dbname
    DB_USERPASS="${DB_URL%%@*}"
    DB_USER_PARSED="${DB_USERPASS%%:*}"
    DB_PASSWORD_PARSED="${DB_USERPASS#*:}"

    # Extract host:port/dbname?params
    DB_HOSTPORTDB="${DB_URL#*@}"
    DB_HOSTPORT="${DB_HOSTPORTDB%%/*}"
    DB_HOST_PARSED="${DB_HOSTPORT%%:*}"
    if [[ "$DB_HOSTPORT" == *":"* ]]; then
        DB_PORT_PARSED="${DB_HOSTPORT#*:}"
    else
        DB_PORT_PARSED="5432"
    fi

    # Extract dbname (strip query params)
    DB_NAMERAW="${DB_HOSTPORTDB#*/}"
    DB_NAME_PARSED="${DB_NAMERAW%%\?*}"

    # Extract sslmode from query params if present
    if [[ "$DATABASE_URL" == *"sslmode="* ]]; then
        DB_SSLMODE_PARSED=$(echo "$DATABASE_URL" | sed -n 's/.*sslmode=\([^&]*\).*/\1/p')
    fi
fi

# ── Override with individual env vars if set (env vars > DATABASE_URL > defaults)
DB_HOST="${DB_HOST:-${DB_HOST_PARSED:-localhost}}"
DB_PORT="${DB_PORT:-${DB_PORT_PARSED:-5432}}"
DB_USER="${DB_USER:-${DB_USER_PARSED:-odoo}}"
DB_PASSWORD="${DB_PASSWORD:-${DB_PASSWORD_PARSED:-odoo}}"
DB_NAME="${DB_NAME:-${DB_NAME_PARSED:-False}}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-admin}"
DB_SSLMODE="${DB_SSLMODE:-${DB_SSLMODE_PARSED:-prefer}}"

log "DB_HOST=$DB_HOST  DB_PORT=$DB_PORT  DB_USER=$DB_USER  DB_NAME=$DB_NAME  DB_SSLMODE=$DB_SSLMODE"

# ── Patch odoo.conf with resolved values ─────────────────────────────────────
sed -i "s|^db_host.*|db_host = ${DB_HOST}|"         "$ODOO_CONF"
sed -i "s|^db_port.*|db_port = ${DB_PORT}|"         "$ODOO_CONF"
sed -i "s|^db_user.*|db_user = ${DB_USER}|"         "$ODOO_CONF"
sed -i "s|^db_password.*|db_password = ${DB_PASSWORD}|" "$ODOO_CONF"
sed -i "s|^db_name.*|db_name = ${DB_NAME}|"         "$ODOO_CONF"
sed -i "s|^admin_passwd.*|admin_passwd = ${ADMIN_PASSWORD}|" "$ODOO_CONF"
sed -i "s|^db_sslmode.*|db_sslmode = ${DB_SSLMODE}|" "$ODOO_CONF"

# ── Handle Render's PORT env var ─────────────────────────────────────────────
if [ -n "$PORT" ]; then
    log "Render PORT=$PORT detected, updating http_port..."
    sed -i "s|^http_port.*|http_port = ${PORT}|" "$ODOO_CONF"
fi

# ── Wait for PostgreSQL to be ready ──────────────────────────────────────────
MAX_RETRIES=30
RETRY_INTERVAL=2
log "Waiting for PostgreSQL at $DB_HOST:$DB_PORT ..."

for i in $(seq 1 $MAX_RETRIES); do
    if pg_isready -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -q 2>/dev/null; then
        log "PostgreSQL is ready! (attempt $i/$MAX_RETRIES)"
        break
    fi

    if [ "$i" -eq "$MAX_RETRIES" ]; then
        log "WARNING: PostgreSQL not reachable after $MAX_RETRIES attempts. Starting Odoo anyway..."
        break
    fi

    log "PostgreSQL not ready yet (attempt $i/$MAX_RETRIES), retrying in ${RETRY_INTERVAL}s..."
    sleep $RETRY_INTERVAL
done

# ── Start Odoo ───────────────────────────────────────────────────────────────
if [ -n "$INIT_MODULES" ]; then
    log "Initializing modules: $INIT_MODULES (this may take several minutes)..."
    odoo -c "$ODOO_CONF" -i "$INIT_MODULES" --stop-after-init
    log "Module initialization complete. Starting Odoo server..."
fi

exec odoo -c "$ODOO_CONF" "$@"

