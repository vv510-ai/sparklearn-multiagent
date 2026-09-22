#!/usr/bin/env bash
set -Eeuo pipefail
exec 9>/run/lock/sparklearn-cert-renew.lock
flock -n 9 || exit 0
docker run --rm \
  -v /etc/letsencrypt:/etc/letsencrypt \
  -v /opt/sparklearn/shared/letsencrypt-webroot:/var/www/certbot \
  certbot/certbot:v5.4.0 renew --quiet --no-directory-hooks
# Certbot runs in a container without the host Docker socket. Reload on the host.
docker exec sparklearn-nginx-1 nginx -t
docker exec sparklearn-nginx-1 nginx -s reload
