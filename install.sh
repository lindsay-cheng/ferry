#!/usr/bin/env bash
# curl|bash installer; builds a Go binary into ~/.local/bin
set -euo pipefail

REPO="https://github.com/lindsay-cheng/ferry.git"
INSTALL_DIR="${HOME}/.local/bin"
BINARY="${INSTALL_DIR}/ferry"

check_only=false
if [[ "${1:-}" == "--check" ]]; then
  check_only=true
fi

case "$(uname -s)" in
  Darwin|Linux) ;;
  *) echo "ferry install supports macOS and Linux only"; exit 1 ;;
esac

if ! command -v go >/dev/null 2>&1; then
  echo "go not found; install Go 1.22+ from https://go.dev/dl/"
  exit 1
fi

go_minor="$(go version | sed -n 's/.*go1\.\([0-9]*\).*/\1/p')"
if [[ -z "${go_minor}" ]] || [[ "${go_minor}" -lt 22 ]]; then
  echo "Go 1.22+ required (found $(go version))"
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

mkdir -p "${INSTALL_DIR}"

if [[ -f go.mod ]] && [[ -d cmd/ferry ]]; then
  go build -o "${BINARY}" ./cmd/ferry
else
  tmp="$(mktemp -d)"
  trap 'rm -rf "${tmp}"' EXIT
  if ! git clone --depth 1 "${REPO}" "${tmp}/ferry"; then
    echo "clone failed; if the repo is private, clone it with your GitHub access and run ./install.sh from the repo root"
    exit 1
  fi
  (cd "${tmp}/ferry" && go build -o "${BINARY}" ./cmd/ferry)
fi

case ":${PATH}:" in
  *":${INSTALL_DIR}:"*) ;;
  *)
    echo "add ${INSTALL_DIR} to PATH, for example:"
    echo "  export PATH=\"${INSTALL_DIR}:\$PATH\""
    ;;
esac

echo "installed ferry to ${BINARY}. run: ferry help"
