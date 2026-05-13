"""Routes CRUD + déclenchement de scans Red Teaming."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import SessionLocal, get_db
from ..enums import ScanStatus
from ..models import Report, Scan, Target
from ..schemas import ReportRead, ScanCreate, ScanDetail, ScanSummary
from ..services.attack_engine import get_engine
from ..services.report import get_report_generator

logger = logging.getLogger(__name__)
router = APIRouter()

# Référence forte sur les tâches en arrière-plan pour empêcher le GC.
_background_tasks: set[asyncio.Task] = set()


@router.post(
    "",
    response_model=ScanDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Créer et déclencher un scan",
)
async def create_scan(payload: ScanCreate, db: Session = Depends(get_db)) -> Scan:
    target = db.get(Target, payload.target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Target not found")

    scan = Scan(
        target_id=payload.target_id,
        status=ScanStatus.PENDING,
        selected_categories_json=json.dumps([c.value for c in payload.selected_categories]),
        max_attempts_per_category=payload.max_attempts_per_category,
    )
    db.add(scan)
    db.commit()
    db.refresh(scan)

    task = asyncio.create_task(_run_scan_safely(scan.id))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    return scan


@router.get(
    "",
    response_model=list[ScanSummary],
    summary="Lister les scans (les plus récents d'abord)",
)
async def list_scans(
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
) -> list[Scan]:
    stmt = select(Scan).order_by(Scan.created_at.desc()).limit(limit)
    return list(db.execute(stmt).scalars().all())


@router.get(
    "/{scan_id}",
    response_model=ScanDetail,
    summary="Détail d'un scan + liste des tentatives",
)
async def get_scan(scan_id: int, db: Session = Depends(get_db)) -> Scan:
    scan = db.get(Scan, scan_id)
    if scan is None:
        raise HTTPException(status_code=404, detail="Scan not found")
    # `scan.attempts` est chargé en lazy lors de la sérialisation Pydantic.
    return scan


@router.post(
    "/{scan_id}/report",
    response_model=ReportRead,
    summary="(Re)générer le rapport HTML d'un scan",
)
async def create_or_update_report(
    scan_id: int, db: Session = Depends(get_db)
) -> dict:
    scan = db.get(Scan, scan_id)
    if scan is None:
        raise HTTPException(status_code=404, detail="Scan not found")
    generator = get_report_generator()
    report = await generator.generate(scan_id, db)
    return _serialize_report(report)


@router.get(
    "/{scan_id}/report",
    response_model=ReportRead,
    summary="Métadonnées du rapport HTML d'un scan",
)
async def get_report_meta(scan_id: int, db: Session = Depends(get_db)) -> dict:
    scan = db.get(Scan, scan_id)
    if scan is None:
        raise HTTPException(status_code=404, detail="Scan not found")
    report = db.query(Report).filter(Report.scan_id == scan_id).one_or_none()
    if report is None:
        raise HTTPException(status_code=404, detail="Report not generated yet")
    return _serialize_report(report)


def _serialize_report(report: Report) -> dict:
    return {
        "id": report.id,
        "scan_id": report.scan_id,
        "html_path": report.html_path,
        "html_url": f"/scans/{report.scan_id}/report",
        "generated_at": report.generated_at,
    }


@router.post(
    "/{scan_id}/abort",
    summary="Marquer un scan comme abandonné (best-effort)",
)
async def abort_scan(scan_id: int, db: Session = Depends(get_db)) -> dict:
    scan = db.get(Scan, scan_id)
    if scan is None:
        raise HTTPException(status_code=404, detail="Scan not found")
    if scan.status not in (ScanStatus.PENDING, ScanStatus.RUNNING):
        return {"scan_id": scan_id, "status": scan.status.value, "noop": True}
    scan.status = ScanStatus.ABORTED
    scan.finished_at = datetime.now(timezone.utc)
    db.commit()
    return {"scan_id": scan_id, "status": scan.status.value, "noop": False}


async def _run_scan_safely(scan_id: int) -> None:
    """Wrapper du run_scan : marque le scan failed si exception non rattrapée.

    Publie également un event `scan_failed` puis ferme le flux côté bus,
    pour que les clients SSE soient informés et puissent se déconnecter.
    """
    try:
        engine = get_engine()
        await engine.run_scan(scan_id)
    except Exception as exc:  # noqa: BLE001 - on capture toute défaillance
        logger.exception("Scan %d crashed: %s", scan_id, exc)
        try:
            with SessionLocal() as s:
                scan = s.get(Scan, scan_id)
                if scan is not None:
                    scan.status = ScanStatus.FAILED
                    scan.error_message = f"Engine crashed: {exc}"
                    scan.finished_at = datetime.now(timezone.utc)
                    s.commit()
        except Exception as inner:  # noqa: BLE001
            logger.exception("Failed to mark scan %d as failed: %s", scan_id, inner)

        # Imports locaux : évite tout cycle au module-load.
        from ..services.attack_engine import ScanEvent
        from ..services.event_bus import get_event_bus

        bus = get_event_bus()
        try:
            await bus.publish(scan_id, ScanEvent(
                "scan_failed",
                datetime.now(timezone.utc),
                {"scan_id": scan_id, "error_message": str(exc)},
            ))
        finally:
            await bus.close_scan(scan_id)
