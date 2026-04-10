#!/usr/bin/env bash
# install.sh — symlink ita into ~/.local/bin
# Run once after installing the plugin, or after cloning the repo directly.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="${HOME}/.local/bin"
TARGET="${BIN_DIR}/ita"
SOURCE="${SCRIPT_DIR}/src/ita.py"

mkdir -p "${BIN_DIR}"

if [ ! -f "${SOURCE}" ]; then
  echo "error: ${SOURCE} not found" >&2
  exit 1
fi

chmod +x "${SOURCE}"

if [ -L "${TARGET}" ] || [ -f "${TARGET}" ]; then
  echo "removing existing ${TARGET}"
  rm "${TARGET}"
fi

ln -s "${SOURCE}" "${TARGET}"
echo "installed: ${TARGET} → ${SOURCE}"
echo ""
echo "Make sure ${BIN_DIR} is in your PATH. If not, add this to ~/.zshrc:"
echo "  export PATH=\"${BIN_DIR}:\$PATH\""
echo ""
echo "Then verify: ita --help"
