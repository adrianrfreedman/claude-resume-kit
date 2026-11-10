#!/bin/zsh
# Wrapper invoked by launchd. Runs the scan scripts back to back and emails
# the digest. No Claude session: Claude is only used per JD, inside score.py.
#
# Flow:
#   0.  prefetch.py   fetch + parse + dedupe listings, JD bodies (state/candidates_<today>.json)
#   0b. score.py      score JDs in parallel MCP-free headless Sonnet calls (state/scores_<today>.json)
#   0c. digest.py     render digests/digest_<today>.md + .json sidecar, append state/seen.jsonl and the run log
#   2.  send_digest.py  email the digest (recipient from config.md) via SMTP
#                       using a Gmail app password stored in macOS Keychain.

set -euo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
SCANNER="${REPO}/job_scanner"
LOG_DIR="${SCANNER}/state/runs"
TS="$(date +%Y-%m-%d_%H%M%S)"
TODAY="$(date +%Y-%m-%d)"
LOG="${LOG_DIR}/launchd_${TS}.log"
DIGEST="${SCANNER}/digests/digest_${TODAY}.md"

mkdir -p "${LOG_DIR}"

# Load login PATH so `claude` (used by score.py) and `python3` resolve.
source "${HOME}/.zshrc" 2>/dev/null || true

cd "${REPO}"

{
  echo "=== scan-jobs run @ ${TS} ==="
  echo "PATH=${PATH}"
  echo "PWD=$(pwd)"

  echo "--- step 0: prefetch ---"
  # Parallel fetch + parse + dedupe -> state/candidates_<today>.json. Failure is
  # not fatal here; digest.py exits 1 if the file is missing and nothing is sent.
  prefetch_status=0
  /usr/bin/env python3 "${SCANNER}/prefetch.py" --deadline 240 || prefetch_status=$?
  echo "prefetch.py exited ${prefetch_status}"

  echo "--- step 0b: score ---"
  # One MCP-free headless call per JD -> state/scores_<today>.json. Failure is not
  # fatal: unscored JDs land in the digest's "Not scored" section, retried next run.
  score_status=0
  /usr/bin/env python3 "${SCANNER}/score.py" --deadline 600 || score_status=$?
  echo "score.py exited ${score_status}"

  echo "--- step 0c: digest ---"
  # Ranks scored JDs, writes the digest + sidecar, appends the ledger and run log.
  digest_status=0
  /usr/bin/env python3 "${SCANNER}/digest.py" || digest_status=$?
  echo "digest.py exited ${digest_status}"

  echo "--- step 2: send digest ---"
  send_status=1
  if [[ "${digest_status}" -eq 0 && -f "${DIGEST}" ]]; then
    send_status=0
    /usr/bin/env python3 "${SCANNER}/send_digest.py" "${DIGEST}" || send_status=$?
    echo "send_digest.py exited ${send_status}"
  else
    echo "WARN: digest.py exited ${digest_status} or ${DIGEST} missing; skipping email"
  fi

  echo "=== overall exit (prefetch=${prefetch_status}, score=${score_status}, digest=${digest_status}, send=${send_status}) ==="
} >> "${LOG}" 2>&1
