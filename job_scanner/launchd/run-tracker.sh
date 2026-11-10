#!/bin/zsh
# Wrapper invoked by launchd. Usage: run-tracker.sh check|digest
# Output goes to the launchd log files; track.py keeps its own track.log.

set -euo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
mode="${1:-}"
case "${mode}" in
  check|digest) ;;
  *) echo "usage: $0 check|digest" >&2; exit 64 ;;
esac

# Load login PATH so `claude` and `python3` resolve.
source "${HOME}/.zshrc" 2>/dev/null || true

cd "${REPO}"
exec /usr/bin/env python3 job_scanner/track.py "--${mode}"
