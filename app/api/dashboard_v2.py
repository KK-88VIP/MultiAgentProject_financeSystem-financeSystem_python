from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.common import ApiResponse
from app.models.dashboard_dsl import DashboardDSL, DashboardRenderRequest
from app.services.dashboard_dsl_service import DashboardDSLService
from app.utils.runtime_filters import validate_runtime_filters

router = APIRouter()
service = DashboardDSLService()


def _build_scope(user_role: str) -> dict:
    # 当前阶段不做细粒度 dashboard 资源权限，保留缓存 scope 字段契约
    return {"role": user_role, "authorized_companies": []}


@router.post("/dsl/create", response_model=ApiResponse[dict])
async def create_dashboard(
    dsl: DashboardDSL,
    user_id: str | None = Header(None, alias="X-User-Id"),
    db: AsyncSession = Depends(get_db),
):
    await service.create(db, dsl, user_id or "anonymous")
    return ApiResponse.success(data={"id": dsl.id})


@router.get("/dsl/{dashboard_id}", response_model=ApiResponse[dict])
async def get_dashboard(
    dashboard_id: str,
    db: AsyncSession = Depends(get_db),
):
    data = await service.get(db, dashboard_id)
    return ApiResponse.success(data=data)


@router.get("/dsl", response_model=ApiResponse[list[dict]])
async def list_dashboards(db: AsyncSession = Depends(get_db)):
    data = await service.list_all(db)
    return ApiResponse.success(data=data)


@router.put("/dsl/{dashboard_id}", response_model=ApiResponse[dict])
async def update_dashboard(
    dashboard_id: str,
    dsl: DashboardDSL,
    user_id: str | None = Header(None, alias="X-User-Id"),
    db: AsyncSession = Depends(get_db),
):
    await service.update(db, dashboard_id, dsl, user_id or "anonymous")
    return ApiResponse.success(data={"id": dashboard_id})


@router.delete("/dsl/{dashboard_id}", response_model=ApiResponse[dict])
async def delete_dashboard(
    dashboard_id: str,
    user_id: str | None = Header(None, alias="X-User-Id"),
    db: AsyncSession = Depends(get_db),
):
    await service.delete(db, dashboard_id, user_id or "anonymous")
    return ApiResponse.success(data={"id": dashboard_id})


@router.post("/dsl/render", response_model=ApiResponse[dict])
async def render_dashboard(
    req: DashboardRenderRequest,
    user_role: str = Header("user", alias="X-User-Role"),
    db: AsyncSession = Depends(get_db),
):
    if not req.dsl and not req.dashboard_id:
        raise HTTPException(status_code=422, detail="DSL_INVALID: dsl or dashboard_id required")

    validate_runtime_filters(req.runtime_filters)

    dsl = req.dsl
    if req.dashboard_id:
        row = await service.get(db, req.dashboard_id)
        raw = row.get("dsl_json")
        if not isinstance(raw, dict):
            raise HTTPException(status_code=422, detail="DSL_INVALID: stored dsl_json is invalid")
        dsl = DashboardDSL(**raw)

    assert dsl is not None
    # runtime_filters 生效：在 render 前合并到全局 filters 默认值中
    if req.runtime_filters:
        merged = []
        for f in dsl.filters:
            item = f.model_copy()
            if item.name in req.runtime_filters:
                item.default = req.runtime_filters[item.name]
            merged.append(item)
        dsl = dsl.model_copy(update={"filters": merged})

    data = await service.render(db, dsl, _build_scope(user_role))
    return ApiResponse.success(data=data)

