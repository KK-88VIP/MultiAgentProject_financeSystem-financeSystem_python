# -*- coding: utf-8 -*-
"""
@file: auth.py
@version: 0.1.0
@purpose: 权限相关接口，返回当前用户角色与授权公司范围。
@created: 2026-04-17 15:27:17 +08:00
@updated: 2026-04-17 15:27:17 +08:00
@author: aPy
"""

from fastapi import APIRouter, Header, Query

from app.core.config import settings
from app.models.auth import PermissionResponse
from app.models.common import ApiResponse
from app.services.permission_service import PermissionService

router = APIRouter()
service = PermissionService()


@router.get("/permissions", response_model=ApiResponse[PermissionResponse])
async def get_permissions(
    user_id: str = Query(..., description="用户 ID"),
    role: str | None = Query(
        None,
        description="可选；传 admin 时返回全量公司权限标记；未传时尝试使用请求头 X-User-Role",
    ),
    x_user_role: str | None = Header(None, alias="X-User-Role"),
) -> ApiResponse[PermissionResponse]:
    """
    角色来源优先级：Query role > Header X-User-Role。
    与 /api/dashboard/filters 一致：本地可在 .env 设置 DEV_ASSUME_ADMIN_FOR_FILTERS=true（且 APP_ENV=dev）
    时，在未显式传 admin 且头/参均为 user 或缺省时，按 admin 返回（仅联调）。
    """
    effective = (role if role is not None and str(role).strip() != "" else None) or x_user_role
    if (
        settings.DEV_ASSUME_ADMIN_FOR_FILTERS
        and settings.APP_ENV == "dev"
        and (effective is None or str(effective).strip().lower() == "user")
    ):
        effective = "admin"
    data = service.get_user_permissions(user_id, effective)
    return ApiResponse.success(data=data)
