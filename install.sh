#!/usr/bin/env bash
# ponytail: curl|bash installer; pipx or pip --user, no clone step
set -euo pipefail

REPO="https://github.com/lindsay-cheng/weave.git"
PKG="git+${REPO}"

check_only=false
if [[ "${1:-}" == "--check" ]]; then
  check_only=true
fi

case "$(uname -s)" in
  Darwin|Linux) ;;
  *) echo "weave install supports macOS and Linux only"; exit 1 ;;
esac

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found; install Python 3.11+"
  exit 1
fi

if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
  echo "Python 3.11+ required (found $(python3 -V 2>&1))"
  exit 1
fi

if ! command -v git >/dev/null 2>&1; then
  echo "git not found; required to install from GitHub"
  exit 1
fi

if $check_only; then
  echo "checks passed"
  exit 0
fi

if command -v pipx >/dev/null 2>&1; then
  pipx install --force "$PKG"
  echo "installed weave (pipx). run: weave help"
else
  python3 -m pip install --user "$PKG"
  bindir="$(python3 -m site --user-base)/bin"
  echo "installed weave. add to PATH if needed: export PATH=\"${bindir}:\$PATH\""
  echo "then run: weave help"
fi
