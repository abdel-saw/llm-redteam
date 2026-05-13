"""Routes UI : pages Jinja2 + partial form-fields pour HTMX."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..enums import AttackCategory
from ..models import Scan, Target

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter()


CATEGORY_LABELS: dict[str, str] = {
    AttackCategory.PROMPT_INJECTION.value: "Prompt Injection (LLM01)",
    AttackCategory.JAILBREAK.value: "Jailbreak / Safety Bypass",
    AttackCategory.SYSTEM_PROMPT_LEAK.value: "Fuite de prompt système (LLM07)",
    AttackCategory.SENSITIVE_INFO_DISCLOSURE.value: "Divulgation d'informations (LLM02)",
    AttackCategory.MISINFORMATION.value: "Désinformation (LLM09)",
}


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        request,
        "index.html",
        {"category_labels": CATEGORY_LABELS},
    )


@router.get("/target-form-fields", response_class=HTMLResponse)
async def target_form_fields(
    request: Request,
    target_type: Literal["text", "json_custom", "openai_compatible"] = Query(
        default="openai_compatible"
    ),
):
    return templates.TemplateResponse(
        request,
        "components/target_form_fields.html",
        {"target_type": target_type},
    )


@router.get("/scans/{scan_id}/live", response_class=HTMLResponse)
async def scan_live(
    request: Request,
    scan_id: int,
    db: Session = Depends(get_db),
):
    scan = db.get(Scan, scan_id)
    if scan is None:
        raise HTTPException(status_code=404, detail="Scan not found")
    return templates.TemplateResponse(
        request,
        "scan_live.html",
        {
            "scan": scan,
            "target": scan.target,
            "category_labels": CATEGORY_LABELS,
        },
    )


@router.get("/history", response_class=HTMLResponse)
async def history(request: Request, db: Session = Depends(get_db)):
    stmt = select(Scan).order_by(Scan.created_at.desc()).limit(100)
    scans = list(db.execute(stmt).scalars().all())
    # Pré-charge les targets pour éviter le N+1 dans le template.
    for s in scans:
        _ = s.target.name  # déclenche le lazy load tant que la session est ouverte
    return templates.TemplateResponse(
        request,
        "history.html",
        {"scans": scans, "category_labels": CATEGORY_LABELS},
    )
