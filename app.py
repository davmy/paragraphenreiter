import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from dotenv import load_dotenv
from rag import ParagraphenreiterRAG

load_dotenv()

if not os.environ.get("ANTHROPIC_API_KEY"):
    raise RuntimeError(
        "ANTHROPIC_API_KEY ist nicht gesetzt. "
        "Bitte .env Datei anlegen oder Umgebungsvariable setzen."
    )

rag = ParagraphenreiterRAG()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await rag.initialize()
    yield


app = FastAPI(title="Paragraphenreiter", lifespan=lifespan)


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = []


@app.post("/api/chat")
async def chat(request: ChatRequest):
    history = [{"role": m.role, "content": m.content} for m in request.history]

    async def event_generator():
        try:
            async for chunk in rag.stream_answer(request.message, history):
                yield chunk
        except Exception as e:
            import json
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/index/status")
async def index_status():
    return {
        "law_count": len(rag.law_index),
        "ready": len(rag.law_index) > 0,
    }


@app.post("/api/index/refresh")
async def refresh_index():
    import asyncio
    from crawler import fetch_law_index
    loop = asyncio.get_event_loop()
    rag.law_index = await loop.run_in_executor(None, lambda: fetch_law_index(force_refresh=True))
    return {"law_count": len(rag.law_index)}


app.mount("/", StaticFiles(directory="static", html=True), name="static")
