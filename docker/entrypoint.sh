#!/bin/sh
#
# SAMADCON entrypoint.
#
# Generates the Kerberos and Samba configuration from environment variables,
# prepares the tmpfs credential-cache directory and hands over to supervisor.
# Everything here must work as an unprivileged user, so nothing is written
# outside the directories owned by the samadcon account.

set -eu

SAMADCON_REALM="${SAMADCON_REALM:-}"
SAMADCON_WORKGROUP="${SAMADCON_WORKGROUP:-}"
SAMADCON_DC_HOSTS="${SAMADCON_DC_HOSTS:-}"
SAMADCON_CONF_DIR="${SAMADCON_CONF_DIR:-/etc/samadcon}"
SAMADCON_CCACHE_DIR="${SAMADCON_CCACHE_DIR:-/dev/shm/samadcon-ccache}"
SAMADCON_TLS_CERT="${SAMADCON_TLS_CERT:-${SAMADCON_CONF_DIR}/tls/server.crt}"
SAMADCON_TLS_KEY="${SAMADCON_TLS_KEY:-${SAMADCON_CONF_DIR}/tls/server.key}"

log() { printf '%s [entrypoint] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >&2; }
die() { log "FATAL: $*"; exit 1; }

# A realm is optional: administrators can point SAMADCON at a domain when they
# sign in. Configuring one only sets the default the sign-in form offers.
if [ -n "${SAMADCON_REALM}" ]; then
    SAMADCON_REALM=$(printf '%s' "${SAMADCON_REALM}" | tr '[:lower:]' '[:upper:]')
    if [ -z "${SAMADCON_WORKGROUP}" ]; then
        SAMADCON_WORKGROUP=$(printf '%s' "${SAMADCON_REALM}" | cut -d. -f1)
    fi
else
    log "no default realm configured — the sign-in form will ask for a server address"
fi
export SAMADCON_REALM SAMADCON_WORKGROUP

mkdir -p "${SAMADCON_CONF_DIR}" "${SAMADCON_CONF_DIR}/tls"

# --------------------------------------------------------------------------
# Credential cache directory (tmpfs — never survives a restart, by design)
# --------------------------------------------------------------------------
mkdir -p "${SAMADCON_CCACHE_DIR}"
chmod 700 "${SAMADCON_CCACHE_DIR}"
# Stale caches from a previous run of the same container are useless: the
# session store that referenced them is gone.
find "${SAMADCON_CCACHE_DIR}" -mindepth 1 -maxdepth 1 -type f -delete 2>/dev/null || true

# --------------------------------------------------------------------------
# krb5.conf
#
# Written by the application, not here: it maintains one [realms] block per
# domain anyone signs in to, including the KDC address for domains reached by
# IP. All this does is make sure the path is set and the file exists.
# --------------------------------------------------------------------------
KRB5_CONF="${SAMADCON_CONF_DIR}/krb5.conf"
if [ ! -f "${KRB5_CONF}" ]; then
    {
        echo "# Managed by SAMADCON — realms are added as administrators sign in."
        echo "[libdefaults]"
        echo "    dns_lookup_realm = false"
        echo "    dns_lookup_kdc = true"
        echo "    rdns = false"
        echo "    forwardable = true"
        echo "    renewable = true"
        echo "    ticket_lifetime = ${SAMADCON_TICKET_LIFETIME:-10h}"
        echo "    renew_lifetime = ${SAMADCON_RENEW_LIFETIME:-7d}"
        echo "    default_ccache_name = FILE:${SAMADCON_CCACHE_DIR}/default"
    } > "${KRB5_CONF}"
fi
export KRB5_CONFIG="${KRB5_CONF}"

# --------------------------------------------------------------------------
# smb.conf — only what loadparm needs for a client-side connection.
# Realm and workgroup are set per connection by the application.
# --------------------------------------------------------------------------
SMB_CONF="${SAMADCON_CONF_DIR}/smb.conf"
{
    echo "[global]"
    if [ -n "${SAMADCON_REALM}" ]; then
        echo "    realm = ${SAMADCON_REALM}"
        echo "    workgroup = ${SAMADCON_WORKGROUP}"
    fi
    echo "    security = ads"
    echo "    client signing = mandatory"
    # Deliberately NOT "seal": SAMADCON connects over LDAPS, and SASL sign/seal
    # on top of TLS is rejected — every authenticated bind then fails with
    # NT_STATUS_INVALID_PARAMETER. TLS provides the encryption. The application
    # sets this per connection as well (see auth/kerberos.apply_tls_settings).
    echo "    client ldap sasl wrapping = plain"
    echo "    client min protocol = SMB3"
    echo "    client use spnego = yes"
    echo "    kerberos method = secrets and keytab"

    echo "    log level = ${SAMADCON_SAMBA_LOG_LEVEL:-0}"
    echo "    private dir = /var/lib/samadcon"
    echo "    state directory = /var/lib/samadcon"
    echo "    cache directory = /var/cache/samadcon"
    echo "    lock directory = /var/cache/samadcon"
} > "${SMB_CONF}"
export SAMADCON_SMB_CONF="${SMB_CONF}"

# --------------------------------------------------------------------------
# TLS material — self-signed fallback so a fresh container is usable at once.
# Production deployments mount a real certificate over /etc/samadcon/tls.
#
# A bind mount from the host does not inherit the image's ownership, so the
# configured directory may well not be writable by this unprivileged user. In
# that case we fall back to a directory we do own, rather than starting nginx
# without a certificate.
# --------------------------------------------------------------------------
if [ ! -f "${SAMADCON_TLS_CERT}" ] || [ ! -f "${SAMADCON_TLS_KEY}" ]; then
    tls_dir=$(dirname "${SAMADCON_TLS_CERT}")
    if ! mkdir -p "${tls_dir}" 2>/dev/null || [ ! -w "${tls_dir}" ]; then
        log "WARNING: ${tls_dir} is not writable — using /var/lib/samadcon/tls instead."
        log "         Mount a certificate there, or make the directory writable for uid $(id -u)."
        mkdir -p /var/lib/samadcon/tls
        SAMADCON_TLS_CERT=/var/lib/samadcon/tls/server.crt
        SAMADCON_TLS_KEY=/var/lib/samadcon/tls/server.key
    fi

    if [ ! -f "${SAMADCON_TLS_CERT}" ]; then
        log "no TLS certificate found, generating a self-signed one (replace it for production)"
        if ! openssl req -x509 -newkey rsa:2048 -nodes -days 825 \
            -subj "/CN=${SAMADCON_PUBLIC_HOST:-samadcon.local}" \
            -addext "subjectAltName=DNS:${SAMADCON_PUBLIC_HOST:-samadcon.local},DNS:localhost,IP:127.0.0.1" \
            -keyout "${SAMADCON_TLS_KEY}" -out "${SAMADCON_TLS_CERT}" 2>/tmp/openssl.err
        then
            log "FATAL: could not create a TLS certificate:"
            cat /tmp/openssl.err >&2
            exit 1
        fi
        chmod 600 "${SAMADCON_TLS_KEY}"
    fi
fi
export SAMADCON_TLS_CERT SAMADCON_TLS_KEY

# --------------------------------------------------------------------------
# Which hop in front of us may be believed about the caller's address.
#
# nginx sees only the machine that connected to it. Behind a reverse proxy
# that machine is the proxy, and without this every audit entry records the
# proxy rather than the administrator who acted — the one field meant to tell
# two administrators apart.
#
# X-Forwarded-For answers it, but only from someone entitled to set it: it is
# a plain header, and a client can send its own. So the trusted hops are named
# here and nowhere else. Empty by default, which means believe nobody and use
# the address that actually connected.
# --------------------------------------------------------------------------
REAL_IP_CONF="${SAMADCON_CONF_DIR}/real-ip.conf"
{
    echo "# Generated by entrypoint.sh from SAMADCON_TRUSTED_PROXIES."
    if [ -n "${SAMADCON_TRUSTED_PROXIES:-}" ]; then
        # Commas or spaces, so the variable can be written either way.
        for proxy in $(printf '%s' "${SAMADCON_TRUSTED_PROXIES}" | tr ',' ' '); do
            echo "set_real_ip_from ${proxy};"
        done
        echo "real_ip_header X-Forwarded-For;"
        # Walks the chain from the right and stops at the first address that
        # is not a trusted hop. That address is the caller.
        echo "real_ip_recursive on;"
    else
        echo "# SAMADCON_TRUSTED_PROXIES is unset: no forwarded header is believed."
    fi
} > "${REAL_IP_CONF}"

# --------------------------------------------------------------------------
# nginx configuration. Only the placeholders listed on the envsubst command
# line are substituted, so nginx's own $host/$request_uri survive untouched.
# --------------------------------------------------------------------------
if [ -f "${SAMADCON_CONF_DIR}/nginx.conf.template" ]; then
    SAMADCON_PUBLIC_HTTPS_PORT="${SAMADCON_PUBLIC_HTTPS_PORT:-443}"
    export SAMADCON_PUBLIC_HTTPS_PORT
    if [ "${SAMADCON_PUBLIC_HTTPS_PORT}" = "443" ]; then
        REDIRECT_TARGET='https://$host$request_uri'
    else
        REDIRECT_TARGET="https://\$host:${SAMADCON_PUBLIC_HTTPS_PORT}\$request_uri"
    fi
    export REDIRECT_TARGET
    # Only these placeholders are substituted, so nginx's own $host and
    # $request_uri survive untouched.
    envsubst '${REDIRECT_TARGET} ${SAMADCON_TLS_CERT} ${SAMADCON_TLS_KEY} ${SAMADCON_CONF_DIR}' \
        < "${SAMADCON_CONF_DIR}/nginx.conf.template" \
        > "${SAMADCON_CONF_DIR}/nginx.conf"
fi

mkdir -p /run/samadcon

log "realm=${SAMADCON_REALM:-<chosen at sign-in>} dcs=${SAMADCON_DC_HOSTS:-<dns-discovery>}"
# `samba-tool --version` prints the version but also complains about a missing
# subcommand, and the complaint goes to stdout — so redirecting stderr, which
# is what this line used to do, discarded nothing and the log read
# "samba samba-tool: missing subcommand" with the version on a line of its own.
# Pick the version out instead of assuming where the noise lands.
samba_version=$(samba-tool --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+[^[:space:]]*' | head -n 1)
log "samba ${samba_version:-unknown}"

case "${1:-supervisor}" in
    supervisor)
        exec supervisord -c /etc/samadcon/supervisord.conf
        ;;
    api)
        # Single-process mode, useful for development against a mounted source tree.
        exec uvicorn samadcon.main:app --host 0.0.0.0 --port 8000
        ;;
    shell)
        exec /bin/sh
        ;;
    *)
        exec "$@"
        ;;
esac
