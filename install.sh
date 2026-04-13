#!/usr/bin/env bash
# install.sh — install ita as a uv-managed tool.
#
# ita is a proper Python package (src/ita/). `uv tool install` builds a
# wheel and drops an `ita` launcher into uv's bin dir (~/.local/bin).
# Re-run this script after pulling new code to refresh the installed copy.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v uv >/dev/null 2>&1; then
  echo "error: uv not found. Install from https://github.com/astral-sh/uv" >&2
  exit 1
fi

echo "Installing ita from ${SCRIPT_DIR}..."
uv tool install --force --from "${SCRIPT_DIR}" ita

UV_BIN="${HOME}/.local/bin"
case ":${PATH:-}:" in
  *":${UV_BIN}:"*) ;;
  *)
    echo ""
    echo "Add ${UV_BIN} to your PATH (e.g. in ~/.zshrc):"
    echo "  export PATH=\"${UV_BIN}:\$PATH\""
    ;;
esac

echo ""
echo "Verify: ita --version"
