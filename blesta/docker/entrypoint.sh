#!/bin/sh
set -eu

mkdir -p /tmp/nginx/client-body /tmp/nginx/fastcgi /tmp/nginx/proxy
mkdir -p /opt/blesta/data/config /opt/blesta/data/cache /opt/blesta/data/logs \
  /opt/blesta/data/uploads /opt/blesta/data/sessions

# First boot on a fresh volume: seed config/cache from the image's defaults
# (routes.php, mime.php, the DB config template, ...). Never overwrites an
# existing config/blesta.php from a real install on a subsequent boot.
if [ ! -f /opt/blesta/data/config/blesta-new.php ]; then
  cp -rn /opt/blesta/defaults/config/. /opt/blesta/data/config/
fi
if [ -z "$(ls -A /opt/blesta/data/cache 2>/dev/null)" ]; then
  cp -rn /opt/blesta/defaults/cache/. /opt/blesta/data/cache/
fi

chown -R nobody:nobody /opt/blesta/data

trap 'kill -TERM ${PHPFPM_PID:-} ${NGINX_PID:-} 2>/dev/null || true; wait' TERM INT

php-fpm -F &
PHPFPM_PID=$!

nginx -c /etc/nginx/nginx.conf &
NGINX_PID=$!

wait -n "$PHPFPM_PID" "$NGINX_PID"
