#!/bin/sh
set -eu

CERT_NAME="${TLS_CERT_NAME:-47.121.24.54}"
TLS_ENABLED="${TLS_ENABLED:-false}"
case "${CERT_NAME}" in
  ''|*[!A-Za-z0-9._:-]*)
    echo "Invalid TLS_CERT_NAME: ${CERT_NAME}" >&2
    exit 1
    ;;
esac

case "${TLS_ENABLED}" in
  true|1|yes|on)
    TLS_ENABLED="true"
    ;;
  false|0|no|off|'')
    TLS_ENABLED="false"
    ;;
  *)
    echo "Invalid TLS_ENABLED: ${TLS_ENABLED}" >&2
    exit 1
    ;;
esac

CERT_DIR="/etc/letsencrypt/live/${CERT_NAME}"
if [ "${TLS_ENABLED}" = "true" ] && [ -s "${CERT_DIR}/fullchain.pem" ] && [ -s "${CERT_DIR}/privkey.pem" ]; then
  sed "s|__CERT_NAME__|${CERT_NAME}|g" \
    /etc/sparklearn/nginx.https.conf > /etc/nginx/conf.d/default.conf
  if [ "${TLS_REDIRECT:-true}" = "false" ]; then
    # Keep HTTP available until an external client verifies the new TLS listener.
    sed -n '/^server {/,$p' /etc/sparklearn/nginx.http.conf > /etc/nginx/conf.d/http.conf
  else
    cp /etc/sparklearn/nginx.redirect.conf /etc/nginx/conf.d/http.conf
  fi
  echo "SparkLearn nginx: HTTPS enabled for ${CERT_NAME}"
elif [ "${TLS_ENABLED}" = "true" ]; then
  cp /etc/sparklearn/nginx.http.conf /etc/nginx/conf.d/default.conf
  echo "SparkLearn nginx: TLS requested but certificate not present; HTTP remains enabled"
else
  cp /etc/sparklearn/nginx.http.conf /etc/nginx/conf.d/default.conf
  echo "SparkLearn nginx: TLS disabled; HTTP remains enabled"
fi

exec nginx -g 'daemon off;'
