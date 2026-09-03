#!/bin/sh
set -eu

mkdir -p /tmp/nginx/client-body /tmp/nginx/fastcgi /tmp/nginx/proxy
chown -R nobody:nobody /tmp/nginx
mkdir -p /opt/blesta/data/config /opt/blesta/data/cache /opt/blesta/data/logs \
  /opt/blesta/data/uploads /opt/blesta/data/sessions

# First boot on a fresh volume: seed config/cache from the image's defaults
# (routes.php, mime.php, the DB config template, ...). Never overwrites an
# existing config/blesta.php from a real install on a subsequent boot.
# tar (not `cp -rn .../.`) because Alpine's busybox cp doesn't reliably
# support -n / the trailing-dot recursive-copy idiom the way GNU cp does.
if [ ! -f /opt/blesta/data/config/blesta-new.php ]; then
  (cd /opt/blesta/defaults/config && tar cf - .) | (cd /opt/blesta/data/config && tar xf -)
fi
if [ -z "$(ls -A /opt/blesta/data/cache 2>/dev/null)" ]; then
  (cd /opt/blesta/defaults/cache && tar cf - .) | (cd /opt/blesta/data/cache && tar xf -)
fi

chown -R nobody:nobody /opt/blesta/data

# Unconditional marker (verifies which build is actually running -- remove
# once the license lookup below is confirmed to actually execute).
echo "entrypoint-marker-v3 FORCE_REINSTALL=${FORCE_REINSTALL:-unset} LOOKUP_LICENSE=${LOOKUP_LICENSE:-unset}" \
  > /opt/blesta/blesta/marker 2>&1 || true
chmod 644 /opt/blesta/blesta/marker || true

# One-time reinstall, gated by an env var (not left unconditional like the
# earlier debugging pass -- flip FORCE_REINSTALL off in Dokploy's compose
# env right after this runs once, no code change/redeploy needed to undo it).
if [ "${FORCE_REINSTALL:-0}" = "1" ]; then
  {
    echo "--- force reinstall: resetting DB and config ---"
    mariadb --host=mariadb --user=root --password="${MARIADB_ROOT_PASSWORD}" \
      -e "DROP DATABASE IF EXISTS blesta; CREATE DATABASE blesta CHARACTER SET utf8mb4;"
    rm -f /opt/blesta/data/config/blesta.php
    echo "--- running installer ---"
    cd /opt/blesta/blesta && printf 'Y\nmariadb\n3306\nblesta\nblesta\n%s\n%s\n\nJean\nKassi\njean.kassi@synelia.tech\nadmin\n%s\n' \
      "${MARIADB_BLESTA_PASSWORD}" "${BLESTA_DOMAIN:-blesta.osdconsulting.net}" "${BLESTA_ADMIN_PASSWORD}" \
      | timeout 40 php index.php install
  } > /opt/blesta/blesta/diag 2>&1 || true
  chmod 644 /opt/blesta/blesta/diag || true
fi

# Separate, non-destructive, read-only lookup -- independent gate so
# checking on something never risks re-triggering the reinstall above.
if [ "${LOOKUP_LICENSE:-0}" = "1" ]; then
  {
    echo "--- tables with 'licen' or 'setting' in the name ---"
    mariadb --host=mariadb --user=root --password="${MARIADB_ROOT_PASSWORD}" blesta \
      -e "SELECT table_name FROM information_schema.tables WHERE table_schema='blesta' AND (table_name LIKE '%licen%' OR table_name LIKE '%setting%');" 2>&1 || true
    echo "--- company_settings rows matching 'licen' ---"
    mariadb --host=mariadb --user=root --password="${MARIADB_ROOT_PASSWORD}" blesta \
      -e "SELECT * FROM company_settings WHERE \`key\` LIKE '%licen%';" 2>&1 || true
  } > /opt/blesta/blesta/license-diag 2>&1 || true
  chmod 644 /opt/blesta/blesta/license-diag || true
fi

trap 'kill -TERM ${PHPFPM_PID:-} ${NGINX_PID:-} 2>/dev/null || true; wait' TERM INT

php-fpm -F &
PHPFPM_PID=$!

nginx -c /etc/nginx/nginx.conf &
NGINX_PID=$!

wait -n "$PHPFPM_PID" "$NGINX_PID"
