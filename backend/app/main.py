import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from .config import settings
from .database import init_db
from .routes import pages as pages_routes
from .routes import scans as scans_routes
from .routes import stream as stream_routes
from .routes import targets as targets_routes
from .security.log_filter import install_redacting_filter

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

logging.basicConfig(
    level=logging.DEBUG if settings.is_dev else logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
install_redacting_filter()


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

# Routes API
app.include_router(targets_routes.router, prefix="/api/targets", tags=["targets"])
app.include_router(scans_routes.router, prefix="/api/scans", tags=["scans"])
app.include_router(stream_routes.router, prefix="/api/scans", tags=["stream"])

# Routes UI (server-rendered)
app.include_router(pages_routes.router, tags=["ui"])


_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
}


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next) -> Response:
    response = await call_next(request)
    for name, value in _SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    return response
