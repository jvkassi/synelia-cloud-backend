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

# Temporary diagnostic: no log access to this host via the Dokploy API, so
# write php-fpm's config test + php -v to a static file servable over HTTP.
# Remove once the 502 is root-caused.
{
  echo "--- php -v ---"; php -v
  echo "--- ls data/config ---"; ls -la /opt/blesta/data/config
  echo "--- CLI run of index.php ---"
  cd /opt/blesta/blesta && REQUEST_URI=/ SCRIPT_NAME=/index.php php index.php
  echo "--- end CLI run (exit $?) ---"
} > /opt/blesta/blesta/diag 2>&1 || true
chmod 644 /opt/blesta/blesta/diag || true

trap 'kill -TERM ${PHPFPM_PID:-} ${NGINX_PID:-} 2>/dev/null || true; wait' TERM INT

php-fpm -F &
PHPFPM_PID=$!

nginx -c /etc/nginx/nginx.conf &
NGINX_PID=$!

wait -n "$PHPFPM_PID" "$NGINX_PID"
