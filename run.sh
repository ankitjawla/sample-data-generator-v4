#!/usr/bin/env bash
# Sample Data Generator v4 (superset) — macOS / Linux launcher.
# Creates a .venv if missing (else reuses it), installs/updates dependencies,
# then runs the Streamlit app. Optional first arg overrides the port.
set -e
cd "$(dirname "$0")"
PORT="${1:-8504}"

echo "==> Sample Data Generator v4 (superset)"

PY=""
for c in python3 python; do command -v "$c" >/dev/null 2>&1 && { PY="$c"; break; }; done
if [ -z "$PY" ]; then
  echo "ERROR: Python 3 is not installed. Get it from https://www.python.org/downloads/"
  exit 1
fi

if [ ! -d ".venv" ]; then
  echo "==> Creating virtual environment (.venv)..."
  "$PY" -m venv .venv
fi
VENV_PY=".venv/bin/python"

echo "==> Installing dependencies..."
"$VENV_PY" -m pip install --quiet --upgrade pip
"$VENV_PY" -m pip install --quiet -r requirements.txt

mkdir -p "$HOME/.streamlit"
[ -f "$HOME/.streamlit/credentials.toml" ] || printf '[general]\nemail = ""\n' > "$HOME/.streamlit/credentials.toml"

echo "==> Starting at http://localhost:$PORT  (press Ctrl+C to stop)"
exec "$VENV_PY" -m streamlit run app.py --server.port "$PORT"
