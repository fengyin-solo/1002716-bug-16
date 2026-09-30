"""箱单（对单）接口：导入归并、批次查询、按勾选箱状态出单与对账合计。

详情页与列表页的导出共用 export_batch 一个口径，保证同一批数据两处对上。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, ManifestImportPayload, PageResult
from app.services.manifest import (
    TEMPLATE_COLUMNS,
    VALID_STATUSES,
    ManifestService,
    ManifestValidationError,
)

router = APIRouter(prefix="/api/manifests", tags=["箱单对单"])

service = ManifestService()


@router.get("/template")
def get_template() -> dict[str, Any]:
    """箱单模板列序与合法箱状态：前端导入/勾选都以这里为准。"""
    return {"columns": TEMPLATE_COLUMNS, "statuses": VALID_STATUSES}


@router.post("/import", response_model=ActionResult)
def import_manifest(payload: ManifestImportPayload) -> ActionResult:
    """导入一次箱单导出结果：空行跳过、同箱号归并、列序不符整批打回、批次号幂等。"""
    try:
        result = service.import_manifest(
            batch_no=payload.batch_no, columns=payload.columns, rows=payload.rows
        )
    except ManifestValidationError as exc:
        # 整批打回：不落任何数据，把原因完整回给对单人员。
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ActionResult(ok=True, message=result.pop("message", ""), entry=result)


@router.get("", response_model=PageResult[dict])
def list_batches(page: int = 1, size: int = 20) -> PageResult[dict]:
    """箱单批次列表。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_batches(page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/reconciliation")
def reconciliation_totals() -> dict[str, Any]:
    """对账看板合计：跟着当前这批箱单实时重算。"""
    return service.reconciliation_totals()


@router.get("/{batch_no}")
def get_batch(batch_no: str) -> dict[str, Any]:
    """批次详情：归并后箱量、跳过行号、重复归并行号。"""
    batch = service.get_batch(batch_no)
    if batch is None:
        raise HTTPException(status_code=404, detail=f"箱单批次 {batch_no} 不存在")
    return batch


@router.get("/{batch_no}/export")
def export_batch(
    batch_no: str,
    status: list[str] = Query(default_factory=list, description="勾选的箱状态，可重复传；不勾为全部"),
) -> dict[str, Any]:
    """出单：按当前勾选的箱状态过滤，危品等级与铅封号一并带出。

    详情页和列表页都打这个接口，保证两边导出同一批数据对得上。
    """
    try:
        result = service.export_batch(batch_no, statuses=status)
    except ManifestValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail=f"箱单批次 {batch_no} 不存在")
    return result
