#!/bin/sh
#
# SAMCON entrypoint.
#
# Generates the Kerberos and Samba configuration from environment variables,
# prepares the tmpfs credential-cache directory and hands over to supervisor.
# Everything here must work as an unprivileged user, so nothing is written
# outside the directories owned by the samcon account.

set -eu

SAMCON_REALM="${SAMCON_REALM:-}"
SAMCON_WORKGROUP="${SAMCON_WORKGROUP:-}"
SAMCON_DC_HOSTS="${SAMCON_DC_HOSTS:-}"
SAMCON_CONF_DIR="${SAMCON_CONF_DIR:-/etc/samcon}"
SAMCON_CCACHE_DIR="${SAMCON_CCACHE_DIR:-/dev/shm/samcon-ccache}"
SAMCON_TLS_CERT="${SAMCON_TLS_CERT:-${SAMCON_CONF_DIR}/tls/server.crt}"
SAMCON_TLS_KEY="${SAMCON_TLS_KEY:-${SAMCON_CONF_DIR}/tls/server.key}"

log() { printf '%s [entrypoint] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >&2; }
die() { log "FATAL: $*"; exit 1; }

# A realm is optional: administrators can point SAMCON at a domain when they
# sign in. Configuring one only sets the default the sign-in form offers.
if [ -n "${SAMCON_REALM}" ]; then
    SAMCON_REALM=$(printf '%s' "${SAMCON_REALM}" | tr '[:lower:]' '[:upper:]')
    if [ -z "${SAMCON_WORKGROUP}" ]; then
        SAMCON_WORKGROUP=$(printf '%s' "${SAMCON_REALM}" | cut -d. -f1)
    fi
else
    log "no default realm configured — the sign-in form will ask for a server address"
fi
export SAMCON_REALM SAMCON_WORKGROUP

mkdir -p "${SAMCON_CONF_DIR}" "${SAMCON_CONF_DIR}/tls"

# --------------------------------------------------------------------------
# Credential cache directory (tmpfs — never survives a restart, by design)
# --------------------------------------------------------------------------
mkdir -p "${SAMCON_CCACHE_DIR}"
chmod 700 "${SAMCON_CCACHE_DIR}"
# Stale caches from a previous run of the same container are useless: the
# session store that referenced them is gone.
find "${SAMCON_CCACHE_DIR}" -mindepth 1 -maxdepth 1 -type f -delete 2>/dev/null || true

# --------------------------------------------------------------------------
# krb5.conf
#
# Written by the application, not here: it maintains one [realms] block per
# domain anyone signs in to, including the KDC address for domains reached by
# IP. All this does is make sure the path is set and the file exists.
# --------------------------------------------------------------------------
KRB5_CONF="${SAMCON_CONF_DIR}/krb5.conf"
if [ ! -f "${KRB5_CONF}" ]; then
    {
        echo "# Managed by SAMCON — realms are added as administrators sign in."
        echo "[libdefaults]"
        echo "    dns_lookup_realm = false"
        echo "    dns_lookup_kdc = true"
        echo "    rdns = false"
        echo "    forwardable = true"
        echo "    renewable = true"
        echo "    ticket_lifetime = ${SAMCON_TICKET_LIFETIME:-10h}"
        echo "    renew_lifetime = ${SAMCON_RENEW_LIFETIME:-7d}"
        echo "    default_ccache_name = FILE:${SAMCON_CCACHE_DIR}/default"
    } > "${KRB5_CONF}"
fi
export KRB5_CONFIG="${KRB5_CONF}"

# --------------------------------------------------------------------------
# smb.conf — only what loadparm needs for a client-side connection.
# Realm and workgroup are set per connection by the application.
# --------------------------------------------------------------------------
SMB_CONF="${SAMCON_CONF_DIR}/smb.conf"
{
    echo "[global]"
    if [ -n "${SAMCON_REALM}" ]; then
        echo "    realm = ${SAMCON_REALM}"
        echo "    workgroup = ${SAMCON_WORKGROUP}"
    fi
    echo "    security = ads"
    echo "    client signing = mandatory"
    # Deliberately NOT "seal": SAMCON connects over LDAPS, and SASL sign/seal
    # on top of TLS is rejected — every authenticated bind then fails with
    # NT_STATUS_INVALID_PARAMETER. TLS provides the encryption. The application
    # sets this per connection as well (see auth/kerberos.apply_tls_settings).
    echo "    client ldap sasl wrapping = plain"
    echo "    client min protocol = SMB3"
    echo "    client use spnego = yes"
    echo "    kerberos method = secrets and keytab"
    echo "    log level = ${SAMCON_SAMBA_LOG_LEVEL:-0}"
    echo "    private dir = /var/lib/samcon"
    echo "    state directory = /var/lib/samcon"
    echo "    cache directory = /var/cache/samcon"
    echo "    lock directory = /var/cache/samcon"
} > "${SMB_CONF}"
export SAMCON_SMB_CONF="${SMB_CONF}"

# --------------------------------------------------------------------------
# TLS material — self-signed fallback so a fresh container is usable at once.
# Production deployments mount a real certificate over /etc/samcon/tls.
#
# A bind mount from the host does not inherit the image's ownership, so the
# configured directory may well not be writable by this unprivileged user. In
# that case we fall back to a directory we do own, rather than starting nginx
# without a certificate.
# --------------------------------------------------------------------------
if [ ! -f "${SAMCON_TLS_CERT}" ] || [ ! -f "${SAMCON_TLS_KEY}" ]; then
    tls_dir=$(dirname "${SAMCON_TLS_CERT}")
    if ! mkdir -p "${tls_dir}" 2>/dev/null || [ ! -w "${tls_dir}" ]; then
        log "WARNING: ${tls_dir} is not writable — using /var/lib/samcon/tls instead."
        log "         Mount a certificate there, or make the directory writable for uid $(id -u)."
        mkdir -p /var/lib/samcon/tls
        SAMCON_TLS_CERT=/var/lib/samcon/tls/server.crt
        SAMCON_TLS_KEY=/var/lib/samcon/tls/server.key
    fi

    if [ ! -f "${SAMCON_TLS_CERT}" ]; then
        log "no TLS certificate found, generating a self-signed one (replace it for production)"
        if ! openssl req -x509 -newkey rsa:2048 -nodes -days 825 \
            -subj "/CN=${SAMCON_PUBLIC_HOST:-samcon.local}" \
            -addext "subjectAltName=DNS:${SAMCON_PUBLIC_HOST:-samcon.local},DNS:localhost,IP:127.0.0.1" \
            -keyout "${SAMCON_TLS_KEY}" -out "${SAMCON_TLS_CERT}" 2>/tmp/openssl.err
        then
            log "FATAL: could not create a TLS certificate:"
            cat /tmp/openssl.err >&2
            exit 1
        fi
        chmod 600 "${SAMCON_TLS_KEY}"
    fi
fi
export SAMCON_TLS_CERT SAMCON_TLS_KEY

# --------------------------------------------------------------------------
# nginx configuration. Only the placeholders listed on the envsubst command
# line are substituted, so nginx's own $host/$request_uri survive untouched.
# --------------------------------------------------------------------------
if [ -f "${SAMCON_CONF_DIR}/nginx.conf.template" ]; then
    SAMCON_PUBLIC_HTTPS_PORT="${SAMCON_PUBLIC_HTTPS_PORT:-443}"
    export SAMCON_PUBLIC_HTTPS_PORT
    if [ "${SAMCON_PUBLIC_HTTPS_PORT}" = "443" ]; then
        REDIRECT_TARGET='https://$host$request_uri'
    else
        REDIRECT_TARGET="https://\$host:${SAMCON_PUBLIC_HTTPS_PORT}\$request_uri"
    fi
    export REDIRECT_TARGET
    # Only these placeholders are substituted, so nginx's own $host and
    # $request_uri survive untouched.
    envsubst '${REDIRECT_TARGET} ${SAMCON_TLS_CERT} ${SAMCON_TLS_KEY}' \
        < "${SAMCON_CONF_DIR}/nginx.conf.template" \
        > "${SAMCON_CONF_DIR}/nginx.conf"
fi

mkdir -p /run/samcon

log "realm=${SAMCON_REALM:-<chosen at sign-in>} dcs=${SAMCON_DC_HOSTS:-<dns-discovery>}"
log "samba $(samba-tool --version 2>/dev/null || echo unknown)"

case "${1:-supervisor}" in
    supervisor)
        exec supervisord -c /etc/samcon/supervisord.conf
        ;;
    api)
        # Single-process mode, useful for development against a mounted source tree.
        exec uvicorn samcon.main:app --host 0.0.0.0 --port 8000
        ;;
    shell)
        exec /bin/sh
        ;;
    *)
        exec "$@"
        ;;
esac
