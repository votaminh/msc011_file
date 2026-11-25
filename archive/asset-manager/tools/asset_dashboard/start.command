#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="${0:A:h}"
ROOT_DIR="${SCRIPT_DIR:h:h}"
VAULT_DIR="$ROOT_DIR/asset-vault"

if [[ ! -d "$VAULT_DIR" ]]; then
  echo "Không tìm thấy asset-vault: $VAULT_DIR"
  read -r "?Nhấn Enter để đóng..."
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "Không tìm thấy python3."
  read -r "?Nhấn Enter để đóng..."
  exit 1
fi

PORT=""
for candidate in {8765..8795}; do
  health="$(curl -fsS "http://127.0.0.1:${candidate}/api/health" 2>/dev/null || true)"
  if [[ -n "$health" ]]; then
    if [[ "$health" == *"$VAULT_DIR"* ]]; then
      echo "Dashboard đã chạy: http://127.0.0.1:${candidate}/"
      open "http://127.0.0.1:${candidate}/"
      exit 0
    fi
    continue
  fi
  if ! nc -z 127.0.0.1 "$candidate" >/dev/null 2>&1; then
    PORT="$candidate"
    break
  fi
done

if [[ -z "$PORT" ]]; then
  echo "Không tìm thấy port trống trong khoảng 8765-8795."
  read -r "?Nhấn Enter để đóng..."
  exit 1
fi

URL="http://127.0.0.1:${PORT}/"

echo "Đang chạy asset dashboard tại $URL"
echo "Đóng cửa sổ Terminal này để dừng server."
exec python3 "$SCRIPT_DIR/server.py" \
  --vault "$VAULT_DIR" \
  --host 127.0.0.1 \
  --port "$PORT" \
  --open
