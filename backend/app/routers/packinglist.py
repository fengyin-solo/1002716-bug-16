"""箱单对单接口：导入校正、批次列表/详情、出单、对账合计。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.packinglist import (
    BOX_STATUSES,
    TEMPLATE_COLUMNS,
    BatchRejected,
    service,
)

router = APIRouter(prefix="/api/packinglist", tags=["箱单对单"])


class ImportPayload(BaseModel):
    """一次导出（一个批次）提交的表头与数据行。"""

    batch_no: str = Field(..., description="批次号：同一次导出的归并键")
    columns: list[str] = Field(..., description="表头，须与模板列序逐列一致")
    rows: list[list[Any]] = Field(default_factory=list, description="按 columns 顺序排列的数据行")


def _raise_for_batch(exc: BatchRejected) -> None:
    raise HTTPException(status_code=400, detail=exc.to_detail())


@router.get("/template")
def get_template() -> dict[str, Any]:
    """返回箱单模板列序与可选箱状态，前端按它对齐列。"""
    return {"columns": list(TEMPLATE_COLUMNS), "statuses": list(BOX_STATUSES)}


@router.get("/reconciliation")
def reconciliation() -> dict[str, Any]:
    """对账看板合计：随当前已落库箱单实时重算。"""
    return service.reconciliation()


@router.post("/batches/import")
def import_batch(payload: ImportPayload) -> dict[str, Any]:
    """导入一批箱单：列序不符整批打回；空行跳过；批内/跨批重复只认第一次。"""
    try:
        return service.import_batch(batch_no=payload.batch_no, columns=payload.columns, rows=payload.rows)
    except BatchRejected as exc:
        _raise_for_batch(exc)


@router.get("/batches")
def list_batches() -> dict[str, Any]:
    """批次列表（不含明细行），用于列表页与对账。"""
    items = service.list_batches()
    return {"module": "packinglist", "total": len(items), "items": items}


@router.get("/batches/{batch_id}/export")
def export_batch(
    batch_id: int,
    status: list[str] | None = Query(default=None, description="勾选的箱状态，可多值；不传表示不限"),
) -> dict[str, Any]:
    """出单：详情页与列表页共用同一出口，按勾选箱状态过滤，带危品等级与铅封号。"""
    try:
        return service.export_batch(batch_id, status)
    except BatchRejected as exc:
        _raise_for_batch(exc)


@router.get("/batches/{batch_id}")
def get_batch(batch_id: int) -> dict[str, Any]:
    """批次详情：出单对账以它为准。"""
    batch = service.get_batch(batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail={"code": "BATCH_NOT_FOUND", "message": f"批次 {batch_id} 不存在或已归档"})
    return {
        "id": batch["id"],
        "batch_no": batch["batch_no"],
        "rows": batch["rows"],
        "skipped_lines": batch["skipped_lines"],
        "duplicate_in_batch": batch["duplicate_in_batch"],
        "duplicate_prior": batch["duplicate_prior"],
    }
