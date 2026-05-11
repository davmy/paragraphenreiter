# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

**Start the dev server:**
```bash
./start.sh
```
This script creates the `.venv` if missing, installs dependencies, validates `ANTHROPIC_API_KEY`, and starts uvicorn on port 8000 with `--reload`.

**Manual setup:**
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

**Environment:** Copy `.env.example` to `.env` and set `ANTHROPIC_API_KEY`. The optional `LEGAL_NOTICE_URL` adds an imprint link to the UI.

**Run tests:**
```bash
pip install -r requirements-dev.txt
pytest tests/ -v
```

**Lint (Black style check):**
```bash
black --check app.py rag.py crawler.py tests/
```

**Auto-format:**
```bash
black app.py rag.py crawler.py tests/
```

## Architecture

**Paragraphenreiter** is an AI-powered German legal chatbot that answers questions by retrieving relevant statutes from `gesetze-im-internet.de` and generating streaming responses using Claude Sonnet 4.6.

### Data flow

1. User sends a question via the chat UI → `POST /api/chat`
2. `app.py` delegates to `rag.py:ParagraphenreiterRAG.stream_answer()`
3. The RAG class calls `crawler.py:search_index()` to score ~30 candidate laws by keyword overlap
4. Claude is called once to filter those 30 candidates down to the truly relevant ones
5. Full law text is fetched via `crawler.py:fetch_law_content()` (7-day cache in `cache/`)
6. Claude streams the final answer with citations; SSE events are forwarded to the client

### Key files

- **`app.py`** — FastAPI app with lifespan startup (initializes the RAG singleton), SSE streaming endpoint `/api/chat`, and static file mounting
- **`rag.py`** — `ParagraphenreiterRAG` class: system prompt, two-stage Claude calls (relevance filter + answer generation), streaming logic
- **`crawler.py`** — scrapes and caches the law index (24 h TTL) and law content (7-day TTL) from `gesetze-im-internet.de`; `search_index()` does keyword-based scoring

### Frontend

Single-file SPA at `static/index.html` — vanilla JS, no bundler. Consumes the `/api/chat` SSE stream and renders markdown via `marked.js` (CDN). Language is detected from the browser and stored in `localStorage`; 12 languages are supported via an inline translation map.

### Caching

JSON files are written to `cache/` (gitignored). The index is refreshed via `POST /api/index/refresh` or automatically on startup if stale. Cache is read by the crawler and is the only persistence layer.

## When to commit

- Create commits after completing each logical unit of work.
- Do not push to the remote repository unless asked.
- Use conventional commit messages (e.g. "feat:", "fix:", "refactor:").
- Ommit the hint Co-Authored-By: ...
