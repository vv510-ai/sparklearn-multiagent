#!/usr/bin/env bash
set -Eeuo pipefail

umask 027

APP_ROOT="${SPARKLEARN_ROOT:-/opt/sparklearn}"
REPO_URL="${SPARKLEARN_REPO_URL:-git@github.com:vv510-ai/sparklearn-multiagent.git}"
BRANCH="${SPARKLEARN_DEPLOY_BRANCH:-main}"
DEPLOY_KEY="${SPARKLEARN_DEPLOY_KEY:-/root/.ssh/sparklearn_github_deploy_ed25519}"
KEEP_RELEASES="${SPARKLEARN_KEEP_RELEASES:-5}"
WAIT_TIMEOUT="${SPARKLEARN_WAIT_TIMEOUT:-420}"

REPO_DIR="${APP_ROOT}/repository"
RELEASES_DIR="${APP_ROOT}/releases"
SHARED_DIR="${APP_ROOT}/shared"
CURRENT_LINK="${APP_ROOT}/current"
ENV_FILE="${SHARED_DIR}/.env"
DEPLOYED_COMMIT_FILE="${SHARED_DIR}/deployed_commit"
LOCK_FILE="/run/lock/sparklearn-auto-deploy.lock"

log() {
  printf '[%s] %s\n' "$(date --iso-8601=seconds)" "$*"
}

die() {
  log "ERROR: $*"
  exit 1
}

[[ "${BRANCH}" =~ ^[A-Za-z0-9._/-]+$ ]] || die "Invalid deploy branch: ${BRANCH}"
[[ "${KEEP_RELEASES}" =~ ^[1-9][0-9]*$ ]] || die "SPARKLEARN_KEEP_RELEASES must be a positive integer"
[[ "${WAIT_TIMEOUT}" =~ ^[1-9][0-9]*$ ]] || die "SPARKLEARN_WAIT_TIMEOUT must be a positive integer"
[[ -r "${DEPLOY_KEY}" ]] || die "GitHub deploy key not found: ${DEPLOY_KEY}"
[[ -r "${ENV_FILE}" ]] || die "Production environment file not found: ${ENV_FILE}"
[[ -s /root/.ssh/known_hosts ]] || die "SSH known_hosts is missing"

install -d -m 0750 "${APP_ROOT}" "${RELEASES_DIR}" "${SHARED_DIR}"
install -d -m 0755 "$(dirname "${LOCK_FILE}")"
exec 9>"${LOCK_FILE}"
if ! flock -n 9; then
  log "Another deployment is already running; skip this check"
  exit 0
fi

export GIT_SSH_COMMAND="ssh -i ${DEPLOY_KEY} -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes"

if [[ ! -d "${REPO_DIR}/.git" ]]; then
  log "Creating the read-only GitHub checkout"
  git clone --no-checkout "${REPO_URL}" "${REPO_DIR}"
else
  git -C "${REPO_DIR}" remote set-url origin "${REPO_URL}"
fi

log "Checking origin/${BRANCH}"
git -C "${REPO_DIR}" fetch --prune origin "+refs/heads/${BRANCH}:refs/remotes/origin/${BRANCH}"
TARGET_COMMIT="$(git -C "${REPO_DIR}" rev-parse "refs/remotes/origin/${BRANCH}")"
[[ "${TARGET_COMMIT}" =~ ^[0-9a-f]{40}$ ]] || die "GitHub returned an invalid commit id"

CURRENT_COMMIT=""
if [[ -r "${DEPLOYED_COMMIT_FILE}" ]]; then
  CURRENT_COMMIT="$(tr -d '[:space:]' < "${DEPLOYED_COMMIT_FILE}")"
fi

compose() {
  local release="$1"
  local image_tag="$2"
  shift 2
  IMAGE_TAG="${image_tag}" docker compose \
    --project-name sparklearn \
    --project-directory "${release}" \
    --env-file "${ENV_FILE}" \
    -f "${release}/docker-compose.prod.yml" \
    "$@"
}

if [[ "${TARGET_COMMIT}" == "${CURRENT_COMMIT}" && -L "${CURRENT_LINK}" ]]; then
  if curl --fail --silent --max-time 20 http://127.0.0.1/ >/dev/null; then
    log "Already running healthy release ${TARGET_COMMIT:0:12}; nothing to deploy"
    exit 0
  fi

  current_release="$(readlink -f "${CURRENT_LINK}")"
  log "Release ${TARGET_COMMIT:0:12} is current but unhealthy; restarting it"
  compose "${current_release}" "${TARGET_COMMIT}" up -d --remove-orphans --wait --wait-timeout "${WAIT_TIMEOUT}"
  curl --fail --silent --show-error --max-time 20 http://127.0.0.1/ >/dev/null
  exit 0
fi

RELEASE_DIR="${RELEASES_DIR}/${TARGET_COMMIT}"
PREVIOUS_RELEASE=""
if [[ -L "${CURRENT_LINK}" ]]; then
  PREVIOUS_RELEASE="$(readlink -f "${CURRENT_LINK}" || true)"
fi

case "${RELEASE_DIR}" in
  "${RELEASES_DIR}"/[0-9a-f]*) ;;
  *) die "Unsafe release directory: ${RELEASE_DIR}" ;;
esac

if [[ -e "${RELEASE_DIR}" ]]; then
  rm -rf -- "${RELEASE_DIR}"
fi
install -d -m 0750 "${RELEASE_DIR}"

log "Preparing release ${TARGET_COMMIT:0:12}"
git -C "${REPO_DIR}" archive --format=tar "${TARGET_COMMIT}" | tar -xf - -C "${RELEASE_DIR}"
ln -s "${ENV_FILE}" "${RELEASE_DIR}/.env"
printf '%s\n' "${TARGET_COMMIT}" > "${RELEASE_DIR}/.release_commit"

[[ -f "${RELEASE_DIR}/docker-compose.prod.yml" ]] || die "docker-compose.prod.yml is missing in ${BRANCH}"
[[ -f "${RELEASE_DIR}/deploy/nginx.conf" ]] || die "deploy/nginx.conf is missing in ${BRANCH}"

deploy_release() {
  log "Validating production Compose config"
  compose "${RELEASE_DIR}" "${TARGET_COMMIT}" config --quiet || return $?
  log "Building ${TARGET_COMMIT:0:12}"
  compose "${RELEASE_DIR}" "${TARGET_COMMIT}" build || return $?
  log "Starting containers and waiting for health checks"
  compose "${RELEASE_DIR}" "${TARGET_COMMIT}" up -d --remove-orphans --wait --wait-timeout "${WAIT_TIMEOUT}" || return $?
  curl --fail --silent --show-error --max-time 20 http://127.0.0.1/ >/dev/null || return $?
}

rollback() {
  [[ -n "${PREVIOUS_RELEASE}" ]] || return 0
  [[ -f "${PREVIOUS_RELEASE}/docker-compose.prod.yml" ]] || return 0

  local previous_commit="${CURRENT_COMMIT:-rollback}"
  log "Rolling back to ${previous_commit:0:12}"
  compose "${PREVIOUS_RELEASE}" "${previous_commit}" up -d --remove-orphans --wait --wait-timeout "${WAIT_TIMEOUT}" || \
    compose "${PREVIOUS_RELEASE}" "${previous_commit}" up -d --build --remove-orphans --wait --wait-timeout "${WAIT_TIMEOUT}"
}

status=0
deploy_release || status=$?
if (( status != 0 )); then
  touch "${RELEASE_DIR}/.failed"
  rollback || log "Rollback also failed; manual recovery is required"
  die "Release ${TARGET_COMMIT:0:12} failed with status ${status}"
fi

ln -sfn "${RELEASE_DIR}" "${CURRENT_LINK}.new"
mv -Tf "${CURRENT_LINK}.new" "${CURRENT_LINK}"
printf '%s\n' "${TARGET_COMMIT}" > "${DEPLOYED_COMMIT_FILE}.new"
mv -f "${DEPLOYED_COMMIT_FILE}.new" "${DEPLOYED_COMMIT_FILE}"

log "Release ${TARGET_COMMIT:0:12} is healthy and active"

# A successful release also refreshes the deployer itself, so future changes to
# this repository-owned deployment chain do not require another manual install.
install -D -m 0755 "${RELEASE_DIR}/deploy/auto-deploy.sh" "${APP_ROOT}/bin/auto-deploy.sh.new"
mv -f "${APP_ROOT}/bin/auto-deploy.sh.new" "${APP_ROOT}/bin/auto-deploy.sh"
install -D -m 0644 "${RELEASE_DIR}/deploy/systemd/sparklearn-auto-deploy.service" /etc/systemd/system/sparklearn-auto-deploy.service
install -D -m 0644 "${RELEASE_DIR}/deploy/systemd/sparklearn-auto-deploy.timer" /etc/systemd/system/sparklearn-auto-deploy.timer
systemctl daemon-reload

mapfile -t release_dirs < <(find "${RELEASES_DIR}" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' | sort -rn | cut -d' ' -f2-)
if (( ${#release_dirs[@]} > KEEP_RELEASES )); then
  for old_release in "${release_dirs[@]:KEEP_RELEASES}"; do
    [[ "${old_release}" == "${RELEASE_DIR}" ]] && continue
    case "${old_release}" in
      "${RELEASES_DIR}"/*) rm -rf -- "${old_release}" ;;
    esac
  done
fi

docker image prune -f --filter 'until=168h' >/dev/null || true
