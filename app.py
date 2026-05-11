import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import structlog
from logging_config import configure_logging
from rag import ParagraphenreiterRAG

configure_logging()
logger = structlog.get_logger()

load_dotenv()

if not os.environ.get("ANTHROPIC_API_KEY"):
    raise RuntimeError(
        "ANTHROPIC_API_KEY ist nicht gesetzt. "
        "Bitte .env Datei anlegen oder Umgebungsvariable setzen."
    )

rag = ParagraphenreiterRAG()
limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await rag.initialize()
    logger.info("startup_complete", law_count=len(rag.law_index))
    yield
    logger.info("shutdown")


app = FastAPI(title="Paragraphenreiter", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(
    RateLimitExceeded,
    lambda request, exc: JSONResponse(
        {"detail": "Too many requests. Please wait before sending another message."},
        status_code=429,
    ),
)


class ChatMessage(BaseModel):
    role: str = Field(pattern=r"^(user|assistant)$")
    content: str = Field(max_length=4000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    history: list[ChatMessage] = Field(default=[], max_length=20)
    language: str = Field(
        default="de", pattern=r"^(de|en|tr|ar|ru|uk|pl|ro|fr|es|vi|zh)$"
    )


@app.post("/api/chat")
@limiter.limit("10/minute")
async def chat(request: Request, body: ChatRequest):
    log = logger.bind(
        ip=request.client.host if request.client else "unknown",
        language=body.language,
        message_length=len(body.message),
    )
    log.info("chat_request")
    history = [{"role": m.role, "content": m.content} for m in body.history]

    async def event_generator():
        try:
            async for chunk in rag.stream_answer(body.message, history, body.language):
                yield chunk
            log.info("chat_complete")
        except Exception as e:
            import json

            log.error("chat_error", error=str(e))
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/health")
async def health():
    return {"status": "ok", "index_ready": len(rag.law_index) > 0}


@app.get("/api/config")
async def config():
    return {"legal_notice_url": os.environ.get("LEGAL_NOTICE_URL") or None}


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
    rag.law_index = await loop.run_in_executor(
        None, lambda: fetch_law_index(force_refresh=True)
    )
    return {"law_count": len(rag.law_index)}


app.mount("/", StaticFiles(directory="static", html=True), name="static")
