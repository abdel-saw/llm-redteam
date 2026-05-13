from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .database import init_db
from .routes import targets as targets_routes

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="LLM-RT",
    description="Agent autonome de Red Teaming pour applications LLM.",
    version="0.1.0",
    debug=settings.is_dev,
    lifespan=lifespan,
)

STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

app.include_router(targets_routes.router, prefix="/api/targets", tags=["targets"])


@app.get("/", response_class=PlainTextResponse)
async def root() -> str:
    return "LLM-RT MVP - up and running"
