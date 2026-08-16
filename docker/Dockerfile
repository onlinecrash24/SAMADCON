# syntax=docker/dockerfile:1.7
#
# SAMCON — Samba AD Console
#
# Debian instead of Alpine on purpose: the runtime needs python3-samba, which
# exists only as a distribution package. There is no PyPI equivalent, and
# rebuilding the Samba python bindings by hand is not worth the trouble.

ARG DEBIAN_RELEASE=trixie
ARG NODE_VERSION=22

# ---------------------------------------------------------------------------
# Stage 1 — frontend bundle
# ---------------------------------------------------------------------------
FROM node:${NODE_VERSION}-slim AS frontend

WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi

# Copied file by file rather than `COPY frontend/ ./`: that form would drop the
# host's node_modules on top of the ones just installed, and a Windows-built
# tsc shim cannot run here. The .dockerignore covers this too — this makes the
# build correct even without it.
COPY frontend/index.html frontend/tsconfig.json frontend/vite.config.ts ./
COPY frontend/src ./src
COPY frontend/public ./public

RUN npm run build

# ---------------------------------------------------------------------------
# Stage 2 — runtime
# ---------------------------------------------------------------------------
FROM debian:${DEBIAN_RELEASE}-slim AS runtime

ARG SAMCON_VERSION=0.1.0
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    SAMCON_VERSION=${SAMCON_VERSION}

# python3-samba pulls in the LDAP/SMB/NDR bindings, samba-common-bin gives us
# samba-tool for cross-checking, krb5-user gives us klist/kinit for diagnostics.
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 \
        python3-venv \
        python3-pip \
        python3-samba \
        python3-lxml \
        python3-dnspython \
        samba-common-bin \
        samba-dsdb-modules \
        samba-vfs-modules \
        libsmbclient \
        krb5-user \
        ca-certificates \
        nginx \
        supervisor \
        tini \
        curl \
        openssl \
        gettext-base \
    && rm -rf /var/lib/apt/lists/*

# --system-site-packages keeps the distribution's samba bindings visible inside
# the venv; without it every `import samba` fails.
RUN python3 -m venv --system-site-packages /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

WORKDIR /opt/samcon

COPY backend/pyproject.toml ./
COPY backend/samcon ./samcon
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

COPY --from=frontend /build/dist /srv/samcon/www
COPY docker/nginx.conf.template /etc/samcon/nginx.conf.template
COPY docker/supervisord.conf /etc/samcon/supervisord.conf
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Non-root. The ccache directory lives on tmpfs and is created by the
# entrypoint, since /dev/shm is mounted fresh on every start.
# The tls/ca/servers directories must exist in the image and belong to samcon:
# docker seeds a named volume from the image directory, permissions included.
# Without them, a volume mounted at /etc/samcon/tls arrives owned by root and
# the entrypoint cannot write the fallback certificate.
RUN groupadd --gid 1000 samcon \
    && useradd --uid 1000 --gid 1000 --home-dir /var/lib/samcon --create-home samcon \
    && mkdir -p /var/lib/samcon/tls /var/log/samcon /var/cache/samcon \
                /etc/samcon/tls /etc/samcon/ca /etc/samcon/servers \
                /var/lib/nginx /var/log/nginx /run/samcon \
    && chown -R samcon:samcon /var/lib/samcon /var/log/samcon /var/cache/samcon \
                              /etc/samcon /var/lib/nginx /var/log/nginx /run/samcon \
                              /srv/samcon

USER samcon

# Ports above 1024 so nginx can bind without extra capabilities.
EXPOSE 8080 8443

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8080/api/v1/health || exit 1

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/entrypoint.sh"]
CMD ["supervisor"]

# ---------------------------------------------------------------------------
# Stage 3 — test image
#
# Adds the test suite and pytest on top of the runtime image, so integration
# tests exercise exactly the image that ships. Selected with SAMCON_TARGET=test
# in .env, which docker-compose.yml passes through as the build target.
# ---------------------------------------------------------------------------
FROM runtime AS test

USER root
COPY backend/tests /opt/samcon/tests
RUN pip install --no-cache-dir "pytest>=8.2" "pytest-asyncio>=0.23" "httpx>=0.27" \
    && chown -R samcon:samcon /opt/samcon
USER samcon
