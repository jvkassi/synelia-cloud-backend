### Blesta — custom image (Dokploy / any Docker host)
#
# Built from source (not the community ppmathis/blesta image) so that
# custom modules/plugins developed for the Synelia <-> OpenStack provisioner
# integration can be baked in at build time via plugins/ and modules/
# below, without depending on someone else's release cadence.
#
# Persistence model: /opt/blesta/data is a Docker volume (see
# docker-compose.yml). config/ and cache/ live there and are symlinked
# into the webroot; uploads/ and logs/ directories are also created there
# but must be pointed to from Blesta's own admin settings once, post-install
# (Settings -> System -> General -> Basic Setup) — see ../README.md.
FROM alpine:3.20

ARG BLESTA_VERSION=6.0.1
ARG BLESTA_DOWNLOAD_ID=317
ARG IONCUBE_VERSION=14.0.0
ARG PHP_VERSION=82

# ---- Download Blesta at build time (never vendored into git) --------------
RUN apk add --no-cache curl unzip \
    && curl -fsSLo /tmp/blesta.zip \
        "https://account.blesta.com/plugin/download_manager/client_main/download/${BLESTA_DOWNLOAD_ID}/blesta-${BLESTA_VERSION}.zip" \
    && mkdir -p /opt/blesta \
    && unzip -q /tmp/blesta.zip -d /opt/blesta \
    && rm -f /tmp/blesta.zip

# ---- ioncube loader (Blesta ships ~3 encoded files that need it) ----------
RUN ARCH="$(uname -m | sed -e 's/x86_64/x86-64/;s/aarch64/aarch64/')" \
    && curl -fsSLo /tmp/ioncube.tar.gz \
        "https://downloads.ioncube.com/loader_downloads/ioncube_loaders_lin_${ARCH}_${IONCUBE_VERSION}.tar.gz" \
    && mkdir -p /opt/ioncube \
    && tar -xf /tmp/ioncube.tar.gz -C /opt/ioncube --strip-components=1 \
    && cp "/opt/ioncube/ioncube_loader_lin_$(echo ${PHP_VERSION} | sed 's/\(.\)\(.*\)/\1.\2/').so" /opt/ioncube/ioncube_loader_lin.so \
    && rm -f /tmp/ioncube.tar.gz

# ---- System packages: nginx + PHP-FPM + required extensions ---------------
RUN apk add --no-cache \
        nginx \
        mariadb-client \
        ca-certificates \
        "php${PHP_VERSION}" \
        "php${PHP_VERSION}-curl" \
        "php${PHP_VERSION}-fileinfo" \
        "php${PHP_VERSION}-fpm" \
        "php${PHP_VERSION}-gd" \
        "php${PHP_VERSION}-gmp" \
        "php${PHP_VERSION}-iconv" \
        "php${PHP_VERSION}-imap" \
        "php${PHP_VERSION}-mbstring" \
        "php${PHP_VERSION}-pdo" \
        "php${PHP_VERSION}-pdo_mysql" \
        "php${PHP_VERSION}-pecl-mailparse" \
        "php${PHP_VERSION}-session" \
        "php${PHP_VERSION}-simplexml" \
        "php${PHP_VERSION}-soap" \
        "php${PHP_VERSION}-xml" \
        "php${PHP_VERSION}-tokenizer" \
        "php${PHP_VERSION}-ctype" \
        "php${PHP_VERSION}-dom" \
        "php${PHP_VERSION}-opcache" \
        "php${PHP_VERSION}-phar" \
        "php${PHP_VERSION}-zip" \
    && ln -sf "/usr/bin/php${PHP_VERSION}" /usr/bin/php \
    && ln -sf "/usr/sbin/php-fpm${PHP_VERSION}" /usr/sbin/php-fpm \
    && ln -sf "/etc/php${PHP_VERSION}" /etc/php

# ---- Custom modules/plugins (Synelia <-> OpenStack provisioner lives here) ­
COPY plugins/ /opt/blesta/blesta/plugins/
COPY modules/ /opt/blesta/blesta/components/modules/

# ---- Persistent data dir: the volume starts empty, so the config/cache
# directories Blesta ships with (routes.php, mime.php, the DB config
# template, ...) are preserved as "defaults" and copied into the volume by
# entrypoint.sh on first boot only -- never overwriting a real install.
RUN mkdir -p /opt/blesta/defaults \
    && cp -r /opt/blesta/blesta/config /opt/blesta/defaults/config \
    && cp -r /opt/blesta/blesta/cache /opt/blesta/defaults/cache \
    && rm -rf /opt/blesta/blesta/config /opt/blesta/blesta/cache \
    && ln -s /opt/blesta/data/config /opt/blesta/blesta/config \
    && ln -s /opt/blesta/data/cache /opt/blesta/blesta/cache

COPY docker/nginx.conf /etc/nginx/nginx.conf
COPY docker/php-custom.ini "/etc/php${PHP_VERSION}/conf.d/99-custom.ini"
COPY docker/php-fpm-pool.conf "/etc/php${PHP_VERSION}/php-fpm.d/www.conf"
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

RUN mkdir -p /run/nginx \
    && chown -R nobody:nobody /opt/blesta/blesta /run/nginx /var/lib/nginx /var/log/nginx

VOLUME ["/opt/blesta/data"]
EXPOSE 8080
ENTRYPOINT ["/entrypoint.sh"]
