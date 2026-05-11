# Paragraphenreiter

[![CI](https://github.com/davmy/paragraphenreiter/actions/workflows/ci.yml/badge.svg)](https://github.com/davmy/paragraphenreiter/actions/workflows/ci.yml)
[![Coverage](https://codecov.io/gh/davmy/paragraphenreiter/branch/main/graph/badge.svg)](https://codecov.io/gh/davmy/paragraphenreiter)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue)](https://www.python.org/)

An AI-powered legal chatbot that answers questions about German law with direct links to the relevant statutes on [gesetze-im-internet.de](https://www.gesetze-im-internet.de).

**Live:** [paragraphenreiter.meier-david.de](https://paragraphenreiter.meier-david.de)

---

## How it works

1. The user submits a legal question via the chat UI.
2. A keyword search scores all ~6,000 laws in the index and selects up to 30 candidates.
3. Claude Sonnet 4.6 filters those 30 candidates down to the 3–5 most relevant laws.
4. The full text of each selected law is fetched from gesetze-im-internet.de (cached for 7 days).
5. Claude streams a concise answer with inline links to the exact paragraphs.
6. The UI displays the answer in real time via Server-Sent Events (SSE).

The law index is refreshed automatically on startup if older than 24 hours.

## Setup

```bash
git clone https://github.com/davmy/paragraphenreiter.git
cd paragraphenreiter
cp .env.example .env          # fill in ANTHROPIC_API_KEY
./start.sh                    # creates venv, installs deps, starts server
```

Or manually:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.lock
uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

The app is then available at `http://localhost:8000`.

## Configuration

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | Anthropic API key for Claude Sonnet 4.6 |
| `LEGAL_NOTICE_URL` | No | URL of an imprint/legal notice page — shown as a link in the footer |

## API

### `POST /api/chat`

Streams an answer to a legal question via Server-Sent Events.

**Rate limit:** 10 requests per minute per IP.

**Request body:**

```json
{
  "message": "Wann darf mein Vermieter kündigen?",
  "history": [
    { "role": "user", "content": "..." },
    { "role": "assistant", "content": "..." }
  ],
  "language": "de"
}
```

| Field | Type | Constraints | Default |
|---|---|---|---|
| `message` | string | 1–2000 characters | — |
| `history` | array | max 20 entries, each content max 4000 chars | `[]` |
| `language` | string | `de en tr ar ru uk pl ro fr es vi zh` | `de` |

**SSE event types:**

| Type | Payload | Description |
|---|---|---|
| `status` | `{ "content": "..." }` | Progress update (searching, loading laws, …) |
| `content` | `{ "content": "..." }` | Streamed answer token |
| `sources` | `{ "sources": [...] }` | Law sources used |
| `error` | `{ "content": "..." }` | Error message |
| `done` | `{}` | Stream finished |

### `GET /api/health`

Returns `200` when the app is up and the law index is loaded.

```json
{ "status": "ok", "index_ready": true }
```

### `GET /api/config`

Returns runtime configuration for the frontend.

```json
{ "legal_notice_url": "https://example.com/impressum" }
```

### `GET /api/index/status`

Returns the current state of the law index.

```json
{ "law_count": 6132, "ready": true }
```

### `POST /api/index/refresh`

Forces a refresh of the law index from gesetze-im-internet.de (ignores the 24-hour cache).

```json
{ "law_count": 6132 }
```

## Development

```bash
pip install -r requirements.lock
pip install -r requirements-dev.txt

# Run tests (coverage report included)
pytest tests/ -v

# Lint
black --check app.py rag.py crawler.py logging_config.py tests/
ruff check app.py rag.py crawler.py logging_config.py tests/
mypy app.py rag.py crawler.py logging_config.py

# Auto-format
black app.py rag.py crawler.py logging_config.py tests/
```

After changing `requirements.txt`, regenerate the lockfile:

```bash
pip install -r requirements.txt
pip freeze | grep -v "^-e" > requirements.lock
```

## Caching

| Cache | Location | TTL |
|---|---|---|
| Law index | `cache/law_index.json` | 24 hours |
| Law content | `cache/law_<abbrev>.json` | 7 days |

The `cache/` directory is gitignored. Delete files there to force a refresh.
