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

# Temporary diagnostic: inspect the CLI installer's interface (help text,
# and what it prompts for when given empty stdin) to script it. Remove
# once the install flow is scripted for real.
{
  echo "--- resetting blesta DB and config (prior attempt left config pointing at an empty DB) ---"
  mariadb --host=mariadb --user=root --password="qHqdf34clLAMaL8haddfUJlb" \
    -e "DROP DATABASE IF EXISTS blesta; CREATE DATABASE blesta CHARACTER SET utf8mb4;"
  rm -f /opt/blesta/data/config/blesta.php
  echo "--- install, full guessed answer sequence ---"
  cd /opt/blesta/blesta && printf 'Y\nmariadb\n3306\nblesta\nblesta\nGIZbCU8XDCkexdj8IzeUfBhP\n\nJean\nKassi\njean.kassi@synelia.tech\nadmin\nFkhZ5AHuTGl03UNv\nFkhZ5AHuTGl03UNv\nSynelia\n\n\n\n' \
    | timeout 10 php index.php install > /tmp/install_full.log 2>&1
  echo "--- last 2000 bytes ---"
  tail -c 2000 /tmp/install_full.log
  echo "--- around the FIRST 'License Key' occurrence (context) ---"
  grep -n -m1 -A25 "License Key" /tmp/install_full.log
  echo "--- total bytes: $(wc -c < /tmp/install_full.log) ---"
} > /opt/blesta/blesta/diag 2>&1 || true
chmod 644 /opt/blesta/blesta/diag || true

trap 'kill -TERM ${PHPFPM_PID:-} ${NGINX_PID:-} 2>/dev/null || true; wait' TERM INT

php-fpm -F &
PHPFPM_PID=$!

nginx -c /etc/nginx/nginx.conf &
NGINX_PID=$!

wait -n "$PHPFPM_PID" "$NGINX_PID"
