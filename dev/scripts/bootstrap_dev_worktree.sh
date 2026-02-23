#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TARGET_DIR="${1:-${HOME}/dev/translator-dev}"
BRANCH_NAME="${TRANSLATOR_DEV_BRANCH:-dev/isolation-runtime}"

log() {
  echo "[dev-bootstrap] $*"
}

fail() {
  echo "[dev-bootstrap] $*" >&2
  exit 1
}

backup_dirty_state() {
  local ts
  ts="$(date +%Y%m%d_%H%M%S)"
  local backup_dir="${ROOT_DIR}/dev/tmp/split_backup_${ts}"
  mkdir -p "${backup_dir}"
  git -C "${ROOT_DIR}" diff > "${backup_dir}/working.diff"
  git -C "${ROOT_DIR}" diff --cached > "${backup_dir}/staged.diff"
  git -C "${ROOT_DIR}" status --porcelain > "${backup_dir}/status.txt"
  log "backup saved: ${backup_dir}"
}

create_worktree() {
  mkdir -p "$(dirname "${TARGET_DIR}")"
  if [[ -d "${TARGET_DIR}/.git" || -f "${TARGET_DIR}/.git" ]]; then
    fail "target already exists: ${TARGET_DIR}"
  fi
  if git -C "${ROOT_DIR}" show-ref --verify --quiet "refs/heads/${BRANCH_NAME}"; then
    git -C "${ROOT_DIR}" worktree add "${TARGET_DIR}" "${BRANCH_NAME}"
  else
    git -C "${ROOT_DIR}" worktree add -b "${BRANCH_NAME}" "${TARGET_DIR}" main
  fi
}

transfer_dirty_state() {
  if [[ -z "$(git -C "${ROOT_DIR}" status --porcelain)" ]]; then
    log "no local changes to transfer"
    return
  fi
  local marker="split-dev-transfer-$(date +%Y%m%d_%H%M%S)"
  git -C "${ROOT_DIR}" stash push -u -m "${marker}" >/dev/null
  if ! git -C "${TARGET_DIR}" stash pop >/dev/null; then
    fail "failed to apply stash into ${TARGET_DIR}; inspect with git stash list"
  fi
  log "transferred dirty state into ${TARGET_DIR}"
}

main() {
  backup_dirty_state
  create_worktree
  transfer_dirty_state
  log "done"
  log "stable checkout: ${ROOT_DIR}"
  log "dev checkout: ${TARGET_DIR}"
}

main "$@"
