"""Routes CRUD + test de connexion pour les cibles LLM."""

from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Target
from ..schemas import TargetCreate, TargetRead, TargetTestRequest, TargetTestResponse
from ..services.target_adapter import get_adapter

router = APIRouter()


@router.post(
    "",
    response_model=TargetRead,
    status_code=status.HTTP_201_CREATED,
    summary="Créer une cible LLM",
)
async def create_target(payload: TargetCreate, db: Session = Depends(get_db)) -> Target:
    target = Target(
        name=payload.name,
        target_type=payload.target_type,
        endpoint_url=payload.endpoint_url,
        headers_json=json.dumps(payload.headers) if payload.headers else None,
        request_template=payload.request_template,
        response_path=payload.response_path,
        model_name=payload.model_name,
    )
    db.add(target)
    db.commit()
    db.refresh(target)
    return target


@router.get("", response_model=list[TargetRead], summary="Lister les cibles")
async def list_targets(db: Session = Depends(get_db)) -> list[Target]:
    stmt = select(Target).order_by(Target.created_at.desc())
    return list(db.execute(stmt).scalars().all())


@router.get("/{target_id}", response_model=TargetRead, summary="Récupérer une cible")
async def get_target(target_id: int, db: Session = Depends(get_db)) -> Target:
    target = db.get(Target, target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Target not found")
    return target


@router.delete(
    "/{target_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Supprimer une cible",
)
async def delete_target(target_id: int, db: Session = Depends(get_db)) -> None:
    target = db.get(Target, target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Target not found")
    db.delete(target)
    db.commit()


@router.post(
    "/{target_id}/test",
    response_model=TargetTestResponse,
    summary="Tester la connexion à une cible",
)
async def test_target(
    target_id: int,
    payload: Optional[TargetTestRequest] = None,
    db: Session = Depends(get_db),
) -> TargetTestResponse:
    target = db.get(Target, target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Target not found")
    adapter = get_adapter(target)
    prompt = payload.prompt if payload and payload.prompt else None
    result = await adapter.test_connection(prompt=prompt)
    return TargetTestResponse(**result.model_dump())
