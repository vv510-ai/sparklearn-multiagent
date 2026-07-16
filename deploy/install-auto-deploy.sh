#!/usr/bin/env bash
set -Eeuo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Please run this installer as root." >&2
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_ROOT="${SPARKLEARN_ROOT:-/opt/sparklearn}"

[[ -r "${APP_ROOT}/shared/.env" ]] || {
  echo "Missing ${APP_ROOT}/shared/.env; production secrets must be installed first." >&2
  exit 1
}
[[ -r /root/.ssh/sparklearn_github_deploy_ed25519 ]] || {
  echo "Missing the read-only GitHub deploy key." >&2
  exit 1
}

install -D -m 0755 "${REPO_ROOT}/deploy/auto-deploy.sh" "${APP_ROOT}/bin/auto-deploy.sh"
install -D -m 0644 "${REPO_ROOT}/deploy/systemd/sparklearn-auto-deploy.service" /etc/systemd/system/sparklearn-auto-deploy.service
install -D -m 0644 "${REPO_ROOT}/deploy/systemd/sparklearn-auto-deploy.timer" /etc/systemd/system/sparklearn-auto-deploy.timer

systemctl daemon-reload
systemctl enable --now sparklearn-auto-deploy.timer
systemctl start sparklearn-auto-deploy.service

echo "SparkLearn auto-deploy is installed."
systemctl --no-pager status sparklearn-auto-deploy.timer || true
