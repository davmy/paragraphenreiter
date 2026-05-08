#!/usr/bin/env bash
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

# Create venv if missing
if [ ! -d ".venv" ]; then
  echo "Erstelle Python-Umgebung…"
  python3 -m venv .venv
fi

source .venv/bin/activate

# Install / upgrade deps
pip install -q -r requirements.txt

# Check API key
if [ -z "$ANTHROPIC_API_KEY" ]; then
  if [ -f ".env" ]; then
    export $(grep -v '^#' .env | xargs)
  fi
fi

if [ -z "$ANTHROPIC_API_KEY" ]; then
  echo ""
  echo "⚠️  ANTHROPIC_API_KEY nicht gesetzt!"
  echo "   Bitte .env Datei anlegen:"
  echo "   echo 'ANTHROPIC_API_KEY=sk-ant-...' > .env"
  echo ""
  exit 1
fi

echo ""
echo "🐎 Paragraphenreiter startet…"
echo "   → http://localhost:8000"
echo ""

uvicorn app:app --host 0.0.0.0 --port 8000 --reload
