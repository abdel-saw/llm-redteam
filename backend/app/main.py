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
from .utils.db_path import emit_startup_db_warnings, ensure_sqlite_dir

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

logging.basicConfig(
    level=logging.DEBUG if settings.is_dev else logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
install_redacting_filter()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Préparation FS AVANT create_all : sinon SQLite échoue avec
    # "unable to open database file" si le dossier n'existe pas
    # (cas typique : container Docker non-root + volume non monté).
    ensure_sqlite_dir(settings.database_url)
    emit_startup_db_warnings(settings.database_url)
    Path(settings.reports_dir).mkdir(parents=True, exist_ok=True)
    init_db()
    yield


app = FastAPI(
    title=settings.app_name,
    description=settings.app_tagline,
    version=settings.app_version,
    debug=settings.is_dev,
    lifespan=lifespan,
)


@app.get("/healthz", include_in_schema=False)
async def healthz() -> dict:
    """Endpoint de liveness — utilisé par Docker HEALTHCHECK et HF Space."""
    return {"status": "ok", "version": settings.app_version, "name": settings.app_name}

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
