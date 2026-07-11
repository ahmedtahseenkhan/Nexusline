"""Reports API — metric catalog, KPI dashboard widgets and computed dashboard data."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.core.deps import CurrentUser, DbSession, require
from app.models.widget import DashboardWidget
from app.schemas.report import (
    MetricInfo,
    WidgetCreate,
    WidgetData,
    WidgetRead,
    WidgetUpdate,
)
from app.services import metrics

router = APIRouter(prefix="/reports", tags=["reports"])


async def _load(db, widget_id: uuid.UUID) -> DashboardWidget:
    obj = await db.scalar(select(DashboardWidget).where(DashboardWidget.id == widget_id))
    if obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Widget not found")
    return obj


@router.get("/metrics", response_model=list[MetricInfo], dependencies=[Depends(require("report:read"))])
async def list_metrics(_: CurrentUser) -> list[MetricInfo]:
    return [MetricInfo(**m) for m in metrics.catalog()]


@router.get("/widgets", response_model=list[WidgetRead], dependencies=[Depends(require("report:read"))])
async def list_widgets(db: DbSession, _: CurrentUser) -> list[WidgetRead]:
    rows = (
        await db.scalars(select(DashboardWidget).order_by(DashboardWidget.order_index, DashboardWidget.created_at))
    ).all()
    return [WidgetRead.model_validate(r) for r in rows]


@router.post("/widgets", response_model=WidgetRead, status_code=201, dependencies=[Depends(require("report:write"))])
async def create_widget(body: WidgetCreate, db: DbSession, user: CurrentUser) -> WidgetRead:
    if body.metric_key not in metrics.CATALOG:
        raise HTTPException(status_code=422, detail=f"Unknown metric '{body.metric_key}'")
    obj = DashboardWidget(tenant_id=user.tenant_id, **body.model_dump())
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    return WidgetRead.model_validate(obj)


@router.patch("/widgets/{widget_id}", response_model=WidgetRead, dependencies=[Depends(require("report:write"))])
async def update_widget(widget_id: uuid.UUID, body: WidgetUpdate, db: DbSession) -> WidgetRead:
    obj = await _load(db, widget_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    await db.flush()
    await db.refresh(obj)
    return WidgetRead.model_validate(obj)


@router.delete("/widgets/{widget_id}", status_code=204, dependencies=[Depends(require("report:write"))])
async def delete_widget(widget_id: uuid.UUID, db: DbSession) -> None:
    await db.delete(await _load(db, widget_id))


@router.get("/dashboard", response_model=list[WidgetData], dependencies=[Depends(require("report:read"))])
async def dashboard(db: DbSession, user: CurrentUser) -> list[WidgetData]:
    rows = (
        await db.scalars(select(DashboardWidget).order_by(DashboardWidget.order_index, DashboardWidget.created_at))
    ).all()
    out: list[WidgetData] = []
    for w in rows:
        wr = WidgetRead.model_validate(w)
        try:
            data = await metrics.compute(db, w.metric_key, user.tenant_id)
            out.append(WidgetData(widget=wr, kind=data["kind"], value=data["value"], series=data["series"]))
        except KeyError:
            out.append(WidgetData(widget=wr, kind="scalar", error="Unknown metric"))
    return out
