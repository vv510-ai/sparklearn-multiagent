#!/bin/sh
set -eu

if docker inspect sparklearn-nginx-1 >/dev/null 2>&1; then
  docker restart sparklearn-nginx-1 >/dev/null
fi
