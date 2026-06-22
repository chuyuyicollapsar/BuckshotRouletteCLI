#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUT_DIR="${OUTPUT_DIR:-dist/client/linux}"
PYINSTALLER_VERSION="${PYINSTALLER_VERSION:-6.21.0}"
OUTPUT_PATH="${ROOT}/${OUTPUT_DIR}"

mkdir -p "${OUTPUT_PATH}"

docker build \
  -f "${ROOT}/Dockerfile.client-linux" \
  --build-arg "PYINSTALLER_VERSION=${PYINSTALLER_VERSION}" \
  --target export \
  --output "type=local,dest=${OUTPUT_PATH}" \
  "${ROOT}"

chmod +x "${OUTPUT_PATH}/buckshot-client"
echo "Linux client binary: ${OUTPUT_PATH}/buckshot-client"
