import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app import cosmos_client, redis_client
from app.chat import router as chat_router
from app.models import HealthResponse

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("VectoChat service starting up.")
    yield
    logger.info("VectoChat service shutting down.")
    await redis_client.close()


app = FastAPI(
    title="VectoChat",
    version="1.0.0",
    lifespan=lifespan,
    # Disable docs in production via env var
    docs_url="/docs" if os.environ.get("ENABLE_DOCS", "false").lower() == "true" else None,
    redoc_url=None,
)

# ── API routes ────────────────────────────────────────────────────────────────
app.include_router(chat_router, prefix="/api")


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    redis_ok = await redis_client.ping()
    cosmos_ok = cosmos_client.ping()
    return HealthResponse(
        status="ok" if (redis_ok and cosmos_ok) else "degraded",
        redis="pong" if redis_ok else "unreachable",
        cosmos="ok" if cosmos_ok else "unreachable",
    )


# ── Static web UI ─────────────────────────────────────────────────────────────
_static_dir = Path(__file__).parent / "static"

if _static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")

    @app.get("/", include_in_schema=False)
    async def index():
        return FileResponse(str(_static_dir / "index.html"))
